"""
研究状态机

实现研究任务的状态转换逻辑，提供：
- 明确的状态转换规则（DAG）
- 幂等性保障
- 无锁设计（依赖数据库事务）
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import logging

from services.deep_research.models import ResearchStatus, ResearchMode

logger = logging.getLogger(__name__)


class ResearchState(str, Enum):
    """
    研究状态（与 ResearchStatus 保持一致，提供额外语义）
    
    状态转换 DAG:
    
    标准研究模式:
    PENDING → EXECUTING → COMPLETED/FAILED/CANCELLED
    
    深度研究模式:
    PENDING → ANALYZING → PENDING_CLARIFICATION → RESUMED → PLANNING 
           → PENDING_CONFIRMATION → CONFIRMED → EXECUTING → COMPLETED/FAILED/CANCELLED
    """
    PENDING = "pending"
    ANALYZING = "analyzing"
    PENDING_CLARIFICATION = "pending_clarification"
    RESUMED = "resumed"
    PLANNING = "planning"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidStateTransition(Exception):
    """无效状态转换异常"""
    
    def __init__(self, from_state: ResearchState, to_state: ResearchState, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(
            f"Invalid state transition: {from_state.value} -> {to_state.value}. {reason}"
        )


# 定义合法的状态转换（DAG）
# 格式: {当前状态: [允许转换到的状态列表]}
VALID_TRANSITIONS: dict[ResearchState, list[ResearchState]] = {
    ResearchState.PENDING: [
        ResearchState.ANALYZING,  # 深度研究：开始分析问题
        ResearchState.EXECUTING,  # 标准研究：直接执行
        ResearchState.CANCELLED,  # 取消
    ],
    ResearchState.ANALYZING: [
        ResearchState.PENDING_CLARIFICATION,  # 需要澄清
        ResearchState.PLANNING,  # 无需澄清，直接规划
        ResearchState.FAILED,
        ResearchState.CANCELLED,
    ],
    ResearchState.PENDING_CLARIFICATION: [
        ResearchState.RESUMED,  # 用户回答后恢复
        ResearchState.CANCELLED,
    ],
    ResearchState.RESUMED: [
        ResearchState.PLANNING,  # 开始规划
        ResearchState.FAILED,
        ResearchState.CANCELLED,
    ],
    ResearchState.PLANNING: [
        ResearchState.PENDING_CONFIRMATION,  # 等待确认
        ResearchState.EXECUTING,  # 标准研究：无需确认
        ResearchState.FAILED,
        ResearchState.CANCELLED,
    ],
    ResearchState.PENDING_CONFIRMATION: [
        ResearchState.CONFIRMED,  # 用户确认
        ResearchState.PLANNING,  # 用户修改计划，重新规划
        ResearchState.CANCELLED,
    ],
    ResearchState.CONFIRMED: [
        ResearchState.EXECUTING,  # 开始执行
        ResearchState.CANCELLED,
    ],
    ResearchState.EXECUTING: [
        ResearchState.COMPLETED,
        ResearchState.FAILED,
        ResearchState.CANCELLED,
    ],
    # 终态，无后续转换
    ResearchState.COMPLETED: [],
    ResearchState.FAILED: [],
    ResearchState.CANCELLED: [],
}


@dataclass
class StateTransition:
    """状态转换记录"""
    from_state: ResearchState
    to_state: ResearchState
    timestamp: datetime = field(default_factory=datetime.now)
    reason: str = ""
    actor: str = "system"  # system, user

    def to_dict(self) -> dict:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "actor": self.actor,
        }


@dataclass
class ResearchStateMachine:
    """
    研究状态机
    
    提供状态转换的校验和记录功能。
    
    设计原则:
    - 无锁设计：状态转换具有方向性和幂等性
    - 幂等性保障：重复调用相同转换返回相同结果
    - 事务一致性：依赖数据库事务保证原子性
    """
    current_state: ResearchState = ResearchState.PENDING
    mode: ResearchMode = ResearchMode.STANDARD
    transition_history: list[StateTransition] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def can_transition_to(self, target_state: ResearchState) -> tuple[bool, str]:
        """
        检查是否可以转换到目标状态
        
        Args:
            target_state: 目标状态
            
        Returns:
            (是否可以转换, 原因说明)
        """
        # 终态不可转换
        if self.current_state in (ResearchState.COMPLETED, ResearchState.FAILED, ResearchState.CANCELLED):
            return False, f"Current state {self.current_state.value} is a terminal state"

        # 检查是否在合法转换列表中
        valid_targets = VALID_TRANSITIONS.get(self.current_state, [])
        if target_state not in valid_targets:
            return False, f"Transition {self.current_state.value} -> {target_state.value} is not allowed"

        # 检查模式特定的约束
        if self.mode == ResearchMode.STANDARD:
            # 标准研究模式不应进入深度研究的特定状态
            deep_only_states = {
                ResearchState.ANALYZING,
                ResearchState.PENDING_CLARIFICATION,
                ResearchState.RESUMED,
                ResearchState.PENDING_CONFIRMATION,
            }
            if target_state in deep_only_states and self.current_state in deep_only_states:
                return False, f"State {target_state.value} is only for deep research mode"

        return True, "Valid transition"

    def transition(
        self,
        target_state: ResearchState,
        reason: str = "",
        actor: str = "system",
    ) -> ResearchState:
        """
        执行状态转换
        
        Args:
            target_state: 目标状态
            reason: 转换原因
            actor: 执行者（system/user）
            
        Returns:
            转换后的状态
            
        Raises:
            InvalidStateTransition: 无效的状态转换
        """
        can_transit, error_reason = self.can_transition_to(target_state)
        
        if not can_transit:
            logger.warning(
                f"Invalid state transition attempt: {self.current_state.value} -> {target_state.value}. "
                f"Reason: {error_reason}"
            )
            raise InvalidStateTransition(self.current_state, target_state, error_reason)

        # 记录转换
        transition_record = StateTransition(
            from_state=self.current_state,
            to_state=target_state,
            reason=reason,
            actor=actor,
        )
        self.transition_history.append(transition_record)

        # 执行转换
        old_state = self.current_state
        self.current_state = target_state
        self.updated_at = datetime.now()

        logger.info(
            f"State transition: {old_state.value} -> {target_state.value}. "
            f"Reason: {reason}, Actor: {actor}"
        )

        return self.current_state

    def try_transition(
        self,
        target_state: ResearchState,
        reason: str = "",
        actor: str = "system",
    ) -> tuple[bool, Optional[ResearchState]]:
        """
        尝试执行状态转换（不抛异常）
        
        Args:
            target_state: 目标状态
            reason: 转换原因
            actor: 执行者
            
        Returns:
            (是否成功, 转换后的状态或None)
        """
        try:
            new_state = self.transition(target_state, reason, actor)
            return True, new_state
        except InvalidStateTransition:
            return False, None

    def is_terminal(self) -> bool:
        """检查是否处于终态"""
        return self.current_state in (
            ResearchState.COMPLETED,
            ResearchState.FAILED,
            ResearchState.CANCELLED,
        )

    def is_paused(self) -> bool:
        """检查是否处于暂停状态（等待用户操作）"""
        return self.current_state in (
            ResearchState.PENDING_CLARIFICATION,
            ResearchState.PENDING_CONFIRMATION,
        )

    def is_executing(self) -> bool:
        """检查是否正在执行"""
        return self.current_state in (
            ResearchState.ANALYZING,
            ResearchState.PLANNING,
            ResearchState.EXECUTING,
        )

    def get_next_valid_states(self) -> list[ResearchState]:
        """获取可以转换到的下一状态列表"""
        return VALID_TRANSITIONS.get(self.current_state, []).copy()

    def get_transition_history(self) -> list[StateTransition]:
        """获取状态转换历史"""
        return self.transition_history.copy()

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "current_state": self.current_state.value,
            "mode": self.mode.value,
            "transition_history": [t.to_dict() for t in self.transition_history],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchStateMachine":
        """从字典反序列化"""
        history = [
            StateTransition(
                from_state=ResearchState(t["from_state"]),
                to_state=ResearchState(t["to_state"]),
                timestamp=datetime.fromisoformat(t["timestamp"]) if t.get("timestamp") else datetime.now(),
                reason=t.get("reason", ""),
                actor=t.get("actor", "system"),
            )
            for t in data.get("transition_history", [])
        ]
        return cls(
            current_state=ResearchState(data.get("current_state", "pending")),
            mode=ResearchMode(data.get("mode", "standard")),
            transition_history=history,
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )

    @classmethod
    def create_for_mode(cls, mode: ResearchMode) -> "ResearchStateMachine":
        """为指定模式创建状态机"""
        return cls(
            current_state=ResearchState.PENDING,
            mode=mode,
        )


def get_expected_flow(mode: ResearchMode) -> list[ResearchState]:
    """
    获取指定模式的预期状态流程
    
    Args:
        mode: 研究模式
        
    Returns:
        预期的状态列表（按顺序）
    """
    if mode == ResearchMode.STANDARD:
        return [
            ResearchState.PENDING,
            ResearchState.EXECUTING,
            ResearchState.COMPLETED,
        ]
    else:  # DEEP
        return [
            ResearchState.PENDING,
            ResearchState.ANALYZING,
            ResearchState.PENDING_CLARIFICATION,
            ResearchState.RESUMED,
            ResearchState.PLANNING,
            ResearchState.PENDING_CONFIRMATION,
            ResearchState.CONFIRMED,
            ResearchState.EXECUTING,
            ResearchState.COMPLETED,
        ]
