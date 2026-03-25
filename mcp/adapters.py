"""
MCP 适配器模块

提供 MCP 工具的加载和适配功能
支持百度云 Web Search MCP 服务
"""
import asyncio
import json
from typing import List, Optional, Dict, Any
from langchain_core.tools import BaseTool

from config import Config


class BaiduWebSearchTool(BaseTool):
    """
    百度云 Web Search MCP 工具
    
    直接调用百度云的 Web Search MCP 服务
    使用 JSON-RPC 2.0 协议
    """
    
    name: str = "web_search"
    description: str = """根据用户提问，搜索实时网页信息。
    
使用场景：
- 用户询问实时新闻、天气、股价等时效性信息
- 用户需要查询最新的技术文档或API信息
- 用户询问模型知识截止日期之后发生的事件
- 用户需要查找特定产品、服务的信息

输入参数：
- query: 搜索查询字符串

返回：相关的网页搜索结果
"""
    
    args_schema: type = None
    
    # 类变量：缓存的工具名称
    _cached_tool_name: Optional[str] = None
    _request_id: int = 0
    
    def _run(self, query: str) -> str:
        """同步执行搜索"""
        return asyncio.run(self._arun(query))
    
    async def _arun(self, query: str) -> str:
        """异步执行搜索"""
        import httpx
        
        if not Config.BAIDU_MCP_API_KEY:
            return "错误：未配置百度云 MCP API Key"
        
        url = Config.BAIDU_MCP_URL
        headers = {
            "Authorization": f"Bearer {Config.BAIDU_MCP_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # 首先获取工具列表，找到正确的工具名称
                if self._cached_tool_name is None:
                    tool_name = await self._discover_tool_name(client, url, headers)
                    if tool_name is None:
                        return "错误：无法发现可用的搜索工具"
                    self._cached_tool_name = tool_name
                
                # 调用工具
                self._request_id += 1
                payload = {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "tools/call",
                    "params": {
                        "name": self._cached_tool_name,
                        "arguments": {
                            "query": query
                        }
                    }
                }
                
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code == 200:
                    result = response.json()
                    return self._parse_mcp_response(result)
                else:
                    return f"搜索失败：HTTP {response.status_code} - {response.text}"
                    
        except httpx.TimeoutException:
            return "搜索超时，请稍后重试"
        except Exception as e:
            return f"搜索出错：{str(e)}"
    
    async def _discover_tool_name(self, client, url: str, headers: Dict) -> Optional[str]:
        """发现可用的工具名称"""
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
            "params": {}
        }
        
        try:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                
                # 解析工具列表
                if "result" in result and "tools" in result["result"]:
                    tools = result["result"]["tools"]
                    print(f"[MCP] 发现 {len(tools)} 个工具:")
                    for tool in tools:
                        tool_name = tool.get("name", "unknown")
                        tool_desc = tool.get("description", "")[:50]
                        print(f"  - {tool_name}: {tool_desc}...")
                    
                    # 返回第一个工具（假设只有一个搜索工具）
                    if tools:
                        return tools[0].get("name")
                
                # 直接在 result 中查找 tools
                if "result" in result and isinstance(result["result"], list):
                    print(f"[MCP] 发现 {len(result['result'])} 个工具")
                    if result["result"]:
                        return result["result"][0].get("name")
                
                print(f"[MCP] 工具列表响应: {json.dumps(result, ensure_ascii=False, indent=2)}")
            
            return None
            
        except Exception as e:
            print(f"[MCP] 发现工具失败: {e}")
            return None
    
    def _parse_mcp_response(self, response: Dict[str, Any]) -> str:
        """解析 MCP 协议响应"""
        try:
            # 检查是否有错误
            if "error" in response:
                error = response["error"]
                return f"搜索错误：{error.get('message', str(error))}"
            
            # MCP 协议的成功响应格式
            if "result" in response:
                result = response["result"]
                
                # result 可能包含 content 字段
                if isinstance(result, dict):
                    if "content" in result:
                        contents = result["content"]
                        if isinstance(contents, list):
                            text_parts = []
                            for item in contents:
                                if isinstance(item, dict):
                                    if item.get("type") == "text":
                                        text_parts.append(item.get("text", ""))
                                    elif "text" in item:
                                        text_parts.append(item["text"])
                            return "\n".join(text_parts) if text_parts else str(result)
                        return str(contents)
                    return str(result)
                return str(result)
            
            # 直接的 content 字段
            if "content" in response:
                contents = response["content"]
                if isinstance(contents, list):
                    text_parts = []
                    for item in contents:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    return "\n".join(text_parts) if text_parts else str(response)
                return str(contents)
            
            return str(response)
            
        except Exception as e:
            return f"解析响应失败：{str(e)}\n原始响应：{json.dumps(response, ensure_ascii=False, indent=2)}"


def get_web_search_tool() -> Optional[BaseTool]:
    """
    获取 Web 搜索工具
    
    根据配置返回百度云 MCP Web Search 工具
    
    Returns:
        Web Search 工具实例，如果未配置 API Key 则返回 None
    """
    if not Config.BAIDU_MCP_API_KEY:
        print("Warning: BAIDU_MCP_API_KEY not configured. Web search disabled.")
        return None
    
    return BaiduWebSearchTool()


async def get_mcp_tools_async() -> List[BaseTool]:
    """
    异步加载 MCP 工具
    
    Returns:
        MCP 工具列表
    """
    tools = []
    
    # 添加百度云 Web Search 工具
    web_search = get_web_search_tool()
    if web_search:
        tools.append(web_search)
    
    return tools


def get_mcp_tools() -> List[BaseTool]:
    """
    同步获取 MCP 工具列表
    
    Returns:
        MCP 工具列表
    """
    return asyncio.run(get_mcp_tools_async())


def get_all_available_tools() -> List[BaseTool]:
    """
    获取所有可用的工具（同步版本）
    
    Returns:
        工具列表
    """
    tools = []
    
    # 添加 Web 搜索工具
    web_search = get_web_search_tool()
    if web_search:
        tools.append(web_search)
    
    return tools
