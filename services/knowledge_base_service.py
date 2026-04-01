"""
兼容层 - 知识库管理服务

保持向后兼容，从新模块导出。
"""
from services.knowledge_base.knowledge_base_service import KnowledgeBaseService, knowledge_base_service

__all__ = ['KnowledgeBaseService', 'knowledge_base_service']
