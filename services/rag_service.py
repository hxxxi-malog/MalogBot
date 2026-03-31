"""
RAG检索服务

提供混合检索功能：
1. 向量检索（语义相似度）
2. BM25检索（关键词匹配）
3. 加权重排序融合
4. MMR多样性重排序
"""
import logging
from typing import List, Dict, Any, Optional
import asyncio

from sqlalchemy import text
import numpy as np

from config import Config
from services.db_manager import db_manager
from services.embedding_service import embedding_service
from services.bm25_service import bm25_service
from services.mmr_reranker import mmr_reranker
from models.knowledge_base import DocumentChunk

logger = logging.getLogger(__name__)


class RAGService:
    """RAG检索服务 - 支持混合检索和MMR多样性重排序"""

    def __init__(self):
        """初始化服务"""
        self.top_n = Config.RAG_TOP_N  # 初始检索数量
        self.top_k = Config.RAG_TOP_K  # 重排序后返回的数量
        
        # 混合检索配置
        self.enable_hybrid = getattr(Config, 'ENABLE_HYBRID_SEARCH', True)
        self.bm25_weight = getattr(Config, 'BM25_WEIGHT', 0.3)
        self.vector_weight = getattr(Config, 'VECTOR_WEIGHT', 0.7)
        
        # MMR配置
        self.enable_mmr = getattr(Config, 'ENABLE_MMR', True)
        self.mmr_alpha = getattr(Config, 'MMR_ALPHA', 0.7)
        
        logger.info(f"[RAG Service] 混合检索: {'启用' if self.enable_hybrid else '禁用'}")
        if self.enable_hybrid:
            logger.info(f"[RAG Service] 权重配置 - 向量: {self.vector_weight}, BM25: {self.bm25_weight}")
        logger.info(f"[RAG Service] MMR多样性: {'启用' if self.enable_mmr else '禁用'}")
        if self.enable_mmr:
            logger.info(f"[RAG Service] MMR alpha: {self.mmr_alpha} (相关性权重)")

    async def search(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int = None,
        top_k: int = None,
        use_mmr: bool = None
    ) -> List[Dict[str, Any]]:
        """
        在知识库中检索相关内容

        混合检索流程：
        1. 并行执行向量检索和BM25检索
        2. 对结果进行分数归一化
        3. 加权融合分数
        4. 使用重排序模型对候选结果重排
        5. MMR多样性重排序（可选）
        6. 返回 top_k 个最相关的结果

        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 初始检索数量
            top_k: 重排序后返回的数量
            use_mmr: 是否使用MMR重排序（默认使用配置）

        Returns:
            检索结果列表，每个包含 content, score, metadata 等
        """
        logger.info(f"[RAG Service] 开始检索: kb={knowledge_base_id}, query={query[:30]}...")
        
        top_n = top_n or self.top_n
        top_k = top_k or self.top_k
        
        # 判断是否使用MMR
        if use_mmr is None:
            use_mmr = self.enable_mmr

        # 判断是否启用混合检索
        if self.enable_hybrid:
            return await self._hybrid_search(query, knowledge_base_id, top_n, top_k, use_mmr)
        else:
            return await self._vector_only_search(query, knowledge_base_id, top_n, top_k, use_mmr)

    async def _hybrid_search(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int,
        top_k: int,
        use_mmr: bool = True
    ) -> List[Dict[str, Any]]:
        """
        混合检索：向量 + BM25 + MMR重排序
        
        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 初始检索数量
            top_k: 重排序后返回数量
            use_mmr: 是否使用MMR重排序
            
        Returns:
            检索结果列表
        """
        # 1. 并行获取查询向量和BM25检索
        query_embedding_task = asyncio.create_task(
            embedding_service.get_single_embedding(query)
        )
        bm25_search_task = asyncio.create_task(
            asyncio.to_thread(bm25_service.search, query, knowledge_base_id, top_n * 2)
        )
        
        # 等待结果
        query_embedding, bm25_results = await asyncio.gather(
            query_embedding_task, bm25_search_task
        )
        
        if not query_embedding:
            logger.error("[RAG Service] 无法获取查询向量")
            return []
        
        logger.info(f"[RAG Service] 获取向量成功, 维度: {len(query_embedding)}")

        # 2. 向量检索
        vector_results = await self._vector_search(query_embedding, knowledge_base_id, top_n * 2)
        logger.info(f"[RAG Service] 向量检索找到 {len(vector_results)} 个结果")
        
        # 3. BM25检索结果（已获取）
        logger.info(f"[RAG Service] BM25检索找到 {len(bm25_results)} 个结果")

        # 4. 分数归一化和加权融合
        merged_results = self._merge_and_rank(vector_results, bm25_results)
        logger.info(f"[RAG Service] 合并后有 {len(merged_results)} 个候选结果")

        if not merged_results:
            return []

        # 5. 重排序
        # 取合并后的前 top_n * 2 个候选进行重排
        candidates = merged_results[:top_n * 2]
        documents = [item['content'] for item in candidates]
        reranked = await embedding_service.rerank(query, documents, len(candidates))
        
        logger.info(f"[RAG Service] 重排序完成, 获得 {len(reranked)} 个结果")

        # 6. 组合结果（保留相关性分数）
        results = []
        for item in reranked:
            idx = item['index']
            if idx < len(candidates):
                result = candidates[idx].copy()
                result['score'] = item['relevance_score']
                # 保留原始分数信息
                result['vector_score'] = candidates[idx].get('vector_score', 0)
                result['bm25_score'] = candidates[idx].get('bm25_score', 0)
                result['hybrid_score'] = candidates[idx].get('hybrid_score', 0)
                results.append(result)

        # 7. MMR多样性重排序
        if use_mmr and len(results) > top_k:
            # 获取向量嵌入用于MMR
            results_with_embeddings = await self._add_embeddings_to_results(
                results, knowledge_base_id
            )
            
            # 使用MMR重排序
            mmr_reranker.alpha = self.mmr_alpha
            results = mmr_reranker.rerank(
                results_with_embeddings,
                relevance_key='score',
                content_key='content',
                embedding_key='embedding',
                top_k=top_k
            )
            logger.info(f"[RAG Service] MMR重排序完成, 返回 {len(results)} 个多样化结果")
        else:
            results = results[:top_k]

        return results

    async def _vector_only_search(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int,
        top_k: int,
        use_mmr: bool = True
    ) -> List[Dict[str, Any]]:
        """
        仅向量检索（原有逻辑） + MMR重排序
        
        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 初始检索数量
            top_k: 重排序后返回数量
            use_mmr: 是否使用MMR重排序
            
        Returns:
            检索结果列表
        """
        # 1. 获取查询向量
        query_embedding = await embedding_service.get_single_embedding(query)
        if not query_embedding:
            logger.error("[RAG Service] 无法获取查询向量")
            return []
        
        logger.info(f"[RAG Service] 获取向量成功, 维度: {len(query_embedding)}")

        # 2. 向量检索
        chunks = await self._vector_search(query_embedding, knowledge_base_id, top_n * 2)
        if not chunks:
            logger.warning(f"[RAG Service] 未找到相关内容, kb={knowledge_base_id}")
            return []
        
        logger.info(f"[RAG Service] 向量检索找到 {len(chunks)} 个结果")

        # 3. 重排序
        documents = [chunk['content'] for chunk in chunks]
        reranked = await embedding_service.rerank(query, documents, len(chunks))
        
        logger.info(f"[RAG Service] 重排序完成, 获得 {len(reranked)} 个结果")

        # 4. 组合结果
        results = []
        for item in reranked:
            idx = item['index']
            if idx < len(chunks):
                result = chunks[idx].copy()
                result['score'] = item['relevance_score']
                results.append(result)

        # 5. MMR多样性重排序
        if use_mmr and len(results) > top_k:
            # 获取向量嵌入用于MMR
            results_with_embeddings = await self._add_embeddings_to_results(
                results, knowledge_base_id
            )
            
            mmr_reranker.alpha = self.mmr_alpha
            results = mmr_reranker.rerank(
                results_with_embeddings,
                relevance_key='score',
                content_key='content',
                embedding_key='embedding',
                top_k=top_k
            )
            logger.info(f"[RAG Service] MMR重排序完成, 返回 {len(results)} 个多样化结果")
        else:
            results = results[:top_k]

        return results

    async def _add_embeddings_to_results(
        self,
        results: List[Dict[str, Any]],
        knowledge_base_id: str
    ) -> List[Dict[str, Any]]:
        """
        为检索结果添加向量嵌入（用于MMR计算）
        
        Args:
            results: 检索结果列表
            knowledge_base_id: 知识库ID
            
        Returns:
            包含嵌入的检索结果列表
        """
        if not results:
            return results
        
        try:
            chunk_ids = [r['id'] for r in results]
            
            with db_manager.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, embedding
                    FROM document_chunks
                    WHERE id = ANY(:ids)
                    AND embedding IS NOT NULL
                """), {'ids': chunk_ids})
                
                # 构建ID到嵌入的映射
                embedding_map = {}
                for row in result.fetchall():
                    chunk_id = str(row[0])
                    embedding = row[1]
                    if embedding is not None:
                        if hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                            embedding_map[chunk_id] = list(embedding)
                        else:
                            embedding_map[chunk_id] = embedding
                
                # 添加嵌入到结果
                for r in results:
                    r['embedding'] = embedding_map.get(r['id'])
                    
        except Exception as e:
            logger.error(f"[RAG Service] 获取嵌入失败: {str(e)}")
        
        return results

    def _merge_and_rank(
        self,
        vector_results: List[Dict[str, Any]],
        bm25_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        合并向量检索和BM25检索结果，并进行加权排序
        
        Args:
            vector_results: 向量检索结果
            bm25_results: BM25检索结果
            
        Returns:
            合并后的结果列表
        """
        # 分数归一化
        vector_scores = self._normalize_scores([r.get('score', 0) for r in vector_results])
        bm25_scores = self._normalize_scores([r.get('score', 0) for r in bm25_results])
        
        # 更新归一化后的分数
        for i, result in enumerate(vector_results):
            result['vector_score'] = vector_scores[i]
            result['bm25_score'] = 0.0
        
        for i, result in enumerate(bm25_results):
            result['bm25_score'] = bm25_scores[i]
            if 'vector_score' not in result:
                result['vector_score'] = 0.0
        
        # 按ID合并结果
        merged = {}
        
        # 添加向量检索结果
        for result in vector_results:
            chunk_id = result['id']
            merged[chunk_id] = result.copy()
        
        # 合并BM25结果
        for result in bm25_results:
            chunk_id = result['id']
            if chunk_id in merged:
                # 已存在，更新分数
                merged[chunk_id]['bm25_score'] = result['bm25_score']
            else:
                # 新结果
                merged[chunk_id] = result.copy()
        
        # 计算混合分数
        for chunk_id, result in merged.items():
            result['hybrid_score'] = (
                self.vector_weight * result['vector_score'] +
                self.bm25_weight * result['bm25_score']
            )
        
        # 按混合分数排序
        sorted_results = sorted(
            merged.values(),
            key=lambda x: x['hybrid_score'],
            reverse=True
        )
        
        return sorted_results

    def _normalize_scores(self, scores: List[float]) -> List[float]:
        """
        分数归一化（Min-Max归一化）
        
        Args:
            scores: 原始分数列表
            
        Returns:
            归一化后的分数列表（0-1范围）
        """
        if not scores:
            return []
        
        min_score = min(scores)
        max_score = max(scores)
        
        if max_score == min_score:
            # 所有分数相同
            return [0.5] * len(scores)
        
        return [(s - min_score) / (max_score - min_score) for s in scores]

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
