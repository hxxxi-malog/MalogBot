"""
知识库管理模块

提供知识库和文档管理功能：
1. 知识库管理（knowledge_base_service）
2. 文档处理（document_service）
"""
from services.knowledge_base.knowledge_base_service import KnowledgeBaseService, knowledge_base_service
from services.knowledge_base.document_service import DocumentService, document_service

__all__ = [
    'KnowledgeBaseService',
    'knowledge_base_service',
    'DocumentService',
    'document_service'
]
