"""
SSE 事件类型定义

定义研究过程中的实时事件类型和数据结构，
用于前端 SSE (Server-Sent Events) 推送。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
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
    
    # 报告生成事件（流式）
    REPORT_STREAM = "report_stream"  # 报告流式内容
    REPORT_COMPLETE = "report_complete"  # 报告生成完成
    
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


@dataclass
class ReportStreamData:
    """
    报告流式数据
    
    用于推送 LLM 流式生成的报告内容。
    """
    content: str  # 本次推送的内容片段
    section: str = ""  # 当前章节：summary, directions, synthesis, answer, sources
    is_final: bool = False  # 是否是最后一个片段
    accumulated_length: int = 0  # 已累计的字符数

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "section": self.section,
            "is_final": self.is_final,
            "accumulated_length": self.accumulated_length,
        }


@dataclass
class ReportCompleteData:
    """
    报告生成完成数据
    
    用于推送报告生成完成事件。
    """
    report_id: str
    word_count: int
    source_count: int
    pdf_generating: bool = False  # PDF 是否正在后台生成（默认 False，PDF 已移除）

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "word_count": self.word_count,
            "source_count": self.source_count,
            "pdf_generating": self.pdf_generating,
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


def create_report_stream_event(
    task_id: str,
    track_id: str,
    content: str,
    section: str = "",
    is_final: bool = False,
    accumulated_length: int = 0,
) -> SSEEvent:
    """创建报告流式内容事件"""
    data = ReportStreamData(
        content=content,
        section=section,
        is_final=is_final,
        accumulated_length=accumulated_length,
    )
    return SSEEvent(
        event=SSEEventType.REPORT_STREAM,
        task_id=task_id,
        track_id=track_id,
        data=data.to_dict(),
    )


def create_report_complete_event(
    task_id: str,
    track_id: str,
    report_id: str,
    word_count: int,
    source_count: int,
    pdf_generating: bool = True,
) -> SSEEvent:
    """创建报告生成完成事件"""
    data = ReportCompleteData(
        report_id=report_id,
        word_count=word_count,
        source_count=source_count,
        pdf_generating=pdf_generating,
    )
    return SSEEvent(
        event=SSEEventType.REPORT_COMPLETE,
        task_id=task_id,
        track_id=track_id,
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

