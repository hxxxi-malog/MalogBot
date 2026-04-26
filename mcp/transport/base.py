"""
MCP 传输层抽象基类

定义传输层的基本接口，所有具体传输实现都必须继承此类。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TransportType(str, Enum):
    """传输类型枚举"""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


@dataclass
class MCPResponse:
    """MCP 响应结果"""

    success: bool
    result: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None
    session_id: Optional[str] = None

    def get_content(self) -> str:
        """提取响应内容文本"""
        if not self.success:
            error_msg = self.error.get("message", str(self.error)) if self.error else "Unknown error"
            return f"Error: {error_msg}"

        if not self.result:
            return ""

        # 处理 MCP 协议的 content 字段
        if "content" in self.result:
            contents = self.result["content"]
            if isinstance(contents, list):
                text_parts = []
                for item in contents:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return "\n".join(text_parts)

        return str(self.result)


class TransportError(Exception):
    """传输层错误"""

    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code


class Transport(ABC):
    """
    MCP 传输层抽象基类

    所有传输实现都必须提供以下能力：
    1. 发送请求并获取响应
    2. 可选：订阅事件（SSE 模式）
    3. 会话管理（部分协议支持）
    """

    transport_type: TransportType

    @abstractmethod
    async def send_request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> MCPResponse:
        """
        发送 MCP 请求

        Args:
            method: MCP 方法名（如 tools/list, tools/call）
            params: 方法参数
            session_id: 会话 ID（部分传输支持）

        Returns:
            MCPResponse 对象
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """关闭传输连接，释放资源"""
        pass

    @property
    def is_connected(self) -> bool:
        """检查连接状态"""
        return True

    async def discover_tools(self) -> MCPResponse:
        """发现可用工具列表"""
        return await self.send_request("tools/list", {})

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any], session_id: Optional[str] = None
    ) -> MCPResponse:
        """
        调用工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数
            session_id: 会话 ID

        Returns:
            MCPResponse 对象
        """
        params = {"name": tool_name, "arguments": arguments}
        return await self.send_request("tools/call", params, session_id)

    async def initialize(self) -> MCPResponse:
        """初始化 MCP 会话"""
        return await self.send_request("initialize", {"protocolVersion": "2025-03-26"})

    async def ping(self) -> MCPResponse:
        """心跳检测"""
        return await self.send_request("ping", {})
