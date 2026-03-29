"""
TaskManager 工具模块 - 持久化任务图管理

提供复杂的任务编排能力：
1. 任务持久化到磁盘（JSON文件）
2. 支持任务依赖关系（DAG）
3. 自动解锁依赖链
4. 任务图状态查询

设计思路：
- 简单线性任务使用 TodoManager
- 复杂有依赖的任务使用 TaskManager
- 任务图可以跨会话持久化
"""
import json
import threading
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool


class TaskManager:
    """
    任务图管理器 - 持久化 + DAG依赖
    
    核心概念：
    - 任务持久化为独立的 JSON 文件
    - 每个任务有前置依赖(blockedBy)和后置依赖(blocks)
    - 任务完成时自动解锁后续任务
    
    三个核心问题：
    1. 什么可以做？ -> pending 且 blockedBy 为空
    2. 什么被卡住？ -> 有 blockedBy 的任务
    3. 什么做完了？ -> completed 的任务
    """
    
    # 状态常量
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    
    # 有效状态集合
    VALID_STATUSES = {STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_FAILED}
    
    def __init__(self, tasks_dir: Path):
        """
        初始化任务管理器
        
        Args:
            tasks_dir: 任务文件存储目录
        """
        self.dir = Path(tasks_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1
        self._lock = threading.Lock()
    
    def _max_id(self) -> int:
        """获取当前最大的任务ID"""
        max_id = 0
        for f in self.dir.glob("task_*.json"):
            try:
                task_id = int(f.stem.replace("task_", ""))
                max_id = max(max_id, task_id)
            except ValueError:
                continue
        return max_id
    
    def _task_file(self, task_id: int) -> Path:
        """获取任务文件路径"""
        return self.dir / f"task_{task_id:04d}.json"
    
    def _save(self, task: Dict[str, Any]) -> None:
        """保存任务到文件"""
        task["updated_at"] = datetime.now().isoformat()
        file_path = self._task_file(task["id"])
        file_path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    
    def _load(self, task_id: int) -> Optional[Dict[str, Any]]:
        """从文件加载任务"""
        file_path = self._task_file(task_id)
        if file_path.exists():
            return json.loads(file_path.read_text(encoding="utf-8"))
        return None
    
    def _load_all(self) -> List[Dict[str, Any]]:
        """加载所有任务"""
        tasks = []
        for f in self.dir.glob("task_*.json"):
            try:
                task = json.loads(f.read_text(encoding="utf-8"))
                tasks.append(task)
            except (json.JSONDecodeError, Exception):
                continue
        return sorted(tasks, key=lambda t: t.get("id", 0))
    
    def _clear_dependency(self, completed_id: int) -> int:
        """
        解除对已完成任务的依赖
        
        当任务完成时调用，自动解锁后续任务。
        
        Args:
            completed_id: 已完成的任务ID
            
        Returns:
            被解锁的任务数量
        """
        unlocked_count = 0
        for task in self._load_all():
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
                # 如果 blockedBy 变为空且状态是 pending，则解锁
                if not task["blockedBy"] and task.get("status") == self.STATUS_PENDING:
                    unlocked_count += 1
        return unlocked_count
    
    # ==================== 公共 API ====================
    
    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: Optional[List[int]] = None,
        context: str = ""
    ) -> str:
        """
        创建新任务
        
        Args:
            subject: 任务主题/标题
            description: 任务详细描述
            blocked_by: 前置依赖任务ID列表
            context: 执行上下文（如文件路径、URL等）
            
        Returns:
            任务JSON字符串
        """
        with self._lock:
            blocked_by = blocked_by or []
            
            # 验证前置依赖是否存在
            for dep_id in blocked_by:
                if not self._load(dep_id):
                    return json.dumps({
                        "error": f"前置任务 {dep_id} 不存在",
                        "hint": "请先创建前置任务，或检查任务ID是否正确"
                    }, ensure_ascii=False, indent=2)
            
            task = {
                "id": self._next_id,
                "subject": subject,
                "description": description,
                "status": self.STATUS_PENDING,
                "blockedBy": blocked_by,  # 前置依赖
                "blocks": [],             # 后置依赖（自动维护）
                "owner": "",
                "context": context,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            self._save(task)
            
            # 更新前置任务的 blocks 列表
            for dep_id in blocked_by:
                dep_task = self._load(dep_id)
                if dep_task:
                    if task["id"] not in dep_task.get("blocks", []):
                        dep_task.setdefault("blocks", []).append(task["id"])
                        self._save(dep_task)
            
            self._next_id += 1
            
            return json.dumps(task, ensure_ascii=False, indent=2)
    
    def update(
        self,
        task_id: int,
        status: Optional[str] = None,
        add_blocked_by: Optional[int] = None,
        add_blocks: Optional[int] = None,
        owner: Optional[str] = None,
        note: Optional[str] = None
    ) -> str:
        """
        更新任务状态和依赖
        
        Args:
            task_id: 任务ID
            status: 新状态
            add_blocked_by: 添加前置依赖
            add_blocks: 添加后置依赖
            owner: 任务执行者
            note: 备注
            
        Returns:
            更新后的任务JSON
        """
        with self._lock:
            task = self._load(task_id)
            if not task:
                return json.dumps({
                    "error": f"任务 {task_id} 不存在"
                }, ensure_ascii=False, indent=2)
            
            # 更新状态
            if status:
                if status not in self.VALID_STATUSES:
                    return json.dumps({
                        "error": f"无效的状态: {status}",
                        "valid_statuses": list(self.VALID_STATUSES)
                    }, ensure_ascii=False, indent=2)
                
                old_status = task.get("status")
                task["status"] = status
                
                # 如果任务完成，自动解锁依赖
                if status == self.STATUS_COMPLETED and old_status != self.STATUS_COMPLETED:
                    unlocked = self._clear_dependency(task_id)
                    task["unlocked_count"] = unlocked
            
            # 添加前置依赖
            if add_blocked_by is not None:
                if add_blocked_by not in task.get("blockedBy", []):
                    # 验证前置任务存在
                    dep_task = self._load(add_blocked_by)
                    if not dep_task:
                        return json.dumps({
                            "error": f"前置任务 {add_blocked_by} 不存在"
                        }, ensure_ascii=False, indent=2)
                    
                    task.setdefault("blockedBy", []).append(add_blocked_by)
                    
                    # 更新前置任务的 blocks
                    if task_id not in dep_task.get("blocks", []):
                        dep_task.setdefault("blocks", []).append(task_id)
                        self._save(dep_task)
            
            # 添加后置依赖
            if add_blocks is not None:
                if add_blocks not in task.get("blocks", []):
                    # 验证后置任务存在
                    block_task = self._load(add_blocks)
                    if not block_task:
                        return json.dumps({
                            "error": f"后置任务 {add_blocks} 不存在"
                        }, ensure_ascii=False, indent=2)
                    
                    task.setdefault("blocks", []).append(add_blocks)
                    
                    # 更新后置任务的 blockedBy
                    if task_id not in block_task.get("blockedBy", []):
                        block_task.setdefault("blockedBy", []).append(task_id)
                        self._save(block_task)
            
            # 更新其他字段
            if owner:
                task["owner"] = owner
            if note:
                task["note"] = note
            
            self._save(task)
            
            return json.dumps(task, ensure_ascii=False, indent=2)
    
    def get(self, task_id: int) -> str:
        """
        获取单个任务详情
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务JSON字符串
        """
        task = self._load(task_id)
        if not task:
            return json.dumps({
                "error": f"任务 {task_id} 不存在"
            }, ensure_ascii=False, indent=2)
        return json.dumps(task, ensure_ascii=False, indent=2)
    
    # ==================== 查询接口 ====================
    
    def get_ready_tasks(self) -> str:
        """
        获取可执行的任务列表
        
        返回状态为 pending 且 blockedBy 为空的任务。
        这些任务可以立即开始执行。
        
        Returns:
            可执行任务列表
        """
        tasks = self._load_all()
        ready = [
            t for t in tasks
            if t.get("status") == self.STATUS_PENDING
            and not t.get("blockedBy", [])
        ]
        
        result = {
            "question": "什么可以做？",
            "count": len(ready),
            "tasks": ready
        }
        
        if ready:
            result["hint"] = "这些任务可以立即开始执行，使用 task_update 将状态改为 in_progress"
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_blocked_tasks(self) -> str:
        """
        获取被阻塞的任务列表
        
        返回有前置依赖未完成的任务。
        这些任务需要等待前置任务完成。
        
        Returns:
            被阻塞任务列表
        """
        tasks = self._load_all()
        blocked = [
            t for t in tasks
            if t.get("blockedBy", [])
            and t.get("status") in [self.STATUS_PENDING, self.STATUS_IN_PROGRESS]
        ]
        
        # 为每个任务添加依赖详情
        for task in blocked:
            task["blockedByDetails"] = []
            for dep_id in task.get("blockedBy", []):
                dep_task = self._load(dep_id)
                if dep_task:
                    task["blockedByDetails"].append({
                        "id": dep_id,
                        "subject": dep_task.get("subject", ""),
                        "status": dep_task.get("status", "")
                    })
        
        result = {
            "question": "什么被卡住？",
            "count": len(blocked),
            "tasks": blocked
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_completed_tasks(self) -> str:
        """
        获取已完成的任务列表
        
        Returns:
            已完成任务列表
        """
        tasks = self._load_all()
        completed = [t for t in tasks if t.get("status") == self.STATUS_COMPLETED]
        
        result = {
            "question": "什么做完了？",
            "count": len(completed),
            "tasks": completed
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_in_progress_tasks(self) -> str:
        """
        获取正在进行的任务列表
        
        Returns:
            进行中任务列表
        """
        tasks = self._load_all()
        in_progress = [t for t in tasks if t.get("status") == self.STATUS_IN_PROGRESS]
        
        result = {
            "question": "正在做什么？",
            "count": len(in_progress),
            "tasks": in_progress,
            "hint": "建议同时只处理一个任务" if len(in_progress) > 1 else None
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_status(self) -> str:
        """
        获取任务图整体状态
        
        Returns:
            状态摘要
        """
        tasks = self._load_all()
        
        stats = {
            "total": len(tasks),
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "cancelled": 0,
            "failed": 0,
            "blocked": 0,
            "ready": 0
        }
        
        for task in tasks:
            status = task.get("status", self.STATUS_PENDING)
            if status in stats:
                stats[status] += 1
            
            # 统计阻塞和就绪
            if status == self.STATUS_PENDING:
                if task.get("blockedBy", []):
                    stats["blocked"] += 1
                else:
                    stats["ready"] += 1
        
        # 计算进度
        if stats["total"] > 0:
            progress = stats["completed"] / stats["total"] * 100
        else:
            progress = 0
        
        result = {
            "summary": stats,
            "progress": f"{progress:.1f}%",
            "questions": {
                "什么可以做？": f"{stats['ready']} 个任务就绪",
                "什么被卡住？": f"{stats['blocked']} 个任务等待中",
                "什么做完了？": f"{stats['completed']} 个任务已完成"
            }
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def list_all(self) -> str:
        """
        列出所有任务
        
        Returns:
            所有任务列表
        """
        tasks = self._load_all()
        
        result = {
            "count": len(tasks),
            "tasks": tasks
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def visualize(self) -> str:
        """
        可视化任务图
        
        Returns:
            文本风格的任务图
        """
        tasks = self._load_all()
        
        if not tasks:
            return "任务图为空"
        
        lines = ["任务图", ""]
        
        # 按状态分组
        by_status = {
            self.STATUS_IN_PROGRESS: [],
            self.STATUS_PENDING: [],
            self.STATUS_COMPLETED: [],
            self.STATUS_CANCELLED: [],
            self.STATUS_FAILED: []
        }
        
        for task in tasks:
            status = task.get("status", self.STATUS_PENDING)
            if status in by_status:
                by_status[status].append(task)
        
        # 渲染进行中的任务
        if by_status[self.STATUS_IN_PROGRESS]:
            lines.append("### 进行中")
            for task in by_status[self.STATUS_IN_PROGRESS]:
                blocked = "[被阻塞]" if task.get("blockedBy") else ""
                lines.append(f"  [{task['id']}] {task['subject']} {blocked}")
            lines.append("")
        
        # 渲染待处理的任务
        if by_status[self.STATUS_PENDING]:
            lines.append("### 待处理")
            for task in by_status[self.STATUS_PENDING]:
                if task.get("blockedBy"):
                    deps = ", ".join(str(d) for d in task["blockedBy"])
                    lines.append(f"  [{task['id']}] {task['subject']} (等待: {deps})")
                else:
                    lines.append(f"  [{task['id']}] {task['subject']} [可执行]")
            lines.append("")
        
        # 渲染已完成的任务
        if by_status[self.STATUS_COMPLETED]:
            lines.append("### 已完成")
            for task in by_status[self.STATUS_COMPLETED]:
                lines.append(f"  [{task['id']}] {task['subject']}")
            lines.append("")
        
        # 渲染失败/取消的任务
        if by_status[self.STATUS_FAILED] or by_status[self.STATUS_CANCELLED]:
            lines.append("### 失败/取消")
            for task in by_status[self.STATUS_FAILED]:
                lines.append(f"  [{task['id']}] {task['subject']} (失败)")
            for task in by_status[self.STATUS_CANCELLED]:
                lines.append(f"  [{task['id']}] {task['subject']} (取消)")
        
        return "\n".join(lines)
    
    def delete(self, task_id: int) -> str:
        """
        删除任务
        
        同时会从其他任务的依赖列表中移除该任务。
        
        Args:
            task_id: 任务ID
            
        Returns:
            操作结果
        """
        with self._lock:
            task = self._load(task_id)
            if not task:
                return json.dumps({
                    "error": f"任务 {task_id} 不存在"
                }, ensure_ascii=False, indent=2)
            
            # 从前置任务的 blocks 列表中移除
            for dep_id in task.get("blockedBy", []):
                dep_task = self._load(dep_id)
                if dep_task and task_id in dep_task.get("blocks", []):
                    dep_task["blocks"].remove(task_id)
                    self._save(dep_task)
            
            # 从后置任务的 blockedBy 列表中移除
            for block_id in task.get("blocks", []):
                block_task = self._load(block_id)
                if block_task and task_id in block_task.get("blockedBy", []):
                    block_task["blockedBy"].remove(task_id)
                    self._save(block_task)
            
            # 删除任务文件
            self._task_file(task_id).unlink()
            
            return json.dumps({
                "success": True,
                "message": f"任务 {task_id} 已删除",
                "deleted_task": task["subject"]
            }, ensure_ascii=False, indent=2)
    
    def clear_all(self) -> str:
        """
        清空所有任务
        
        Returns:
            操作结果
        """
        with self._lock:
            count = 0
            for f in self.dir.glob("task_*.json"):
                f.unlink()
                count += 1
            self._next_id = 1
            
            return json.dumps({
                "success": True,
                "message": f"已清空 {count} 个任务"
            }, ensure_ascii=False, indent=2)


# ==================== 会话级别的 TaskManager 管理 ====================

# 全局会话任务管理器存储
# key: session_id, value: TaskManager 实例
_session_managers: Dict[str, TaskManager] = {}

# 默认任务存储根目录
TASKS_ROOT_DIR = Path(__file__).parent.parent.parent / "tasks"


def get_task_manager(session_id: str) -> TaskManager:
    """
    获取会话的 TaskManager 实例
    
    Args:
        session_id: 会话ID
        
    Returns:
        TaskManager 实例
    """
    if session_id not in _session_managers:
        # 每个会话使用独立的任务目录
        tasks_dir = TASKS_ROOT_DIR / session_id
        _session_managers[session_id] = TaskManager(tasks_dir)
    return _session_managers[session_id]


def remove_task_manager(session_id: str) -> None:
    """
    删除会话的 TaskManager 实例
    
    Args:
        session_id: 会话ID
    """
    if session_id in _session_managers:
        del _session_managers[session_id]


# ==================== LangChain 工具定义 ====================

# 复用 todo_manager 的会话上下文
from agent.tools.todo_manager import get_current_session


@tool
def task_create(
    subject: str,
    description: str = "",
    blocked_by: Optional[List[int]] = None,
    context: str = ""
) -> str:
    """
    创建支持依赖关系的任务。详细用法: get_tool_usage('task_management')
    
    Args:
        subject: 任务主题
        description: 任务描述(可选)
        blocked_by: 前置依赖任务ID列表(可选)
        context: 执行上下文(可选)
        
    Returns:
        创建的任务JSON
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.create(subject, description, blocked_by, context)


@tool
def task_update(
    task_id: int,
    status: Optional[str] = None,
    add_blocked_by: Optional[int] = None,
    add_blocks: Optional[int] = None,
    note: Optional[str] = None
) -> str:
    """
    更新任务状态。详细用法: get_tool_usage('task_management')
    
    Args:
        task_id: 任务ID
        status: 新状态(pending/in_progress/completed/cancelled/failed)
        add_blocked_by: 添加前置依赖(可选)
        add_blocks: 添加后置依赖(可选)
        note: 备注信息(可选)
        
    Returns:
        更新后的任务JSON
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.update(task_id, status, add_blocked_by, add_blocks, note=note)


@tool
def task_get(task_id: int) -> str:
    """
    获取任务详情。
    
    Args:
        task_id: 任务ID
        
    Returns:
        任务详情JSON
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get(task_id)


@tool
def task_get_ready() -> str:
    """
    获取可立即执行的任务(pending且无阻塞)。
    
    Returns:
        可执行任务列表
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_ready_tasks()


@tool
def task_get_blocked() -> str:
    """
    获取被阻塞的任务。
    
    Returns:
        被阻塞任务列表
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_blocked_tasks()


@tool
def task_get_status() -> str:
    """
    获取任务图整体状态。
    
    Returns:
        任务图状态摘要
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_status()


@tool
def task_visualize() -> str:
    """
    可视化任务图。
    
    Returns:
        任务图可视化
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.visualize()


@tool
def task_list() -> str:
    """
    列出所有任务。
    
    Returns:
        所有任务列表
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.list_all()


@tool
def task_delete(task_id: int) -> str:
    """
    删除一个任务。
    
    会自动从其他任务的依赖列表中移除该任务。
    
    Args:
        task_id: 要删除的任务ID
        
    Returns:
        操作结果
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.delete(task_id)


@tool
def task_clear() -> str:
    """
    清空所有任务。
    
    此操作不可恢复！
    
    Returns:
        操作结果
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.clear_all()


# ==================== 工具列表 ====================

TASK_MANAGER_TOOLS = [
    task_create,
    task_update,
    task_get,
    task_get_ready,
    task_get_blocked,
    task_get_status,
    task_visualize,
    task_list,
    task_delete,
    task_clear
]


# ==================== 导出 ====================

__all__ = [
    'TaskManager',
    'get_task_manager',
    'remove_task_manager',
    'task_create',
    'task_update',
    'task_get',
    'task_get_ready',
    'task_get_blocked',
    'task_get_status',
    'task_visualize',
    'task_list',
    'task_delete',
    'task_clear',
    'TASK_MANAGER_TOOLS'
]
