"""
数据库模型模块（简化版）

只包含核心的会话和消息存储，用于：
1. 会话隔离
2. 上下文持久化
"""
from sqlalchemy import Column, String, Text, DateTime, Integer, Index, ForeignKey, Boolean
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
    """消息模型"""
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    
    # 关系
    session = relationship("Session", back_populates="messages")
    
    # 索引
    __table_args__ = (
        Index('idx_messages_session_timestamp', 'session_id', 'timestamp'),
    )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


# 导出所有模型
__all__ = ['Base', 'Session', 'Message', 'ContextArchive']
