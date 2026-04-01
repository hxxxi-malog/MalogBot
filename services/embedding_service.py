"""
兼容层 - 向量嵌入服务

保持向后兼容，从新模块导出。
"""
from services.rag.embedding_service import EmbeddingService, embedding_service

__all__ = ['EmbeddingService', 'embedding_service']
