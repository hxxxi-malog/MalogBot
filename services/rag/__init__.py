"""
RAG检索模块

提供检索增强生成功能，包括：
1. 向量检索（embedding_service）
2. BM25检索（bm25_service）
3. 混合检索（rag_service）
4. MMR重排序（mmr_reranker）
5. 查询优化（query_optimizer）
6. 增强版RAG服务（enhanced_rag_service）
"""
from services.rag.rag_service import RAGService, rag_service
from services.rag.embedding_service import EmbeddingService, embedding_service
from services.rag.bm25_service import BM25Service, bm25_service
from services.rag.mmr_reranker import MMRReranker, mmr_reranker
from services.rag.query_optimizer import (
    QueryOptimizer,
    QueryOptimizationConfig,
    QueryComplexity,
    OptimizedQuery,
    CoreferenceResolver,
    StepBackGenerator,
    QuestionDecomposer,
    MultiQueryRewriter,
    ResultIntegrator,
    default_config
)
from services.rag.enhanced_rag_service import (
    EnhancedRAGService,
    EnhancedSearchResult,
    get_enhanced_rag_service
)

__all__ = [
    # 基础服务
    'RAGService',
    'rag_service',
    'EmbeddingService',
    'embedding_service',
    'BM25Service',
    'bm25_service',
    'MMRReranker',
    'mmr_reranker',
    # 查询优化
    'QueryOptimizer',
    'QueryOptimizationConfig',
    'QueryComplexity',
    'OptimizedQuery',
    'CoreferenceResolver',
    'StepBackGenerator',
    'QuestionDecomposer',
    'MultiQueryRewriter',
    'ResultIntegrator',
    'default_config',
    # 增强版 RAG
    'EnhancedRAGService',
    'EnhancedSearchResult',
    'get_enhanced_rag_service'
]
