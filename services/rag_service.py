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
        向量检索 - 使用 HNSW 索引加速

        使用 PostgreSQL pgvector 的向量相似度搜索

        Args:
            query_embedding: 查询向量
            knowledge_base_id: 知识库ID
            limit: 返回数量

        Returns:
            检索结果列表
        """
        try:
            # 将查询向量转换为字符串格式
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            with db_manager.engine.connect() as conn:
                # 使用 pgvector 的余弦距离搜索
                # HNSW 索引会自动加速此查询
                # 注意：使用字符串格式化而非参数绑定来处理向量
                result = conn.execute(text(f"""
                    SELECT 
                        id, document_id, content, chunk_metadata,
                        1 - (embedding <=> '{embedding_str}'::vector) as similarity
                    FROM document_chunks
                    WHERE knowledge_base_id = '{knowledge_base_id}'
                    AND embedding IS NOT NULL
                    ORDER BY embedding <=> '{embedding_str}'::vector
                    LIMIT {limit}
                """))
                
                rows = result.fetchall()
                logger.info(f"[RAG Service] HNSW 检索找到 {len(rows)} 个结果")
                
                results = []
                for row in rows:
                    results.append({
                        'id': str(row[0]),
                        'content': row[2],
                        'score': float(row[4]) if row[4] else 0.0,
                        'metadata': row[3],
                        'document_id': str(row[1])
                    })
                
                return results

        except Exception as e:
            logger.error(f"Vector search error: {str(e)}")
            # 回退到原始方法
            return await self._vector_search_fallback(query_embedding, knowledge_base_id, limit)
    
    async def _vector_search_fallback(
        self,
        query_embedding: List[float],
        knowledge_base_id: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        向量检索回退方法（Python 计算）

        当 pgvector 搜索失败时使用

        Args:
            query_embedding: 查询向量
            knowledge_base_id: 知识库ID
            limit: 返回数量

        Returns:
            检索结果列表
        """
        try:
            with db_manager.engine.connect() as conn:
                # 使用原生 SQL 查询获取分块
                result = conn.execute(text("""
                    SELECT id, document_id, content, chunk_metadata, embedding
                    FROM document_chunks
                    WHERE knowledge_base_id = :kb_id
                    AND embedding IS NOT NULL
                """), {'kb_id': knowledge_base_id})
                
                rows = result.fetchall()
                logger.info(f"[RAG Service] 回退方法找到 {len(rows)} 个分块")

                if not rows:
                    return []

                # 计算相似度
                chunk_scores = []
                query_vec = np.array(query_embedding)
                query_norm = np.linalg.norm(query_vec)

                for row in rows:
                    chunk_embedding = row[4]  # embedding 列
                    if chunk_embedding is not None:
                        # 处理不同类型的 embedding 数据
                        if hasattr(chunk_embedding, '__iter__') and not isinstance(chunk_embedding, str):
                            chunk_vec = np.array(list(chunk_embedding))
                        else:
                            continue
                            
                        chunk_norm = np.linalg.norm(chunk_vec)

                        if chunk_norm > 0 and query_norm > 0:
                            # 余弦相似度
                            similarity = np.dot(query_vec, chunk_vec) / (query_norm * chunk_norm)
                            chunk_scores.append((row, similarity))

                logger.info(f"[RAG Service] 计算了 {len(chunk_scores)} 个分块的相似度")

                # 按相似度降序排序
                chunk_scores.sort(key=lambda x: x[1], reverse=True)

                # 返回 top_n 结果
                results = []
                for row, score in chunk_scores[:limit]:
                    results.append({
                        'id': str(row[0]),
                        'content': row[2],
                        'score': float(score),
                        'metadata': row[3],
                        'document_id': str(row[1])
                    })

                return results

        except Exception as e:
            logger.error(f"Vector search fallback error: {str(e)}")
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
