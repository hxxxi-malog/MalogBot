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
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any, Optional, Dict
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
from services.deep_research.event_buffer import event_buffer

# 导入数据库模型
from models.research import (
    ResearchTask as DBResearchTask,
    ResearchPlan as DBResearchPlan,
    ResearchDirection as DBResearchDirection,
    ResearchReport as DBResearchReport,
    ResearchSearch as DBResearchSearch,
)
from services.db_manager import db_manager

# 导入会话存储，用于持久化研究消息到聊天历史
from services.session_store import session_store

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


# ============ 后台异步任务执行器 ============

class BackgroundAsyncExecutor:
    """
    后台异步任务执行器
    
    解决 Flask 同步框架中 asyncio.create_task 无法正常工作的问题。
    维护一个持久的后台线程，运行事件循环来执行异步任务。
    """
    
    _instance = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _thread: Optional[threading.Thread] = None
    _tasks: Dict[str, asyncio.Task] = {}
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._start_background_loop()
        return cls._instance
    
    @classmethod
    def _start_background_loop(cls):
        """启动后台事件循环线程"""
        def run_loop():
            cls._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(cls._loop)
            logger.info("[BackgroundExecutor] Background event loop started")
            cls._loop.run_forever()
        
        cls._thread = threading.Thread(target=run_loop, daemon=True, name="BackgroundAsyncExecutor")
        cls._thread.start()
        
        # 等待事件循环启动
        while cls._loop is None:
            time.sleep(0.01)
    
    @classmethod
    def submit(cls, coro, task_id: Optional[str] = None) -> asyncio.Task:
        """
        提交异步任务到后台执行
        
        Args:
            coro: 协程对象
            task_id: 可选的任务ID，用于追踪
            
        Returns:
            asyncio.Task 对象
        """
        if cls._loop is None:
            raise RuntimeError("Background event loop not initialized")
        
        # 在后台事件循环中创建任务
        future = asyncio.run_coroutine_threadsafe(coro, cls._loop)
        task = future  # 返回 future 以便调用者可以等待
        
        if task_id:
            with cls._lock:
                cls._tasks[task_id] = task
        
        logger.debug(f"[BackgroundExecutor] Submitted task: {task_id or 'anonymous'}")
        return task
    
    @classmethod
    def get_task(cls, task_id: str) -> Optional[asyncio.Task]:
        """获取任务"""
        with cls._lock:
            return cls._tasks.get(task_id)
    
    @classmethod
    def remove_task(cls, task_id: str):
        """移除任务"""
        with cls._lock:
            cls._tasks.pop(task_id, None)
    
    @classmethod
    def shutdown(cls):
        """关闭后台执行器"""
        if cls._loop:
            cls._loop.call_soon_threadsafe(cls._loop.stop)
        if cls._thread:
            cls._thread.join(timeout=5)
        logger.info("[BackgroundExecutor] Shutdown complete")


# 全局后台执行器实例
background_executor = BackgroundAsyncExecutor()


# ============ SSE 网关 ============

