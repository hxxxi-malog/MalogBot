"""
RAG检索服务

提供向量检索和重排序功能
"""
import logging
from typing import List, Dict, Any, Optional
import asyncio

from sqlalchemy import text
import numpy as np

from config import Config
from services.db_manager import db_manager
from services.embedding_service import embedding_service
from models.knowledge_base import DocumentChunk

logger = logging.getLogger(__name__)


class RAGService:
    """RAG检索服务"""

    def __init__(self):
        """初始化服务"""
        self.top_n = Config.RAG_TOP_N  # 初始检索数量
        self.top_k = Config.RAG_TOP_K  # 重排序后返回的数量

    async def search(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int = None,
        top_k: int = None
    ) -> List[Dict[str, Any]]:
        """
        在知识库中检索相关内容

        流程：
        1. 将查询向量化
        2. 向量检索获取 top_n 个结果
        3. 使用重排序模型对结果进行重排序
        4. 返回 top_k 个最相关的结果

        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 初始检索数量
            top_k: 重排序后返回的数量

        Returns:
            检索结果列表，每个包含 content, score, metadata 等
        """
        logger.info(f"[RAG Service] 开始检索: kb={knowledge_base_id}, query={query[:30]}...")
        
        top_n = top_n or self.top_n
        top_k = top_k or self.top_k

        # 1. 获取查询向量
        query_embedding = await embedding_service.get_single_embedding(query)
        if not query_embedding:
            logger.error("[RAG Service] 无法获取查询向量")
            return []
        
        logger.info(f"[RAG Service] 获取向量成功, 维度: {len(query_embedding)}")

        # 2. 向量检索
        chunks = await self._vector_search(query_embedding, knowledge_base_id, top_n)
        if not chunks:
            logger.warning(f"[RAG Service] 未找到相关内容, kb={knowledge_base_id}")
            return []
        
        logger.info(f"[RAG Service] 向量检索找到 {len(chunks)} 个结果")

        # 3. 重排序
        documents = [chunk['content'] for chunk in chunks]
        reranked = await embedding_service.rerank(query, documents, top_k)
        
        logger.info(f"[RAG Service] 重排序完成, 返回 {len(reranked)} 个结果")

        # 4. 组合结果
        results = []
        for item in reranked:
            idx = item['index']
            if idx < len(chunks):
                result = chunks[idx].copy()
                result['score'] = item['relevance_score']
                results.append(result)

        return results

    async def _vector_search(
        self,
        query_embedding: List[float],
        knowledge_base_id: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        向量检索

        使用 PostgreSQL 的向量相似度搜索

        Args:
            query_embedding: 查询向量
            knowledge_base_id: 知识库ID
            limit: 返回数量

        Returns:
            检索结果列表
        """
        try:
            with db_manager.get_session() as session:
                # 获取该知识库的所有分块
                logger.info(f"[RAG Service] 查询知识库分块: kb_id={knowledge_base_id}")
                chunks = session.query(DocumentChunk).filter_by(
                    knowledge_base_id=knowledge_base_id
                ).all()
                
                logger.info(f"[RAG Service] 找到 {len(chunks)} 个分块")

                if not chunks:
                    return []

                # 计算相似度
                chunk_scores = []
                query_vec = np.array(query_embedding)
                query_norm = np.linalg.norm(query_vec)

                for chunk in chunks:
                    if chunk.embedding:
                        chunk_vec = np.array(chunk.embedding)
                        chunk_norm = np.linalg.norm(chunk_vec)

                        if chunk_norm > 0 and query_norm > 0:
                            # 余弦相似度
                            similarity = np.dot(query_vec, chunk_vec) / (query_norm * chunk_norm)
                            chunk_scores.append((chunk, similarity))
                    else:
                        logger.warning(f"[RAG Service] 分块 {chunk.id} 没有向量")

                logger.info(f"[RAG Service] 计算了 {len(chunk_scores)} 个分块的相似度")

                # 按相似度降序排序
                chunk_scores.sort(key=lambda x: x[1], reverse=True)

                # 返回 top_n 结果
                results = []
                for chunk, score in chunk_scores[:limit]:
                    results.append({
                        'id': str(chunk.id),
                        'content': chunk.content,
                        'score': float(score),
                        'metadata': chunk.chunk_metadata,
                        'document_id': str(chunk.document_id)
                    })

                return results

        except Exception as e:
            logger.error(f"Vector search error: {str(e)}")
            return []

    async def search_with_context(
        self,
        query: str,
        knowledge_base_id: str,
        max_context_length: int = 2000
    ) -> str:
        """
        检索并构建上下文

        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            max_context_length: 最大上下文长度

        Returns:
            构建好的上下文字符串
        """
        results = await self.search(query, knowledge_base_id)

        if not results:
            return ""

        context_parts = []
        current_length = 0

        for i, result in enumerate(results):
            content = result['content']
            if current_length + len(content) > max_context_length:
                break

            context_parts.append(f"[片段{i+1}]\n{content}\n")
            current_length += len(content)

        return "\n".join(context_parts)


# 创建全局实例
rag_service = RAGService()

__all__ = ['RAGService', 'rag_service']
