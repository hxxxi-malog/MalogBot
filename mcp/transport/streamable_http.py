"""
MCP Streamable HTTP 传输实现

实现 MCP v2025.03.26 的 Streamable HTTP 传输协议。

核心特性：
1. 统一消息入口：所有消息通过单一 /message 端点
2. 会话管理：服务器可返回 Mcp-Session-Id 头
3. 动态 SSE 升级：服务器可将请求升级为 SSE 连接
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime

import httpx

from mcp.transport.base import (
    Transport,
    TransportError,
    TransportType,
    MCPResponse,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPSession:
    """
    MCP 会话状态管理

    封装会话 ID、创建时间、最后活动时间等信息。
    提供会话状态检查和更新能力。
    """

    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """更新最后活动时间"""
        self.last_activity = datetime.utcnow()

    def is_expired(self, timeout_seconds: int = 3600) -> bool:
        """
        检查会话是否过期

        Args:
            timeout_seconds: 超时时间（秒），默认 1 小时

        Returns:
            是否已过期
        """
        elapsed = (datetime.utcnow() - self.last_activity).total_seconds()
        return elapsed > timeout_seconds

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "metadata": self.metadata,
        }


class StreamableHTTPTransport(Transport):
    """
    Streamable HTTP 传输实现

    实现 MCP v2025.03.26 的 Streamable HTTP 协议：
    - 所有请求发送到统一的 /message 端点
    - 支持会话管理（Mcp-Session-Id 头）
    - 支持 SSE 升级（Accept: text/event-stream）

    使用示例:
        transport = StreamableHTTPTransport("http://localhost:8020/mcp")
        response = await transport.discover_tools()
        print(response.get_content())
    """

    transport_type = TransportType.STREAMABLE_HTTP

    # MCP 协议版本
    PROTOCOL_VERSION = "2025-03-26"

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 30.0

    # 最大重试次数
    MAX_RETRIES = 3

    # 重试延迟（指数退避基数）
    RETRY_BASE_DELAY = 1.0

    def __init__(
        self,
        base_url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        session_id: Optional[str] = None,
    ):
        """
        初始化 Streamable HTTP 传输

        Args:
            base_url: MCP 服务基础 URL（如 http://localhost:8020/mcp）
            headers: 请求头（如 Authorization）
            timeout: 请求超时时间（秒）
            session_id: 初始会话 ID（可选）
        """
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout
        self._session_id = session_id
        self._request_id = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False

        # 会话管理
        self._sessions: dict[str, MCPSession] = {}
        if session_id:
            self._sessions[session_id] = MCPSession(session_id=session_id)

        logger.info(f"[StreamableHTTP] 初始化传输层: {self.base_url}")

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @property
    def session_id(self) -> Optional[str]:
        """当前会话 ID"""
        return self._session_id

    @session_id.setter
    def session_id(self, value: Optional[str]) -> None:
        """设置会话 ID"""
        self._session_id = value
        if value and value not in self._sessions:
            self._sessions[value] = MCPSession(session_id=value)
        if value:
            self._sessions[value].touch()

    @property
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._connected

    def _build_message_url(self) -> str:
        """
        构建消息端点 URL

        MCP v2025.03.26 规定服务器提供单一的 MCP 端点路径（如 /mcp），
        所有消息直接发送到该端点，而不是 /message 子路径。
        """
        return self.base_url

    def _get_next_request_id(self) -> int:
        """获取下一个请求 ID"""
        self._request_id += 1
        return self._request_id

    def _build_headers(self, for_sse: bool = False) -> dict[str, str]:
        """
        构建请求头

        Args:
            for_sse: 是否为 SSE 请求

        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
            **self.headers,
        }

        # SSE 升级请求需要设置 Accept 头
        if for_sse:
            headers["Accept"] = "text/event-stream"
        else:
            headers["Accept"] = "application/json, text/event-stream"

        # 添加会话 ID
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        return headers

    async def send_request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> MCPResponse:
        """
        发送 MCP 请求

        实现重试机制：
        - 网络错误自动重试（指数退避）
        - 超时错误重试
        - 服务器错误（5xx）重试

        Args:
            method: MCP 方法名
            params: 方法参数
            session_id: 可选的会话 ID（覆盖当前会话）

        Returns:
            MCPResponse 对象
        """
        # 临时覆盖会话 ID（仅本次请求使用）
        if session_id:
            self.session_id = session_id

        return await self._send_with_retry(method, params)

    async def _send_with_retry(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> MCPResponse:
        """
        带重试的请求发送

        Args:
            method: MCP 方法名
            params: 方法参数

        Returns:
            MCPResponse 对象
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._send_single_request(method, params)
                self._connected = True
                return response

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                logger.warning(
                    f"[StreamableHTTP] 请求失败 (尝试 {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )

                if attempt < self.MAX_RETRIES - 1:
                    # 指数退避
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.info(f"[StreamableHTTP] 等待 {delay}秒后重试...")
                    await asyncio.sleep(delay)
                    continue

            except httpx.HTTPStatusError as e:
                # 5xx 错误重试
                if 500 <= e.response.status_code < 600:
                    last_error = e
                    logger.warning(
                        f"[StreamableHTTP] 服务器错误 {e.response.status_code} (尝试 {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    if attempt < self.MAX_RETRIES - 1:
                        delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                else:
                    # 4xx 错误不重试
                    self._connected = False
                    return MCPResponse(
                        success=False,
                        error={
                            "code": e.response.status_code,
                            "message": f"HTTP {e.response.status_code}: {e.response.text}",
                        },
                    )

            except Exception as e:
                last_error = e
                logger.error(f"[StreamableHTTP] 未预期的错误: {e}")
                break

        # 所有重试失败
        self._connected = False
        return MCPResponse(
            success=False,
            error={
                "code": "TRANSPORT_ERROR",
                "message": str(last_error) if last_error else "Unknown error",
            },
        )

    async def _send_single_request(
        self, method: str, params: Optional[dict[str, Any]] = None
    ) -> MCPResponse:
        """
        发送单个请求（无重试）

        Args:
            method: MCP 方法名
            params: 方法参数

        Returns:
            MCPResponse 对象
        """
        client = await self._get_client()
        url = self._build_message_url()
        headers = self._build_headers()

        # 构建 JSON-RPC 请求
        payload = {
            "jsonrpc": "2.0",
            "id": self._get_next_request_id(),
            "method": method,
            "params": params or {},
        }

        logger.debug(f"[StreamableHTTP] 发送请求: {method} -> {url}")

        response = await client.post(url, headers=headers, json=payload)

        # 检查响应状态
        if response.status_code != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}",
                request=response.request,
                response=response,
            )

        # 提取会话 ID
        new_session_id = response.headers.get("Mcp-Session-Id")
        if new_session_id and new_session_id != self._session_id:
            logger.info(f"[StreamableHTTP] 收到新会话 ID: {new_session_id}")
            self.session_id = new_session_id

        # 检查是否为 SSE 响应
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            logger.debug("[StreamableHTTP] 收到 SSE 响应，处理事件流...")
            return await self._handle_sse_response(response)

        # 处理普通 JSON 响应
        return self._handle_json_response(response)

    def _handle_json_response(self, response: httpx.Response) -> MCPResponse:
        """
        处理 JSON 响应

        Args:
            response: HTTP 响应对象

        Returns:
            MCPResponse 对象
        """
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"[StreamableHTTP] JSON 解析失败: {e}")
            return MCPResponse(
                success=False,
                error={"code": "PARSE_ERROR", "message": f"Invalid JSON: {e}"},
            )

        # 检查 JSON-RPC 错误
        if "error" in data:
            return MCPResponse(
                success=False,
                error=data["error"],
                session_id=self._session_id,
            )

        # 返回成功结果
        return MCPResponse(
            success=True,
            result=data.get("result"),
            session_id=self._session_id,
        )

    async def _handle_sse_response(self, response: httpx.Response) -> MCPResponse:
        """
        处理 SSE 事件流响应

        Args:
            response: HTTP 响应对象

        Returns:
            MCPResponse 对象（包含最后一个事件的数据）
        """
        last_event_data: Optional[dict[str, Any]] = None

        try:
            # 读取 SSE 事件流
            async for line in response.aiter_lines():
                line = line.strip()

                # 跳过空行和注释
                if not line or line.startswith(":"):
                    continue

                # 解析 data 字段
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        event_data = json.loads(data_str)

                        # 检查是否为最终响应
                        if "result" in event_data or "error" in event_data:
                            last_event_data = event_data

                        # 可以在这里添加事件回调机制

                    except json.JSONDecodeError:
                        logger.warning(f"[StreamableHTTP] 无法解析 SSE 数据: {data_str}")

        except Exception as e:
            logger.error(f"[StreamableHTTP] SSE 流处理错误: {e}")
            return MCPResponse(
                success=False,
                error={"code": "SSE_ERROR", "message": str(e)},
            )

        # 返回最后一个事件的结果
        if last_event_data:
            if "error" in last_event_data:
                return MCPResponse(
                    success=False,
                    error=last_event_data["error"],
                    session_id=self._session_id,
                )
            return MCPResponse(
                success=True,
                result=last_event_data.get("result"),
                session_id=self._session_id,
            )

        return MCPResponse(
            success=False,
            error={"code": "NO_DATA", "message": "No data received from SSE stream"},
            session_id=self._session_id,
        )

    async def close(self) -> None:
        """关闭传输连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info("[StreamableHTTP] 连接已关闭")

        self._connected = False
        self._client = None

    # ==================== 会话管理 ====================

    def create_session(self, session_id: Optional[str] = None) -> MCPSession:
        """
        创建新会话

        Args:
            session_id: 可选的会话 ID（不提供则自动生成）

        Returns:
            MCPSession 对象
        """
        if not session_id:
            import uuid

            session_id = str(uuid.uuid4())

        session = MCPSession(session_id=session_id)
        self._sessions[session_id] = session
        logger.info(f"[StreamableHTTP] 创建会话: {session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[MCPSession]:
        """获取会话"""
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> bool:
        """移除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"[StreamableHTTP] 移除会话: {session_id}")
            return True
        return False

    def cleanup_expired_sessions(self, timeout_seconds: int = 3600) -> int:
        """
        清理过期会话

        Args:
            timeout_seconds: 超时时间（秒）

        Returns:
            清理的会话数量
        """
        expired = [
            sid for sid, session in self._sessions.items() if session.is_expired(timeout_seconds)
        ]

        for sid in expired:
            del self._sessions[sid]

        if expired:
            logger.info(f"[StreamableHTTP] 清理过期会话: {len(expired)} 个")

        return len(expired)

    # ==================== 静态工具方法 ====================

    @staticmethod
    def is_streamable_http_url(url: str) -> bool:
        """
        判断 URL 是否可能是 Streamable HTTP 端点

        Args:
            url: 服务 URL

        Returns:
            是否可能是 Streamable HTTP
        """
        # Streamable HTTP 通常以 /mcp 结尾
        return url.rstrip("/").endswith("/mcp")

    # ==================== MCP 便捷方法 ====================

    async def initialize(
        self,
        client_name: str = "MalogBot",
        client_version: str = "1.0.0",
        capabilities: Optional[dict[str, Any]] = None,
    ) -> MCPResponse:
        """
        初始化 MCP 连接

        Args:
            client_name: 客户端名称
            client_version: 客户端版本
            capabilities: 客户端能力

        Returns:
            MCPResponse 对象
        """
        params = {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": capabilities or {},
            "clientInfo": {
                "name": client_name,
                "version": client_version,
            },
        }
        return await self.send_request("initialize", params)

    async def list_tools(self) -> MCPResponse:
        """
        获取工具列表

        Returns:
            MCPResponse 对象，result 包含 tools 列表
        """
        return await self.send_request("tools/list")

    async def call_tool(
        self,
        name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> MCPResponse:
        """
        调用工具

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            MCPResponse 对象
        """
        params = {
            "name": name,
            "arguments": arguments or {},
        }
        return await self.send_request("tools/call", params)

    async def list_resources(self) -> MCPResponse:
        """
        获取资源列表

        Returns:
            MCPResponse 对象
        """
        return await self.send_request("resources/list")

    async def read_resource(self, uri: str) -> MCPResponse:
        """
        读取资源

        Args:
            uri: 资源 URI

        Returns:
            MCPResponse 对象
        """
        return await self.send_request("resources/read", {"uri": uri})

    async def list_prompts(self) -> MCPResponse:
        """
        获取提示词列表

        Returns:
            MCPResponse 对象
        """
        return await self.send_request("prompts/list")

    async def get_prompt(
        self,
        name: str,
        arguments: Optional[dict[str, str]] = None,
    ) -> MCPResponse:
        """
        获取提示词

        Args:
            name: 提示词名称
            arguments: 提示词参数

        Returns:
            MCPResponse 对象
        """
        params = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return await self.send_request("prompts/get", params)

    async def ping(self) -> MCPResponse:
        """
        发送 ping 请求

        Returns:
            MCPResponse 对象
        """
        return await self.send_request("ping")

    @staticmethod
    async def probe(base_url: str, timeout: float = 5.0) -> bool:
        """
        探测服务是否支持 Streamable HTTP

        Args:
            base_url: 服务基础 URL
            timeout: 超时时间

        Returns:
            是否支持
        """
        transport = StreamableHTTPTransport(base_url, timeout=timeout)
        try:
            response = await transport.ping()
            return response.success
        except Exception:
            return False
        finally:
            await transport.close()


__all__ = ["StreamableHTTPTransport", "MCPSession"]
