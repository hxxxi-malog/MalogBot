"""
任务看板模块

实现任务看板和DAG依赖管理：
1. 任务创建和状态管理
2. DAG依赖关系维护
3. 任务领取机制
4. 进度追踪
"""
import json
import logging
import threading
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from agent.team.types import (
    SubTask,
    TaskStatus,
    TaskPriority,
    DAGPlan
)

logger = logging.getLogger(__name__)


class TaskBoard:
    """
    任务看板
    
    核心功能：
    1. 维护DAG任务依赖关系
    2. 管理任务状态转换
    3. 支持Follower领取任务
    4. 持久化存储
    """
    
    def __init__(self, storage_file: Optional[Path] = None):
        """
        初始化任务看板
        
        Args:
            storage_file: 持久化存储文件路径
        """
        self._lock = threading.RLock()
        self._storage_file = storage_file
        self._plan: Optional[DAGPlan] = None
        self._task_assignments: Dict[str, str] = {}  # task_id -> follower_id
        self._follower_tasks: Dict[str, Set[str]] = defaultdict(set)  # follower_id -> task_ids
        
        # 从文件加载
        self._load_from_file()
    
    def create_plan(
        self,
        goal: str,
        subtasks: List[Dict[str, Any]]
    ) -> DAGPlan:
        """
        创建执行计划
        
        Args:
            goal: 总目标
            subtasks: 子任务列表，每个任务包含：
                - id: 任务ID
                - description: 任务描述
                - dependencies: 依赖的任务ID列表
                - priority: 优先级
                - tool_hints: 建议工具
                - skill_hint: 建议技能
                
        Returns:
            DAGPlan对象
        """
        with self._lock:
            task_dict = {}
            
            for task_data in subtasks:
                task_id = task_data.get("id")
                if not task_id:
                    continue
                
                priority_str = task_data.get("priority", "medium")
                try:
                    priority = TaskPriority[priority_str.upper()]
                except KeyError:
                    priority = TaskPriority.MEDIUM
                
                task = SubTask(
                    id=task_id,
                    description=task_data.get("description", ""),
                    status=TaskStatus.PENDING,
                    priority=priority,
                    dependencies=set(task_data.get("dependencies", [])),
                    tool_hints=task_data.get("tool_hints", []),
                    skill_hint=task_data.get("skill_hint"),
                    context=task_data.get("context", {})
                )
                task_dict[task_id] = task
            
            # 计算拓扑排序
            execution_order = self._topological_sort(task_dict)
            
            # 计算可并行组
            parallel_groups = self._compute_parallel_groups(task_dict)
            
            self._plan = DAGPlan(
                goal=goal,
                subtasks=task_dict,
                execution_order=execution_order,
                parallel_groups=parallel_groups
            )
            
            self._save_to_file()
            
            logger.info(f"[TaskBoard] 创建计划: {goal}, {len(task_dict)}个任务")
            return self._plan
    
    def get_ready_tasks(self) -> List[SubTask]:
        """
        获取就绪的任务（依赖已满足，未分配）
        
        Returns:
            就绪任务列表
        """
        with self._lock:
            if not self._plan:
                return []
            
            ready = []
            completed = self._get_completed_task_ids()
            
            for task in self._plan.subtasks.values():
                # 任务状态为PENDING且依赖已满足且未被分配
                if (task.status == TaskStatus.PENDING and
                    task.is_ready(completed) and
                    task.id not in self._task_assignments):
                    ready.append(task)
            
            # 按优先级排序
            ready.sort(key=lambda t: t.priority.value, reverse=True)
            return ready
    
    def claim_task(
        self,
        task_id: str,
        follower_id: str
    ) -> Optional[SubTask]:
        """
        Follower领取任务
        
        Args:
            task_id: 任务ID
            follower_id: Follower ID
            
        Returns:
            领取的任务，如果无法领取返回None
        """
        with self._lock:
            if not self._plan:
                return None
            
            task = self._plan.subtasks.get(task_id)
            if not task:
                logger.warning(f"[TaskBoard] 任务不存在: {task_id}")
                return None
            
            # 检查任务状态
            if task.status != TaskStatus.PENDING:
                logger.warning(f"[TaskBoard] 任务状态不正确: {task_id}, {task.status}")
                return None
            
            # 检查是否已被分配
            if task_id in self._task_assignments:
                logger.warning(f"[TaskBoard] 任务已被分配: {task_id}")
                return None
            
            # 检查依赖是否满足
            completed = self._get_completed_task_ids()
            if not task.is_ready(completed):
                logger.warning(f"[TaskBoard] 任务依赖未满足: {task_id}")
                return None
            
            # 分配任务
            task.status = TaskStatus.IN_PROGRESS
            task.assigned_to = follower_id
            task.started_at = datetime.now()
            
            self._task_assignments[task_id] = follower_id
            self._follower_tasks[follower_id].add(task_id)
            
            self._save_to_file()
            
            logger.info(f"[TaskBoard] Follower {follower_id} 领取任务 {task_id}")
            return task
    
    def complete_task(
        self,
        task_id: str,
        result: str,
        follower_id: str
    ) -> bool:
        """
        完成任务
        
        Args:
            task_id: 任务ID
            result: 执行结果
            follower_id: Follower ID
            
        Returns:
            是否成功
        """
        with self._lock:
            if not self._plan:
                return False
            
            task = self._plan.subtasks.get(task_id)
            if not task:
                return False
            
            # 验证分配
            if self._task_assignments.get(task_id) != follower_id:
                logger.warning(f"[TaskBoard] 任务分配验证失败: {task_id}")
                return False
            
            # 更新状态
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now()
            
            # 清理分配记录
            del self._task_assignments[task_id]
            self._follower_tasks[follower_id].discard(task_id)
            
            self._save_to_file()
            
            logger.info(f"[TaskBoard] 任务完成: {task_id}")
            return True
    
    def fail_task(
        self,
        task_id: str,
        error: str,
        follower_id: str
    ) -> bool:
        """
        标记任务失败
        
        Args:
            task_id: 任务ID
            error: 错误信息
            follower_id: Follower ID
            
        Returns:
            是否成功
        """
        with self._lock:
            if not self._plan:
                return False
            
            task = self._plan.subtasks.get(task_id)
            if not task:
                return False
            
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now()
            
            # 清理分配记录
            if task_id in self._task_assignments:
                del self._task_assignments[task_id]
            self._follower_tasks[follower_id].discard(task_id)
            
            self._save_to_file()
            
            logger.warning(f"[TaskBoard] 任务失败: {task_id}, {error}")
            return True
    
    def get_task(self, task_id: str) -> Optional[SubTask]:
        """获取任务"""
        with self._lock:
            if not self._plan:
                return None
            return self._plan.subtasks.get(task_id)
    
    def get_plan(self) -> Optional[DAGPlan]:
        """获取当前计划"""
        with self._lock:
            return self._plan
    
    def get_progress(self) -> Dict[str, Any]:
        """
        获取进度信息
        
        Returns:
            进度统计
        """
        with self._lock:
            if not self._plan:
                return {"status": "no_plan"}
            
            progress = self._plan.get_progress()
            
            return {
                "status": "active",
                "goal": self._plan.goal,
                "total": len(self._plan.subtasks),
                "progress": progress,
                "in_progress": len(self._plan.get_in_progress_tasks()),
                "ready": len(self.get_ready_tasks()),
                "blocked": len(self._plan.get_blocked_tasks()),
                "completed_ids": list(self._get_completed_task_ids())
            }
    
    def render(self) -> str:
        """
        渲染任务看板为可读字符串
        """
        with self._lock:
            if not self._plan:
                return "当前没有执行计划"
            
            lines = ["[任务看板]", ""]
            lines.append(f"目标: {self._plan.goal}")
            lines.append("")
            
            # 按执行顺序显示
            completed = self._get_completed_task_ids()
            
            for task_id in self._plan.execution_order:
                task = self._plan.subtasks[task_id]
                
                # 状态图标
                if task.status == TaskStatus.COMPLETED:
                    icon = "[x]"
                elif task.status == TaskStatus.IN_PROGRESS:
                    icon = "[>]"
                elif task.status == TaskStatus.FAILED:
                    icon = "[!]"
                elif task.is_ready(completed):
                    icon = "[o]"  # 就绪
                else:
                    icon = "[ ]"  # 阻塞
                
                # 任务行
                priority_str = f"P{task.priority.value}"
                assignee = f" -> {task.assigned_to}" if task.assigned_to else ""
                lines.append(f"  {icon} [{task.id}] {priority_str} {task.description}{assignee}")
            
            # 统计
            progress = self._plan.get_progress()
            lines.append("")
            lines.append(f"进度: 完成 {progress['completed']} | 进行中 {progress['in_progress']} | 待处理 {progress['pending']} | 失败 {progress['failed']}")
            
            return "\n".join(lines)
    
    def clear(self):
        """清空任务看板"""
        with self._lock:
            self._plan = None
            self._task_assignments.clear()
            self._follower_tasks.clear()
            self._save_to_file()
    
    def _get_completed_task_ids(self) -> Set[str]:
        """获取已完成任务的ID集合"""
        if not self._plan:
            return set()
        return {
            tid for tid, task in self._plan.subtasks.items()
            if task.status == TaskStatus.COMPLETED
        }
    
    def _topological_sort(self, tasks: Dict[str, SubTask]) -> List[str]:
        """
        拓扑排序
        
        返回任务的执行顺序
        """
        # 构建入度字典
        in_degree = {tid: 0 for tid in tasks}
        graph = defaultdict(list)
        
        for tid, task in tasks.items():
            for dep_id in task.dependencies:
                if dep_id in tasks:
                    graph[dep_id].append(tid)
                    in_degree[tid] += 1
        
        # Kahn算法
        queue = [tid for tid, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            # 按优先级排序队列
            queue.sort(key=lambda t: tasks[t].priority.value, reverse=True)
            tid = queue.pop(0)
            result.append(tid)
            
            for next_tid in graph[tid]:
                in_degree[next_tid] -= 1
                if in_degree[next_tid] == 0:
                    queue.append(next_tid)
        
        return result
    
    def _compute_parallel_groups(self, tasks: Dict[str, SubTask]) -> List[List[str]]:
        """
        计算可并行执行的任务组
        
        每组内的任务可以并行执行
        """
        if not tasks:
            return []
        
        # 按层级分组
        levels = {}  # task_id -> level
        completed_ids = set()
        
        def get_level(tid: str) -> int:
            if tid in levels:
                return levels[tid]
            
            task = tasks.get(tid)
            if not task:
                return 0
            
            if not task.dependencies:
                levels[tid] = 0
                return 0
            
            max_dep_level = 0
            for dep_id in task.dependencies:
                if dep_id in tasks:
                    dep_level = get_level(dep_id)
                    max_dep_level = max(max_dep_level, dep_level + 1)
            
            levels[tid] = max_dep_level
            return max_dep_level
        
        # 计算每个任务的层级
        for tid in tasks:
            get_level(tid)
        
        # 按层级分组
        max_level = max(levels.values()) if levels else 0
        groups = [[] for _ in range(max_level + 1)]
        
        for tid, level in levels.items():
            groups[level].append(tid)
        
        return groups
    
    def _load_from_file(self):
        """从文件加载"""
        if not self._storage_file or not self._storage_file.exists():
            return
        
        try:
            data = json.loads(self._storage_file.read_text(encoding="utf-8"))
            
            # 重建DAGPlan
            if data.get("plan"):
                plan_data = data["plan"]
                tasks = {}
                
                for tid, tdata in plan_data.get("subtasks", {}).items():
                    task = SubTask(
                        id=tid,
                        description=tdata.get("description", ""),
                        status=TaskStatus(tdata.get("status", "pending")),
                        priority=TaskPriority(tdata.get("priority", 2)),
                        dependencies=set(tdata.get("dependencies", [])),
                        assigned_to=tdata.get("assigned_to"),
                        result=tdata.get("result"),
                        error=tdata.get("error"),
                        tool_hints=tdata.get("tool_hints", []),
                        skill_hint=tdata.get("skill_hint"),
                        context=tdata.get("context", {})
                    )
                    tasks[tid] = task
                
                self._plan = DAGPlan(
                    goal=plan_data.get("goal", ""),
                    subtasks=tasks,
                    execution_order=plan_data.get("execution_order", []),
                    parallel_groups=plan_data.get("parallel_groups", [])
                )
            
            self._task_assignments = data.get("assignments", {})
            
            logger.info(f"[TaskBoard] 从文件加载成功")
            
        except Exception as e:
            logger.error(f"[TaskBoard] 加载失败: {e}")
    
    def _save_to_file(self):
        """保存到文件"""
        if not self._storage_file:
            return
        
        try:
            data = {
                "plan": self._plan.to_dict() if self._plan else None,
                "assignments": self._task_assignments,
                "updated_at": datetime.now().isoformat()
            }
            
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            self._storage_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"[TaskBoard] 保存失败: {e}")


# ==================== 会话级任务看板管理 ====================

_task_boards: Dict[str, TaskBoard] = {}
TASKS_ROOT_DIR = Path(__file__).parent.parent.parent / "tasks"


def get_task_board(session_id: str) -> TaskBoard:
    """获取会话的任务看板"""
    if session_id not in _task_boards:
        storage_file = TASKS_ROOT_DIR / session_id / "task_board.json"
        _task_boards[session_id] = TaskBoard(storage_file)
    return _task_boards[session_id]


def remove_task_board(session_id: str):
    """删除会话的任务看板"""
    if session_id in _task_boards:
        del _task_boards[session_id]


# 导出
__all__ = [
    'TaskBoard',
    'get_task_board',
    'remove_task_board'
]
