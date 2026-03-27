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
    
    VALID_STATUSES = {STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_FAILED}
    
    def __init__(self, tasks_dir: Path):
        """初始化任务管理器"""
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
        """解除对已完成任务的依赖"""
        unlocked_count = 0
        for task in self._load_all():
            if completed_id in task.get("blockedBy", []):
                task["blockedBy"].remove(completed_id)
                self._save(task)
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
        """创建新任务"""
        with self._lock:
            blocked_by = blocked_by or []
            
            for dep_id in blocked_by:
                if not self._load(dep_id):
                    return json.dumps({
                        "error": f"前置任务 {dep_id} 不存在",
                        "hint": "请先创建前置任务"
                    }, ensure_ascii=False, indent=2)
            
            task = {
                "id": self._next_id,
                "subject": subject,
                "description": description,
                "status": self.STATUS_PENDING,
                "blockedBy": blocked_by,
                "blocks": [],
                "owner": "",
                "context": context,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            self._save(task)
            
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
        """更新任务状态和依赖"""
        with self._lock:
            task = self._load(task_id)
            if not task:
                return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False, indent=2)
            
            if status:
                if status not in self.VALID_STATUSES:
                    return json.dumps({
                        "error": f"无效的状态: {status}",
                        "valid_statuses": list(self.VALID_STATUSES)
                    }, ensure_ascii=False, indent=2)
                
                old_status = task.get("status")
                task["status"] = status
                
                if status == self.STATUS_COMPLETED and old_status != self.STATUS_COMPLETED:
                    unlocked = self._clear_dependency(task_id)
                    task["unlocked_count"] = unlocked
            
            if add_blocked_by is not None:
                if add_blocked_by not in task.get("blockedBy", []):
                    dep_task = self._load(add_blocked_by)
                    if not dep_task:
                        return json.dumps({"error": f"前置任务 {add_blocked_by} 不存在"}, ensure_ascii=False, indent=2)
                    
                    task.setdefault("blockedBy", []).append(add_blocked_by)
                    if task_id not in dep_task.get("blocks", []):
                        dep_task.setdefault("blocks", []).append(task_id)
                        self._save(dep_task)
            
            if add_blocks is not None:
                if add_blocks not in task.get("blocks", []):
                    block_task = self._load(add_blocks)
                    if not block_task:
                        return json.dumps({"error": f"后置任务 {add_blocks} 不存在"}, ensure_ascii=False, indent=2)
                    
                    task.setdefault("blocks", []).append(add_blocks)
                    if task_id not in block_task.get("blockedBy", []):
                        block_task.setdefault("blockedBy", []).append(task_id)
                        self._save(block_task)
            
            if owner:
                task["owner"] = owner
            if note:
                task["note"] = note
            
            self._save(task)
            return json.dumps(task, ensure_ascii=False, indent=2)
    
    def get(self, task_id: int) -> str:
        """获取单个任务详情"""
        task = self._load(task_id)
        if not task:
            return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False, indent=2)
        return json.dumps(task, ensure_ascii=False, indent=2)
    
    # ==================== 查询接口 ====================
    
    def get_ready_tasks(self) -> str:
        """获取可执行的任务"""
        tasks = self._load_all()
        ready = [t for t in tasks if t.get("status") == self.STATUS_PENDING and not t.get("blockedBy", [])]
        
        result = {
            "question": "什么可以做？",
            "count": len(ready),
            "tasks": ready
        }
        if ready:
            result["hint"] = "这些任务可以立即开始执行"
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    def get_blocked_tasks(self) -> str:
        """获取被阻塞的任务"""
        tasks = self._load_all()
        blocked = [t for t in tasks if t.get("blockedBy", []) and t.get("status") in [self.STATUS_PENDING, self.STATUS_IN_PROGRESS]]
        
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
        
        return json.dumps({
            "question": "什么被卡住？",
            "count": len(blocked),
            "tasks": blocked
        }, ensure_ascii=False, indent=2)
    
    def get_completed_tasks(self) -> str:
        """获取已完成的任务"""
        tasks = self._load_all()
        completed = [t for t in tasks if t.get("status") == self.STATUS_COMPLETED]
        
        return json.dumps({
            "question": "什么做完了？",
            "count": len(completed),
            "tasks": completed
        }, ensure_ascii=False, indent=2)
    
    def get_in_progress_tasks(self) -> str:
        """获取正在进行的任务"""
        tasks = self._load_all()
        in_progress = [t for t in tasks if t.get("status") == self.STATUS_IN_PROGRESS]
        
        return json.dumps({
            "question": "正在做什么？",
            "count": len(in_progress),
            "tasks": in_progress
        }, ensure_ascii=False, indent=2)
    
    def get_status(self) -> str:
        """获取任务图整体状态"""
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
            
            if status == self.STATUS_PENDING:
                if task.get("blockedBy", []):
                    stats["blocked"] += 1
                else:
                    stats["ready"] += 1
        
        progress = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        
        return json.dumps({
            "summary": stats,
            "progress": f"{progress:.1f}%",
            "questions": {
                "什么可以做？": f"{stats['ready']} 个任务就绪",
                "什么被卡住？": f"{stats['blocked']} 个任务等待中",
                "什么做完了？": f"{stats['completed']} 个任务已完成"
            }
        }, ensure_ascii=False, indent=2)
    
    def list_all(self) -> str:
        """列出所有任务"""
        tasks = self._load_all()
        return json.dumps({"count": len(tasks), "tasks": tasks}, ensure_ascii=False, indent=2)
    
    def visualize(self) -> str:
        """可视化任务图"""
        tasks = self._load_all()
        
        if not tasks:
            return "任务图为空"
        
        lines = ["任务图", ""]
        
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
        
        if by_status[self.STATUS_IN_PROGRESS]:
            lines.append("### 进行中")
            for task in by_status[self.STATUS_IN_PROGRESS]:
                lines.append(f"  [{task['id']}] {task['subject']}")
            lines.append("")
        
        if by_status[self.STATUS_PENDING]:
            lines.append("### 待处理")
            for task in by_status[self.STATUS_PENDING]:
                if task.get("blockedBy"):
                    deps = ", ".join(str(d) for d in task["blockedBy"])
                    lines.append(f"  [{task['id']}] {task['subject']} (等待: {deps})")
                else:
                    lines.append(f"  [{task['id']}] {task['subject']} [可执行]")
            lines.append("")
        
        if by_status[self.STATUS_COMPLETED]:
            lines.append("### 已完成")
            for task in by_status[self.STATUS_COMPLETED]:
                lines.append(f"  [{task['id']}] {task['subject']}")
        
        return "\n".join(lines)
    
    def delete(self, task_id: int) -> str:
        """删除任务"""
        with self._lock:
            task = self._load(task_id)
            if not task:
                return json.dumps({"error": f"任务 {task_id} 不存在"}, ensure_ascii=False, indent=2)
            
            for dep_id in task.get("blockedBy", []):
                dep_task = self._load(dep_id)
                if dep_task and task_id in dep_task.get("blocks", []):
                    dep_task["blocks"].remove(task_id)
                    self._save(dep_task)
            
            for block_id in task.get("blocks", []):
                block_task = self._load(block_id)
                if block_task and task_id in block_task.get("blockedBy", []):
                    block_task["blockedBy"].remove(task_id)
                    self._save(block_task)
            
            self._task_file(task_id).unlink()
            
            return json.dumps({
                "success": True,
                "message": f"任务 {task_id} 已删除",
                "deleted_task": task["subject"]
            }, ensure_ascii=False, indent=2)
    
    def clear_all(self) -> str:
        """清空所有任务"""
        with self._lock:
            count = 0
            for f in self.dir.glob("task_*.json"):
                f.unlink()
                count += 1
            self._next_id = 1
            
            return json.dumps({"success": True, "message": f"已清空 {count} 个任务"}, ensure_ascii=False, indent=2)


