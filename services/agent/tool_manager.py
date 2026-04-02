"""
工具管理器模块

管理Agent可用的工具，包括：
1. 工具注册和配置
2. 根据会话设置动态返回工具列表
3. 子Agent工具隔离
"""
from typing import List, Dict, Any, Optional
import logging

from config import Config

logger = logging.getLogger(__name__)


class ToolManager:
    """工具管理器 - 管理Agent可用工具"""
    
    def __init__(self):
        """初始化工具管理器"""
        # 延迟导入工具，避免循环依赖
        self._base_tools = None
        self._sub_agent_tools = None
        self._web_search_tool = None
        self._skills_tools = None
        self._memory_tools = None
        self._task_manager_tools = None
        self._planning_tools = None
        
    def _init_base_tools(self):
        """延迟初始化基础工具"""
        if self._base_tools is not None:
            return
            
        from agent.tools.bash import (
            execute_bash,
            get_bash_tool_detailed_usage,
        )
        from agent.tools.todo_manager import (
            todo_manager,
            get_todo_status,
            complete_and_next,
        )
        
        # 基础工具（主Agent使用）
        self._base_tools = [
            execute_bash,
            get_bash_tool_detailed_usage,
            todo_manager,
            get_todo_status,
            complete_and_next,
        ]
        
    def _init_sub_agent_tools(self):
        """延迟初始化子Agent工具"""
        if self._sub_agent_tools is not None:
            return
            
        from agent.tools.bash import (
            execute_bash,
            get_bash_tool_detailed_usage,
        )
        from agent.tools.todo_manager import (
            todo_manager,
            get_todo_status,
            complete_and_next,
        )
        
        # 子Agent工具（不包含spawn_sub_agent，防止无限递归）
        self._sub_agent_tools = [
            execute_bash,
            get_bash_tool_detailed_usage,
            todo_manager,
            get_todo_status,
            complete_and_next,
        ]
        
    def _init_skills_tools(self):
        """延迟初始化技能工具"""
        if self._skills_tools is not None:
            return
        from agent.tools.skills import SKILLS_TOOLS
        self._skills_tools = list(SKILLS_TOOLS)
        
    def _init_memory_tools(self):
        """延迟初始化记忆工具"""
        if self._memory_tools is not None:
            return
        from agent.tools.memory import MEMORY_TOOLS
        self._memory_tools = list(MEMORY_TOOLS)
        
    def _init_task_manager_tools(self):
        """延迟初始化任务管理工具"""
        if self._task_manager_tools is not None:
            return
        from agent.tools.task_manager import TASK_MANAGER_TOOLS
        self._task_manager_tools = list(TASK_MANAGER_TOOLS)
        
    def _init_planning_tools(self):
        """延迟初始化规划工具"""
        if self._planning_tools is not None:
            return
        from agent.tools.planning import PLANNING_TOOLS
        self._planning_tools = list(PLANNING_TOOLS)
        
    def _get_web_search_tool(self):
        """懒加载Web搜索工具"""
        if self._web_search_tool is None:
            try:
                from mcp.adapters import get_web_search_tool
                self._web_search_tool = get_web_search_tool()
            except Exception as e:
                logger.error(f"[ToolManager] 加载Web搜索工具失败: {e}")
        return self._web_search_tool
    
    def get_tools_for_session(
        self,
        session_id: str,
        session_store,
        include_sub_agent: bool = True
    ) -> List:
        """
        获取会话可用的工具列表
        
        根据会话的设置动态返回可用的工具
        
        Args:
            session_id: 会话ID
            session_store: 会话存储服务
            include_sub_agent: 是否包含spawn_sub_agent工具
            
        Returns:
            工具列表
        """
        # 确保工具已初始化
        self._init_base_tools()
        self._init_sub_agent_tools()
        self._init_skills_tools()
        self._init_memory_tools()
        self._init_task_manager_tools()
        self._init_planning_tools()
        
        # 根据是否是子Agent选择基础工具集
        if include_sub_agent:
            tools = list(self._base_tools)
        else:
            tools = list(self._sub_agent_tools)
            
        # 添加任务管理工具
        tools.extend(self._task_manager_tools)
        
        # 添加规划工具
        tools.extend(self._planning_tools)
        
        # 添加技能工具
        tools.extend(self._skills_tools)
        
        # 添加记忆工具
        tools.extend(self._memory_tools)
        
        # 如果是主Agent，添加spawn_sub_agent
        if include_sub_agent:
            from agent.tools.sub_agent import spawn_sub_agent
            tools.append(spawn_sub_agent)
        
        # 检查会话是否启用联网搜索
        web_search_enabled = session_store.get_web_search_enabled(session_id)
        
        if web_search_enabled:
            web_search_tool = self._get_web_search_tool()
            if web_search_tool:
                tools.append(web_search_tool)
                
        return tools
    
    def setup_sub_agent_tools(self, session_id: str, session_store):
        """
        设置子Agent的工具配置
        
        Args:
            session_id: 会话ID
            session_store: 会话存储服务
        """
        from agent.tools.sub_agent import set_sub_agent_tools, set_sub_agent_session
        
        # 设置当前会话ID
        set_sub_agent_session(session_id)
        
        # 获取子Agent可用的工具
        sub_tools = self.get_tools_for_session(
            session_id, 
            session_store, 
            include_sub_agent=False
        )
        
        # 配置子Agent工具
        set_sub_agent_tools(sub_tools, session_id)


# 创建全局实例
tool_manager = ToolManager()

__all__ = ['ToolManager', 'tool_manager']
