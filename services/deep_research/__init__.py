"""
深度研究模块

提供多轮、多方向的深度研究功能，支持：
- 标准研究模式：直接开始多轮搜索分析
- 深度研究模式：先澄清问题，生成研究计划确认后执行
- 研究过程透明可控：实时进度推送、用户干预
"""

from services.deep_research.models import (
    ResearchTask,
    ResearchPlan,
    ResearchDirection,
    ResearchReport,
    ResearchMode,
    ResearchStatus,
    ResearchDirectionStatus,
)
from services.deep_research.state_machine import (
    ResearchState,
    ResearchStateMachine,
    InvalidStateTransition,
)
from services.deep_research.events import (
    SSEEventType,
    SSEEvent,
    ProgressData,
    ClarificationData,
    PlanConfirmData,
    DirectionProgressData,
    CompletedData,
    ErrorData,
)

__all__ = [
    # 数据模型
    'ResearchTask',
    'ResearchPlan',
    'ResearchDirection',
    'ResearchReport',
    'ResearchMode',
    'ResearchStatus',
    'ResearchDirectionStatus',
    # 状态机
    'ResearchState',
    'ResearchStateMachine',
    'InvalidStateTransition',
    # SSE 事件
    'SSEEventType',
    'SSEEvent',
    'ProgressData',
    'ClarificationData',
    'PlanConfirmData',
    'DirectionProgressData',
    'CompletedData',
    'ErrorData',
]
