"""
深度研究模块

提供深度研究功能，包括：
- 多轮、多方向研究
- 专家型 Agent 协作
- 结构化报告生成
- PDF 导出
"""
from services.deep_research.models import (
    ResearchTask,
    ResearchPlan,
    ResearchDirection,
    ResearchReport,
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
from services.deep_research.track import (
    ResearchTrack,
    TrackManager,
    TrackStatus,
)
from services.deep_research.research_service import (
    ResearchService,
    ResearchError,
    ResearchCancelledError,
    ResearchFailedError,
    SSEGateway,
    CPUTaskExecutor,
)
from services.deep_research.events import (
    SSEEvent,
    SSEEventType,
    create_progress_event,
    create_clarification_event,
    create_completed_event,
    create_error_event,
)
from services.deep_research.utils import (
    Deduplicator,
    RedisDeduplicator,
    WebContentCleaner,
)

__all__ = [
    # Models
    "ResearchTask",
    "ResearchPlan",
    "ResearchDirection",
    "ResearchReport",
    "ResearchMode",
    "ResearchStatus",
    "DirectionSpec",
    "Learning",
    "Source",
    "ClarificationQuestion",
    # State Machine
    "ResearchStateMachine",
    "ResearchState",
    "InvalidStateTransition",
    # Track
    "ResearchTrack",
    "TrackManager",
    "TrackStatus",
    # Service
    "ResearchService",
    "ResearchError",
    "ResearchCancelledError",
    "ResearchFailedError",
    "SSEGateway",
    "CPUTaskExecutor",
    # Events
    "SSEEvent",
    "SSEEventType",
    "create_progress_event",
    "create_clarification_event",
    "create_completed_event",
    "create_error_event",
    # Utils
    "Deduplicator",
    "RedisDeduplicator",
    "WebContentCleaner",
]
