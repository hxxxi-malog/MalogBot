"""
TodoManager 工具模块

提供任务管理能力，帮助模型在处理复杂任务时保持注意力：
1. 状态机管理任务状态
2. 问责机制：超过N轮不调用时强制提醒
3. 同一时间只允许一个 in_progress 任务

设计思路：
- 简单任务不需要调用此工具
- 复杂任务模型可自行决定调用，用于跟踪进度
- 通过问责机制防止模型遗忘任务状态
"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool


class TodoManager:
    """
    任务管理器 - 状态机模式
    
    状态转换规则：
    - pending -> in_progress: 开始任务
    - in_progress -> completed: 完成任务
    - in_progress -> cancelled: 取消任务
    - 同一时间只能有一个任务处于 in_progress 状态
    
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
    
    def __init__(self):
        """初始化任务管理器"""
        self.items: List[Dict[str, Any]] = []
        self._turns_since_last_update: int = 0
        self._last_rendered: str = ""
    
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
                "status": status
            })
        
        # 关键约束：同一时间只允许一个 in_progress
        if in_progress_count > 1:
            raise ValueError(
                f"状态约束违反：同一时间只能有一个任务处于 in_progress 状态，"
                f"当前有 {in_progress_count} 个 in_progress 任务。"
            )
        
        self.items = validated
        self._turns_since_last_update = 0  # 重置计数器
        return self.render()
    
    def render(self) -> str:
        """
        渲染任务列表为可读字符串
        
        Returns:
            格式化的任务列表字符串
        """
        if not self.items:
            return "当前没有待办任务"
        
        lines = ["[任务列表]", ""]
        
        # 按状态排序：in_progress > pending > completed/cancelled
        status_order = {
            self.STATUS_IN_PROGRESS: 0,
            self.STATUS_PENDING: 1,
            self.STATUS_COMPLETED: 2,
            self.STATUS_CANCELLED: 3
        }
        
        sorted_items = sorted(
            self.items,
            key=lambda x: status_order.get(x["status"], 99)
        )
        
        # 找到当前进行中的任务和下一个待处理任务
        current_task = None
        next_pending_task = None
        
        for item in sorted_items:
            status = item["status"]
            text = item["text"]
            task_id = item["id"]
            
            # 状态标识
            if status == self.STATUS_IN_PROGRESS:
                icon = "[进行中]"
                current_task = item
            elif status == self.STATUS_COMPLETED:
                icon = "[已完成]"
            elif status == self.STATUS_CANCELLED:
                icon = "[已取消]"
            else:  # pending
                icon = "[待处理]"
                if next_pending_task is None:
                    next_pending_task = item
            
            lines.append(f"{icon} [{task_id}] {text}")
        
        # 统计信息
        total = len(self.items)
        completed = sum(1 for i in self.items if i["status"] == self.STATUS_COMPLETED)
        pending = sum(1 for i in self.items if i["status"] == self.STATUS_PENDING)
        in_progress = sum(1 for i in self.items if i["status"] == self.STATUS_IN_PROGRESS)
        
        lines.append("")
        lines.append(f"统计：总计 {total} | 进行中 {in_progress} | 待处理 {pending} | 已完成 {completed}")
        
        # 添加下一步行动提示
        if current_task:
            lines.append("")
            lines.append(f"当前任务：[{current_task['id']}] {current_task['text']}")
            lines.append("完成后请立即调用 todo_manager 更新状态为 completed")
        elif next_pending_task and in_progress == 0:
            # 没有进行中的任务但有待处理的任务，提示开始下一个
            lines.append("")
            lines.append(f"注意：有 {pending} 个待处理任务但没有进行中的任务")
            lines.append(f"请开始执行 [{next_pending_task['id']}] {next_pending_task['text']}")
            lines.append("并调用 todo_manager 将其状态更新为 in_progress")
        
        result = "\n".join(lines)
        self._last_rendered = result
        return result
    
    def increment_turn(self) -> bool:
        """
        增加未调用计数器
        
        每次模型响应后调用此方法，用于追踪问责
        
        Returns:
            是否超过阈值（需要提醒）
        """
        self._turns_since_last_update += 1
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
        
        Returns:
            确认消息
        """
        self.items = []
        self._turns_since_last_update = 0
        return "任务列表已清空"


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
        _session_managers[session_id] = TodoManager()
    return _session_managers[session_id]


def remove_todo_manager(session_id: str) -> None:
    """
    删除会话的 TodoManager 实例
    
    Args:
        session_id: 会话ID
    """
    if session_id in _session_managers:
        del _session_managers[session_id]


# ==================== LangChain 工具定义 ====================

# 用于在工具调用时传递 session_id 的上下文变量
# 由于 LangChain 工具不支持额外的上下文参数，我们使用 thread-local 存储
import threading

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
    
    **重要规则：每次完成一个任务步骤后，必须立即调用此工具更新状态！**
    
    状态类型：pending, in_progress, completed, cancelled
    约束：同一时间只能有一个任务处于 in_progress 状态。
    
    Args:
        items: 任务列表，每个任务包含：
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
        return f"错误：{str(e)}"
    except Exception as e:
        return f"更新任务列表失败：{str(e)}"


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
    
    return result


# ==================== 导出 ====================

__all__ = [
    'TodoManager',
    'todo_manager',
    'get_todo_status',
    'get_todo_manager',
    'remove_todo_manager',
    'set_current_session',
    'get_current_session'
]
