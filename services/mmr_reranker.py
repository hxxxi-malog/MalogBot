"""
兼容层 - MMR重排序服务

保持向后兼容，从新模块导出。
"""
from services.rag.mmr_reranker import MMRReranker, mmr_reranker

__all__ = ['MMRReranker', 'mmr_reranker']
