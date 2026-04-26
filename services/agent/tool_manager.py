"""
工具管理器模块

管理Agent可用的工具，采用 Registry 模式：
1. 工具在模块中声明即自动注册
2. ToolManager 从 Registry 获取工具
3. 新增工具无需修改此文件
"""
from typing import List, Dict, Any, Optional
import logging

from config import Config
from agent.tools.registry import (
    registry,
    ToolCategory,
    get_all_tools,
    get_tools_by_category
)

logger = logging.getLogger(__name__)


class ToolManager:
    """
    工具管理器 - 基于 Registry 模式
    
    特点：
    - 新增工具只需在工具模块中注册，无需修改此类
    - 支持按分类、子Agent可用性过滤工具
    - 支持动态加载工具模块
    """
    
    # 工具模块路径
    TOOL_MODULES = [
        'agent.tools.bash',
        'agent.tools.todo_manager',
        'agent.tools.skills',
        'agent.tools.memory',
        'agent.tools.task_manager',
        'agent.tools.planning',
        'agent.tools.knowledge_tools',
        'agent.tools.sub_agent',
    ]
    
    def __init__(self):
        """初始化工具管理器"""
        self._initialized = False
        self._web_search_tool = None
    
    def _ensure_initialized(self):
        """确保工具模块已加载"""
        if self._initialized:
            return
        
        # 导入所有工具模块，触发注册
        for module_path in self.TOOL_MODULES:
            if not registry.is_module_loaded(module_path):
                try:
                    __import__(module_path)
                    registry.mark_module_loaded(module_path)
                    logger.debug(f"[ToolManager] 加载工具模块: {module_path}")
                except Exception as e:
                    logger.error(f"[ToolManager] 加载工具模块失败: {module_path}, 错误: {e}")
        
        self._initialized = True
        
        # 打印统计信息
        stats = registry.get_stats()
        logger.info(f"[ToolManager] 工具加载完成: 共 {stats['total_tools']} 个工具")
        for cat, count in stats['by_category'].items():
            logger.info(f"  - {cat}: {count} 个")
    
    def _get_web_search_tool(self):
        """
        从 MCP Registry 获取启用的 Web 搜索工具
        
        优先级：
        1. 从 MCP Registry 获取 category='search' 且 enabled=True 的服务
        2. 如果没有，返回 None
        
        Returns:
            Web 搜索工具实例，如果未配置则返回 None
        """
        if self._web_search_tool is None:
            try:
                from mcp.registry import mcp_registry
                from mcp.tools import mcp_tools_manager
                
                # 初始化 Registry
                mcp_registry.initialize()
                
                # 获取所有启用的 search 类别服务
                servers = mcp_registry.list_services(enabled_only=True, category='search')
                
                if not servers:
                    logger.info("[ToolManager] 没有启用的搜索服务")
                    return None
                
                # 同步工具管理器
                mcp_tools_manager.sync_from_registry()
                
                # 获取搜索类别的工具
                search_tools = mcp_registry.get_tools_by_category('search')
                
                if search_tools:
                    # 返回第一个搜索工具
                    tool_info = search_tools[0]
                    tool = mcp_tools_manager.get_tool(tool_info.name)
                    if tool:
                        self._web_search_tool = tool
                        logger.info(f"[ToolManager] 使用 MCP 搜索工具: {tool_info.name} (服务: {tool_info.server_name})")
                        return self._web_search_tool
                
                logger.info("[ToolManager] 未找到可用的搜索工具")
                return None
                
            except Exception as e:
                logger.error(f"[ToolManager] 加载Web搜索工具失败: {e}")
                return None
        
        return self._web_search_tool
    
    def get_tools_for_session(
        self,
        session_id: str,
        session_store,
        include_sub_agent: bool = True
    ) -> List:
        """
        获取会话可用的工具列表
        
        Args:
            session_id: 会话ID
            session_store: 会话存储服务
            include_sub_agent: 是否包含spawn_sub_agent工具
            
        Returns:
            工具列表
        """
        # 确保工具已加载
        self._ensure_initialized()
        
        # 根据是否是主Agent获取工具
        if include_sub_agent:
            # 主Agent: 获取所有工具
            tools = registry.get_tools(for_sub_agent=None)
        else:
            # 子Agent: 只获取子Agent可用的工具
            tools = registry.get_tools(for_sub_agent=True)
        
        # 检查会话是否启用联网搜索
        web_search_enabled = session_store.get_web_search_enabled(session_id)
        
        if web_search_enabled:
            web_search_tool = self._get_web_search_tool()
            if web_search_tool:
                tools.append(web_search_tool)
        
        logger.info(f"[ToolManager] 会话 {session_id} 获取工具: {len(tools)} 个 (include_sub_agent={include_sub_agent})")
        
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
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """获取工具注册统计信息"""
        self._ensure_initialized()
        return registry.get_stats()
    
    def get_tool_meta(self, tool_name: str) -> Optional[Any]:
        """获取工具元数据"""
        self._ensure_initialized()
        return registry.get_meta(tool_name)
    
    def clear_web_search_cache(self):
        """清除 Web 搜索工具缓存
        
        当用户切换搜索服务时调用此方法，下次获取工具时会重新从 Registry 获取
        """
        self._web_search_tool = None
        logger.info("[ToolManager] Web 搜索工具缓存已清除")
    
    def get_available_search_services(self) -> List[Dict[str, Any]]:
        """
        获取所有可用的搜索服务列表
        
        Returns:
            搜索服务信息列表
        """
        from mcp.registry import mcp_registry
        
        mcp_registry.initialize()
        servers = mcp_registry.list_services(enabled_only=True, category='search')
        
        return [
            {
                'name': s.get('name'),
                'display_name': s.get('display_name', s.get('name')),
                'tools_count': s.get('tools_count', 0),
                'status': s.get('status'),
            }
            for s in servers
        ]


# 创建全局实例
tool_manager = ToolManager()


__all__ = ['ToolManager', 'tool_manager']
