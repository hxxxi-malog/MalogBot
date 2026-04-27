"""
研究流程编排服务

协调各专家型 Agent 完成研究任务，提供：
- 标准研究模式：直接开始多轮搜索分析
- 深度研究模式：先澄清问题，生成研究计划确认后执行
- 并行执行多个研究方向
- SSE 实时进度推送
"""
import asyncio
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc

from services.deep_research.models import (
    ResearchTask as ResearchTaskModel,
    ResearchPlan as ResearchPlanModel,
    ResearchDirection as ResearchDirectionModel,
    ResearchReport as ResearchReportModel,
    ResearchMode,
    ResearchStatus,
    DirectionSpec,
    Learning,
    Source,
    ClarificationQuestion,
)
from services.deep_research.state_machine import (
    ResearchStateMachine,
    ResearchState,
    InvalidStateTransition,
)
from services.deep_research.track import ResearchTrack, TrackManager, TrackStatus
from services.deep_research.agents.base import AgentContext, AgentResult
from services.deep_research.agents.explorer_agent import ExplorerAgent
from services.deep_research.agents.analyzer_agent import AnalyzerAgent
from services.deep_research.agents.synthesizer_agent import SynthesizerAgent
from services.deep_research.utils.deduplicator import Deduplicator, RedisDeduplicator
from services.deep_research.utils.content_cleaner import WebContentCleaner
from services.deep_research.events import SSEEvent, SSEEventType

# 导入数据库模型
from models.research import (
    ResearchTask as DBResearchTask,
    ResearchPlan as DBResearchPlan,
    ResearchDirection as DBResearchDirection,
    ResearchReport as DBResearchReport,
    ResearchSearch as DBResearchSearch,
)
from services.db_manager import db_manager

# 导入 Redis
from services.redis_service import redis_manager, is_redis_available

# 导入 MCP 工具
from mcp.tools import mcp_tools_manager
from mcp.registry import mcp_registry

logger = logging.getLogger(__name__)


# ============ 异常定义 ============

class ResearchError(Exception):
    """研究错误基类"""
    pass


class ResearchCancelledError(ResearchError):
    """研究被取消"""
    pass


class ResearchFailedError(ResearchError):
    """研究失败"""
    pass


# ============ CPU 任务执行器 ============

class CPUTaskExecutor:
    """
    CPU 密集型任务执行器
    
    管理共享进程池，用于执行 CPU 密集型任务（如 PDF 解析、向量化计算）。
    """
    
    _instance = None
    _pool: Optional[ProcessPoolExecutor] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # 进程池大小 = CPU 核数 - 1（预留 1 核给主进程）
            import os
            max_workers = max(1, os.cpu_count() - 1)
            cls._pool = ProcessPoolExecutor(max_workers=max_workers)
            logger.info(f"CPU task executor initialized with {max_workers} workers")
        return cls._instance
    
    async def submit(self, func, *args, **kwargs) -> Any:
        """
        提交 CPU 任务到进程池
        
        Args:
            func: 任务函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            任务结果
        """
        loop = asyncio.get_event_loop()
        # 使用 partial 绑定 kwargs
        if kwargs:
            func = partial(func, **kwargs)
        return await loop.run_in_executor(self._pool, func, *args)
    
    def shutdown(self):
        """关闭进程池"""
        if self._pool:
            self._pool.shutdown(wait=True)
            logger.info("CPU task executor shutdown")


# ============ SSE 网关 ============

