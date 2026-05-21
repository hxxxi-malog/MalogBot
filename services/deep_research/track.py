"""
研究轨道运行时结构

ResearchTrack 是研究方向的运行时执行单元，提供：
- 独立的研究上下文
- 独立的消息队列
- 本地去重缓存
- 执行状态管理
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid
import logging

from services.deep_research.models import (
    ResearchDirection,
    Learning,
    Source,
    DirectionSpec,
)

logger = logging.getLogger(__name__)


class TrackStatus(str, Enum):
    """轨道状态"""
    RUNNING = "running"  # 正在执行
    PAUSED = "paused"  # 暂停（等待用户输入）
    CLARIFYING = "clarifying"  # 澄清中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


@dataclass
class ExecutionStep:
    """
    执行步骤
    
    表示研究方向中的一个执行步骤。
    """
    index: int
    name: str
    description: str = ""
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class ResearchTrack:
    """
    研究轨道
    
    每个研究方向对应一个独立的 Track，拥有：
    - 独立的研究上下文
    - 独立的消息队列（SSE 推送）
    - 本地去重缓存
    - 执行计划和进度
    """
    # 标识信息
    track_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    task_id: str = ""
    direction_id: str = ""  # 对应 ResearchPlan 中的 DirectionSpec.id
    topic: str = ""  # 研究主题/方向名称

    # 执行计划
    plan: list[ExecutionStep] = field(default_factory=list)
    current_step_index: int = 0

    # 研究成果
    learnings: list[Learning] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    # 去重缓存
    visited_urls: set[str] = field(default_factory=set)
    searched_queries: set[str] = field(default_factory=set)

    # 状态
    status: TrackStatus = TrackStatus.RUNNING
    error_message: str = ""

    # 进度信息（实时更新，供 periodic_progress_update 读取）
    progress: int = 0  # 0-100
    current_action: str = ""  # 当前操作描述

    # 消息队列（用于 SSE 推送）
    sse_queue: Optional[asyncio.Queue] = field(default=None, repr=False)

    # 上下文数据（用于 Agent 执行）
    context: dict[str, Any] = field(default_factory=dict)

    # 时间戳
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """初始化消息队列"""
        if self.sse_queue is None:
            self.sse_queue = asyncio.Queue()

    def initialize_plan(self, direction_spec: DirectionSpec) -> None:
        """
        根据研究方向规格初始化执行计划
        
        Args:
            direction_spec: 研究方向规格
        """
        self.direction_id = direction_spec.id
        self.topic = direction_spec.name
        
        # 默认的执行步骤（可被自定义覆盖）
        self.plan = [
            ExecutionStep(index=0, name="search", description=f"搜索 {direction_spec.name} 相关信息"),
            ExecutionStep(index=1, name="analyze", description="分析搜索结果，提取关键信息"),
            ExecutionStep(index=2, name="synthesize", description="总结研究发现"),
        ]
        logger.info(f"Track {self.track_id} initialized with {len(self.plan)} steps for direction: {self.topic}")

    def get_current_step(self) -> Optional[ExecutionStep]:
        """获取当前步骤"""
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None

    def advance_step(self) -> bool:
        """
        推进到下一步
        
        Returns:
            是否还有下一步
        """
        current = self.get_current_step()
        if current:
            current.status = "completed"
            current.completed_at = datetime.now()
        
        self.current_step_index += 1
        next_step = self.get_current_step()
        
        if next_step:
            next_step.status = "running"
            next_step.started_at = datetime.now()
            logger.debug(f"Track {self.track_id} advanced to step {self.current_step_index}: {next_step.name}")
            return True
        else:
            self.status = TrackStatus.COMPLETED
            self.completed_at = datetime.now()
            logger.info(f"Track {self.track_id} completed all steps")
            return False

    def fail_current_step(self, error: str) -> None:
        """标记当前步骤失败"""
        current = self.get_current_step()
        if current:
            current.status = "failed"
            current.error = error
            current.completed_at = datetime.now()
        self.status = TrackStatus.FAILED
        self.error_message = error
        logger.error(f"Track {self.track_id} step {self.current_step_index} failed: {error}")

    def add_learning(self, learning: Learning) -> None:
        """添加学习成果"""
        self.learnings.append(learning)
        self.context.setdefault("total_learnings", 0)
        self.context["total_learnings"] += 1
        self.update_timestamp()
        logger.debug(f"Track {self.track_id} added learning: {learning.content[:50]}...")

    def add_source(self, source: Source) -> None:
        """添加信息来源"""
        # 去重
        if source.url not in self.visited_urls:
            self.sources.append(source)
            self.visited_urls.add(source.url)
            self.update_timestamp()
            logger.debug(f"Track {self.track_id} added source: {source.url}")

    def mark_visited(self, url: str) -> None:
        """标记 URL 已访问"""
        self.visited_urls.add(url)

    def is_visited(self, url: str) -> bool:
        """检查 URL 是否已访问"""
        return url in self.visited_urls

    def mark_searched(self, query: str) -> None:
        """标记查询已执行"""
        self.searched_queries.add(query.lower().strip())

    def is_searched(self, query: str) -> bool:
        """检查查询是否已执行"""
        return query.lower().strip() in self.searched_queries

    async def push_event(self, event_type: str, data: dict) -> None:
        """
        推送 SSE 事件到消息队列
        
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if self.sse_queue is None:
            logger.warning(f"Track {self.track_id} has no SSE queue")
            return
        
        event = {
            "event": event_type,
            "track_id": self.track_id,
            "task_id": self.task_id,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        await self.sse_queue.put(event)
        logger.debug(f"Track {self.track_id} pushed event: {event_type}")

    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = datetime.now()

    def get_progress(self) -> dict:
        """获取进度信息"""
        total_steps = len(self.plan)
        completed_steps = sum(1 for s in self.plan if s.status == "completed")
        progress_pct = int((completed_steps / total_steps * 100)) if total_steps > 0 else 0
        
        # 同步更新 progress 属性（供外部读取）
        self.progress = progress_pct
        
        return {
            "track_id": self.track_id,
            "topic": self.topic,
            "status": self.status.value,
            "current_step": self.current_step_index,
            "total_steps": total_steps,
            "progress_pct": progress_pct,
            "learnings_count": len(self.learnings),
            "sources_count": len(self.sources),
        }

    def to_research_direction(self) -> ResearchDirection:
        """转换为 ResearchDirection 数据模型"""
        return ResearchDirection(
            id=self.direction_id,
            task_id=self.task_id,
            direction_id=self.direction_id,
            name=self.topic,
            status=self._map_status(),
            progress=self.get_progress()["progress_pct"],
            learnings=self.learnings,
            sources=self.sources,
            summary=self.context.get("summary", ""),
            started_at=self.started_at,
            completed_at=self.completed_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def _map_status(self) -> str:
        """映射 TrackStatus 到 ResearchDirectionStatus"""
        from services.deep_research.models import ResearchDirectionStatus
        mapping = {
            TrackStatus.RUNNING: ResearchDirectionStatus.EXPLORING,
            TrackStatus.PAUSED: ResearchDirectionStatus.PENDING,
            TrackStatus.CLARIFYING: ResearchDirectionStatus.PENDING,
            TrackStatus.COMPLETED: ResearchDirectionStatus.COMPLETED,
            TrackStatus.FAILED: ResearchDirectionStatus.FAILED,
        }
        return mapping.get(self.status, ResearchDirectionStatus.PENDING)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "track_id": self.track_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "direction_id": self.direction_id,
            "topic": self.topic,
            "plan": [s.to_dict() for s in self.plan],
            "current_step_index": self.current_step_index,
            "learnings": [l.to_dict() for l in self.learnings],
            "sources": [s.to_dict() for s in self.sources],
            "visited_urls": list(self.visited_urls),
            "searched_queries": list(self.searched_queries),
            "status": self.status.value,
            "error_message": self.error_message,
            "context": self.context,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TrackManager:
    """
    轨道管理器
    
    管理多个 ResearchTrack 实例，提供：
    - 轨道创建和销毁
    - 轨道查找
    - 资源清理
    """
    
    def __init__(self):
        self._tracks: dict[str, ResearchTrack] = {}
        self._session_tracks: dict[str, list[str]] = {}  # session_id -> track_ids
        self._task_tracks: dict[str, list[str]] = {}  # task_id -> track_ids
    
    def create_track(
        self,
        session_id: str,
        task_id: str,
        direction_spec: DirectionSpec,
    ) -> ResearchTrack:
        """
        创建新的研究轨道
        
        Args:
            session_id: 会话 ID
            task_id: 任务 ID
            direction_spec: 研究方向规格
            
        Returns:
            创建的 ResearchTrack 实例
        """
        track = ResearchTrack(
            session_id=session_id,
            task_id=task_id,
        )
        track.initialize_plan(direction_spec)
        
        # 注册到索引
        self._tracks[track.track_id] = track
        
        if session_id not in self._session_tracks:
            self._session_tracks[session_id] = []
        self._session_tracks[session_id].append(track.track_id)
        
        if task_id not in self._task_tracks:
            self._task_tracks[task_id] = []
        self._task_tracks[task_id].append(track.track_id)
        
        logger.info(f"Created track {track.track_id} for task {task_id}, direction: {direction_spec.name}")
        return track

    def get_track(self, track_id: str) -> Optional[ResearchTrack]:
        """获取轨道"""
        return self._tracks.get(track_id)

    def get_tracks_by_session(self, session_id: str) -> list[ResearchTrack]:
        """获取会话下的所有轨道"""
        track_ids = self._session_tracks.get(session_id, [])
        return [self._tracks[tid] for tid in track_ids if tid in self._tracks]

    def get_tracks_by_task(self, task_id: str) -> list[ResearchTrack]:
        """获取任务下的所有轨道"""
        track_ids = self._task_tracks.get(task_id, [])
        return [self._tracks[tid] for tid in track_ids if tid in self._tracks]

    def remove_track(self, track_id: str) -> bool:
        """移除轨道"""
        track = self._tracks.get(track_id)
        if not track:
            return False
        
        # 从索引中移除
        del self._tracks[track_id]
        
        if track.session_id in self._session_tracks:
            self._session_tracks[track.session_id] = [
                tid for tid in self._session_tracks[track.session_id] if tid != track_id
            ]
        
        if track.task_id in self._task_tracks:
            self._task_tracks[track.task_id] = [
                tid for tid in self._task_tracks[track.task_id] if tid != track_id
            ]
        
        logger.info(f"Removed track {track_id}")
        return True

    def clear_task_tracks(self, task_id: str) -> int:
        """清除任务下的所有轨道"""
        track_ids = self._task_tracks.get(task_id, [])
        count = 0
        for track_id in track_ids:
            if self.remove_track(track_id):
                count += 1
        return count

    def get_all_active_tracks(self) -> list[ResearchTrack]:
        """获取所有活跃的轨道"""
        return [
            t for t in self._tracks.values()
            if t.status == TrackStatus.RUNNING
        ]


# 全局单例
track_manager = TrackManager()
