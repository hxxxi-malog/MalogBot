"""
MCP 服务数据库模型

用于存储动态注册的 MCP 服务配置
支持服务的 CRUD 操作和状态管理
"""
import uuid
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, Index, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from models.database import Base


class MCPServer(Base):
    """
    MCP 服务配置模型
    
    存储用户注册的 MCP 服务信息，支持：
    - 多种传输类型：stdio, sse, http
    - 自动发现和注册
    - 服务状态管理
    """
    __tablename__ = 'mcp_servers'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # 基本信息
    name = Column(String(100), unique=True, nullable=False, index=True)  # 服务名称（唯一标识）
    display_name = Column(String(200), nullable=True)  # 显示名称
    description = Column(Text, nullable=True)  # 服务描述
    
    # 连接配置
    transport_type = Column(String(20), nullable=False, default='stdio')  # stdio, sse, http
    command = Column(String(500), nullable=True)  # 启动命令（stdio模式）
    args = Column(Text, nullable=True)  # 命令参数（JSON数组格式）
    env = Column(Text, nullable=True)  # 环境变量（JSON对象格式）
    url = Column(String(500), nullable=True)  # 服务URL（sse/http模式）
    headers = Column(Text, nullable=True)  # HTTP头（JSON对象格式，用于认证等）
    
    # 服务状态
    status = Column(String(20), default='disabled', nullable=False)  # disabled, enabled, connected, error
    enabled = Column(Boolean, default=True, nullable=False)  # 是否启用
    auto_start = Column(Boolean, default=True, nullable=False)  # 是否自动启动
    
    # 发现的工具信息
    tools_cache = Column(Text, nullable=True)  # 工具列表缓存（JSON格式）
    tools_count = Column(Integer, default=0)  # 工具数量
    
    # 元数据
    category = Column(String(50), nullable=True)  # 分类标签
    tags = Column(Text, nullable=True)  # 标签（JSON数组格式）
    icon = Column(String(100), nullable=True)  # 图标名称
    documentation_url = Column(String(500), nullable=True)  # 文档链接
    
    # 错误信息
    last_error = Column(Text, nullable=True)  # 最后一次错误信息
    last_connected_at = Column(DateTime, nullable=True)  # 最后连接时间
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 索引
    __table_args__ = (
        Index('idx_mcp_servers_status', 'status'),
        Index('idx_mcp_servers_enabled', 'enabled'),
        Index('idx_mcp_servers_category', 'category'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        
        args_list = None
        if self.args:
            try:
                args_list = json.loads(self.args)
            except:
                args_list = None
        
        env_dict = None
        if self.env:
            try:
                env_dict = json.loads(self.env)
            except:
                env_dict = None
        
        headers_dict = None
        if self.headers:
            try:
                headers_dict = json.loads(self.headers)
            except:
                headers_dict = None
        
        tools_list = None
        if self.tools_cache:
            try:
                tools_list = json.loads(self.tools_cache)
            except:
                tools_list = None
        
        tags_list = None
        if self.tags:
            try:
                tags_list = json.loads(self.tags)
            except:
                tags_list = None
        
        return {
            'id': str(self.id),
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'transport_type': self.transport_type,
            'command': self.command,
            'args': args_list,
            'env': env_dict,
            'url': self.url,
            'headers': headers_dict,
            'status': self.status,
            'enabled': self.enabled,
            'auto_start': self.auto_start,
            'tools': tools_list,
            'tools_count': self.tools_count,
            'category': self.category,
            'tags': tags_list,
            'icon': self.icon,
            'documentation_url': self.documentation_url,
            'last_error': self.last_error,
            'last_connected_at': self.last_connected_at.isoformat() if self.last_connected_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def get_config(self) -> dict:
        """获取服务启动配置（用于MCP客户端）"""
        import json
        
        config = {
            'name': self.name,
            'transportType': self.transport_type,
        }
        
        if self.transport_type == 'stdio':
            config['command'] = self.command
            if self.args:
                try:
                    config['args'] = json.loads(self.args)
                except:
                    config['args'] = []
            if self.env:
                try:
                    config['env'] = json.loads(self.env)
                except:
                    config['env'] = {}
        elif self.transport_type in ('sse', 'http'):
            config['url'] = self.url
            if self.headers:
                try:
                    config['headers'] = json.loads(self.headers)
                except:
                    config['headers'] = {}
        
        return config


class MCPTool(Base):
    """
    MCP 工具模型
    
    存储从 MCP 服务发现的工具信息
    """
    __tablename__ = 'mcp_tools'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(UUID(as_uuid=True), ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False)
    
    # 工具信息
    name = Column(String(200), nullable=False, index=True)  # 工具名称
    description = Column(Text, nullable=True)  # 工具描述
    input_schema = Column(Text, nullable=True)  # 输入参数schema（JSON格式）
    
    # 状态
    enabled = Column(Boolean, default=True, nullable=False)  # 是否启用
    call_count = Column(Integer, default=0)  # 调用次数
    last_called_at = Column(DateTime, nullable=True)  # 最后调用时间
    
    # 时间戳
    discovered_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 索引
    __table_args__ = (
        Index('idx_mcp_tools_server_id', 'server_id'),
        Index('idx_mcp_tools_enabled', 'enabled'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        
        schema = None
        if self.input_schema:
            try:
                schema = json.loads(self.input_schema)
            except:
                schema = None
        
        return {
            'id': str(self.id),
            'server_id': str(self.server_id),
            'name': self.name,
            'description': self.description,
            'input_schema': schema,
            'enabled': self.enabled,
            'call_count': self.call_count,
            'last_called_at': self.last_called_at.isoformat() if self.last_called_at else None,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# 导出
__all__ = ['MCPServer', 'MCPTool']