class SSEGateway:
    """
    SSE 消息网关
    
    管理多 Track 消息路由，支持单连接多路复用。
    """
    
    def __init__(self):
        self._connections: dict[str, asyncio.Queue] = {}  # session_id -> queue
        self._track_to_session: dict[str, str] = {}  # track_id -> session_id
        logger.info("SSE Gateway initialized")
    
    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """
        前端建立 SSE 连接
        
        Args:
            session_id: 会话 ID
            
        Returns:
            消息队列
        """
        queue = asyncio.Queue()
        self._connections[session_id] = queue
        logger.info(f"SSE connection established for session: {session_id}")
        return queue
    
    def unsubscribe(self, session_id: str):
        """断开 SSE 连接"""
        if session_id in self._connections:
            del self._connections[session_id]
            logger.info(f"SSE connection closed for session: {session_id}")
    
    def register_track(self, track_id: str, session_id: str):
        """注册 Track 到 Session 映射"""
        self._track_to_session[track_id] = session_id
    
    async def push(
        self,
        event_type: str,
        task_id: str,
        track_id: str,
        data: dict,
    ):
        """
        Track 推送消息
        
        Args:
            event_type: 事件类型
            task_id: 任务 ID
            track_id: 轨道 ID
            data: 事件数据
        """
        session_id = self._track_to_session.get(track_id)
        if not session_id:
            logger.warning(f"No session found for track: {track_id}")
            return
        
        if session_id not in self._connections:
            logger.debug(f"No SSE connection for session: {session_id}")
            return
        
        msg = {
            "event": event_type,
            "task_id": task_id,
            "track_id": track_id,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        
        await self._connections[session_id].put(msg)
        logger.debug(f"Pushed event {event_type} to session {session_id}")


# 全局单例
sse_gateway = SSEGateway()
cpu_executor = CPUTaskExecutor()


# ============ 研究服务 ============

class ResearchService:
    """
    研究流程编排服务
    
    核心职责：
    - 管理研究任务的生命周期
    - 协调专家型 Agent 执行
    - 提供并行执行能力
    - 推送实时进度
    
    使用方式：
        service = ResearchService()
        
        # 发起研究
        task = await service.start_research(query, mode, session_id)
        
        # 恢复研究（深度模式）
        task = await service.resume_research(task_id, answer)
        
        # 取消研究
        await service.cancel_research(task_id)
    """
    
    def __init__(
        self,
        deduplicator: Optional[Deduplicator] = None,
        content_cleaner: Optional[WebContentCleaner] = None,
        db_session: Optional[DBSession] = None,
    ):
        """
        初始化研究服务
        
        Args:
            deduplicator: 去重器实例（可选）
            content_cleaner: 内容清洗器实例（可选）
            db_session: 数据库会话（可选）
        """
        # 使用 Redis 去重器（如果 Redis 可用）
        if deduplicator is None:
            if is_redis_available():
                self.deduplicator = RedisDeduplicator(
                    redis_client=redis_manager.client,
                    similarity_threshold=0.88
                )
                logger.info("[ResearchService] Using Redis deduplicator")
            else:
                self.deduplicator = Deduplicator()
                logger.info("[ResearchService] Using in-memory deduplicator")
        else:
            self.deduplicator = deduplicator
        
        self.content_cleaner = content_cleaner or WebContentCleaner()
        self.track_manager = TrackManager()
        
        # 数据库会话
        self._db = db_session
        
        # 任务存储（运行时缓存）
        self._tasks: dict[str, ResearchTaskModel] = {}
        self._plans: dict[str, ResearchPlanModel] = {}
        self._tracks: dict[str, list[ResearchTrack]] = {}  # task_id -> tracks
        
        # Agent 实例池（按需创建）
        self._explorer_agents: list[ExplorerAgent] = []
        self._analyzer_agents: list[AnalyzerAgent] = []
        self._synthesizer_agents: list[SynthesizerAgent] = []
        
        logger.info("ResearchService initialized")
    
    def _get_db(self) -> DBSession:
        """获取数据库会话"""
        if self._db:
            return self._db
        # 使用 db_manager 创建新会话
        return db_manager.session_factory()
    
    def _db_task_to_model(self, db_task: DBResearchTask) -> ResearchTaskModel:
        """将数据库模型转换为内存模型"""
        # 解析澄清问题
        questions = []
        for q_data in (db_task.clarification_questions or []):
            if isinstance(q_data, dict):
                questions.append(ClarificationQuestion(
                    question=q_data.get("question", ""),
                    answer=q_data.get("answer"),
                ))
        
        return ResearchTaskModel(
            id=str(db_task.id),
            session_id=db_task.session_id,
            query=db_task.query,
            mode=ResearchMode(db_task.mode),
            status=ResearchStatus(db_task.status),
            clarification_questions=questions,
            current_step=db_task.current_step,
            error_message=db_task.error_message,
            started_at=db_task.started_at,
            completed_at=db_task.completed_at,
            created_at=db_task.created_at,
            updated_at=db_task.updated_at,
        )
    
    def _update_task_status(self, task_id: str, status: ResearchStatus, **kwargs):
        """更新任务状态到数据库"""
        db = self._get_db()
        try:
            db_task = db.query(DBResearchTask).filter(
                DBResearchTask.id == uuid.UUID(task_id)
            ).first()
            if db_task:
                db_task.status = status.value
                for key, value in kwargs.items():
                    if hasattr(db_task, key):
                        setattr(db_task, key, value)
                db.commit()
                logger.info(f"[ResearchService] Updated task {task_id} status to {status.value}")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to update task status: {e}")
        finally:
            if self._db is None:
                db.close()
    
    def _save_plan_to_db(self, plan: ResearchPlanModel):
        """保存研究计划到数据库"""
        db = self._get_db()
        try:
            db_plan = DBResearchPlan(
                task_id=uuid.UUID(plan.task_id),
                directions=[d.to_dict() for d in plan.directions],
                is_confirmed=plan.is_confirmed,
            )
            db.add(db_plan)
            db.commit()
            db.refresh(db_plan)
            plan.id = str(db_plan.id)
            logger.info(f"[ResearchService] Saved plan {plan.id} to DB")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to save plan: {e}")
        finally:
            if self._db is None:
                db.close()
    
    def _save_direction_to_db(self, task_id: str, track: ResearchTrack):
        """保存研究方向进度到数据库"""
        db = self._get_db()
        try:
            # 查找或创建方向记录
            db_direction = db.query(DBResearchDirection).filter(
                DBResearchDirection.task_id == uuid.UUID(task_id),
                DBResearchDirection.direction_id == track.direction_id,
            ).first()
            
            if not db_direction:
                db_direction = DBResearchDirection(
                    task_id=uuid.UUID(task_id),
                    direction_id=track.direction_id,
                    name=track.name,
                )
                db.add(db_direction)
            
            # 更新状态
            db_direction.status = track.status.value
            db_direction.progress = track.progress
            db_direction.learnings = [l.to_dict() for l in track.learnings]
            db_direction.sources = [s.to_dict() for s in track.sources]
            db_direction.summary = track.summary
            
            if track.status == TrackStatus.EXPLORING:
                db_direction.started_at = datetime.now()
            elif track.status in (TrackStatus.COMPLETED, TrackStatus.FAILED):
                db_direction.completed_at = datetime.now()
            
            db.commit()
            logger.debug(f"[ResearchService] Saved direction {track.direction_id} to DB")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to save direction: {e}")
        finally:
            if self._db is None:
                db.close()
    
    # ============ 公共 API ============
    
    async def start_research(
        self,
        query: str,
        mode: ResearchMode,
        session_id: str,
    ) -> ResearchTaskModel:
        """
        发起研究任务
        
        Args:
            query: 用户问题
            mode: 研究模式
            session_id: 会话 ID
            
        Returns:
            创建的研究任务
        """
        # 1. 创建任务（数据库持久化）
        db_task = DBResearchTask(
            session_id=session_id,
            query=query,
            mode=mode.value,
            status=ResearchStatus.PENDING.value,
        )
        
        # 保存到数据库
        db = self._get_db()
        try:
            db.add(db_task)
            db.commit()
            db.refresh(db_task)
            
            logger.info(f"[ResearchService] Research task created in DB: {db_task.id}, mode={mode.value}, query={query[:50]}")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to create task in DB: {e}")
            raise
        finally:
            if self._db is None:
                db.close()
        
        # 2. 转换为内存模型
        task = self._db_task_to_model(db_task)
        self._tasks[task.id] = task
        task.started_at = datetime.now()
        
        # 3. 根据模式执行
        if mode == ResearchMode.STANDARD:
            # 标准模式：直接执行
            asyncio.create_task(self._execute_standard_research(task))
        else:
            # 深度模式：先分析问题
            asyncio.create_task(self._analyze_and_plan(task))
        
        return task
    
    async def resume_research(
        self,
        task_id: str,
        answer: str,
    ) -> ResearchTaskModel:
        """
        恢复暂停的研究（深度模式）
        
        Args:
            task_id: 任务 ID
            answer: 用户回答
            
        Returns:
            更新后的研究任务
        """
        task = self._get_task(task_id)
        
        if task.status != ResearchStatus.PENDING_CLARIFICATION:
            raise ResearchError(
                f"Task {task_id} is not in PENDING_CLARIFICATION state, "
                f"current state: {task.status.value}"
            )
        
        logger.info(f"Resuming research task {task_id} with answer: {answer[:50]}")
        
        # 记录用户回答
        if task.clarification_questions:
            # 简单起见，将回答关联到第一个未回答的问题
            for q in task.clarification_questions:
                if q.answer is None:
                    q.answer = answer
                    break
        
        # 创建状态机并转换状态
        sm = ResearchStateMachine.create_for_mode(task.mode)
        sm.current_state = ResearchState.PENDING_CLARIFICATION
        sm.transition(ResearchState.RESUMED, reason="User answered clarification")
        
        task.status = ResearchStatus.RESUMED
        task.update_timestamp()
        
        # 继续执行：生成研究计划
        asyncio.create_task(self._generate_and_confirm_plan(task, [answer]))
        
        return task
    
    async def cancel_research(self, task_id: str) -> bool:
        """
        取消研究任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            是否成功取消
        """
        task = self._get_task(task_id)
        
        if task.status in (ResearchStatus.COMPLETED, ResearchStatus.FAILED, ResearchStatus.CANCELLED):
            logger.warning(f"Cannot cancel task {task_id} in terminal state: {task.status.value}")
            return False
        
        logger.info(f"Cancelling research task {task_id}")
        
        # 更新状态
        task.status = ResearchStatus.CANCELLED
        task.update_timestamp()
        
        # 清理 Track
        tracks = self._tracks.get(task_id, [])
        for track in tracks:
            track.status = TrackStatus.FAILED
            track.error_message = "Research cancelled by user"
        
        # 清理去重缓存
        self.deduplicator.clear_session(task.session_id)
        
        return True
    
    async def get_status(self, task_id: str) -> dict:
        """
        获取研究状态
        
        Args:
            task_id: 任务 ID
            
        Returns:
            状态信息字典
        """
        task = self._get_task(task_id)
        
        # 收集 Track 进度
        tracks = self._tracks.get(task_id, [])
        directions_progress = [
            track.get_progress()
            for track in tracks
        ]
        
        return {
            "task_id": task.id,
            "status": task.status.value,
            "mode": task.mode.value,
            "query": task.query,
            "current_step": task.current_step,
            "progress": {
                "directions": directions_progress,
                "current_action": task.current_step,
            },
            "error_message": task.error_message,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
    
    async def get_plan(self, task_id: str) -> Optional[ResearchPlanModel]:
        """获取研究计划"""
        return self._plans.get(task_id)
    
    async def update_plan(
        self,
        task_id: str,
        plan: ResearchPlanModel,
    ) -> ResearchPlanModel:
        """
        更新研究计划
        
        Args:
            task_id: 任务 ID
            plan: 新的研究计划
            
        Returns:
            更新后的计划
        """
        task = self._get_task(task_id)
        
        if task.status != ResearchStatus.PENDING_CONFIRMATION:
            raise ResearchError(
                f"Cannot update plan in state: {task.status.value}"
            )
        
        plan.task_id = task_id
        plan.update_timestamp()
        self._plans[task_id] = plan
        
        logger.info(f"Plan updated for task {task_id}: {len(plan.directions)} directions")
        
        return plan
    
    async def confirm_plan(self, task_id: str) -> ResearchTaskModel:
        """
        确认研究计划并开始执行
        
        Args:
            task_id: 任务 ID
            
        Returns:
            更新后的任务
        """
        task = self._get_task(task_id)
        plan = self._plans.get(task_id)
        
        if not plan:
            raise ResearchError(f"No plan found for task {task_id}")
        
        if task.status != ResearchStatus.PENDING_CONFIRMATION:
            raise ResearchError(
                f"Cannot confirm plan in state: {task.status.value}"
            )
        
        logger.info(f"Plan confirmed for task {task_id}")
        
        # 更新状态
        plan.confirm()
        task.status = ResearchStatus.CONFIRMED
        task.update_timestamp()
        
        # 开始执行
        asyncio.create_task(self._execute_research(task, plan))
        
        return task
    
    async def generate_report(self, task_id: str) -> ResearchReportModel:
        """
        生成研究报告
        
        Args:
            task_id: 任务 ID
            
        Returns:
            研究报告
        """
        task = self._get_task(task_id)
        
        if task.status != ResearchStatus.COMPLETED:
            raise ResearchError(
                f"Cannot generate report in state: {task.status.value}"
            )
        
        # 收集所有 Track 的成果
        tracks = self._tracks.get(task_id, [])
        contexts = []
        
        for track in tracks:
            context = AgentContext(
                task_id=task_id,
                track_id=track.track_id,
                session_id=task.session_id,
                query=task.query,
                topic=track.topic,
                existing_learnings=track.learnings,
                existing_sources=track.sources,
            )
            contexts.append(context)
        
        # 使用 SynthesizerAgent 生成报告
        synthesizer = self._get_synthesizer_agent()
        result = synthesizer.synthesize(
            contexts=contexts,
            user_query=task.query,
            title=f"研究报告：{task.query[:50]}",
        )
        
        # 创建报告对象
        report = ResearchReportModel(
            task_id=task_id,
            title=f"研究报告：{task.query[:50]}",
            content_markdown=result.data.get("markdown", ""),
            source_count=len(result.sources),
        )
        report.calculate_word_count()
        
        logger.info(f"Report generated for task {task_id}: {report.word_count} words")
        
        return report
    
    # ============ 内部方法 ============
    
    async def _execute_standard_research(self, task: ResearchTaskModel):
        """
        执行标准研究流程
        
        Args:
            task: 研究任务
        """
        try:
            logger.info(f"Starting standard research for task {task.id}")
            
            # 1. 更新状态
            task.status = ResearchStatus.EXECUTING
            task.current_step = "正在生成研究计划"
            task.update_timestamp()
            
            # 2. 生成简单的研究计划
            plan = await self._generate_simple_plan(task)
            self._plans[task.id] = plan
            
            # 3. 执行研究
            await self._execute_research(task, plan)
            
        except ResearchCancelledError:
            logger.info(f"Research task {task.id} was cancelled")
        except Exception as e:
            logger.error(f"Standard research failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
    
    async def _analyze_and_plan(self, task: ResearchTaskModel):
        """
        分析问题并生成研究计划（深度模式）
        
        Args:
            task: 研究任务
        """
        try:
            logger.info(f"Starting deep research analysis for task {task.id}")
            
            # 1. 更新状态为分析中
            task.status = ResearchStatus.ANALYZING
            task.current_step = "正在分析问题"
            task.update_timestamp()
            
            # 推送进度
            await self._push_progress(task, "正在分析问题的核心意图")
            
            # 2. 分析问题（使用 LLM）
            analysis_result = await self._analyze_query(task.query)
            
            # 3. 判断是否需要澄清
            if analysis_result.get("needs_clarification", False):
                # 生成澄清问题
                questions = analysis_result.get("questions", [])
                task.clarification_questions = [
                    ClarificationQuestion(question=q)
                    for q in questions[:3]  # 最多 3 个问题
                ]
                task.status = ResearchStatus.PENDING_CLARIFICATION
                task.current_step = "等待用户回答澄清问题"
                task.update_timestamp()
                
                # 推送事件
                await self._push_clarification_needed(task, task.clarification_questions)
                
                logger.info(f"Task {task.id} waiting for clarification")
            else:
                # 无需澄清，直接生成计划
                await self._generate_and_confirm_plan(task, [])
            
        except Exception as e:
            logger.error(f"Deep research analysis failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
    
    async def _generate_and_confirm_plan(
        self,
        task: ResearchTaskModel,
        clarification_answers: list[str],
    ):
        """
        生成研究计划并等待确认
        
        Args:
            task: 研究任务
            clarification_answers: 用户澄清回答
        """
        try:
            # 1. 更新状态
            task.status = ResearchStatus.PLANNING
            task.current_step = "正在生成研究计划"
            task.update_timestamp()
            
            await self._push_progress(task, "正在生成研究计划")
            
            # 2. 使用 ToT 生成研究计划
            plan = await self._generate_plan_with_tot(task, clarification_answers)
            self._plans[task.id] = plan
            
            # 3. 等待用户确认
            task.status = ResearchStatus.PENDING_CONFIRMATION
            task.current_step = "等待用户确认研究计划"
            task.update_timestamp()
            
            # 推送计划生成事件
            await self._push_plan_generated(task, plan)
            
            logger.info(f"Plan generated for task {task.id}, waiting for confirmation")
            
        except Exception as e:
            logger.error(f"Plan generation failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
    
    async def _execute_research(self, task: ResearchTaskModel, plan: ResearchPlanModel):
        """
        执行研究（并行各方向）
        
        Args:
            task: 研究任务
            plan: 研究计划
        """
        try:
            logger.info(f"Executing research for task {task.id} with {len(plan.directions)} directions")
            
            # 1. 更新状态
            task.status = ResearchStatus.EXECUTING
            task.current_step = "正在执行研究"
            task.update_timestamp()
            
            # 2. 为每个方向创建 Track
            tracks = []
            for direction_spec in plan.directions:
                track = self.track_manager.create_track(
                    session_id=task.session_id,
                    task_id=task.id,
                    direction_spec=direction_spec,
                )
                track.started_at = datetime.now()
                tracks.append(track)
                
                # 注册到 SSE Gateway
                sse_gateway.register_track(track.track_id, task.session_id)
            
            self._tracks[task.id] = tracks
            
            # 3. 并行执行所有研究方向
            results = await asyncio.gather(*[
                self._execute_direction(task, track)
                for track in tracks
            ], return_exceptions=True)
            
            # 4. 检查结果
            failed_count = sum(1 for r in results if isinstance(r, Exception))
            if failed_count > 0:
                logger.warning(f"{failed_count}/{len(tracks)} directions failed")
            
            # 5. 生成最终报告
            task.current_step = "正在生成研究报告"
            task.update_timestamp()
            await self._push_progress(task, "正在生成研究报告")
            
            report = await self.generate_report(task.id)
            
            # 6. 完成
            task.status = ResearchStatus.COMPLETED
            task.completed_at = datetime.now()
            task.update_timestamp()
            
            # 推送完成事件
            await self._push_completed(task, report)
            
            logger.info(f"Research completed for task {task.id}")
            
        except ResearchCancelledError:
            logger.info(f"Research task {task.id} was cancelled during execution")
        except Exception as e:
            logger.error(f"Research execution failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
    
    async def _execute_direction(
        self,
        task: ResearchTaskModel,
        track: ResearchTrack,
    ) -> AgentResult:
        """
        执行单个研究方向
        
        Args:
            task: 研究任务
            track: 研究轨道
            
        Returns:
            执行结果
        """
        try:
            logger.info(f"Executing direction {track.direction_id} for task {task.id}")
            
            # 推送进度
            await self._push_track_progress(track, "exploring", "正在搜索相关信息", 0)
            
            # Phase 1: 探索（搜索）
            explorer = self._get_explorer_agent()
            explorer_context = AgentContext(
                task_id=task.id,
                track_id=track.track_id,
                session_id=task.session_id,
                query=task.query,
                topic=track.topic,
                direction_keywords=track.plan[0].description.split() if track.plan else [],
                visited_urls=track.visited_urls,
                searched_queries=track.searched_queries,
            )
            
            explore_result = explorer.execute(explorer_context, track)
            
            if not explore_result.success:
                track.fail_current_step(explore_result.error)
                return explore_result
            
            # 更新 Track
            for source in explore_result.sources:
                track.add_source(source)
            for learning in explore_result.learnings:
                track.add_learning(learning)
            
            track.advance_step()
            
            # 推送进度
            await self._push_track_progress(track, "analyzing", "正在分析搜索结果", 33)
            
            # Phase 2: 分析
            analyzer = self._get_analyzer_agent()
            analyzer_context = AgentContext(
                task_id=task.id,
                track_id=track.track_id,
                session_id=task.session_id,
                query=task.query,
                topic=track.topic,
                existing_learnings=track.learnings,
                existing_sources=track.sources,
            )
            
            analyze_result = analyzer.execute(analyzer_context, track)
            
            if not analyze_result.success:
                track.fail_current_step(analyze_result.error)
                return analyze_result
            
            # 更新 Track
            for learning in analyze_result.learnings:
                track.add_learning(learning)
            
            track.advance_step()
            
            # 推送进度
            await self._push_track_progress(track, "synthesizing", "正在总结研究发现", 66)
            
            # Phase 3: 总结
            synthesizer = self._get_synthesizer_agent()
            synthesizer_context = AgentContext(
                task_id=task.id,
                track_id=track.track_id,
                session_id=task.session_id,
                query=task.query,
                topic=track.topic,
                existing_learnings=track.learnings,
                existing_sources=track.sources,
            )
            
            synthesis_result = synthesizer.execute(synthesizer_context, track)
            
            if synthesis_result.success:
                track.context["summary"] = synthesis_result.data.get("markdown", "")
                track.advance_step()
                await self._push_track_progress(track, "completed", "研究方向完成", 100)
            else:
                track.fail_current_step(synthesis_result.error)
            
            return synthesis_result
            
        except Exception as e:
            logger.error(f"Direction execution failed: {e}", exc_info=True)
            track.fail_current_step(str(e))
            raise
    
    # ============ Agent 管理 ============
    
    def _get_explorer_agent(self) -> ExplorerAgent:
        """获取探索型 Agent"""
        # 简单实现：创建新实例
        # 实际可以使用 Agent 池
        return ExplorerAgent(tools=self._get_search_tools())
    
    def _get_analyzer_agent(self) -> AnalyzerAgent:
        """获取分析型 Agent"""
        return AnalyzerAgent(tools=[])
    
    def _get_synthesizer_agent(self) -> SynthesizerAgent:
        """获取总结型 Agent"""
        return SynthesizerAgent(tools=[])
    
    def _get_search_tools(self) -> list:
        """获取搜索工具列表"""
        try:
            # 初始化 MCP Registry
            mcp_registry.initialize()
            
            # 同步工具
            mcp_tools_manager.sync_from_registry()
            
            # 获取搜索类别的工具
            search_tools = mcp_registry.get_tools_by_category('search')
            
            if search_tools:
                tools = []
                for tool_info in search_tools:
                    tool = mcp_tools_manager.get_tool(tool_info.name)
                    if tool:
                        tools.append(tool)
                        logger.info(f"[ResearchService] Loaded MCP search tool: {tool_info.name}")
                return tools
            
            logger.warning("[ResearchService] No search tools available from MCP Registry")
            return []
            
        except Exception as e:
            logger.error(f"[ResearchService] Failed to get search tools: {e}")
            return []
    
    # ============ 辅助方法 ============
    
    def _get_task(self, task_id: str) -> ResearchTaskModel:
        """获取研究任务"""
        # 先从内存缓存获取
        task = self._tasks.get(task_id)
        if task:
            return task
        
        # 从数据库加载
        db = self._get_db()
        try:
            db_task = db.query(DBResearchTask).filter(DBResearchTask.id == uuid.UUID(task_id)).first()
            if not db_task:
                raise ResearchError(f"Task not found: {task_id}")
            
            task = self._db_task_to_model(db_task)
            self._tasks[task_id] = task
            return task
        finally:
            if self._db is None:
                db.close()
    
    async def _analyze_query(self, query: str) -> dict:
        """分析用户问题（使用 LLM）"""
        try:
            from agent.llm import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm = get_llm(streaming=False)
            
            prompt = f"""分析以下用户问题，判断是否需要澄清才能进行深入研究。

用户问题：{query}

请按以下 JSON 格式返回分析结果：
{{
  "needs_clarification": true/false,
  "questions": ["问题1", "问题2", "问题3"],  // 如果需要澄清，列出最多3个问题
  "analysis": "问题分析摘要"
}}

判断标准：
1. 问题是否明确、具体？
2. 是否需要了解用户的知识背景？
3. 是否有多个可能的研究方向需要用户选择？

只返回 JSON，不要其他内容。"""
            
            messages = [
                SystemMessage(content="你是一个研究分析专家，擅长分析用户问题的清晰度和研究价值。"),
                HumanMessage(content=prompt)
            ]
            
            response = llm.invoke(messages)
            result_text = response.content.strip()
            
            # 尝试解析 JSON
            try:
                # 提取 JSON 部分
                if '```json' in result_text:
                    result_text = result_text.split('```json')[1].split('```')[0].strip()
                elif '```' in result_text:
                    result_text = result_text.split('```')[1].split('```')[0].strip()
                
                result = json.loads(result_text)
                logger.info(f"[ResearchService] Query analysis result: needs_clarification={result.get('needs_clarification')}")
                return result
            except json.JSONDecodeError:
                logger.warning(f"[ResearchService] Failed to parse LLM response as JSON: {result_text[:100]}")
                return {
                    "needs_clarification": False,
                    "questions": [],
                    "analysis": query,
                }
                
        except Exception as e:
            logger.error(f"[ResearchService] LLM query analysis failed: {e}")
            return {
                "needs_clarification": False,
                "questions": [],
                "analysis": query,
            }
    
    async def _generate_simple_plan(self, task: ResearchTaskModel) -> ResearchPlanModel:
        """生成简单的研究计划（使用 LLM）"""
        try:
            from agent.llm import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm = get_llm(streaming=False)
            
            prompt = f"""为以下研究问题生成研究计划，包含2-3个研究方向。

用户问题：{task.query}

请按以下 JSON 格式返回：
{{
  "directions": [
    {{
      "name": "研究方向名称",
      "description": "方向描述",
      "keywords": ["关键词1", "关键词2"]
    }}
  ]
}}

要求：
1. 每个方向应覆盖问题的不同方面
2. 方向之间应互补而非重复
3. 关键词应便于搜索

只返回 JSON，不要其他内容。"""
            
            messages = [
                SystemMessage(content="你是一个研究规划专家，擅长将复杂问题拆解为可执行的研究方向。"),
                HumanMessage(content=prompt)
            ]
            
            response = llm.invoke(messages)
            result_text = response.content.strip()
            
            # 解析 JSON
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()
            
            result = json.loads(result_text)
            
            # 创建计划
            directions = [
                DirectionSpec(
                    name=d.get("name", "未命名方向"),
                    description=d.get("description", ""),
                    keywords=d.get("keywords", []),
                    priority=i+1,
                )
                for i, d in enumerate(result.get("directions", []))
            ]
            
            if not directions:
                directions = [DirectionSpec(
                    name=f"研究 {task.query[:30]}",
                    description=task.query,
                    keywords=task.query.split()[:5],
                )]
            
            plan = ResearchPlanModel(
                task_id=task.id,
                directions=directions,
            )
            plan.is_confirmed = True  # 标准模式自动确认
            
            logger.info(f"[ResearchService] Generated simple plan with {len(directions)} directions")
            return plan
            
        except Exception as e:
            logger.error(f"[ResearchService] Failed to generate simple plan: {e}")
            # 降级：生成默认方向
            plan = ResearchPlanModel(
                task_id=task.id,
                directions=[
                    DirectionSpec(
                        name=f"研究 {task.query[:30]}",
                        description=task.query,
                        keywords=task.query.split()[:5],
                    )
                ],
            )
            plan.is_confirmed = True
            return plan
    
    async def _generate_plan_with_tot(
        self,
        task: ResearchTaskModel,
        clarification_answers: list[str],
    ) -> ResearchPlanModel:
        """使用 ToT（Tree of Thoughts）生成研究计划"""
        try:
            from agent.llm import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            
            llm = get_llm(streaming=False)
            
            # 构建上下文
            context = f"用户问题：{task.query}\n\n"
            if clarification_answers:
                context += "用户澄清回答：\n"
                for i, answer in enumerate(clarification_answers, 1):
                    context += f"{i}. {answer}\n"
                context += "\n"
            
            prompt = f"""{context}基于以上信息，使用思维树（Tree of Thoughts）方法生成研究计划。

要求：
1. 从不同角度（技术、应用、理论、实践等）生成 3-5 条研究方向
2. 每条方向需包含：名称、描述、关键词、预期发现
3. 方向之间应互补而非重复
4. 考虑用户的澄清回答

请按以下 JSON 格式返回：
{{
  "thoughts": [
    "推理过程1",
    "推理过程2"
  ],
  "directions": [
    {{
      "name": "研究方向名称",
      "description": "方向描述",
      "keywords": ["关键词1", "关键词2"],
      "expected_findings": "预期发现"
    }}
  ]
}}

只返回 JSON。"""
            
            messages = [
                SystemMessage(content="你是一个研究规划专家，擅长使用思维树方法探索研究方向。"),
                HumanMessage(content=prompt)
            ]
            
            response = llm.invoke(messages)
            result_text = response.content.strip()
            
            # 解析 JSON
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()
            
            result = json.loads(result_text)
            
            # 创建计划
            directions = [
                DirectionSpec(
                    name=d.get("name", "未命名方向"),
                    description=d.get("description", ""),
                    keywords=d.get("keywords", []),
                    priority=i+1,
                )
                for i, d in enumerate(result.get("directions", []))
            ]
            
            if not directions:
                raise ValueError("No directions generated")
            
            plan = ResearchPlanModel(
                task_id=task.id,
                directions=directions,
            )
            
            logger.info(f"[ResearchService] Generated ToT plan with {len(directions)} directions")
            return plan
            
        except Exception as e:
            logger.error(f"[ResearchService] ToT plan generation failed: {e}")
            # 降级：生成默认方向
            return ResearchPlanModel(
                task_id=task.id,
                directions=[
                    DirectionSpec(
                        name=f"方向 1: {task.query[:20]}",
                        description=f"研究 {task.query} 的第一个方向",
                        keywords=task.query.split()[:3],
                    ),
                    DirectionSpec(
                        name=f"方向 2: {task.query[:20]}",
                        description=f"研究 {task.query} 的第二个方向",
                        keywords=task.query.split()[3:6] if len(task.query.split()) > 3 else task.query.split(),
                    ),
                ],
            )
    
    # ============ SSE 推送 ============
    
    async def _push_progress(self, task: ResearchTaskModel, message: str):
        """推送进度更新"""
        # 找到第一个 Track（用于路由）
        tracks = self._tracks.get(task.id, [])
        track_id = tracks[0].track_id if tracks else ""
        
        await sse_gateway.push(
            event_type="progress",
            task_id=task.id,
            track_id=track_id,
            data={
                "summary": message,
                "progress_pct": 0,
            },
        )
    
    async def _push_track_progress(
        self,
        track: ResearchTrack,
        phase: str,
        message: str,
        progress_pct: int,
    ):
        """推送 Track 进度"""
        await sse_gateway.push(
            event_type="progress",
            task_id=track.task_id,
            track_id=track.track_id,
            data={
                "phase": phase,
                "summary": message,
                "progress_pct": progress_pct,
            },
        )
    
    async def _push_clarification_needed(
        self,
        task: ResearchTaskModel,
        questions: list[ClarificationQuestion],
    ):
        """推送需要澄清事件"""
        tracks = self._tracks.get(task.id, [])
        track_id = tracks[0].track_id if tracks else ""
        
        await sse_gateway.push(
            event_type="clarification_needed",
            task_id=task.id,
            track_id=track_id,
            data={
                "questions": [q.to_dict() for q in questions],
            },
        )
    
    async def _push_plan_generated(self, task: ResearchTaskModel, plan: ResearchPlanModel):
        """推送计划生成事件"""
        tracks = self._tracks.get(task.id, [])
        track_id = tracks[0].track_id if tracks else ""
        
        await sse_gateway.push(
            event_type="plan_generated",
            task_id=task.id,
            track_id=track_id,
            data={
                "directions": [d.to_dict() for d in plan.directions],
            },
        )
    
    async def _push_completed(self, task: ResearchTaskModel, report: ResearchReportModel):
        """推送完成事件"""
        tracks = self._tracks.get(task.id, [])
        track_id = tracks[0].track_id if tracks else ""
        
        await sse_gateway.push(
            event_type="completed",
            task_id=task.id,
            track_id=track_id,
            data={
                "report_id": report.id,
                "word_count": report.word_count,
                "source_count": report.source_count,
            },
        )
