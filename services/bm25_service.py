"""
兼容层 - BM25检索服务

保持向后兼容，从新模块导出。
"""
from services.rag.bm25_service import BM25Service, bm25_service

__all__ = ['BM25Service', 'bm25_service']
