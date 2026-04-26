"""
MCP 服务注册管理器

实现 MCP 服务的动态注册、发现、加载和管理功能
支持：
- 服务 CRUD 操作
- 自动发现服务工具
- 动态加载和卸载
- 服务状态监控
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from models.mcp_server import MCPServer, MCPTool
from services.infrastructure.database import db_manager
from mcp.transport.streamable_http import StreamableHTTPTransport

logger = logging.getLogger(__name__)


# 支持的传输类型
TRANSPORT_TYPES = ['stdio', 'http', 'sse', 'streamable-http']

# 需要URL的传输类型
URL_REQUIRED_TYPES = ['http', 'sse', 'streamable-http']


@dataclass
class MCPServiceConfig:
    """MCP 服务配置数据类"""
    name: str
    transport_type: str = 'stdio'
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    auto_start: bool = True
    enabled: bool = True

    def validate(self) -> Tuple[bool, str]:
        """
        验证配置的有效性

        Returns:
            (is_valid, error_message)
        """
        # 检查传输类型是否支持
        if self.transport_type not in TRANSPORT_TYPES:
            return False, f"不支持的传输类型: {self.transport_type}，支持的类型: {TRANSPORT_TYPES}"

        # 检查 stdio 模式必须提供 command
        if self.transport_type == 'stdio' and not self.command:
            return False, "stdio 模式必须提供 command 参数"

        # 检查 http/sse/streamable-http 模式必须提供 url
        if self.transport_type in URL_REQUIRED_TYPES and not self.url:
            return False, f"{self.transport_type} 模式必须提供 url 参数"

        return True, ""


@dataclass
class MCPToolInfo:
    """MCP 工具信息数据类"""
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


class MCPRegistry:
    """
    MCP 服务注册管理器
    
    负责管理所有 MCP 服务的注册、发现、加载和状态监控
    """
    
    def __init__(self):
        """初始化注册管理器"""
        self._service_configs: Dict[str, MCPServiceConfig] = {}
        self._discovered_tools: Dict[str, List[MCPToolInfo]] = {}
        self._connection_status: Dict[str, str] = {}
        self._initialized = False
    
    def initialize(self):
        """初始化管理器，加载所有已注册的服务"""
        if self._initialized:
            return
        
        logger.info("[MCP Registry] 初始化服务注册管理器...")
        
        try:
            with db_manager.get_session() as session:
                # 加载所有启用的服务
                servers = session.query(MCPServer).filter(
                    MCPServer.enabled == True
                ).all()
                
                for server in servers:
                    config = MCPServiceConfig(
                        name=server.name,
                        transport_type=server.transport_type,
                        command=server.command,
                        args=json.loads(server.args) if server.args else None,
                        env=json.loads(server.env) if server.env else None,
                        url=server.url,
                        headers=json.loads(server.headers) if server.headers else None,
                        display_name=server.display_name,
                        description=server.description,
                        category=server.category,
                        tags=json.loads(server.tags) if server.tags else None,
                        auto_start=server.auto_start,
                        enabled=server.enabled
                    )
                    self._service_configs[server.name] = config
                    self._connection_status[server.name] = server.status
                    
                    # 加载缓存的工具
                    if server.tools_cache:
                        tools = json.loads(server.tools_cache)
                        self._discovered_tools[server.name] = [
                            MCPToolInfo(
                                name=t.get('name', ''),
                                description=t.get('description', ''),
                                input_schema=t.get('inputSchema', {}),
                                server_name=server.name
                            ) for t in tools
                        ]
                
                self._initialized = True
                logger.info(f"[MCP Registry] 已加载 {len(servers)} 个服务")
                
        except Exception as e:
            logger.error(f"[MCP Registry] 初始化失败: {e}")
    
    # ==================== 服务 CRUD 操作 ====================
    
    def register_service(
        self,
        name: str,
        transport_type: str = 'stdio',
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        auto_start: bool = True,
        enabled: bool = True
    ) -> Tuple[bool, str, Optional[MCPServer]]:
        """
        注册新的 MCP 服务
        
        Args:
            name: 服务名称（唯一标识）
            transport_type: 传输类型（stdio/sse/http/streamable-http）
            command: 启动命令（stdio模式）
            args: 命令参数
            env: 环境变量
            url: 服务URL（sse/http/streamable-http模式）
            headers: HTTP头
            display_name: 显示名称
            description: 描述
            category: 分类
            tags: 标签
            auto_start: 是否自动启动
            enabled: 是否启用
            
        Returns:
            (success, message, server_obj)
        """
        # 验证配置
        config = MCPServiceConfig(
            name=name,
            transport_type=transport_type,
            command=command,
            args=args,
            env=env,
            url=url,
            headers=headers,
            display_name=display_name,
            description=description,
            category=category,
            tags=tags,
            auto_start=auto_start,
            enabled=enabled
        )
        
        is_valid, error_msg = config.validate()
        if not is_valid:
            logger.warning(f"[MCP Registry] 注册服务失败（验证错误）: {name} - {error_msg}")
            return False, error_msg, None
        
        try:
            with db_manager.get_session() as session:
                # 检查是否已存在
                existing = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if existing:
                    return False, f"服务 '{name}' 已存在", None
                
                # 创建新服务
                server = MCPServer(
                    name=name,
                    display_name=display_name or name,
                    description=description,
                    transport_type=transport_type,
                    command=command,
                    args=json.dumps(args) if args else None,
                    env=json.dumps(env) if env else None,
                    url=url,
                    headers=json.dumps(headers) if headers else None,
                    status='disabled',
                    enabled=enabled,
                    auto_start=auto_start,
                    category=category,
                    tags=json.dumps(tags) if tags else None,
                    tools_count=0
                )
                
                session.add(server)
                session.flush()
                
                # 更新内存缓存
                self._service_configs[name] = config
                self._connection_status[name] = 'disabled'
                
                logger.info(f"[MCP Registry] 注册服务成功: {name} (类型: {transport_type})")
                return True, "服务注册成功", server.to_dict()
                
        except Exception as e:
            logger.error(f"[MCP Registry] 注册服务失败: {e}")
            return False, f"注册失败: {str(e)}", None
    
    def register_service_from_config(self, config: MCPServiceConfig) -> Tuple[bool, str, Optional[Dict]]:
        """
        从配置对象注册 MCP 服务
        
        Args:
            config: MCPServiceConfig 配置对象
            
        Returns:
            (success, message, server_dict)
        """
        return self.register_service(
            name=config.name,
            transport_type=config.transport_type,
            command=config.command,
            args=config.args,
            env=config.env,
            url=config.url,
            headers=config.headers,
            display_name=config.display_name,
            description=config.description,
            category=config.category,
            tags=config.tags,
            auto_start=config.auto_start,
            enabled=config.enabled,
        )
    
    def update_service(
        self,
        name: str,
        **kwargs
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        更新 MCP 服务配置
        
        Args:
            name: 服务名称
            **kwargs: 要更新的字段
            
        Returns:
            (success, message, updated_server)
        """
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if not server:
                    return False, f"服务 '{name}' 不存在", None
                
                # 可更新的字段
                updatable_fields = [
                    'display_name', 'description', 'command', 'url',
                    'enabled', 'auto_start', 'category', 'icon', 'documentation_url'
                ]
                
                for field in updatable_fields:
                    if field in kwargs:
                        setattr(server, field, kwargs[field])
                
                # 特殊处理 JSON 字段
                if 'args' in kwargs:
                    server.args = json.dumps(kwargs['args']) if kwargs['args'] else None
                if 'env' in kwargs:
                    server.env = json.dumps(kwargs['env']) if kwargs['env'] else None
                if 'headers' in kwargs:
                    server.headers = json.dumps(kwargs['headers']) if kwargs['headers'] else None
                if 'tags' in kwargs:
                    server.tags = json.dumps(kwargs['tags']) if kwargs['tags'] else None
                
                session.flush()
                
                # 更新内存缓存
                if name in self._service_configs:
                    config = self._service_configs[name]
                    for field in ['display_name', 'description', 'enabled', 'auto_start', 'category']:
                        if field in kwargs:
                            setattr(config, field, kwargs[field])
                
                logger.info(f"[MCP Registry] 更新服务成功: {name}")
                return True, "服务更新成功", server.to_dict()
                
        except Exception as e:
            logger.error(f"[MCP Registry] 更新服务失败: {e}")
            return False, f"更新失败: {str(e)}", None
    
    def delete_service(self, name: str) -> Tuple[bool, str]:
        """
        删除 MCP 服务
        
        Args:
            name: 服务名称
            
        Returns:
            (success, message)
        """
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if not server:
                    return False, f"服务 '{name}' 不存在"
                
                session.delete(server)
                
                # 更新内存缓存
                self._service_configs.pop(name, None)
                self._discovered_tools.pop(name, None)
                self._connection_status.pop(name, None)
                
                logger.info(f"[MCP Registry] 删除服务成功: {name}")
                return True, "服务删除成功"
                
        except Exception as e:
            logger.error(f"[MCP Registry] 删除服务失败: {e}")
            return False, f"删除失败: {str(e)}"
    
    def get_service(self, name: str) -> Optional[Dict]:
        """获取服务详情"""
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if server:
                    return server.to_dict()
                return None
        except Exception as e:
            logger.error(f"[MCP Registry] 获取服务失败: {e}")
            return None
    
    def list_services(
        self,
        enabled_only: bool = False,
        category: Optional[str] = None
    ) -> List[Dict]:
        """
        列出所有 MCP 服务
        
        Args:
            enabled_only: 是否只返回启用的服务
            category: 按分类过滤
            
        Returns:
            服务列表
        """
        try:
            with db_manager.get_session() as session:
                query = session.query(MCPServer)
                
                if enabled_only:
                    query = query.filter(MCPServer.enabled == True)
                
                if category:
                    query = query.filter(MCPServer.category == category)
                
                servers = query.order_by(MCPServer.created_at.desc()).all()
                return [s.to_dict() for s in servers]
                
        except Exception as e:
            logger.error(f"[MCP Registry] 列出服务失败: {e}")
            return []
    
    # ==================== 服务状态管理 ====================
    
    def set_service_status(
        self,
        name: str,
        status: str,
        error: Optional[str] = None
    ) -> bool:
        """
        设置服务状态
        
        Args:
            name: 服务名称
            status: 状态（disabled/enabled/connected/error）
            error: 错误信息
            
        Returns:
            是否成功
        """
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if server:
                    server.status = status
                    if error:
                        server.last_error = error
                    if status == 'connected':
                        server.last_connected_at = datetime.utcnow()
                    
                    self._connection_status[name] = status
                    return True
                return False
                
        except Exception as e:
            logger.error(f"[MCP Registry] 设置状态失败: {e}")
            return False
    
    def enable_service(self, name: str) -> Tuple[bool, str]:
        """启用服务"""
        result, msg, _ = self.update_service(name, enabled=True)
        return result, msg
    
    def disable_service(self, name: str) -> Tuple[bool, str]:
        """禁用服务"""
        result, msg, _ = self.update_service(name, enabled=False)
        if result:
            self.set_service_status(name, 'disabled')
        return result, msg
    
    # ==================== 工具发现 ====================
    
    def _load_service_config_from_db(self, name: str) -> Optional[MCPServiceConfig]:
        """从数据库加载服务配置"""
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if server:
                    return MCPServiceConfig(
                        name=server.name,
                        transport_type=server.transport_type,
                        command=server.command,
                        args=json.loads(server.args) if server.args else None,
                        env=json.loads(server.env) if server.env else None,
                        url=server.url,
                        headers=json.loads(server.headers) if server.headers else None,
                        display_name=server.display_name,
                        description=server.description,
                        category=server.category,
                        tags=json.loads(server.tags) if server.tags else None,
                        auto_start=server.auto_start,
                        enabled=server.enabled
                    )
        except Exception as e:
            logger.error(f"[MCP Registry] 从数据库加载服务配置失败: {e}")
        
        return None
    
    async def discover_tools(self, name: str) -> Tuple[bool, str, List[Dict]]:
        """
        发现服务的工具列表
        
        Args:
            name: 服务名称
            
        Returns:
            (success, message, tools)
        """
        config = self._service_configs.get(name)
        
        # 如果内存缓存中没有，尝试从数据库加载
        if not config:
            config = self._load_service_config_from_db(name)
            if config:
                self._service_configs[name] = config
                logger.info(f"[MCP Registry] 从数据库加载服务配置: {name}")
        
        if not config:
            return False, f"服务 '{name}' 不存在", []
        
        try:
            if config.transport_type == 'streamable-http':
                tools = await self._discover_tools_streamable_http(config)
            elif config.transport_type == 'http':
                tools = await self._discover_tools_http(config)
            elif config.transport_type == 'sse':
                tools = await self._discover_tools_sse(config)
            else:
                tools = await self._discover_tools_stdio(config)
            
            # 更新数据库缓存
            await self._update_tools_cache(name, tools)
            
            # 更新内存缓存
            self._discovered_tools[name] = [
                MCPToolInfo(
                    name=t.get('name', ''),
                    description=t.get('description', ''),
                    input_schema=t.get('inputSchema', {}),
                    server_name=name
                ) for t in tools
            ]
            
            self.set_service_status(name, 'connected')
            
            logger.info(f"[MCP Registry] 发现 {len(tools)} 个工具: {name}")
            return True, f"发现 {len(tools)} 个工具", tools
            
        except Exception as e:
            error_msg = f"工具发现失败: {str(e)}"
            logger.error(f"[MCP Registry] {error_msg}")
            self.set_service_status(name, 'error', error_msg)
            return False, error_msg, []
    
    async def _discover_tools_streamable_http(self, config: MCPServiceConfig) -> List[Dict]:
        """
        通过 Streamable HTTP 发现工具
        
        使用 StreamableHTTPTransport 与 MCP v2025.03.26 服务通信
        
        Args:
            config: 服务配置
            
        Returns:
            工具列表
        """
        if not config.url:
            logger.warning(f"[MCP Registry] streamable-http 服务缺少 URL: {config.name}")
            return []
        
        logger.info(f"[MCP Registry] 使用 StreamableHTTP 发现工具: {config.name} -> {config.url}")
        
        transport = StreamableHTTPTransport(
            base_url=config.url,
            headers=config.headers,
            timeout=30.0
        )
        
        try:
            # 使用传输层的 discover_tools 方法
            response = await transport.discover_tools()
            
            if response.success and response.result:
                tools = response.result.get('tools', [])
                logger.info(f"[MCP Registry] StreamableHTTP 发现 {len(tools)} 个工具: {config.name}")
                return tools
            else:
                error_msg = response.error.get('message', 'Unknown error') if response.error else 'No tools found'
                logger.warning(f"[MCP Registry] StreamableHTTP 工具发现失败: {config.name} - {error_msg}")
                return []
                
        except Exception as e:
            logger.error(f"[MCP Registry] StreamableHTTP 通信错误: {config.name} - {e}")
            return []
        finally:
            await transport.close()
    
    async def _discover_tools_http(self, config: MCPServiceConfig) -> List[Dict]:
        """通过 HTTP 发现工具"""
        import httpx
        
        if not config.url:
            return []
        
        headers = config.headers or {}
        headers['Content-Type'] = 'application/json'
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
            
            response = await client.post(
                config.url,
                headers=headers,
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                if "result" in result and "tools" in result["result"]:
                    return result["result"]["tools"]
            
        return []
    
    async def _discover_tools_sse(self, config: MCPServiceConfig) -> List[Dict]:
        """通过 SSE 发现工具"""
        # SSE 方式与 HTTP 类似，但需要建立长连接
        return await self._discover_tools_http(config)
    
    async def _discover_tools_stdio(self, config: MCPServiceConfig) -> List[Dict]:
        """通过 stdio 发现工具"""
        # stdio 方式需要启动子进程
        # 这里使用模拟数据，实际需要通过子进程通信
        logger.warning(f"[MCP Registry] stdio 模式工具发现需要子进程支持: {config.name}")
        return []
    
    async def _update_tools_cache(self, name: str, tools: List[Dict]):
        """更新工具缓存到数据库"""
        try:
            with db_manager.get_session() as session:
                server = session.query(MCPServer).filter(
                    MCPServer.name == name
                ).first()
                
                if server:
                    server.tools_cache = json.dumps(tools)
                    server.tools_count = len(tools)
                    
                    # 更新 mcp_tools 表
                    # 先删除旧的工具记录
                    session.query(MCPTool).filter(
                        MCPTool.server_id == server.id
                    ).delete()
                    
                    # 添加新的工具记录
                    for tool in tools:
                        mcp_tool = MCPTool(
                            server_id=server.id,
                            name=tool.get('name', ''),
                            description=tool.get('description', ''),
                            input_schema=json.dumps(tool.get('inputSchema', {})),
                            enabled=True
                        )
                        session.add(mcp_tool)
                        
        except Exception as e:
            logger.error(f"[MCP Registry] 更新工具缓存失败: {e}")
    
    async def discover_all_tools(self) -> Dict[str, List[Dict]]:
        """发现所有启用服务的工具"""
        results = {}
        
        for name, config in self._service_configs.items():
            if config.enabled:
                success, msg, tools = await self.discover_tools(name)
                results[name] = tools if success else []
        
        return results
    
    # ==================== 工具获取 ====================
    
    def get_all_tools(self) -> List[MCPToolInfo]:
        """获取所有已发现的工具"""
        all_tools = []
        for tools in self._discovered_tools.values():
            all_tools.extend(tools)
        return all_tools
    
    def get_tools_by_server(self, server_name: str) -> List[MCPToolInfo]:
        """获取指定服务的工具"""
        return self._discovered_tools.get(server_name, [])
    
    def get_tools_by_category(self, category: str) -> List[MCPToolInfo]:
        """按分类获取工具（仅返回启用服务的工具）"""
        tools = []
        for name, config in self._service_configs.items():
            # 只返回启用服务的工具
            if config.category == category and config.enabled:
                tools.extend(self._discovered_tools.get(name, []))
        return tools
    
    # ==================== 配置导出 ====================
    
    def export_config(self) -> Dict[str, Any]:
        """导出所有服务配置（用于 mcp_servers_config.json 格式）"""
        config = {"mcpServers": {}}
        
        for name, cfg in self._service_configs.items():
            server_config = {}
            
            if cfg.transport_type == 'stdio':
                server_config['command'] = cfg.command
                if cfg.args:
                    server_config['args'] = cfg.args
                if cfg.env:
                    server_config['env'] = cfg.env
            else:
                # http/sse/streamable-http 类型
                server_config['url'] = cfg.url
                server_config['transport_type'] = cfg.transport_type
                if cfg.headers:
                    server_config['headers'] = cfg.headers
            
            config['mcpServers'][name] = server_config
        
        return config
    
    def import_config(self, config: Dict[str, Any]) -> Tuple[int, int]:
        """
        从配置导入服务（mcp_servers_config.json 格式）
        
        Returns:
            (成功数量, 失败数量)
        """
        success_count = 0
        fail_count = 0
        
        servers = config.get('mcpServers', {})
        for name, server_config in servers.items():
            # 判断传输类型
            if 'command' in server_config:
                transport_type = 'stdio'
                command = server_config.get('command')
                args = server_config.get('args')
                env = server_config.get('env')
                url = None
                headers = None
            else:
                # 从配置中获取传输类型，默认根据 URL 格式判断
                transport_type = server_config.get('transport_type')
                if not transport_type:
                    # 自动检测：以 /mcp 结尾的视为 streamable-http
                    url = server_config.get('url', '')
                    if url.rstrip('/').endswith('/mcp'):
                        transport_type = 'streamable-http'
                    else:
                        transport_type = 'http'
                command = None
                args = None
                env = None
                url = server_config.get('url')
                headers = server_config.get('headers')
            
            success, msg, _ = self.register_service(
                name=name,
                transport_type=transport_type,
                command=command,
                args=args,
                env=env,
                url=url,
                headers=headers
            )
            
            if success:
                success_count += 1
            else:
                fail_count += 1
                logger.warning(f"[MCP Registry] 导入服务失败: {name} - {msg}")
        
        return success_count, fail_count
    
    # ==================== 刷新操作 ====================
    
    async def refresh_service(self, name: str) -> Tuple[bool, str]:
        """
        刷新单个服务（重新发现工具）
        
        Args:
            name: 服务名称
            
        Returns:
            (success, message)
        """
        if name not in self._service_configs:
            return False, f"服务 '{name}' 不存在"
        
        success, msg, tools = await self.discover_tools(name)
        return success, msg
    
    async def refresh_all_services(self) -> Dict[str, Tuple[bool, str]]:
        """
        刷新所有启用的服务
        
        Returns:
            {服务名: (success, message)}
        """
        results = {}
        
        for name, config in self._service_configs.items():
            if config.enabled:
                success, msg = await self.refresh_service(name)
                results[name] = (success, msg)
        
        return results
    
    # ==================== 统计信息 ====================
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（从数据库获取准确数据）"""
        try:
            with db_manager.get_session() as session:
                # 从数据库获取准确统计
                total_services = session.query(MCPServer).count()
                enabled_services = session.query(MCPServer).filter(MCPServer.enabled == True).count()
                connected_services = session.query(MCPServer).filter(MCPServer.status == 'connected').count()
                error_services = session.query(MCPServer).filter(MCPServer.status == 'error').count()
                total_tools = session.query(MCPTool).count()
                
                return {
                    'total_services': total_services,
                    'enabled_services': enabled_services,
                    'connected_services': connected_services,
                    'error_services': error_services,
                    'disabled_services': total_services - enabled_services,
                    'total_tools': total_tools,
                }
        except Exception as e:
            logger.error(f"[MCP Registry] 获取统计信息失败: {e}")
            # 回退到内存统计
            total_services = len(self._service_configs)
            enabled_services = sum(1 for c in self._service_configs.values() if c.enabled)
            connected_services = sum(1 for s in self._connection_status.values() if s == 'connected')
            error_services = sum(1 for s in self._connection_status.values() if s == 'error')
            total_tools = sum(len(t) for t in self._discovered_tools.values())
            
            return {
                'total_services': total_services,
                'enabled_services': enabled_services,
                'connected_services': connected_services,
                'error_services': error_services,
                'disabled_services': total_services - enabled_services,
                'total_tools': total_tools,
            }
    
    # ==================== 服务自动发现 ====================
    
    def auto_discover_services(self) -> Dict[str, Any]:
        """
        自动发现并注册系统配置的 MCP 服务
        
        扫描 Config 中的 MCP 相关配置，自动注册到数据库中。
        已存在的服务不会被覆盖。
        
        Returns:
            发现结果统计
        """
        from config import Config
        
        logger.info("[MCP Registry] 开始自动发现服务...")
        
        results = {
            'discovered': [],
            'registered': [],
            'skipped': [],
            'errors': []
        }
        
        # 1. 发现百度联网搜索服务
        if Config.BAIDU_MCP_API_KEY:
            service_info = {
                'name': 'baidu_web_search',
                'display_name': '百度联网搜索',
                'description': '百度千帆平台提供的 Web 搜索 MCP 服务，支持实时网页搜索、新闻搜索等功能',
                'transport_type': 'http',
                'url': Config.BAIDU_MCP_URL,
                'headers': {
                    'Authorization': f'Bearer {Config.BAIDU_MCP_API_KEY}'
                },
                'category': 'search',
                'tags': ['web', 'search', 'baidu', 'internet'],
                'enabled': Config.WEB_SEARCH_ENABLED,
                'auto_start': True
            }
            results['discovered'].append(service_info)
            logger.info(f"[MCP Registry] 发现服务配置: baidu_web_search (API Key 已配置)")
        else:
            logger.info("[MCP Registry] 百度联网搜索: API Key 未配置，跳过")
        
        # 2. 注册发现的服务
        for service_info in results['discovered']:
            name = service_info['name']
            
            # 检查是否已存在
            existing = self.get_service(name)
            if existing:
                results['skipped'].append(name)
                logger.info(f"[MCP Registry] 服务已存在，跳过注册: {name}")
                continue
            
            # 注册服务
            try:
                success, msg, _ = self.register_service(
                    name=name,
                    transport_type=service_info.get('transport_type', 'http'),
                    display_name=service_info.get('display_name'),
                    description=service_info.get('description'),
                    url=service_info.get('url'),
                    headers=service_info.get('headers'),
                    command=service_info.get('command'),
                    args=service_info.get('args'),
                    env=service_info.get('env'),
                    category=service_info.get('category'),
                    tags=service_info.get('tags'),
                    enabled=service_info.get('enabled', True),
                    auto_start=service_info.get('auto_start', True)
                )
                
                if success:
                    results['registered'].append(name)
                    logger.info(f"[MCP Registry] 自动注册服务成功: {name}")
                else:
                    results['errors'].append({'name': name, 'error': msg})
                    logger.warning(f"[MCP Registry] 自动注册服务失败: {name} - {msg}")
                    
            except Exception as e:
                results['errors'].append({'name': name, 'error': str(e)})
                logger.error(f"[MCP Registry] 自动注册服务异常: {name} - {e}")
        
        # 汇总日志
        logger.info(
            f"[MCP Registry] 服务发现完成: "
            f"发现 {len(results['discovered'])} 个, "
            f"注册 {len(results['registered'])} 个, "
            f"跳过 {len(results['skipped'])} 个, "
            f"错误 {len(results['errors'])} 个"
        )
        
        return results
    
    def sync_with_adapters(self) -> Dict[str, Any]:
        """
        与 adapters.py 中的硬编码服务同步
        
        确保 adapters.py 中提供的服务也注册到数据库中，
        以便前端可以管理和查看这些服务。
        
        Returns:
            同步结果
        """
        from config import Config
        
        logger.info("[MCP Registry] 同步 adapters 服务...")
        
        results = {
            'synced': [],
            'skipped': [],
            'errors': []
        }
        
        # 百度联网搜索适配器
        if Config.BAIDU_MCP_API_KEY:
            name = 'baidu_web_search'
            existing = self.get_service(name)
            
            if not existing:
                # 注册到数据库
                success, msg, _ = self.register_service(
                    name=name,
                    transport_type='http',
                    display_name='百度联网搜索',
                    description='百度千帆平台提供的 Web 搜索 MCP 服务',
                    url=Config.BAIDU_MCP_URL,
                    headers={'Authorization': f'Bearer {Config.BAIDU_MCP_API_KEY}'},
                    category='search',
                    tags=['web', 'search', 'baidu'],
                    enabled=Config.WEB_SEARCH_ENABLED,
                    auto_start=True
                )
                
                if success:
                    results['synced'].append(name)
                    logger.info(f"[MCP Registry] 同步服务成功: {name}")
                else:
                    results['errors'].append({'name': name, 'error': msg})
            else:
                results['skipped'].append(name)
        
        return results
    
    # ==================== 配置导入导出 ====================
    
    def import_config(self, config_dict: Dict[str, Any]) -> Tuple[bool, str, int]:
        """
        从字典导入服务配置（兼容 Claude Desktop 配置格式）
        
        支持格式:
        {
            "mcpServers": {
                "server_name": {
                    "transport": "http",
                    "url": "https://example.com/mcp"
                }
            }
        }
        
        Args:
            config_dict: 配置字典
            
        Returns:
            (success, message, imported_count)
        """
        imported = 0
        errors = []
        
        mcp_servers = config_dict.get("mcpServers", {})
        if not mcp_servers:
            return False, "配置中没有 mcpServers 字段", 0
        
        for name, server_config in mcp_servers.items():
            try:
                # 解析传输类型
                transport = server_config.get("transport", "stdio")
                # 兼容旧的 transport 字段
                if transport == "http":
                    transport_type = "streamable-http"
                else:
                    transport_type = transport
                
                # 注册服务
                success, msg, _ = self.register_service(
                    name=name,
                    transport_type=transport_type,
                    url=server_config.get("url"),
                    command=server_config.get("command"),
                    args=server_config.get("args"),
                    env=server_config.get("env"),
                    headers=server_config.get("headers"),
                    display_name=server_config.get("display_name", name),
                    description=server_config.get("description"),
                    category=server_config.get("category"),
                    tags=server_config.get("tags"),
                    enabled=server_config.get("enabled", True),
                    auto_start=server_config.get("auto_start", True),
                )
                
                if success:
                    imported += 1
                else:
                    errors.append(f"{name}: {msg}")
                    
            except Exception as e:
                errors.append(f"{name}: {str(e)}")
        
        if errors:
            return True, f"导入了 {imported} 个服务，{len(errors)} 个失败: {'; '.join(errors[:3])}", imported
        
        return True, f"成功导入 {imported} 个服务", imported
    
    def export_config(self, include_disabled: bool = False) -> Dict[str, Any]:
        """
        导出服务配置为字典格式（兼容 Claude Desktop 配置格式）
        
        Args:
            include_disabled: 是否包含禁用的服务
            
        Returns:
            配置字典
        """
        services = self.list_services()
        mcp_servers = {}
        
        for server in services:
            if not include_disabled and not server.get("enabled", True):
                continue
            
            config = {
                "transport": server.get("transport_type", "stdio"),
            }
            
            if server.get("url"):
                config["url"] = server["url"]
            if server.get("command"):
                config["command"] = server["command"]
            if server.get("args"):
                config["args"] = server["args"]
            if server.get("env"):
                config["env"] = server["env"]
            if server.get("headers"):
                config["headers"] = server["headers"]
            if server.get("display_name"):
                config["display_name"] = server["display_name"]
            if server.get("description"):
                config["description"] = server["description"]
            if server.get("category"):
                config["category"] = server["category"]
            if server.get("tags"):
                config["tags"] = server["tags"]
            
            mcp_servers[server["name"]] = config
        
        # 也包含内存缓存中未持久化的服务
        for name, config_obj in self._service_configs.items():
            if name not in mcp_servers:
                if not include_disabled and not config_obj.enabled:
                    continue
                
                config = {
                    "transport": config_obj.transport_type,
                }
                
                if config_obj.url:
                    config["url"] = config_obj.url
                if config_obj.command:
                    config["command"] = config_obj.command
                if config_obj.args:
                    config["args"] = config_obj.args
                if config_obj.env:
                    config["env"] = config_obj.env
                if config_obj.headers:
                    config["headers"] = config_obj.headers
                if config_obj.display_name:
                    config["display_name"] = config_obj.display_name
                if config_obj.description:
                    config["description"] = config_obj.description
                if config_obj.category:
                    config["category"] = config_obj.category
                if config_obj.tags:
                    config["tags"] = config_obj.tags
                
                mcp_servers[name] = config
        
        return {"mcpServers": mcp_servers}
    
    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str, Any]:
        """
        便捷方法：调用指定服务的工具
        
        Args:
            server_name: 服务名称
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            (success, message, result)
        """
        config = self._service_configs.get(server_name)
        if not config:
            config = self._load_service_config_from_db(server_name)
            if config:
                self._service_configs[server_name] = config
        
        if not config:
            return False, f"服务 '{server_name}' 不存在", None
        
        if config.transport_type not in URL_REQUIRED_TYPES:
            return False, f"服务 '{server_name}' 不支持 HTTP 调用", None
        
        try:
            transport = StreamableHTTPTransport(
                base_url=config.url,
                headers=config.headers,
                timeout=30.0,
            )
            
            # 初始化连接
            init_response = await transport.initialize()
            if not init_response.success:
                return False, f"初始化失败: {init_response.error}", None
            
            # 调用工具
            tool_response = await transport.call_tool(tool_name, arguments)
            
            await transport.close()
            
            if tool_response.success:
                return True, "调用成功", tool_response.result
            else:
                return False, f"调用失败: {tool_response.error}", None
                
        except Exception as e:
            logger.error(f"[MCP Registry] 调用工具失败: {e}")
            return False, f"调用异常: {str(e)}", None


# 创建全局实例
mcp_registry = MCPRegistry()


# 导出
__all__ = ['MCPRegistry', 'mcp_registry', 'MCPServiceConfig', 'MCPToolInfo']