class SSEGateway:
    """
    SSE 消息网关
    
    管理多 Track 消息路由，支持单连接多路复用。
    使用 connection_id 防止旧连接误删新连接（同一 session 复用时）。
    
    关键设计：使用 queue.SimpleQueue 替代 asyncio.Queue
    - asyncio.Queue 绑定事件循环，跨 loop 的 put 不会唤醒另一个 loop 的 get
    - SimpleQueue 是线程安全的，不依赖事件循环，可跨线程/事件循环安全使用
    """
    
    def __init__(self):
        import queue as _queue
        self._connections: dict[str, tuple[str, _queue.SimpleQueue]] = {}  # session_id -> (connection_id, SimpleQueue)
        self._track_to_session: dict[str, str] = {}  # track_id -> session_id
        logger.info("SSE Gateway initialized (thread-safe SimpleQueue)")
    
    def subscribe(self, session_id: str, task_id: str = None, last_seq_no: str = "0-0"):
        """
        前端建立 SSE 连接（同步方法，在 Flask 请求线程中调用）
        
        Args:
            session_id: 会话 ID
            task_id: 任务 ID（用于回放 Redis STREAM 历史事件）
            last_seq_no: 前端最后接收到的事件 ID（"0-0" 表示从头回放）
            
        Returns:
            (connection_id, 消息队列) - connection_id 用于 unsubscribe 时防止误删新连接
        """
        import uuid
        import queue as _queue
        connection_id = str(uuid.uuid4())
        q = _queue.SimpleQueue()

        # 先回放 Redis STREAM 历史事件到队列，再注册连接
        # 顺序很重要：先回放再注册，确保 push_to_session 只在注册后推送实时事件
        # 避免回放和实时推送的竞态（即使无锁也安全：注册前的 push 会被丢弃，
        # 但那些事件已在 Redis STREAM 中，下次重连时可回放）
        replay_count = 0
        if task_id:
            buffered_events = event_buffer.replay(task_id, after_seq_no=last_seq_no)
            for evt in buffered_events:
                q.put(evt)
            replay_count = len(buffered_events)
            logger.info(f"[SSEGateway] Replayed {replay_count} events for session={session_id} task={task_id} after={last_seq_no}")

        # 注册连接（放在回放之后，避免竞态）
        self._connections[session_id] = (connection_id, q)
        logger.info(f"[SSEGateway] SSE connection established for session: {session_id}, conn_id: {connection_id}, replayed: {replay_count}, active_sessions: {list(self._connections.keys())}")
        return connection_id, q
    
    def unsubscribe(self, session_id: str, connection_id: str):
        """
        断开 SSE 连接
        
        仅当 connection_id 匹配时才删除，防止旧连接误删新连接。
        """
        if session_id in self._connections:
            stored_conn_id, _ = self._connections[session_id]
            if stored_conn_id == connection_id:
                del self._connections[session_id]
                logger.info(f"[SSEGateway] SSE connection closed for session: {session_id}, conn_id: {connection_id}")
            else:
                logger.info(f"[SSEGateway] Skipping unsubscribe for stale connection: session={session_id}, old_conn={connection_id}, current_conn={stored_conn_id}")
        else:
            logger.info(f"[SSEGateway] Session {session_id} already removed from connections")
    
    def register_track(self, track_id: str, session_id: str):
        """注册 Track 到 Session 映射"""
        self._track_to_session[track_id] = session_id
    
    def push(
        self,
        event_type: str,
        task_id: str,
        track_id: str,
        data: dict,
    ) -> bool:
        """
        Track 推送消息（同步方法，线程安全）
        
        Args:
            event_type: 事件类型
            task_id: 任务 ID
            track_id: 轨道 ID
            data: 事件数据
            
        Returns:
            是否成功推送
        """
        session_id = self._track_to_session.get(track_id)
        if not session_id:
            logger.warning(f"No session found for track: {track_id}")
            return False
        
        return self.push_to_session(event_type, task_id, session_id, data, track_id=track_id)
    
    def push_to_session(
        self,
        event_type: str,
        task_id: str,
        session_id: str,
        data: dict,
        track_id: str = "",
    ) -> bool:
        """
        直接推送到 Session（同步方法，线程安全，不依赖事件循环）
        
        使用 SimpleQueue.put() 实现跨线程/跨事件循环推送。
        可在任意线程和事件循环中调用。
        
        Args:
            event_type: 事件类型
            task_id: 任务 ID
            session_id: 会话 ID
            data: 事件数据
            track_id: 轨道 ID（可选）
            
        Returns:
            是否成功推送
        """
        msg = {
            "event": event_type,
            "task_id": task_id,
            "track_id": track_id,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        # 写入 Redis STREAM（轻量操作，<1ms），双写保证断线可回放
        try:
            seq_no = event_buffer.write(task_id, event_type, data)
            msg["seq_no"] = seq_no  # Redis 自增 ID 附加到消息中
            logger.debug(f"[SSEGateway] EventBuffer write success: task={task_id} seq_no={seq_no}")
        except Exception as e:
            logger.warning(f"[SSEGateway] EventBuffer write failed: {e}, continuing without seq_no")
            msg["seq_no"] = "0-0"  # 降级：不中断实时推送

        if session_id not in self._connections:
            logger.warning(f"[SSEGateway] No SSE connection for session: {session_id}, active_sessions={list(self._connections.keys())}")
            return False

        _, q = self._connections[session_id]
        q.put(msg)  # SimpleQueue.put() 线程安全，永不阻塞
        logger.info(f"[SSEGateway] Pushed event {event_type} to session {session_id} seq_no={msg.get('seq_no', 'N/A')}")
        return True


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
        发起研究任务（单阶段启动）

        创建任务并立即提交异步执行，前端通过 Redis STREAM 回放机制
        确保不丢失事件，无需两阶段启动。

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

        db = self._get_db()
        try:
            db.add(db_task)
            db.commit()
            db.refresh(db_task)
            logger.info(f"[ResearchService] Task created: {db_task.id}, mode={mode.value}, session={session_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to create task: {e}")
            raise
        finally:
            if self._db is None:
                db.close()

        # 2. 转换为内存模型
        task = self._db_task_to_model(db_task)
        self._tasks[task.id] = task
        started_at = datetime.now()
        task.started_at = started_at

        # 将 started_at 持久化到数据库，确保刷新后 duration_seconds 计算一致
        self._update_task_status(task.id, ResearchStatus.PENDING, started_at=started_at)
        logger.info(f"[ResearchService] Task {task.id} started_at persisted to DB: {started_at}")

        # 3. 立即提交异步执行（Redis STREAM 保证事件不丢失）
        if task.mode == ResearchMode.STANDARD:
            background_executor.submit(self._execute_standard_research(task), task_id=f"research_{task.id}")
        else:
            background_executor.submit(self._analyze_and_plan(task), task_id=f"research_{task.id}")

        logger.info(f"[ResearchService] Research execution submitted for task {task.id}")

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
        
        # 继续执行：生成研究计划（使用后台执行器）
        background_executor.submit(self._generate_and_confirm_plan(task, [answer]), task_id=f"resume_{task_id}")
        
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
        
        # 持久化取消状态到数据库，确保刷新后前端能正确判断任务已终止
        self._update_task_status(task_id, ResearchStatus.CANCELLED, completed_at=datetime.now())
        logger.info(f"[ResearchService] Cancelled task {task_id} status persisted to database")
        
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
        
        # 开始执行（使用后台执行器）
        background_executor.submit(self._execute_research(task, plan), task_id=f"execute_{task_id}")
        
        logger.info(f"[ResearchService] Research execution submitted for task {task_id}")
        
        return task
    
    async def generate_report(self, task_id: str) -> ResearchReportModel:
        """
        生成研究报告（非流式，用于后续调用）

        Args:
            task_id: 任务 ID

        Returns:
            研究报告
        """
        from services.deep_research.report_generator import ReportGenerator

        task = self._get_task(task_id)

        # 从数据库加载研究方向数据
        db = self._get_db()
        try:
            db_directions = db.query(DBResearchDirection).filter(
                DBResearchDirection.task_id == uuid.UUID(task_id)
            ).all()

            # 获取研究计划
            db_plan = db.query(DBResearchPlan).filter(
                DBResearchPlan.task_id == uuid.UUID(task_id)
            ).first()

            # 转换为内存模型
            direction_models = []
            for d in db_directions:
                dir_model = ResearchDirectionModel(
                    id=str(d.id),
                    task_id=str(d.task_id),
                    direction_id=d.direction_id,
                    name=d.name,
                    status=d.status,
                    progress=d.progress,
                    summary=d.summary or "",
                )
                # 添加学习成果
                if d.learnings:
                    for l_data in d.learnings:
                        dir_model.learnings.append(Learning.from_dict(l_data))
                # 添加来源
                if d.sources:
                    for s_data in d.sources:
                        dir_model.sources.append(Source.from_dict(s_data))
                direction_models.append(dir_model)

            # 转换计划
            plan_model = None
            if db_plan:
                plan_model = ResearchPlanModel(
                    id=str(db_plan.id),
                    task_id=str(db_plan.task_id),
                    directions=[
                        DirectionSpec.from_dict(d)
                        for d in (db_plan.directions or [])
                    ],
                )

            # 使用 ReportGenerator 生成报告
            generator = ReportGenerator()
            markdown_content = generator.generate_markdown(
                task,
                plan_model,
                direction_models,
            )

            # 创建报告对象
            report = ResearchReportModel(
                task_id=task_id,
                title=f"研究报告：{task.query[:50]}",
                content_markdown=markdown_content,
                source_count=sum(len(d.sources) for d in direction_models),
            )
            report.calculate_word_count()

            logger.info(f"[ResearchService] Report generated for task {task_id}: {report.word_count} words")

            return report

        finally:
            if self._db is None:
                db.close()
    
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
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, "[研究已取消]"
            )
        except Exception as e:
            logger.error(f"Standard research failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
            # 持久化错误消息到会话历史
            error_msg = f"研究执行失败: {str(e)}"
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, error_msg
            )
            logger.info(f"[ResearchService] Error message persisted for failed standard task {task.id}")
    
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
            self._push_progress(task, "正在分析问题的核心意图")
            
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
                self._push_clarification_needed(task, task.clarification_questions)
                
                logger.info(f"Task {task.id} waiting for clarification")
            else:
                # 无需澄清，直接生成计划
                await self._generate_and_confirm_plan(task, [])
            
        except Exception as e:
            logger.error(f"Deep research analysis failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
            # 持久化错误消息到会话历史
            error_msg = f"研究分析失败: {str(e)}"
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, error_msg
            )
            logger.info(f"[ResearchService] Error message persisted for failed deep task {task.id}")
    
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
            
            self._push_progress(task, "正在生成研究计划")
            
            # 2. 使用 ToT 生成研究计划
            plan = await self._generate_plan_with_tot(task, clarification_answers)
            self._plans[task.id] = plan
            
            # 3. 等待用户确认
            task.status = ResearchStatus.PENDING_CONFIRMATION
            task.current_step = "等待用户确认研究计划"
            task.update_timestamp()
            
            # 推送计划生成事件
            self._push_plan_generated(task, plan)
            
            # 计划生成完成，刷盘更新 assistant 占位消息
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, "研究计划已生成，等待用户确认"
            )
            logger.info(f"[ResearchService] Plan generated message persisted for task {task.id}")

            logger.info(f"Plan generated for task {task.id}, waiting for confirmation")
            
        except Exception as e:
            logger.error(f"Plan generation failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
            # 持久化错误消息到会话历史
            error_msg = f"研究计划生成失败: {str(e)}"
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, error_msg
            )
            logger.info(f"[ResearchService] Error message persisted for failed plan task {task.id}")
    
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
            
            # 记录开始时间，用于计算 elapsed_seconds
            research_start_time = time.time()
            
            # 2. 为每个方向创建 Track
            tracks = []
            direction_progress_list = []
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
                
                # 构建方向进度数据
                direction_progress_list.append({
                    "direction_id": track.direction_id,
                    "direction_name": track.topic,
                    "status": "pending",
                    "progress": 0,
                    "current_action": "等待开始",
                    "learnings_count": 0,
                    "sources_count": 0,
                })
            
            self._tracks[task.id] = tracks
            
            # 3. 推送初始研究进度事件（包含所有方向）
            # 事件类型不加 research_ 前缀，前端 useStream.ts 会自动添加
            elapsed = int(time.time() - research_start_time)
            sse_gateway.push_to_session(
                event_type="progress",
                task_id=task.id,
                session_id=task.session_id,
                data={
                    "progress": {
                        "task_id": task.id,
                        "status": "executing",
                        "mode": task.mode.value,
                        "progress_pct": 0,
                        "elapsed_seconds": elapsed,
                        "directions": direction_progress_list,
                        "current_action": "研究计划已确认，开始执行研究...",
                    }
                },
            )
            logger.info(f"[ResearchService] Initial research progress pushed for task {task.id}")
            
            # 4. 启动定时进度推送任务（每5秒推送一次带最新 elapsed_seconds 的进度）
            progress_update_stop = asyncio.Event()
            
            async def periodic_progress_update():
                """定期推送研究进度更新（更新 elapsed_seconds 和方向状态）"""
                while not progress_update_stop.is_set():
                    try:
                        await asyncio.wait_for(progress_update_stop.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass  # 正常超时，继续推送
                    
                    if progress_update_stop.is_set():
                        break
                    
                    # 收集当前各方向状态（Track 已有 progress/current_action 属性，直接读取）
                    current_directions = []
                    for t in tracks:
                        current_directions.append({
                            "direction_id": t.direction_id,
                            "direction_name": t.topic,
                            "status": t.status.value,
                            "progress": t.progress,
                            "current_action": t.current_action,
                            "learnings_count": len(t.learnings),
                            "sources_count": len(t.sources),
                        })
                    
                    elapsed_now = int(time.time() - research_start_time)
                    sse_gateway.push_to_session(
                        event_type="progress",
                        task_id=task.id,
                        session_id=task.session_id,
                        data={
                            "progress": {
                                "task_id": task.id,
                                "status": "executing",
                                "mode": task.mode.value,
                                "progress_pct": 0,
                                "elapsed_seconds": elapsed_now,
                                "directions": current_directions,
                                "current_action": task.current_step or "正在执行研究",
                            }
                        },
                    )
                    logger.debug(f"[ResearchService] Periodic progress update for task {task.id}, elapsed={elapsed_now}s")
            
            # 启动定时进度更新
            progress_task = asyncio.create_task(periodic_progress_update())
            
            # 5. 并行执行所有研究方向
            logger.info(f"[ResearchService] Starting parallel execution of {len(tracks)} directions")
            
            async def run_direction_in_thread(track: ResearchTrack) -> AgentResult:
                """在线程池中执行单个研究方向"""
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,  # 使用默认线程池
                    lambda: self._execute_direction_sync(task, track)
                )
            
            results = await asyncio.gather(*[
                run_direction_in_thread(track)
                for track in tracks
            ], return_exceptions=True)
            
            # 停止定时进度推送
            progress_update_stop.set()
            try:
                await asyncio.wait_for(progress_task, timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(f"[ResearchService] Progress update task did not stop in time for task {task.id}")
            
            # 6. 检查结果
            failed_count = sum(1 for r in results if isinstance(r, Exception))
            if failed_count > 0:
                logger.warning(f"{failed_count}/{len(tracks)} directions failed")
            
            # 7. 推送研究方向全部完成进度
            final_directions = []
            for t in tracks:
                final_directions.append({
                    "direction_id": t.direction_id,
                    "direction_name": t.topic,
                    "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                    "progress": 100 if (hasattr(t, 'status') and t.status == TrackStatus.COMPLETED) else (t.progress if hasattr(t, 'progress') else 0),
                    "current_action": "研究方向完成" if (hasattr(t, 'status') and t.status == TrackStatus.COMPLETED) else "研究方向失败",
                    "learnings_count": len(t.learnings) if hasattr(t, 'learnings') else 0,
                    "sources_count": len(t.sources) if hasattr(t, 'sources') else 0,
                })
            
            elapsed_final = int(time.time() - research_start_time)
            sse_gateway.push_to_session(
                event_type="progress",
                task_id=task.id,
                session_id=task.session_id,
                data={
                    "progress": {
                        "task_id": task.id,
                        "status": "generating_report",
                        "mode": task.mode.value,
                        "progress_pct": 80,
                        "elapsed_seconds": elapsed_final,
                        "directions": final_directions,
                        "current_action": "所有研究方向已完成，正在聚合生成研究报告...",
                    }
                },
            )
            logger.info(f"[ResearchService] All directions completed for task {task.id}, generating report")
            
            # 8. 流式生成最终报告
            task.current_step = "正在生成研究报告"
            task.update_timestamp()
            self._push_progress(task, "正在聚合所有方向的研究结果，生成研究报告...")
            
            # 使用流式报告生成
            report = await self._generate_report_stream(task, tracks)
            
            # 9. 完成
            task.status = ResearchStatus.COMPLETED
            task.completed_at = datetime.now()
            task.update_timestamp()
            
            # 推送完成事件
            self._push_completed(task, report)

            # 持久化助手消息到会话历史，确保刷新后可恢复
            assistant_content = report.content_markdown or ''
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, assistant_content
            )
            logger.info(f"[ResearchService] Assistant message persisted for task {task.id}, content_length={len(assistant_content)}")

            # PDF generation removed - use Markdown copy instead
            
            logger.info(f"Research completed for task {task.id}")
            
        except ResearchCancelledError:
            logger.info(f"Research task {task.id} was cancelled during execution")
            # 持久化取消状态消息
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, "[研究已取消]"
            )
        except Exception as e:
            logger.error(f"Research execution failed for task {task.id}: {e}", exc_info=True)
            task.status = ResearchStatus.FAILED
            task.error_message = str(e)
            task.update_timestamp()
            # 持久化错误消息到会话历史
            error_msg = f"研究执行失败: {str(e)}"
            session_store.update_message_by_research_task_id(
                task.session_id, task.id, error_msg
            )
            logger.info(f"[ResearchService] Error message persisted for failed task {task.id}")
            # 推送错误事件
            try:
                sse_gateway.push_to_session(
                    event_type="error",
                    task_id=task.id,
                    session_id=task.session_id,
                    data={
                        "error_message": str(e),
                        "recoverable": False,
                    },
                )
            except Exception:
                pass
    
    def _execute_direction_sync(
        self,
        task: ResearchTaskModel,
        track: ResearchTrack,
    ) -> AgentResult:
        """
        执行单个研究方向（同步版本，用于线程池执行）
        
        同时更新 Track 的 progress 和 current_action 属性，
        供 periodic_progress_update 读取最新状态。
        
        Args:
            task: 研究任务
            track: 研究轨道
            
        Returns:
            执行结果
        """
        try:
            logger.info(f"[ResearchService] Executing direction {track.direction_id} for task {task.id}")
            
            # Phase 1: 探索（搜索）
            track.progress = 0
            track.current_action = "正在搜索相关信息"
            self._push_track_progress_sync(track, "exploring", track.current_action, track.progress)
            
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
                track.progress = 0
                track.current_action = f"搜索失败: {explore_result.error}"
                track.fail_current_step(explore_result.error)
                self._push_track_progress_sync(track, "failed", track.current_action, track.progress)
                return explore_result
            
            # 更新 Track
            for source in explore_result.sources:
                track.add_source(source)
            for learning in explore_result.learnings:
                track.add_learning(learning)
            
            track.advance_step()
            
            # 搜索完成后推送中间进度（含发现数和来源数）
            track.progress = 20
            track.current_action = f"搜索完成，找到 {len(track.sources)} 个来源，{len(track.learnings)} 条发现"
            self._push_track_progress_sync(track, "exploring", track.current_action, track.progress)
            
            # Phase 2: 分析
            track.progress = 33
            track.current_action = "正在分析搜索结果"
            self._push_track_progress_sync(track, "analyzing", track.current_action, track.progress)
            
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
                track.progress = 33
                track.current_action = f"分析失败: {analyze_result.error}"
                track.fail_current_step(analyze_result.error)
                self._push_track_progress_sync(track, "failed", track.current_action, track.progress)
                return analyze_result
            
            # 更新 Track
            for learning in analyze_result.learnings:
                track.add_learning(learning)
            
            track.advance_step()
            
            # 分析完成后推送中间进度
            track.progress = 50
            track.current_action = f"分析完成，已发现 {len(track.learnings)} 条关键信息"
            self._push_track_progress_sync(track, "analyzing", track.current_action, track.progress)
            
            # Phase 3: 总结
            track.progress = 66
            track.current_action = "正在总结研究发现"
            self._push_track_progress_sync(track, "synthesizing", track.current_action, track.progress)
            
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
                track.progress = 100
                track.current_action = "研究方向完成"
                self._push_track_progress_sync(track, "completed", track.current_action, track.progress)
            else:
                track.progress = 66
                track.current_action = f"总结失败: {synthesis_result.error}"
                track.fail_current_step(synthesis_result.error)
                self._push_track_progress_sync(track, "failed", track.current_action, track.progress)
            
            return synthesis_result
            
        except Exception as e:
            logger.error(f"Direction execution failed: {e}", exc_info=True)
            track.progress = 0
            track.current_action = f"执行异常: {e}"
            track.fail_current_step(str(e))
            self._push_track_progress_sync(track, "failed", track.current_action, 0)
            return AgentResult(success=False, error=str(e))
    
    def _push_track_progress_sync(
        self,
        track: ResearchTrack,
        phase: str,
        message: str,
        progress_pct: int,
    ):
        """
        推送 Track 进度（同步版本，线程安全）
        
        push_to_session 现在是同步方法，使用 SimpleQueue 实现，
        可从任意线程安全调用，无需 asyncio.run_coroutine_threadsafe
        """
        try:
            sse_gateway.push_to_session(
                event_type="direction_progress",
                task_id=track.task_id,
                session_id=track.session_id,
                data={
                    "direction_progress": {
                        "direction_id": track.direction_id,
                        "direction_name": track.topic,
                        "status": phase,
                        "progress": progress_pct,
                        "current_action": message,
                        "learnings_count": len(track.learnings),
                        "sources_count": len(track.sources),
                    }
                },
                track_id=track.track_id,
            )
            logger.info(f"[ResearchService] Progress pushed for direction {track.direction_id}: {phase} - {message}")
        except Exception as e:
            logger.warning(f"[ResearchService] Failed to push progress: {e}")
    
    async def _execute_direction(
        self,
        task: ResearchTaskModel,
        track: ResearchTrack,
    ) -> AgentResult:
        """
        执行单个研究方向（异步包装器，保留向后兼容）
        
        Args:
            task: 研究任务
            track: 研究轨道
            
        Returns:
            执行结果
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._execute_direction_sync(task, track)
        )
    
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
    
    def _estimate_remaining_time(self, task_id: str, elapsed_seconds: float, directions: list) -> str:
        """后端计算剩余时间估算，随 progress 事件推送。

        后端有更准确的执行上下文（搜索延迟、LLM 调用耗时），
        前端仅负责展示，无需自行计算。
        """
        if elapsed_seconds < 5:
            return "计算中..."

        completed = sum(1 for d in directions if d.status == TrackStatus.COMPLETED)
        total = len(directions)

        if total == 0 or completed == 0:
            return "约 3-5 分钟" if elapsed_seconds < 30 else "约 2-4 分钟"

        ratio = completed / total
        estimated_total = elapsed_seconds / ratio
        remaining = max(0, estimated_total - elapsed_seconds)

        if remaining < 30:
            return "不到 1 分钟"
        elif remaining < 90:
            return "约 1 分钟"
        elif remaining < 180:
            return "约 2-3 分钟"
        elif remaining < 300:
            return "约 3-5 分钟"
        else:
            return f"约 {int(remaining / 60)} 分钟"

    def _push_progress(self, task: ResearchTaskModel, message: str):
        """推送进度更新（含后端时间估算）"""
        # 计算已用时间
        elapsed_seconds = 0.0
        if task.started_at:
            elapsed_seconds = (datetime.now() - task.started_at).total_seconds()

        # 估算剩余时间
        directions = self._tracks.get(task.id, [])
        estimated_remaining = self._estimate_remaining_time(task.id, elapsed_seconds, directions)

        # 统一使用 push_to_session，事件类型使用 progress
        # 前端 useStream.ts 会自动添加 research_ 前缀，变成 research_progress
        sse_gateway.push_to_session(
            event_type="progress",
            task_id=task.id,
            session_id=task.session_id,
            data={
                "progress": {
                    "task_id": task.id,
                    "status": task.status.value,
                    "mode": task.mode.value,
                    "progress_pct": 0,
                    "elapsed_seconds": int(elapsed_seconds),
                    "directions": [],
                    "current_action": message,
                    "estimated_remaining": estimated_remaining,
                },
                "summary": message,
            },
        )
        logger.info(f"[ResearchService] Progress pushed: {message[:50]}, estimated_remaining={estimated_remaining}")
    
    def _push_track_progress(
        self,
        track: ResearchTrack,
        phase: str,
        message: str,
        progress_pct: int,
    ):
        """推送 Track 进度（含动态时间估算）"""
        # 计算已用时间
        elapsed_seconds = 0.0
        task = self._tasks.get(track.task_id)
        if task and task.started_at:
            elapsed_seconds = (datetime.now() - task.started_at).total_seconds()

        # 估算剩余时间
        directions = self._tracks.get(track.task_id, [])
        estimated_remaining = self._estimate_remaining_time(track.task_id, elapsed_seconds, directions)

        # 事件类型不加 research_ 前缀，前端会自动添加
        sse_gateway.push_to_session(
            event_type="direction_progress",
            task_id=track.task_id,
            session_id=track.session_id,
            data={
                "direction_progress": {
                    "direction_id": track.direction_id,
                    "direction_name": track.topic,
                    "status": phase,
                    "progress": progress_pct,
                    "current_action": message,
                    "learnings_count": len(track.learnings),
                    "sources_count": len(track.sources),
                },
                "estimated_remaining": estimated_remaining,
            },
        )
    
    def _push_clarification_needed(
        self,
        task: ResearchTaskModel,
        questions: list[ClarificationQuestion],
    ):
        """推送需要澄清事件"""
        # 澄清阶段没有 track，直接使用 session_id 推送
        success = sse_gateway.push_to_session(
            event_type="clarification_needed",
            task_id=task.id,
            session_id=task.session_id,
            data={
                "task_id": task.id,
                "questions": [q.to_dict() for q in questions],
            },
        )
        
        if success:
            logger.info(f"[ResearchService] Pushed clarification event to session {task.session_id}")
        else:
            logger.error(f"[ResearchService] Failed to push clarification event to session {task.session_id}")
    
    def _push_plan_generated(self, task: ResearchTaskModel, plan: ResearchPlanModel):
        """推送计划生成事件"""
        # 计划生成阶段可能没有 track，使用 session_id 推送
        success = sse_gateway.push_to_session(
            event_type="plan_generated",
            task_id=task.id,
            session_id=task.session_id,
            data={
                "task_id": task.id,
                "directions": [d.to_dict() for d in plan.directions],
                "estimated_time": "约 2-5 分钟",
                "can_modify": True,
            },
        )
        
        if success:
            logger.info(f"[ResearchService] Pushed plan event to session {task.session_id}")
        else:
            logger.error(f"[ResearchService] Failed to push plan event to session {task.session_id}")
    
    def _push_completed(self, task: ResearchTaskModel, report: ResearchReportModel):
        """推送完成事件"""
        # 计算研究用时
        duration_seconds = 0
        if task.started_at and task.completed_at:
            duration_seconds = int((task.completed_at - task.started_at).total_seconds())
        elif task.started_at:
            duration_seconds = int((datetime.now() - task.started_at).total_seconds())
        
        # 使用 push_to_session 直接推送
        # 事件类型不加 research_ 前缀，前端 useStream.ts 会自动添加
        sse_gateway.push_to_session(
            event_type="completed",
            task_id=task.id,
            session_id=task.session_id,
            data={
                "task_id": task.id,
                "report_id": report.id,
                "word_count": report.word_count,
                "source_count": report.source_count,
                "duration_seconds": duration_seconds,
            },
        )
        logger.info(f"[ResearchService] Completed event pushed for task {task.id}, duration={duration_seconds}s")

    # ============ 流式报告生成 ============

    async def _generate_report_stream(
        self,
        task: ResearchTaskModel,
        tracks: list[ResearchTrack],
    ) -> ResearchReportModel:
        """
        流式生成研究报告

        通过 LLM 流式生成报告内容，实时推送给前端，
        同时保存报告到数据库。

        Args:
            task: 研究任务
            tracks: 研究轨道列表

        Returns:
            研究报告对象
        """
        logger.info(f"[ResearchService] Starting streaming report generation for task {task.id}")

        # 构建上下文
        from services.deep_research.agents.base import AgentContext
        contexts = []
        for track in tracks:
            context = AgentContext(
                task_id=task.id,
                track_id=track.track_id,
                session_id=task.session_id,
                query=task.query,
                topic=track.topic,
                existing_learnings=track.learnings,
                existing_sources=track.sources,
            )
            contexts.append(context)

        # 直接使用 LLM 流式生成报告（不使用 SynthesizerAgent.synthesize_stream 避免双重推送）
        accumulated_content = ""

        try:
            from agent.llm import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            from services.deep_research.agents.synthesizer_agent import SYNTHESIZER_SYSTEM_PROMPT

            synthesizer = self._get_synthesizer_agent()
            task_message = synthesizer._build_full_report_task(
                contexts, task.query, f"研究报告：{task.query[:50]}"
            )

            llm = get_llm(streaming=True)
            llm_messages = [
                SystemMessage(content=SYNTHESIZER_SYSTEM_PROMPT),
                HumanMessage(content=task_message),
            ]

            async for chunk in llm.astream(llm_messages):
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                accumulated_content += content
                
                # 通过 SSE 推送报告流式内容到前端
                try:
                    sse_gateway.push_to_session(
                        event_type="report_stream",
                        task_id=task.id,
                        session_id=task.session_id,
                        data={
                            "content": content,
                            "accumulated": accumulated_content,
                            "accumulated_length": len(accumulated_content),
                            "task_id": task.id,
                        },
                    )
                except Exception as push_err:
                    logger.warning(f"[ResearchService] Failed to push report stream chunk: {push_err}")
                    
            logger.info(f"[ResearchService] LLM streaming completed, total length: {len(accumulated_content)}")
                    
        except Exception as e:
            logger.error(f"[ResearchService] Streaming report failed: {e}", exc_info=True)
            # 降级：使用非流式生成
            from services.deep_research.report_generator import ReportGenerator
            generator = ReportGenerator()

            # 从数据库加载数据
            db = self._get_db()
            try:
                db_directions = db.query(DBResearchDirection).filter(
                    DBResearchDirection.task_id == uuid.UUID(task.id)
                ).all()
                db_plan = db.query(DBResearchPlan).filter(
                    DBResearchPlan.task_id == uuid.UUID(task.id)
                ).first()

                # 转换
                direction_models = []
                for d in db_directions:
                    dir_model = ResearchDirectionModel(
                        id=str(d.id),
                        task_id=str(d.task_id),
                        direction_id=d.direction_id,
                        name=d.name,
                        status=d.status,
                        summary=d.summary or "",
                    )
                    if d.learnings:
                        for l_data in d.learnings:
                            dir_model.learnings.append(Learning.from_dict(l_data))
                    if d.sources:
                        for s_data in d.sources:
                            dir_model.sources.append(Source.from_dict(s_data))
                    direction_models.append(dir_model)

                plan_model = None
                if db_plan:
                    plan_model = ResearchPlanModel(
                        id=str(db_plan.id),
                        task_id=str(db_plan.task_id),
                        directions=[DirectionSpec.from_dict(d) for d in (db_plan.directions or [])],
                    )

                accumulated_content = generator.generate_markdown(task, plan_model, direction_models)
            finally:
                if self._db is None:
                    db.close()

        # 创建报告对象
        source_count = sum(len(t.sources) for t in tracks)
        report = ResearchReportModel(
            task_id=task.id,
            title=f"研究报告：{task.query[:50]}",
            content_markdown=accumulated_content,
            source_count=source_count,
        )
        report.calculate_word_count()

        # 保存到数据库
        db = self._get_db()
        try:
            db_report = DBResearchReport(
                task_id=uuid.UUID(task.id),
                title=report.title,
                content_markdown=report.content_markdown,
                word_count=report.word_count,
                source_count=report.source_count,
            )
            db.add(db_report)
            db.commit()
            db.refresh(db_report)
            report.id = str(db_report.id)
            logger.info(f"[ResearchService] Report saved to DB: {report.id}")
        except Exception as e:
            db.rollback()
            logger.error(f"[ResearchService] Failed to save report: {e}")
        finally:
            if self._db is None:
                db.close()

        # 推送报告生成完成事件
        sse_gateway.push_to_session(
            event_type="report_complete",
            task_id=task.id,
            session_id=task.session_id,
            data={
                "report_id": report.id,
                "word_count": report.word_count,
                "source_count": report.source_count,
                "task_id": task.id,
            },
        )

        logger.info(f"[ResearchService] Streaming report completed: {report.word_count} words")
        return report


    # ============ 用户干预 ============

    async def add_intervention(self, task_id: str, message: str) -> ResearchTaskModel:
        """
        添加用户干预消息

        在研究执行过程中，用户可以发送干预消息来引导研究方向。

        Args:
            task_id: 任务 ID
            message: 用户干预消息

        Returns:
            更新后的研究任务
        """
        task = self._get_task(task_id)

        # 检查任务状态是否允许干预
        if task.status not in [
            ResearchStatus.EXECUTING,
            ResearchStatus.ANALYZING,
            ResearchStatus.PLANNING,
        ]:
            raise ResearchError(
                f"Task {task_id} is not in a state that accepts interventions, "
                f"current state: {task.status.value}"
            )

        # 添加干预消息
        task.intervention_messages.append(message)
        task.update_timestamp()

        logger.info(f"[ResearchService] Added intervention to task {task_id}: {message[:50]}...")

        # 推送干预确认事件
        sse_gateway.push_to_session(
            event_type="progress",
            task_id=task_id,
            session_id=task.session_id,
            data={
                "summary": f"用户干预: {message[:100]}",
                "intervention_received": True,
                "task_id": task_id,
            },
        )

        return task
