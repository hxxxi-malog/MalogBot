"""
MCP 集成模块

提供 Model Context Protocol (MCP) 工具的集成支持

主要组件：
- registry: MCP 服务注册管理器，管理服务的注册、发现、加载
- tools: MCP 工具适配器，将 MCP 服务转换为 LangChain 工具
- api: MCP 服务 REST API，提供前端调用接口
- adapters: 适配器，提供百度云等现有服务的适配

使用示例：
    # 初始化服务注册管理器
    from mcp import mcp_registry
    mcp_registry.initialize()
    
    # 注册新服务
    mcp_registry.register_service(
        name='my_service',
        transport_type='http',
        url='http://localhost:8080/mcp'
    )
    
    # 获取 LangChain 工具
    from mcp import get_cached_mcp_tools
    tools = get_cached_mcp_tools()
"""

# 从适配器导入（保持向后兼容）
from mcp.adapters import get_mcp_tools, get_web_search_tool

# 从注册管理器导入
from mcp.registry import (
    MCPRegistry,
    mcp_registry,
    MCPServiceConfig,
    MCPToolInfo
)

# 从工具适配器导入
from mcp.tools import (
    MCPDynamicTool,
    MCPToolsManager,
    mcp_tools_manager,
    get_dynamic_mcp_tools,
    get_cached_mcp_tools
)

# 从 API 导入
from mcp.api import mcp_bp


# 导出所有公共接口
__all__ = [
    # 注册管理器
    'MCPRegistry',
    'mcp_registry',
    'MCPServiceConfig',
    'MCPToolInfo',
    
    # 工具适配器
    'MCPDynamicTool',
    'MCPToolsManager',
    'mcp_tools_manager',
    'get_dynamic_mcp_tools',
    'get_cached_mcp_tools',
    
    # API Blueprint
    'mcp_bp',
    
    # 向后兼容
    'get_mcp_tools',
    'get_web_search_tool',
]
