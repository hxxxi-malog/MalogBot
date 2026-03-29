"""
TodoManager 工具模块

提供任务管理能力，帮助模型在处理复杂任务时保持注意力：
1. 状态机管理任务状态
2. 持久化到 JSON 文件（支持跨会话恢复）
3. 同一时间只允许一个 in_progress 任务
4. 问责机制：超过N轮不调用时强制提醒

设计思路：
- 简单任务不需要调用此工具
- 复杂任务模型可自行决定调用，用于跟踪进度
- 任务持久化到磁盘，即使上下文压缩也不会丢失
"""
import json
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from langchain_core.tools import tool


# 任务存储根目录
TASKS_ROOT_DIR = Path(__file__).parent.parent.parent / "tasks"


class TodoManager:
    """
    任务管理器 - 状态机模式 + JSON 持久化
    
    状态转换规则：
    - pending -> in_progress: 开始任务
    - in_progress -> completed: 完成任务
    - in_progress -> cancelled: 取消任务
    - 同一时间只能有一个任务处于 in_progress 状态
    
    持久化：
    - 任务保存为 JSON 文件
    - 支持跨会话恢复
    - 上下文压缩不影响任务状态
    
    问责机制：
    - 记录上次调用后的轮次
    - 超过阈值未调用时，触发提醒
    """
    
    # 状态常量
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    
    # 问责机制阈值（连续多少轮未调用后提醒）
    ACCOUNTABILITY_THRESHOLD = 3
    
    def __init__(self, session_id: str = "default"):
        """
        初始化任务管理器
        
        Args:
            session_id: 会话ID，用于区分不同会话的任务文件
        """
        self.session_id = session_id
        self.items: List[Dict[str, Any]] = []
        self._turns_since_last_update: int = 0
        self._last_rendered: str = ""
        self._lock = threading.Lock()
        
        # 任务文件路径
        self.tasks_dir = TASKS_ROOT_DIR / session_id
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.tasks_dir / "todos.json"
        
        # 从文件加载任务
        self._load_from_file()
    
    def _load_from_file(self) -> None:
        """从 JSON 文件加载任务"""
        if self.tasks_file.exists():
            try:
                data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
                self.items = data.get("items", [])
                self._turns_since_last_update = data.get("turns_since_last_update", 0)
            except (json.JSONDecodeError, Exception):
                self.items = []
                self._turns_since_last_update = 0
    
    def _save_to_file(self) -> None:
        """保存任务到 JSON 文件"""
        data = {
            "session_id": self.session_id,
            "items": self.items,
            "turns_since_last_update": self._turns_since_last_update,
            "updated_at": datetime.now().isoformat()
        }
        self.tasks_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    
    def update(self, items: List[Dict[str, Any]]) -> str:
        """
        更新任务列表
        
        验证规则：
        1. 每个item必须包含 id, text, status
        2. 同一时间只能有一个 in_progress 任务
        
        Args:
            items: 任务列表，每个任务包含：
                - id: 唯一标识符
                - text: 任务描述
                - status: 状态 (pending/in_progress/completed/cancelled)
                
        Returns:
            渲染后的任务列表字符串
            
        Raises:
            ValueError: 当 in_progress 任务超过1个时
        """
        with self._lock:
            validated = []
            in_progress_count = 0
            
            for item in items:
                status = item.get("status", self.STATUS_PENDING)
                
                # 统计 in_progress 数量
                if status == self.STATUS_IN_PROGRESS:
                    in_progress_count += 1
                
                # 验证状态值
                valid_statuses = [
                    self.STATUS_PENDING,
                    self.STATUS_IN_PROGRESS,
                    self.STATUS_COMPLETED,
                    self.STATUS_CANCELLED
                ]
                if status not in valid_statuses:
                    status = self.STATUS_PENDING
                
                validated.append({
                    "id": item.get("id", ""),
                    "text": item.get("text", ""),
                    "status": status,
                    "updated_at": datetime.now().isoformat()
                })
            
            # 关键约束：同一时间只允许一个 in_progress
            if in_progress_count > 1:
                raise ValueError(
                    f"状态约束违反：同一时间只能有一个任务处于 in_progress 状态，"
                    f"当前有 {in_progress_count} 个 in_progress 任务。"
                )
            
            self.items = validated
            self._turns_since_last_update = 0  # 重置计数器
            
            # 持久化到文件
            self._save_to_file()
            
            return self.render()
    
    def render(self) -> str:
        """
        渲染任务列表为可读字符串
        
        Returns:
            格式化的任务列表字符串
        """
        if not self.items:
            return "当前没有待办任务"
        
        lines = ["任务列表", ""]
        
        # 按状态排序：in_progress > pending > completed/cancelled
        status_order = {
            self.STATUS_IN_PROGRESS: 0,
            self.STATUS_PENDING: 1,
            self.STATUS_COMPLETED: 2,
            self.STATUS_CANCELLED: 3
        }
        
        sorted_items = sorted(
            self.items,
            key=lambda x: status_order.get(x.get("status", ""), 99)
        )
        
        for item in sorted_items:
            status = item.get("status", "")
            text = item.get("text", "")
            id_ = item.get("id", "")
            
            if status == self.STATUS_IN_PROGRESS:
                lines.append(f"🔄 [{id_}] {text} (进行中)")
            elif status == self.STATUS_PENDING:
                lines.append(f"⏳ [{id_}] {text} (待处理)")
            elif status == self.STATUS_COMPLETED:
                lines.append(f"✅ [{id_}] {text} (已完成)")
            elif status == self.STATUS_CANCELLED:
                lines.append(f"❌ [{id_}] {text} (已取消)")
        
        # 统计
        completed = sum(1 for i in self.items if i.get("status") == self.STATUS_COMPLETED)
        total = len(self.items)
        lines.append("")
        lines.append(f"进度: {completed}/{total} 已完成")
        
        return "\n".join(lines)
    
    def increment_turn(self) -> bool:
        """
        增加未调用计数器
        
        每次模型响应后调用此方法，用于追踪问责
        
        Returns:
            是否超过阈值（需要提醒）
        """
        with self._lock:
            self._turns_since_last_update += 1
            # 持久化
            self._save_to_file()
            return self._turns_since_last_update > self.ACCOUNTABILITY_THRESHOLD
    
    def should_remind(self) -> bool:
        """
        检查是否需要提醒模型更新任务状态
        
        Returns:
            是否需要提醒
        """
        # 如果没有任务，不需要提醒
        if not self.items:
            return False
        
        # 如果所有任务都已完成或取消，不需要提醒
        active_statuses = [self.STATUS_PENDING, self.STATUS_IN_PROGRESS]
        has_active = any(item["status"] in active_statuses for item in self.items)
        if not has_active:
            return False
        
        return self._turns_since_last_update > self.ACCOUNTABILITY_THRESHOLD
    
    def get_reminder_message(self) -> str:
        """
        生成提醒消息
        
        当超过阈值未调用时，返回提醒消息供注入上下文
        
        Returns:
            提醒消息
        """
        if not self.should_remind():
            return ""
        
        turns = self._turns_since_last_update
        
        reminder = f"""
[任务状态提醒]

你已经连续 {turns} 轮没有更新任务状态了。
当前任务可能需要关注：

{self.render()}

请考虑：
1. 如果当前任务正在进行中，继续执行后调用 todo_manager 更新状态
2. 如果任务已完成，将状态更新为 completed
3. 如果遇到阻塞，考虑拆分任务或调整计划

保持任务列表的更新有助于你更好地追踪复杂任务的进度。
"""
        return reminder
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取当前任务状态摘要
        
        Returns:
            状态字典，包含任务列表和统计信息
        """
        return {
            "items": self.items,
            "turns_since_last_update": self._turns_since_last_update,
            "needs_attention": self.should_remind(),
            "total": len(self.items),
            "completed": sum(1 for i in self.items if i["status"] == self.STATUS_COMPLETED),
            "pending": sum(1 for i in self.items if i["status"] == self.STATUS_PENDING),
            "in_progress": sum(1 for i in self.items if i["status"] == self.STATUS_IN_PROGRESS)
        }
    
    def clear(self) -> str:
        """
        清空任务列表
        
        只有当所有任务都已完成或取消时才允许清空。
        
        Returns:
            确认消息或错误提示
        """
        with self._lock:
            # 检查是否有未完成的任务
            active_statuses = [self.STATUS_PENDING, self.STATUS_IN_PROGRESS]
            active_tasks = [t for t in self.items if t.get("status") in active_statuses]
            
            if active_tasks:
                active_list = "\n".join([f"  - [{t['id']}] {t['text']} ({t['status']})" for t in active_tasks])
                return f"""⚠️ 无法清空：还有 {len(active_tasks)} 个未完成的任务

