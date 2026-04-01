"""
兼容层 - RAG检索服务

保持向后兼容，从新模块导出。
"""
from services.rag.rag_service import RAGService, rag_service

__all__ = ['RAGService', 'rag_service']
