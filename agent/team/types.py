"""
多Agent团队协作系统 - 类型定义

定义Leader-Follower模式的核心数据类型：
1. 任务类型和状态
2. Agent角色定义
3. 路由决策类型
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from datetime import datetime


class QueryCategory(Enum):
    """查询分类"""
    KNOWLEDGE_QA = "knowledge_qa"      # 知识问答
    TASK_EXECUTION = "task_execution"  # 任务执行
    COMPLEX_PROJECT = "complex_project" # 复杂项目


class ExecutionMode(Enum):
    """执行模式"""
    SINGLE_AGENT = "single_agent"      # 单Agent模式
    TEAM_MODE = "team_mode"            # 团队模式


class AgentRole(Enum):
    """Agent角色"""
    LEADER = "leader"                  # Leader：规划、监控、整合
    FOLLOWER = "follower"              # Follower：执行具体任务


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"                # 待处理
    READY = "ready"                    # 就绪（依赖已满足）
    IN_PROGRESS = "in_progress"        # 执行中
    COMPLETED = "completed"            # 已完成
    FAILED = "failed"                  # 失败
    BLOCKED = "blocked"                # 被阻塞


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ComplexityAssessment:
    """复杂度评估结果"""
    score: float                        # 综合评分 (0-10)
    tool_count: int                     # 预估工具数量
    skill_required: bool                 # 是否需要技能
    dependencies: List[str]             # 依赖关系
    parallelizable: bool                # 是否可并行
    estimated_steps: int                # 预估步骤数
    reasoning: str                      # 评估理由
    
    def needs_team(self) -> bool:
        """判断是否需要团队模式"""
        return (
            self.score >= 6.0 or
            self.tool_count >= 5 or
            len(self.dependencies) >= 2 or
            (self.skill_required and self.estimated_steps >= 3)
        )


@dataclass
class RoutingDecision:
    """路由决策"""
    mode: ExecutionMode
    category: QueryCategory
    complexity: ComplexityAssessment
    reasoning: str
    suggested_followers: int = 1       # 建议的Follower数量


@dataclass
class SubTask:
    """子任务"""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: Set[str] = field(default_factory=set)
    assigned_to: Optional[str] = None  # Follower ID
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tool_hints: List[str] = field(default_factory=list)  # 建议使用的工具
    skill_hint: Optional[str] = None  # 建议使用的技能
    context: Dict[str, Any] = field(default_factory=dict)  # 任务上下文
    
    def is_ready(self, completed_tasks: Set[str]) -> bool:
        """检查任务是否就绪（依赖已满足）"""
        return self.dependencies.issubset(completed_tasks)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": list(self.dependencies),
            "assigned_to": self.assigned_to,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tool_hints": self.tool_hints,
            "skill_hint": self.skill_hint,
            "context": self.context
        }


@dataclass
class DAGPlan:
    """DAG执行计划"""
    goal: str                           # 总目标
    subtasks: Dict[str, SubTask]        # 子任务字典
    execution_order: List[str]          # 执行顺序（拓扑排序）
    parallel_groups: List[List[str]]    # 可并行执行的组
    created_at: datetime = field(default_factory=datetime.now)
    
    def get_ready_tasks(self) -> List[SubTask]:
        """获取就绪的任务"""
        completed = {
            tid for tid, task in self.subtasks.items()
            if task.status == TaskStatus.COMPLETED
        }
        return [
            task for task in self.subtasks.values()
            if task.status == TaskStatus.PENDING and task.is_ready(completed)
        ]
    
    def get_in_progress_tasks(self) -> List[SubTask]:
        """获取执行中的任务"""
        return [
            task for task in self.subtasks.values()
            if task.status == TaskStatus.IN_PROGRESS
        ]
    
    def get_pending_tasks(self) -> List[SubTask]:
        """获取待处理的任务"""
        return [
            task for task in self.subtasks.values()
            if task.status == TaskStatus.PENDING
        ]
    
    def get_blocked_tasks(self) -> List[SubTask]:
        """获取被阻塞的任务"""
        completed = {
            tid for tid, task in self.subtasks.items()
            if task.status == TaskStatus.COMPLETED
        }
        return [
            task for task in self.subtasks.values()
            if task.status == TaskStatus.PENDING and not task.is_ready(completed)
        ]
    
    def is_complete(self) -> bool:
        """检查是否全部完成"""
        return all(
            task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            for task in self.subtasks.values()
        )
    
    def get_progress(self) -> Dict[str, int]:
        """获取进度统计"""
        status_counts = {}
        for status in TaskStatus:
            status_counts[status.value] = sum(
                1 for task in self.subtasks.values()
                if task.status == status
            )
        return status_counts
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "subtasks": {tid: task.to_dict() for tid, task in self.subtasks.items()},
            "execution_order": self.execution_order,
            "parallel_groups": self.parallel_groups,
            "created_at": self.created_at.isoformat(),
            "progress": self.get_progress()
        }


@dataclass
class FollowerInfo:
    """Follower信息"""
    id: str
    status: str = "idle"               # idle, busy, offline
    current_task: Optional[str] = None  # 当前任务ID
    completed_tasks: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    
    def is_available(self) -> bool:
        return self.status == "idle"


@dataclass
class TeamResult:
    """团队执行结果"""
    success: bool
    goal: str
    final_output: str
    subtask_results: Dict[str, str]
    execution_log: List[str]
    total_time: float
    followers_used: int
    parallelism_achieved: int  # 实际达到的并行度


# 导出
__all__ = [
    'QueryCategory',
    'ExecutionMode',
    'AgentRole',
    'TaskStatus',
    'TaskPriority',
    'ComplexityAssessment',
    'RoutingDecision',
    'SubTask',
    'DAGPlan',
    'FollowerInfo',
    'TeamResult'
]