未完成任务：
{active_list}

请先完成这些任务或将它们标记为 cancelled 后再清空。"""
            
            # 所有任务都已完成或取消，允许清空
            self.items = []
            self._turns_since_last_update = 0
            self._save_to_file()
        return "✅ 任务列表已清空（所有任务已完成）"
    
    def is_all_completed(self) -> bool:
        """
        检查所有任务是否都已完成
        
        Returns:
            是否所有任务都是 completed 或 cancelled
        """
        if not self.items:
            return True
        
        terminal_statuses = [self.STATUS_COMPLETED, self.STATUS_CANCELLED]
        return all(item.get("status") in terminal_statuses for item in self.items)


# ==================== 会话级别的 TodoManager 管理 ====================

# 全局会话任务管理器存储
# key: session_id, value: TodoManager 实例
_session_managers: Dict[str, TodoManager] = {}


def get_todo_manager(session_id: str) -> TodoManager:
    """
    获取会话的 TodoManager 实例
    
    Args:
        session_id: 会话ID
        
    Returns:
        TodoManager 实例
    """
    if session_id not in _session_managers:
        _session_managers[session_id] = TodoManager(session_id)
    return _session_managers[session_id]


def remove_todo_manager(session_id: str) -> None:
    """
    删除会话的 TodoManager 实例（清理内存缓存）
    
    注意：任务文件仍保留在磁盘上，支持后续恢复
    
    Args:
        session_id: 会话ID
    """
    if session_id in _session_managers:
        del _session_managers[session_id]


# ==================== LangChain 工具定义 ====================

# 用于在工具调用时传递 session_id 的上下文变量
# 由于 LangChain 工具不支持额外的上下文参数，我们使用 thread-local 存储
_current_session_id = threading.local()


def set_current_session(session_id: str) -> None:
    """设置当前会话ID（在工具调用前设置）"""
    _current_session_id.value = session_id


def get_current_session() -> str:
    """获取当前会话ID"""
    return getattr(_current_session_id, 'value', 'default')


@tool
def todo_manager(items: List[Dict[str, Any]]) -> str:
    """
    管理任务列表，用于跟踪复杂任务的进度。
    
    **核心规则：必须传入完整的任务列表，不是只传新增的任务！**
    
    这个工具会完全替换（复写）现有任务列表，所以每次调用都要传入所有任务。
    
    **工作流程：**
    1. 开始时：创建完整的任务列表（只一次）
    2. 执行时：传入完整列表，只更新状态
    3. 完成时：所有任务标记为 completed
    
    **状态类型：** pending, in_progress, completed, cancelled
    
    **约束：**
    - 同一时间只能有一个任务处于 in_progress 状态
    - 任务会持久化到磁盘，不会丢失
    
    Args:
        items: 完整的任务列表（必须包含所有任务），每个任务包含：
            - id: 任务唯一标识（如 "1", "2"）
            - text: 任务描述
            - status: 状态（pending/in_progress/completed/cancelled）
        
    Returns:
        格式化的任务列表字符串
    """
    try:
        session_id = get_current_session()
        manager = get_todo_manager(session_id)
        return manager.update(items)
    except ValueError as e:
        return f"错误: {str(e)}"
    except Exception as e:
        return f"更新任务列表失败: {str(e)}"


@tool
def get_todo_status() -> str:
    """
    获取当前任务状态摘要，包括所有任务及其进度统计。
    
    Returns:
        任务状态摘要字符串
    """
    session_id = get_current_session()
    manager = get_todo_manager(session_id)
    
    status = manager.get_status()
    
    if not status["items"]:
        return "当前没有待办任务。如果需要跟踪复杂任务，可以使用 todo_manager 创建任务列表。"
    
    result = manager.render()
    
    if status["needs_attention"]:
        result += f"\n\n注意：已经 {status['turns_since_last_update']} 轮未更新任务状态"
    
    # 添加完成状态检查
    if manager.is_all_completed():
        result += "\n\n✅ 所有任务已完成！可以开始新的任务了。"
    
    return result


@tool
def clear_todo_list() -> str:
    """
    清空任务列表。
    
    **重要：只有当所有任务都已完成或取消时才能清空！**
    
    如果还有未完成的任务，请先将它们标记为 completed 或 cancelled。
    
    Returns:
        操作结果
    """
    session_id = get_current_session()
    manager = get_todo_manager(session_id)
    return manager.clear()


# ==================== 导出 ====================

__all__ = [
    'TodoManager',
    'todo_manager',
    'get_todo_status',
    'clear_todo_list',
    'get_todo_manager',
    'remove_todo_manager',
    'set_current_session',
    'get_current_session',
    'TASKS_ROOT_DIR'
]
