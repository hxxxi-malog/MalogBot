"""
知识库相关数据库模型

包含：
1. KnowledgeBase - 知识库模型
2. Document - 文档模型
3. DocumentChunk - 文档分块模型
"""
import uuid
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, Index, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy import Float

# 导入 pgvector 的 Vector 类型
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None

from models.database import Base


class KnowledgeBase(Base):
    """知识库模型"""
    __tablename__ = 'knowledge_bases'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    user_id = Column(String(100), nullable=True)  # 用于用户隔离，暂时可为空
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    document_count = Column(Integer, default=0, nullable=False)
    chunk_count = Column(Integer, default=0, nullable=False)

    # 关系
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")

    def to_dict(self):
        """转换为字典"""
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'document_count': self.document_count,
            'chunk_count': self.chunk_count
        }


class Document(Base):
    """文档模型"""
    __tablename__ = 'documents'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=True)  # 文件存储路径
    file_type = Column(String(50), nullable=True)  # 文件类型：txt, pdf, md 等
    file_size = Column(Integer, default=0)  # 文件大小（字节）
    content = Column(Text, nullable=True)  # 原始文本内容
    chunk_count = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default='pending', nullable=False)  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)  # 处理失败时的错误信息
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index('idx_documents_kb_id', 'knowledge_base_id'),
    )

    def to_dict(self):
        """转换为字典"""
        return {
            'id': str(self.id),
            'knowledge_base_id': str(self.knowledge_base_id),
            'filename': self.filename,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'chunk_count': self.chunk_count,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class DocumentChunk(Base):
    """文档分块模型"""
    __tablename__ = 'document_chunks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    knowledge_base_id = Column(UUID(as_uuid=True), ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False)
    chunk_index = Column(Integer, nullable=False)  # 分块在文档中的索引
    content = Column(Text, nullable=False)  # 分块内容
    chunk_metadata = Column(Text, nullable=True)  # JSON 格式的元数据（使用 chunk_metadata 避免与 SQLAlchemy 的 metadata 冲突）
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # embedding 列单独处理，不在模型中定义
    # 使用原生 SQL 进行向量操作，避免 psycopg2 类型问题

    # 关系
    document = relationship("Document", back_populates="chunks")

    # 索引
    __table_args__ = (
        Index('idx_chunks_document_id', 'document_id'),
        Index('idx_chunks_kb_id', 'knowledge_base_id'),
    )

    def to_dict(self):
        """转换为字典"""
        return {
            'id': str(self.id),
            'document_id': str(self.document_id),
            'knowledge_base_id': str(self.knowledge_base_id),
            'chunk_index': self.chunk_index,
            'content': self.content,
            'metadata': self.chunk_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# 导出所有模型
__all__ = ['KnowledgeBase', 'Document', 'DocumentChunk']
