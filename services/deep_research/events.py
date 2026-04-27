"""
SSE 事件类型定义

定义研究过程中的实时事件类型和数据结构，
用于前端 SSE (Server-Sent Events) 推送。
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, AsyncIterator
import json
import logging

logger = logging.getLogger(__name__)


class SSEEventType(str, Enum):
    """SSE 事件类型"""
    # 进度更新
    PROGRESS = "progress"  # 通用进度更新
    DIRECTION_PROGRESS = "direction_progress"  # 研究方向进度
    
    # 交互事件
    CLARIFICATION_NEEDED = "clarification_needed"  # 需要澄清
    PLAN_CONFIRM = "plan_confirm"  # 需要确认计划
    
    # 状态变更
    STATUS_CHANGE = "status_change"  # 状态变更
    
    # 完成事件
    COMPLETED = "completed"  # 研究完成
    ERROR = "error"  # 错误
    
    # 调试事件
    DEBUG = "debug"  # 调试信息


@dataclass
class SSEEvent:
    """
    SSE 事件基类
    
    所有 SSE 事件的通用结构，遵循 spec 4.2.2 的格式规范。
    """
    event: SSEEventType
    task_id: str
    track_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_sse_format(self) -> str:
        """
        转换为 SSE 格式字符串
        
        格式: event: <type>\\ndata: <json>\\n\\n
        """
        message = {
            "event": self.event.value,
            "task_id": self.task_id,
            "track_id": self.track_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
        return f"event: {self.event.value}\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "event": self.event.value,
            "task_id": self.task_id,
            "track_id": self.track_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ProgressData:
    """
    进度更新数据
    
    用于推送研究进度信息。
    """
    step_index: int  # 当前步骤索引
    step_total: int  # 总步骤数
    status: str  # 当前状态：searching, analyzing, synthesizing
    current_action: str  # 当前操作描述
    progress_pct: int  # 进度百分比 0-100

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "step_total": self.step_total,
            "status": self.status,
            "current_action": self.current_action,
            "progress_pct": self.progress_pct,
        }


@dataclass
class DirectionProgressData:
    """
    研究方向进度数据
    
    用于推送单个研究方向的进度。
    """
    direction_id: str
    direction_name: str
    status: str  # pending, exploring, analyzing, synthesizing, completed
    progress: int  # 0-100
    current_action: str = ""
    learnings_count: int = 0
    sources_count: int = 0

    def to_dict(self) -> dict:
        return {
            "direction_id": self.direction_id,
            "direction_name": self.direction_name,
            "status": self.status,
            "progress": self.progress,
            "current_action": self.current_action,
            "learnings_count": self.learnings_count,
            "sources_count": self.sources_count,
        }


@dataclass
class ClarificationData:
    """
    澄清问题数据
    
    用于推送需要用户回答的澄清问题。
    """
    questions: list[dict[str, Any]]  # 问题列表，每个包含 question 和 options

    def to_dict(self) -> dict:
        return {
            "questions": self.questions,
        }


@dataclass
class PlanConfirmData:
    """
    计划确认数据
    
    用于推送需要用户确认的研究计划。
    """
    plan_id: str
    directions: list[dict[str, Any]]  # 研究方向列表
    estimated_time: str = ""  # 预计完成时间
    can_modify: bool = True  # 是否可以修改

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "directions": self.directions,
            "estimated_time": self.estimated_time,
            "can_modify": self.can_modify,
        }


@dataclass
class StatusChangeData:
    """
    状态变更数据
    
    用于推送研究任务状态变更。
    """
    old_status: str
    new_status: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "old_status": self.old_status,
            "new_status": self.new_status,
            "reason": self.reason,
        }


@dataclass
class CompletedData:
    """
    研究完成数据
    
    用于推送研究完成信息。
    """
    report_url: str  # 报告 URL
    source_count: int  # 来源数量
    duration_seconds: int  # 耗时（秒）
    word_count: int = 0  # 报告字数

    def to_dict(self) -> dict:
        return {
            "report_url": self.report_url,
            "source_count": self.source_count,
            "duration_seconds": self.duration_seconds,
            "word_count": self.word_count,
        }


@dataclass
class ErrorData:
    """
    错误数据
    
    用于推送错误信息。
    """
    error_code: str
    error_message: str
    recoverable: bool = False  # 是否可恢复
    suggestion: str = ""  # 建议操作

    def to_dict(self) -> dict:
        return {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "recoverable": self.recoverable,
            "suggestion": self.suggestion,
        }


# ============ 事件工厂函数 ============

def create_progress_event(
    task_id: str,
    track_id: str,
    step_index: int,
    step_total: int,
    status: str,
    current_action: str,
    progress_pct: int,
) -> SSEEvent:
    """创建进度更新事件"""
    data = ProgressData(
        step_index=step_index,
        step_total=step_total,
        status=status,
        current_action=current_action,
        progress_pct=progress_pct,
    )
    return SSEEvent(
        event=SSEEventType.PROGRESS,
        task_id=task_id,
        track_id=track_id,
        data=data.to_dict(),
    )


def create_direction_progress_event(
    task_id: str,
    track_id: str,
    direction_id: str,
    direction_name: str,
    status: str,
    progress: int,
    current_action: str = "",
    learnings_count: int = 0,
    sources_count: int = 0,
) -> SSEEvent:
    """创建研究方向进度事件"""
    data = DirectionProgressData(
        direction_id=direction_id,
        direction_name=direction_name,
        status=status,
        progress=progress,
        current_action=current_action,
        learnings_count=learnings_count,
        sources_count=sources_count,
    )
    return SSEEvent(
        event=SSEEventType.DIRECTION_PROGRESS,
        task_id=task_id,
        track_id=track_id,
        data=data.to_dict(),
    )


def create_clarification_event(
    task_id: str,
    questions: list[dict[str, Any]],
) -> SSEEvent:
    """创建澄清问题事件"""
    data = ClarificationData(questions=questions)
    return SSEEvent(
        event=SSEEventType.CLARIFICATION_NEEDED,
        task_id=task_id,
        data=data.to_dict(),
    )


def create_plan_confirm_event(
    task_id: str,
    plan_id: str,
    directions: list[dict[str, Any]],
    estimated_time: str = "",
) -> SSEEvent:
    """创建计划确认事件"""
    data = PlanConfirmData(
        plan_id=plan_id,
        directions=directions,
        estimated_time=estimated_time,
    )
    return SSEEvent(
        event=SSEEventType.PLAN_CONFIRM,
        task_id=task_id,
        data=data.to_dict(),
    )


def create_status_change_event(
    task_id: str,
    old_status: str,
    new_status: str,
    reason: str = "",
) -> SSEEvent:
    """创建状态变更事件"""
    data = StatusChangeData(
        old_status=old_status,
        new_status=new_status,
        reason=reason,
    )
    return SSEEvent(
        event=SSEEventType.STATUS_CHANGE,
        task_id=task_id,
        data=data.to_dict(),
    )


def create_completed_event(
    task_id: str,
    report_url: str,
    source_count: int,
    duration_seconds: int,
    word_count: int = 0,
) -> SSEEvent:
    """创建完成事件"""
    data = CompletedData(
        report_url=report_url,
        source_count=source_count,
        duration_seconds=duration_seconds,
        word_count=word_count,
    )
    return SSEEvent(
        event=SSEEventType.COMPLETED,
        task_id=task_id,
        data=data.to_dict(),
    )


def create_error_event(
    task_id: str,
    error_code: str,
    error_message: str,
    recoverable: bool = False,
    suggestion: str = "",
) -> SSEEvent:
    """创建错误事件"""
    data = ErrorData(
        error_code=error_code,
        error_message=error_message,
        recoverable=recoverable,
        suggestion=suggestion,
    )
    return SSEEvent(
        event=SSEEventType.ERROR,
        task_id=task_id,
        data=data.to_dict(),
    )


# ============ SSE Gateway ============

class SSEGateway:
    """
    SSE 网关
    
    管理 SSE 连接和消息路由，支持：
    - 多 Session 并发连接
    - 按 track_id 路由消息
    - 离线消息处理
    """
    
    def __init__(self, max_queue_size: int = 100):
        """
        初始化 SSE 网关
        
        Args:
            max_queue_size: 每个连接的消息队列最大长度
        """
        self.connections: dict[str, asyncio.Queue] = {}  # session_id -> queue
        self.max_queue_size = max_queue_size
        self._track_to_session: dict[str, str] = {}  # track_id -> session_id
    
    def register_track(self, track_id: str, session_id: str) -> None:
        """注册 track 到 session 的映射"""
        self._track_to_session[track_id] = session_id
        logger.debug(f"Registered track {track_id} -> session {session_id}")
    
    def unregister_track(self, track_id: str) -> None:
        """取消 track 注册"""
        self._track_to_session.pop(track_id, None)
        logger.debug(f"Unregistered track {track_id}")
    
    def get_session_by_track(self, track_id: str) -> Optional[str]:
        """根据 track_id 获取 session_id"""
        return self._track_to_session.get(track_id)
    
    async def subscribe(self, session_id: str) -> AsyncIterator[str]:
        """
        前端建立 SSE 连接
        
        Args:
            session_id: 会话 ID
            
        Yields:
            SSE 格式的消息字符串
        """
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        self.connections[session_id] = queue
        
        logger.info(f"SSE connection established for session {session_id}")
        
        try:
            while True:
                # 等待消息
                message = await queue.get()
                
                # 检查是否是关闭信号
                if message is None:
                    break
                
                # 格式化输出
                yield message
                
        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for session {session_id}")
        finally:
            self.connections.pop(session_id, None)
            logger.info(f"SSE connection closed for session {session_id}")
    
    async def push(
        self,
        event: SSEEventType,
        task_id: str,
        track_id: str,
        data: dict[str, Any],
    ) -> bool:
        """
        推送消息到对应的 Session
        
        Args:
            event: 事件类型
            task_id: 任务 ID
            track_id: 轨道 ID
            data: 事件数据
            
        Returns:
            是否成功推送
        """
        # 查找对应的 session
        session_id = self.get_session_by_track(track_id)
        if not session_id:
            logger.warning(f"No session found for track {track_id}")
            return False
        
        # 检查连接是否存在
        if session_id not in self.connections:
            logger.warning(f"No SSE connection for session {session_id}, message will be lost")
            return False
        
        # 创建 SSE 事件
        sse_event = SSEEvent(
            event=event,
            task_id=task_id,
            track_id=track_id,
            data=data,
        )
        
        # 格式化为 SSE 字符串
        message = sse_event.to_sse_format()
        
        # 获取队列
        queue = self.connections[session_id]
        
        # 检查队列是否已满
        if queue.full():
            # 丢弃最旧的消息
            try:
                queue.get_nowait()
                logger.warning(f"Queue full for session {session_id}, dropped oldest message")
            except asyncio.QueueEmpty:
                pass
        
        # 放入新消息
        try:
            queue.put_nowait(message)
            logger.debug(f"Pushed event {event.value} to session {session_id}")
            return True
        except asyncio.QueueFull:
            logger.error(f"Failed to push event to session {session_id}, queue full")
            return False
    
    async def push_event(self, event: SSEEvent) -> bool:
        """
        推送 SSEEvent 对象
        
        Args:
            event: SSE 事件对象
            
        Returns:
            是否成功推送
        """
        return await self.push(
            event=event.event,
            task_id=event.task_id,
            track_id=event.track_id,
            data=event.data,
        )
    
    async def close(self, session_id: str) -> None:
        """关闭指定 Session 的连接"""
        if session_id in self.connections:
            queue = self.connections[session_id]
            # 发送关闭信号
            try:
                queue.put_nowait(None)
            except:
                pass
    
    def has_connection(self, session_id: str) -> bool:
        """检查是否有活跃连接"""
        return session_id in self.connections
    
    def get_active_sessions(self) -> list[str]:
        """获取所有活跃的 Session"""
        return list(self.connections.keys())
