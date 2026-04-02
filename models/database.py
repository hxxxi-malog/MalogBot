"""
数据库模型模块（简化版）

只包含核心的会话和消息存储，用于：
1. 会话隔离
2. 上下文持久化
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Index, ForeignKey, Boolean, Float, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

Base = declarative_base()


class Session(Base):
    """会话模型"""
    __tablename__ = 'sessions'
    
    session_id = Column(String(100), primary_key=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    web_search_enabled = Column(Boolean, default=False, nullable=False)  # 是否启用联网搜索
    knowledge_base_id = Column(String(100), nullable=True)  # 当前选中的知识库ID，None表示不使用知识库
    
    # 关系
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    
    def to_dict(self):
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'web_search_enabled': self.web_search_enabled if self.web_search_enabled is not None else False,
            'knowledge_base_id': self.knowledge_base_id
        }


class ContextArchive(Base):
    """上下文归档模型
    
    用于存储压缩前的完整对话历史，支持恢复。
    """
    __tablename__ = 'context_archives'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    archive_id = Column(String(100), unique=True, nullable=False, index=True)  # 归档唯一标识
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=False, index=True)  # 所属会话
    messages = Column(Text, nullable=False)  # JSON 格式的消息列表
    file_path = Column(String(500), nullable=True)  # 归档文件路径（磁盘备份）
    message_count = Column(Integer, default=0)  # 归档的消息数量
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'archive_id': self.archive_id,
            'session_id': self.session_id,
            'message_count': self.message_count,
            'file_path': self.file_path,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Message(Base):
    """消息模型
    
    支持完整的对话历史存储，包括：
    - user: 用户消息
    - assistant: 助手回复（可能包含 tool_calls）
    - system: 系统消息
    - tool: 工具调用结果
    """
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    
    # 工具调用相关字段（用于 tool 角色和 assistant 的 tool_calls）
    tool_call_id = Column(String(100), nullable=True)  # 用于 tool 角色：对应的工具调用ID
    tool_calls = Column(Text, nullable=True)  # 用于 assistant 角色：JSON 格式的工具调用列表
    tool_name = Column(String(100), nullable=True)  # 工具名称（用于 tool 角色）
    
    # 关系
    session = relationship("Session", back_populates="messages")
    
    # 索引
    __table_args__ = (
        Index('idx_messages_session_timestamp', 'session_id', 'timestamp'),
    )
    
    def to_dict(self):
        """转换为字典"""
        result = {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
        
        # 添加工具调用相关字段
        if self.tool_call_id:
            result['tool_call_id'] = self.tool_call_id
        if self.tool_name:
            result['tool_name'] = self.tool_name
        if self.tool_calls:
            import json
            try:
                result['tool_calls'] = json.loads(self.tool_calls)
            except:
                result['tool_calls'] = self.tool_calls
        
        return result



class LongTermMemory(Base):
    """长期记忆模型
    
    用于存储从对话中提取的关键信息，支持向量检索。
    这些记忆可以在后续会话中通过语义搜索被检索出来。
    
    长文本记忆会被分块存储，每个分块通过 parent_id 关联到原始记忆组。
    """
    __tablename__ = 'long_term_memories'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=True, index=True)  # 来源会话，NULL表示全局记忆
    memory_type = Column(String(50), nullable=False, index=True)  # 记忆类型：fact, decision, preference, action, summary
    content = Column(Text, nullable=False)  # 记忆内容
    embedding = Column(Text, nullable=True)  # 向量嵌入（JSON格式存储，兼容性更好）
    source_archive_id = Column(String(100), nullable=True)  # 来源归档ID
    importance = Column(Float, default=0.5)  # 重要性分数 0-1
    access_count = Column(Integer, default=0)  # 访问次数
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 分块相关字段
    parent_id = Column(Integer, nullable=True, index=True)  # 父记忆ID（用于分块关联，NULL表示原始记忆或单条记忆）
    chunk_index = Column(Integer, default=0)  # 分块索引（0表示原始记忆或第一个分块）
    total_chunks = Column(Integer, default=1)  # 总分块数（1表示未分块）
    
    # 元数据
    tags = Column(Text, nullable=True)  # 标签（JSON数组格式）
    metadata_json = Column(Text, nullable=True)  # 其他元数据（JSON格式）
    
    def to_dict(self):
        """转换为字典"""
        import json
        return {
            'id': self.id,
            'session_id': self.session_id,
            'memory_type': self.memory_type,
            'content': self.content,
            'importance': self.importance,
            'access_count': self.access_count,
            'source_archive_id': self.source_archive_id,
            'parent_id': self.parent_id,
            'chunk_index': self.chunk_index,
            'total_chunks': self.total_chunks,
            'tags': json.loads(self.tags) if self.tags else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ConversationJournal(Base):
    """对话日志模型
    
    用于存储原始对话消息的JSONL格式记录，支持上下文注入和恢复。
    """
    __tablename__ = 'conversation_journals'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=False, index=True)
    journal_file = Column(String(500), nullable=False)  # JSONL文件路径
    message_count = Column(Integer, default=0)  # 消息数量
    token_count = Column(Integer, default=0)  # 估算的token数量
    start_time = Column(DateTime, nullable=True)  # 日志开始时间
    end_time = Column(DateTime, nullable=True)  # 日志结束时间
    is_active = Column(Boolean, default=True)  # 是否是当前活跃的日志
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'session_id': self.session_id,
            'journal_file': self.journal_file,
            'message_count': self.message_count,
            'token_count': self.token_count,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# 导出所有模型
__all__ = ['Base', 'Session', 'Message', 'ContextArchive', 'LongTermMemory', 'ConversationJournal']
