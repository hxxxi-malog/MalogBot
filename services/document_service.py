"""
兼容层 - 文档处理服务

保持向后兼容，从新模块导出。
"""
from services.knowledge_base.document_service import DocumentService, document_service

__all__ = ['DocumentService', 'document_service']