# ==================== 会话管理 ====================

_session_managers: Dict[str, TaskManager] = {}
TASKS_ROOT_DIR = Path(__file__).parent.parent.parent / "tasks"


def get_task_manager(session_id: str) -> TaskManager:
    """获取会话的 TaskManager 实例"""
    if session_id not in _session_managers:
        tasks_dir = TASKS_ROOT_DIR / session_id
        _session_managers[session_id] = TaskManager(tasks_dir)
    return _session_managers[session_id]


def remove_task_manager(session_id: str) -> None:
    """删除会话的 TaskManager 实例"""
    if session_id in _session_managers:
        del _session_managers[session_id]


# ==================== LangChain 工具 ====================

from agent.tools.todo_manager import get_current_session


@tool
def task_create(
    subject: str,
    description: str = "",
    blocked_by: Optional[List[int]] = None,
    context: str = ""
) -> str:
    """
    创建一个新任务（支持依赖关系）。
    
    适用场景：
    - 需要管理有依赖关系的复杂任务
    - 任务需要持久化（跨会话保存）
    
    Args:
        subject: 任务主题/标题
        description: 任务详细描述
        blocked_by: 前置依赖任务ID列表
        context: 执行上下文
        
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
    更新任务状态和依赖关系。
    
    状态：pending -> in_progress -> completed
    任务完成时会自动解锁后续任务。
    
    Args:
        task_id: 任务ID
        status: 新状态
        add_blocked_by: 添加前置依赖
        add_blocks: 添加后置依赖
        note: 备注信息
        
    Returns:
        更新后的任务JSON
    """
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.update(task_id, status, add_blocked_by, add_blocks, note=note)


@tool
def task_get(task_id: int) -> str:
    """获取单个任务的详细信息。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get(task_id)


@tool
def task_get_ready() -> str:
    """获取可以立即执行的任务（pending 且无阻塞）。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_ready_tasks()


@tool
def task_get_blocked() -> str:
    """获取被阻塞的任务（等待前置任务完成）。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_blocked_tasks()


@tool
def task_get_status() -> str:
    """获取任务图整体状态。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.get_status()


@tool
def task_visualize() -> str:
    """可视化任务图。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.visualize()


@tool
def task_list() -> str:
    """列出所有任务。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.list_all()


@tool
def task_delete(task_id: int) -> str:
    """删除一个任务。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.delete(task_id)


@tool
def task_clear() -> str:
    """清空所有任务。"""
    session_id = get_current_session()
    manager = get_task_manager(session_id)
    return manager.clear_all()


# ==================== 导出 ====================

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
