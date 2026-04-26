"""
MCP 传输层模块

支持多种传输协议：
- HTTP (传统 JSON-RPC over HTTP)
- SSE (Server-Sent Events)
- stdio (标准输入输出)
- streamable-http (MCP v2025.03.26 Streamable HTTP)
"""

from mcp.transport.base import Transport, TransportError
from mcp.transport.streamable_http import StreamableHTTPTransport, MCPSession

__all__ = [
    "Transport",
    "TransportError",
    "StreamableHTTPTransport",
    "MCPSession",
]
