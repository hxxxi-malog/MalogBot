"""
MCP 工具适配器

将 MCP 服务发现的工具转换为 LangChain 工具
支持动态调用和结果解析
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, create_model

from langchain_core.tools import BaseTool

from mcp.registry import mcp_registry, MCPToolInfo, MCPServiceConfig

logger = logging.getLogger(__name__)


def create_args_schema(tool_info: MCPToolInfo) -> Type[BaseModel]:
    """
    根据工具的 input schema 动态创建 Pydantic 模型
    
    Args:
        tool_info: 工具信息
        
    Returns:
        Pydantic 模型类
    """
    schema = tool_info.input_schema or {}
    properties = schema.get('properties', {})
    required = schema.get('required', [])
    
    # 构建字段定义
    fields = {}
    for prop_name, prop_def in properties.items():
        prop_type = prop_def.get('type', 'string')
        description = prop_def.get('description', '')
        
        # 类型映射
        if prop_type == 'string':
            python_type = str
        elif prop_type == 'integer':
            python_type = int
        elif prop_type == 'number':
            python_type = float
        elif prop_type == 'boolean':
            python_type = bool
        elif prop_type == 'array':
            python_type = list
        elif prop_type == 'object':
            python_type = dict
        else:
            python_type = str
        
        # 设置默认值
        if prop_name in required:
            fields[prop_name] = (python_type, ...)
        else:
            default = prop_def.get('default', None)
            fields[prop_name] = (python_type, default)
    
    # 创建动态模型
    if fields:
        return create_model(
            f"{tool_info.name}_args",
            __config__={'extra': 'forbid'},
            **fields
        )
    else:
        # 无参数的工具
        return create_model(f"{tool_info.name}_args")


class MCPDynamicTool(BaseTool):
    """
    动态 MCP 工具
    
    将 MCP 服务中的工具转换为 LangChain 工具格式
    """
    
    # 工具信息
    tool_info: MCPToolInfo = None
    server_config: MCPServiceConfig = None
    request_id: int = 0
    
    def __init__(
        self,
        tool_info: MCPToolInfo,
        server_config: MCPServiceConfig
    ):
        """
        初始化动态工具
        
        Args:
            tool_info: 工具信息
            server_config: 服务配置
        """
        # 创建参数 schema
        args_schema = create_args_schema(tool_info)
        
        super().__init__(
            name=tool_info.name,
            description=tool_info.description or f"MCP 工具: {tool_info.name}",
            args_schema=args_schema,
            tool_info=tool_info,
            server_config=server_config
        )
    
    def _run(self, **kwargs) -> str:
        """同步执行"""
        return asyncio.run(self._arun(**kwargs))
    
    async def _arun(self, **kwargs) -> str:
        """异步执行"""
        try:
            if self.server_config.transport_type == 'http':
                result = await self._call_http(kwargs)
            elif self.server_config.transport_type == 'sse':
                result = await self._call_sse(kwargs)
            else:
                result = await self._call_stdio(kwargs)
            
            return self._parse_result(result)
            
        except Exception as e:
            error_msg = f"工具调用失败: {str(e)}"
            logger.error(f"[MCP Tool] {error_msg}")
            return error_msg
    
    async def _call_http(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过 HTTP 调用工具"""
        import httpx
        
        if not self.server_config.url:
            return {"error": "服务 URL 未配置"}
        
        headers = self.server_config.headers or {}
        headers['Content-Type'] = 'application/json'
        
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {
                "name": self.tool_info.name,
                "arguments": arguments
            }
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                self.server_config.url,
                headers=headers,
                json=payload
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "error": f"HTTP {response.status_code}",
                    "message": response.text
                }
    
    async def _call_sse(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过 SSE 调用工具"""
        # SSE 方式暂时复用 HTTP
        return await self._call_http(arguments)
    
    async def _call_stdio(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过 stdio 调用工具"""
        # stdio 方式需要子进程通信
        logger.warning(f"[MCP Tool] stdio 模式需要子进程支持: {self.name}")
        return {"error": "stdio 模式暂不支持"}
    
    def _parse_result(self, result: Dict[str, Any]) -> str:
        """解析调用结果"""
        # 检查错误
        if "error" in result:
            error = result["error"]
            if isinstance(error, dict):
                return f"错误: {error.get('message', str(error))}"
            return f"错误: {error}"
        
        # 解析 MCP 协议响应
        if "result" in result:
            res = result["result"]
            
            # content 字段
            if isinstance(res, dict) and "content" in res:
                contents = res["content"]
                if isinstance(contents, list):
                    text_parts = []
                    for item in contents:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif "text" in item:
                                text_parts.append(item["text"])
                    return "\n".join(text_parts) if text_parts else str(res)
            
            return str(res)
        
        # 直接的 content 字段
        if "content" in result:
            contents = result["content"]
            if isinstance(contents, list):
                text_parts = []
                for item in contents:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return "\n".join(text_parts) if text_parts else str(result)
        
        return str(result)


class MCPToolsManager:
    """
    MCP 工具管理器
    
    管理所有动态创建的 MCP 工具
    """
    
    def __init__(self):
        """初始化工具管理器"""
        self._tools: Dict[str, MCPDynamicTool] = {}
    
    def create_tool(
        self,
        tool_info: MCPToolInfo,
        server_config: MCPServiceConfig
    ) -> MCPDynamicTool:
        """
        创建动态工具
        
        Args:
            tool_info: 工具信息
            server_config: 服务配置
            
        Returns:
            创建的工具实例
        """
        tool = MCPDynamicTool(tool_info, server_config)
        self._tools[tool_info.name] = tool
        return tool
    
    def get_tool(self, name: str) -> Optional[MCPDynamicTool]:
        """获取工具"""
        return self._tools.get(name)
    
    def remove_tool(self, name: str):
        """移除工具"""
        self._tools.pop(name, None)
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有工具"""
        return list(self._tools.values())
    
    def sync_from_registry(self):
        """
        从注册管理器同步工具
        
        根据注册管理器中的工具信息创建或更新工具
        """
        # 清除现有工具
        self._tools.clear()
        
        # 从注册管理器获取工具和服务配置
        all_tools = mcp_registry.get_all_tools()
        
        for tool_info in all_tools:
            server_config = mcp_registry._service_configs.get(tool_info.server_name)
            if server_config:
                self.create_tool(tool_info, server_config)
        
        logger.info(f"[MCP Tools] 同步了 {len(self._tools)} 个工具")
    
    async def refresh_and_sync(self):
        """
        刷新所有服务并同步工具
        
        这是主要的刷新入口
        """
        # 刷新所有服务
        await mcp_registry.refresh_all_services()
        
        # 同步工具
        self.sync_from_registry()


# 创建全局实例
mcp_tools_manager = MCPToolsManager()


async def get_dynamic_mcp_tools() -> List[BaseTool]:
    """
    获取所有动态 MCP 工具
    
    Returns:
        LangChain 工具列表
    """
    # 确保注册管理器已初始化
    mcp_registry.initialize()
    
    # 刷新并同步
    await mcp_tools_manager.refresh_and_sync()
    
    return mcp_tools_manager.get_all_tools()


def get_cached_mcp_tools() -> List[BaseTool]:
    """
    获取缓存的 MCP 工具（不刷新）
    
    Returns:
        LangChain 工具列表
    """
    # 确保注册管理器已初始化
    mcp_registry.initialize()
    
    # 同步工具（使用缓存）
    mcp_tools_manager.sync_from_registry()
    
    return mcp_tools_manager.get_all_tools()


# 导出
__all__ = [
    'MCPDynamicTool',
    'MCPToolsManager',
    'mcp_tools_manager',
    'get_dynamic_mcp_tools',
    'get_cached_mcp_tools'
]
