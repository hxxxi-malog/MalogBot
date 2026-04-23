"""
对话服务模块（重构版）

统一的对话服务入口，整合各子模块：
1. 会话管理
2. Agent执行
3. 流式输出
4. 命令确认

这是一个外观模式（Facade），将复杂的子系统调用简化为统一接口。
"""
import uuid
from typing import Generator, Dict, Any, Optional, List

from agent.tools.todo_manager import remove_todo_manager
from agent.tools.task_manager import remove_task_manager
from agent.tools.sub_agent import clear_session_tools

from services.session_store import session_store
from services.context.context_compactor import context_compactor
from services.agent.agent_service import AgentService


class ChatService:
    """
    统一的对话服务类
    
    作为外观模式，整合各子模块，提供简化的调用接口。
    """
    
    def __init__(self):
        """初始化对话服务"""
        # 初始化Agent服务
        self._agent_service = AgentService(session_store, context_compactor)
        
    # ==================== 会话管理 ====================
    
    def create_session(self) -> str:
        """
        创建新会话
        
        Returns:
            新会话的ID
        """
        session_id = str(uuid.uuid4())
        session_store.get_or_create_session(session_id)
        return session_id
    
    def ensure_session_exists(self, session_id: str) -> bool:
        """
        确保会话存在于数据库中
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否成功
        """
        return session_store.get_or_create_session(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """
        删除会话及其所有消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否删除成功
        """
        # 清理会话的 TodoManager
        remove_todo_manager(session_id)
        # 清理会话的 TaskManager
        remove_task_manager(session_id)
        # 清理会话的子Agent工具配置
        clear_session_tools(session_id)
        # 删除会话
        return session_store.delete_session(session_id)
    
    def get_all_sessions(self) -> List[Dict]:
        """
        获取所有会话列表
        
        Returns:
            会话列表
        """
        return session_store.get_all_sessions()
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息字典
        """
        return session_store.get_session_info(session_id)
    
    # ==================== 对话功能 ====================
    
    def chat(self, user_input: str, session_id: str = "default") -> Dict[str, Any]:
        """
        非流式执行对话（带智能路由）
        
        自动判断是否需要团队模式：
        - 简单任务 -> 单Agent执行
        - 复杂任务 -> 团队模式执行
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Returns:
            响应字典
        """
        return self._agent_service.chat_with_routing(user_input, session_id)
    
    def chat_stream(
        self,
        user_input: str,
        session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行对话（带智能路由）
        
        自动判断是否需要团队模式：
        - 简单任务 -> 单Agent流式执行
        - 复杂任务 -> 团队模式执行
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        yield from self._agent_service.chat_stream_with_routing(user_input, session_id)
    
    def confirm_command(
        self,
        command: str,
        session_id: str = "default",
        user_message: str = ""
    ) -> Dict[str, Any]:
        """
        执行用户确认的命令（非流式）
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Returns:
            执行结果
        """
        return self._agent_service.confirm_command(command, session_id, user_message)
    
    def confirm_command_stream(
        self,
        command: str,
        session_id: str = "default",
        user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        执行用户确认的命令（流式）
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Yields:
            流式数据字典
        """
        yield from self._agent_service.confirm_command_stream(command, session_id, user_message)
    
    def handle_onboarding_reply(
        self,
        user_reply: str,
        session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        处理首次对话引导的用户回复
        
        当前端收到 ONBOARDING_REQUIRED 响应后，
        用户回复应调用此方法处理，而不是 chat。
        
        Args:
            user_reply: 用户的回复（包含名字和角色期望）
            session_id: 会话ID
            
        Returns:
            响应字典
        """
        return self._agent_service.handle_onboarding_reply(user_reply, session_id)
    
    def cancel_command_stream(
        self,
        command: str,
        session_id: str = "default",
        user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        处理用户取消的命令
        
        Args:
            command: 用户取消的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Yields:
            流式数据字典
        """
        yield from self._agent_service.cancel_command_stream(command, session_id, user_message)
    
    # ==================== 递归限制继续执行 ====================
    
    def continue_task(self, session_id: str = "default") -> Dict[str, Any]:
        """
        继续执行因递归限制暂停的任务（非流式）
        
        Args:
            session_id: 会话ID
            
        Returns:
            执行结果
        """
        return self._agent_service.continue_task(session_id)
    
    def continue_task_stream(
        self,
        session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        继续执行因递归限制暂停的任务（流式）
        
        Args:
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        yield from self._agent_service.continue_task_stream(session_id)
    
    # ==================== 历史管理 ====================
    
    def get_history(self, session_id: str = "default") -> List[Dict]:
        """获取对话历史"""
        return session_store.get_messages(session_id)
    
    def clear_history(self, session_id: str = "default") -> None:
        """清空对话历史"""
        session_store.clear_messages(session_id)
    
    # ==================== 取消控制 ====================
    
    def request_cancel(self, session_id: str = "default") -> None:
        """请求取消当前会话的流式输出"""
        self._agent_service.request_cancel(session_id)
    
    def is_cancelled(self, session_id: str = "default") -> bool:
        """检查会话是否已被取消"""
        return self._agent_service.is_cancelled(session_id)
    
    def clear_cancel_flag(self, session_id: str = "default") -> None:
        """清除取消标志"""
        self._agent_service.clear_cancel_flag(session_id)
    
    # ==================== 联网搜索设置 ====================
    
    def get_web_search_status(self, session_id: str) -> bool:
        """
        获取会话的联网搜索状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否启用联网搜索
        """
        return session_store.get_web_search_enabled(session_id)
    
    def set_web_search_enabled(self, session_id: str, enabled: bool) -> None:
        """
        设置会话的联网搜索开关
        
        Args:
            session_id: 会话ID
            enabled: 是否启用联网搜索
        """
        session_store.set_web_search_enabled(session_id, enabled)
    
    # ==================== 知识库设置 ====================
    
    def get_knowledge_base_id(self, session_id: str) -> Optional[str]:
        """
        获取会话当前选中的知识库ID
        
        Args:
            session_id: 会话ID
            
        Returns:
            知识库ID
        """
        return session_store.get_knowledge_base_id(session_id)
    
    def set_knowledge_base_id(self, session_id: str, kb_id: Optional[str]) -> None:
        """
        设置会话的知识库
        
        Args:
            session_id: 会话ID
            kb_id: 知识库ID
        """
        session_store.set_knowledge_base_id(session_id, kb_id)
    
    # ==================== 团队状态查询 ====================
    
    def get_team_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取团队执行状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            团队状态信息
        """
        return self._agent_service.get_team_status(session_id)
    
    def get_task_board_view(self, session_id: str) -> str:
        """
        获取任务看板视图
        
        Args:
            session_id: 会话ID
            
        Returns:
            任务看板字符串
        """
        return self._agent_service.get_task_board_view(session_id)


# 创建全局实例
chat_service = ChatService()

# 导出
__all__ = ['ChatService', 'chat_service']
