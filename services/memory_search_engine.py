"""
Agent 记忆检索引擎

根据 agent-self-evolution-knowledge-base-design.md 文档实现阶段二检索引擎：
1. 混合检索（向量相似度 + BM25关键词）
2. MMR 多样性重排
3. 时间衰减机制
4. LRU 时间刷新机制
5. 统一检索接口

检索流程：
向量相似度 (70%) + BM25关键词 (30%) → 混合召回 → MMR去重 → 时间衰减加权 → 最终结果
"""
import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text

from models.agent_knowledge import KnowledgeItem
from services.agent_knowledge_repository import knowledge_item_repo
from services.rag.mmr_reranker import mmr_reranker
from services.rag.embedding_service import embedding_service
from services.db_manager import db_manager

logger = logging.getLogger(__name__)


@dataclass
class SearchConfig:
    """检索配置"""
    # 混合检索权重
    vector_weight: float = 0.7  # 向量相似度权重
    bm25_weight: float = 0.3   # BM25关键词权重
    
    # MMR参数
    mmr_alpha: float = 0.7     # MMR相关性权重
    use_mmr: bool = True       # 是否启用MMR
    
    # 时间衰减参数
    time_decay_lambda: float = 0.02  # 衰减速率，约50天衰减到0.37
    use_time_decay: bool = True      # 是否启用时间衰减
    
    # 质量门槛
    min_hybrid_score: float = 0.3    # 最低混合分数
    min_importance: float = 0.5      # 最低重要性
    
    # 检索数量
    recall_multiplier: int = 3       # 召回倍数（相对于top_k）
    max_recall: int = 100            # 最大召回数量
    min_recall: int = 10             # 最小召回数量
    
    # 标签过滤
    filter_tags: Optional[List[str]] = None
    filter_item_types: Optional[List[str]] = None
    exclude_expired: bool = True     # 是否排除过期记忆


@dataclass
class SearchResult:
    """检索结果"""
    id: int
    content: str
    item_type: str
    source_file_type: Optional[str]
    importance: float
    tags: List[str]
    source_id: Optional[str] = None  # 添加source_id字段
    
    # 分数
    vector_score: float = 0.0
    bm25_score: float = 0.0
    hybrid_score: float = 0.0
    time_decay_factor: float = 1.0
    final_score: float = 0.0
    
    # 元数据
    created_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0
    
    # 排名
    mmr_rank: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'content': self.content,
            'item_type': self.item_type,
            'source_file_type': self.source_file_type,
            'source_id': self.source_id,
            'importance': self.importance,
            'tags': self.tags,
            'vector_score': self.vector_score,
            'bm25_score': self.bm25_score,
            'hybrid_score': self.hybrid_score,
            'time_decay_factor': self.time_decay_factor,
            'final_score': self.final_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            'access_count': self.access_count,
            'mmr_rank': self.mmr_rank
        }


class TimeDecayCalculator:
    """时间衰减计算器
    
    衰减公式：decay = e^(-λ × days_ago)
    其中：
    - λ 是衰减系数，控制衰减速度
    - days_ago 是距离今天的天数
    
    效果：
    - λ=0.02: 约50天衰减到0.37，约100天衰减到0.14
    - λ=0.01: 约100天衰减到0.37
    """
    
    def __init__(self, decay_lambda: float = 0.02):
        """
        初始化时间衰减计算器
        
        Args:
            decay_lambda: 衰减速率，默认0.02
        """
        self.decay_lambda = decay_lambda
        logger.info(f"[TimeDecay] 初始化时间衰减计算器, λ={decay_lambda}")
    
    def calculate_decay(
        self,
        last_accessed_at: Optional[datetime],
        created_at: Optional[datetime],
        current_time: Optional[datetime] = None
    ) -> float:
        """
        计算时间衰减因子
        
        优先使用 last_accessed_at（LRU刷新），若为空则使用 created_at
        
        Args:
            last_accessed_at: 最后访问时间
            created_at: 创建时间
            current_time: 当前时间，默认为当前时间
            
        Returns:
            衰减因子，范围 (0, 1]
        """
        if current_time is None:
            current_time = datetime.now()
        
        # 优先使用最后访问时间
        reference_time = last_accessed_at or created_at
        
        if reference_time is None:
            return 1.0  # 无法计算时间，返回无衰减
        
        # 计算天数差
        if isinstance(reference_time, str):
            reference_time = datetime.fromisoformat(reference_time.replace('Z', '+00:00'))
        
        delta = current_time - reference_time
        days_ago = delta.total_seconds() / (24 * 3600)
        
        # 计算衰减因子
        decay = math.exp(-self.decay_lambda * max(0, days_ago))
        
        return decay
    
    def calculate_with_heat(
        self,
        last_accessed_at: Optional[datetime],
        created_at: Optional[datetime],
        access_count: int,
        current_time: Optional[datetime] = None,
        heat_weight: float = 0.2
    ) -> float:
        """
        计算带热度的衰减因子
        
        公式：decay × (1 + heat_weight × min(access_count / 10, 1))
        
        Args:
            last_accessed_at: 最后访问时间
            created_at: 创建时间
            access_count: 访问次数
            current_time: 当前时间
            heat_weight: 热度加成权重
            
        Returns:
            衰减因子，范围 (0, 1 + heat_weight]
        """
        base_decay = self.calculate_decay(last_accessed_at, created_at, current_time)
        
        # 热度加成：访问次数越多，权重越高（上限100%加成）
        heat_factor = 1.0 + heat_weight * min(access_count / 10.0, 1.0)
        
        return base_decay * heat_factor


class MemorySearchEngine:
    """
    记忆检索引擎
    
    整合混合检索、MMR重排、时间衰减、LRU刷新
    """
    
    def __init__(self, config: SearchConfig = None):
        """
        初始化检索引擎
        
        Args:
            config: 检索配置
        """
        self.config = config or SearchConfig()
        self.time_decay = TimeDecayCalculator(self.config.time_decay_lambda)
        
        logger.info("[MemorySearchEngine] 记忆检索引擎初始化完成")
        logger.info(f"  向量权重: {self.config.vector_weight}")
        logger.info(f"  BM25权重: {self.config.bm25_weight}")
        logger.info(f"  MMR alpha: {self.config.mmr_alpha}")
        logger.info(f"  时间衰减: {'启用' if self.config.use_time_decay else '禁用'}")
    
    async def search(
        self,
        query: str,
        session: DBSession,
        top_k: int = 10,
        config: SearchConfig = None
    ) -> List[SearchResult]:
        """
        统一检索接口
        
        检索流程：
        1. 向量检索 + BM25检索（并行）
        2. 混合加权合并
        3. 质量门槛过滤
        4. MMR多样性重排
        5. 时间衰减加权
        6. LRU刷新（更新访问记录）
        
        Args:
            query: 查询文本
            session: 数据库会话
            top_k: 返回数量
            config: 检索配置（可选，覆盖默认配置）
            
        Returns:
            检索结果列表
        """
        import time
        start_time = time.time()
        
        cfg = config or self.config
        
        logger.info(f"[MemorySearchEngine] 开始检索: query='{query[:50]}...', top_k={top_k}")
        
        # Step 1: 获取查询向量
        query_embedding = await embedding_service.get_single_embedding(query)
        if query_embedding is None:
            logger.error("[MemorySearchEngine] 获取查询向量失败")
            return []
        
        # Step 2: 计算召回量
        recall_k = self._calculate_recall_k(top_k, cfg)
        logger.info(f"[MemorySearchEngine] 召回量: {recall_k}")
        
        # Step 3: 混合检索
        hybrid_results = await self._hybrid_search(
            query=query,
            query_embedding=query_embedding,
            session=session,
            top_k=recall_k,
            config=cfg
        )
        
        logger.info(f"[MemorySearchEngine] 混合检索返回 {len(hybrid_results)} 条结果")
        
        if not hybrid_results:
            return []
        
        # Step 4: 质量门槛过滤
        filtered_results = self._apply_quality_threshold(hybrid_results, cfg)
        logger.info(f"[MemorySearchEngine] 质量过滤后剩余 {len(filtered_results)} 条")
        
        if not filtered_results:
            return []
        
        # Step 5: MMR多样性重排
        if cfg.use_mmr and len(filtered_results) > top_k:
            mmr_results = self._apply_mmr(filtered_results, top_k, cfg)
            logger.info(f"[MemorySearchEngine] MMR重排后 {len(mmr_results)} 条")
        else:
            mmr_results = filtered_results[:top_k]
        
        # Step 6: 时间衰减加权
        if cfg.use_time_decay:
            final_results = self._apply_time_decay(mmr_results, cfg)
        else:
            final_results = mmr_results
            for r in final_results:
                r.final_score = r.hybrid_score
        
        # Step 7: 按最终分数排序
        final_results.sort(key=lambda x: x.final_score, reverse=True)
        
        # Step 8: LRU刷新
        self._refresh_access(final_results, session)
        
        # Step 9: 记录检索指标
        elapsed_ms = (time.time() - start_time) * 1000
        self._record_retrieval_metrics(
            query=query,
            top_k=top_k,
            results=final_results,
            elapsed_ms=elapsed_ms
        )
        
        logger.info(f"[MemorySearchEngine] 检索完成，返回 {len(final_results)} 条结果")
        
        return final_results
    
    def _calculate_recall_k(self, top_k: int, config: SearchConfig) -> int:
        """
        计算召回量
        
        召回量 = top_k × recall_multiplier，但限制在 [min_recall, max_recall] 范围内
        """
        recall_k = top_k * config.recall_multiplier
        recall_k = max(config.min_recall, min(recall_k, config.max_recall))
        return recall_k
    
    async def _hybrid_search(
        self,
        query: str,
        query_embedding: List[float],
        session: DBSession,
        top_k: int,
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        混合检索（向量 + BM25）
        
        Args:
            query: 查询文本
            query_embedding: 查询向量
            session: 数据库会话
            top_k: 召回数量
            config: 检索配置
            
        Returns:
            混合检索结果
        """
        # 构建过滤条件
        filters = self._build_filters(config)
        
        # 向量检索
        vector_results = await self._vector_search(
            query_embedding=query_embedding,
            session=session,
            top_k=top_k,
            filters=filters
        )
        
        # BM25检索
        bm25_results = await self._bm25_search(
            query=query,
            session=session,
            top_k=top_k,
            filters=filters
        )
        
        # 合并结果
        merged = self._merge_results(vector_results, bm25_results, config)
        
        return merged
    
    async def _vector_search(
        self,
        query_embedding: List[float],
        session: DBSession,
        top_k: int,
        filters: Dict[str, Any]
    ) -> List[Dict]:
        """向量相似度检索"""
        try:
            # 转换向量为PostgreSQL格式（使用与存储一致的格式）
            vec_str = '[' + ','.join(f'{x}' for x in query_embedding) + ']'
            
            logger.info(f"[VectorSearch] 查询向量前5个值: {query_embedding[:5]}")
            
            # 禁用索引扫描（IVFFlat索引在数据量较少时可能工作不正常）
            # 使用原始连接执行SET命令
            connection = session.connection()
            connection.execute(text("SET enable_indexscan = off"))
            
            # 构建SQL
            sql = self._build_vector_search_sql(vec_str, top_k, filters)
            
            logger.info(f"[VectorSearch] 执行检索...")
            
            result = connection.execute(text(sql))
            
            results = []
            for row in result:
                results.append({
                    'id': row[0],
                    'content': row[1],
                    'item_type': row[2],
                    'source_file_type': row[3],
                    'importance': row[4],
                    'tags': row[5] or [],
                    'created_at': row[6],
                    'last_accessed_at': row[7],
                    'access_count': row[8] or 0,
                    'source_id': row[9],  # 添加source_id
                    'vector_score': float(row[10])  # 相似度
                })
            
            logger.info(f"[VectorSearch] 返回 {len(results)} 条结果")
            return results
            
        except Exception as e:
            logger.error(f"[VectorSearch] 检索失败: {e}")
            return []
    
    async def _bm25_search(
        self,
        query: str,
        session: DBSession,
        top_k: int,
        filters: Dict[str, Any]
    ) -> List[Dict]:
        """BM25关键词检索"""
        try:
            sql = self._build_bm25_search_sql(query, top_k, filters)
            
            result = session.execute(text(sql), {'query': query, 'limit': top_k})
            
            results = []
            for row in result:
                results.append({
                    'id': row[0],
                    'content': row[1],
                    'item_type': row[2],
                    'source_file_type': row[3],
                    'importance': row[4],
                    'tags': row[5] or [],
                    'created_at': row[6],
                    'last_accessed_at': row[7],
                    'access_count': row[8] or 0,
                    'source_id': row[9],  # 添加source_id
                    'bm25_score': float(row[10]) if row[10] else 0.0  # BM25分数
                })
            
            logger.info(f"[BM25Search] 返回 {len(results)} 条结果")
            return results
            
        except Exception as e:
            logger.error(f"[BM25Search] 检索失败: {e}")
            return []
    
    def _build_filters(self, config: SearchConfig) -> Dict[str, Any]:
        """构建过滤条件"""
        filters = {
            'exclude_expired': config.exclude_expired,
            'filter_tags': config.filter_tags,
            'filter_item_types': config.filter_item_types
        }
        return filters
    
    def _build_vector_search_sql(
        self,
        vec_str: str,
        top_k: int,
        filters: Dict[str, Any]
    ) -> str:
        """构建向量检索SQL"""
        where_clauses = ["embedding IS NOT NULL"]
        
        if filters.get('exclude_expired', True):
            where_clauses.append("is_expired = FALSE")
        
        if filters.get('filter_item_types'):
            types = "','".join(filters['filter_item_types'])
            where_clauses.append(f"item_type IN ('{types}')")
        
        if filters.get('filter_tags'):
            tags = "','".join(filters['filter_tags'])
            where_clauses.append(f"tags && ARRAY['{tags}']")
        
        where_clause = " AND ".join(where_clauses)
        
        return f"""
            SELECT id, content, item_type, source_file_type, importance, 
                   tags, created_at, last_accessed_at, access_count, source_id,
                   1 - (embedding <=> '{vec_str}'::vector) as similarity
            FROM knowledge_items
            WHERE {where_clause}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {top_k}
        """
    
    def _build_bm25_search_sql(
        self,
        query: str,
        top_k: int,
        filters: Dict[str, Any]
    ) -> str:
        """构建BM25检索SQL"""
        where_clauses = [
            "to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)"
        ]
        
        if filters.get('exclude_expired', True):
            where_clauses.append("is_expired = FALSE")
        
        if filters.get('filter_item_types'):
            types = "','".join(filters['filter_item_types'])
            where_clauses.append(f"item_type IN ('{types}')")
        
        if filters.get('filter_tags'):
            tags = "','".join(filters['filter_tags'])
            where_clauses.append(f"tags && ARRAY['{tags}']")
        
        where_clause = " AND ".join(where_clauses)
        
        return f"""
            SELECT id, content, item_type, source_file_type, importance, tags,
                   created_at, last_accessed_at, access_count, source_id,
                   ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) as score
            FROM knowledge_items
            WHERE {where_clause}
            ORDER BY score DESC
            LIMIT :limit
        """
    
    def _merge_results(
        self,
        vector_results: List[Dict],
        bm25_results: List[Dict],
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        合并向量和BM25结果
        
        步骤：
        1. 分数归一化
        2. 按ID合并
        3. 计算混合分数
        """
        # 归一化向量分数
        if vector_results:
            vec_max = max(r['vector_score'] for r in vector_results)
            vec_min = min(r['vector_score'] for r in vector_results)
            vec_range = vec_max - vec_min if vec_max > vec_min else 1.0
            for r in vector_results:
                r['vector_score_norm'] = (r['vector_score'] - vec_min) / vec_range
        else:
            vec_max = 1.0
        
        # 归一化BM25分数
        if bm25_results:
            bm25_max = max(r['bm25_score'] for r in bm25_results)
            bm25_min = min(r['bm25_score'] for r in bm25_results)
            bm25_range = bm25_max - bm25_min if bm25_max > bm25_min else 1.0
            for r in bm25_results:
                r['bm25_score_norm'] = (r['bm25_score'] - bm25_min) / bm25_range
        else:
            bm25_max = 1.0
        
        # 合并结果
        merged = {}
        
        for r in vector_results:
            merged[r['id']] = SearchResult(
                id=r['id'],
                content=r['content'],
                item_type=r['item_type'],
                source_file_type=r['source_file_type'],
                importance=r['importance'],
                tags=r['tags'],
                created_at=r['created_at'],
                last_accessed_at=r['last_accessed_at'],
                access_count=r['access_count'],
                source_id=r.get('source_id'),  # 添加source_id
                vector_score=r.get('vector_score_norm', r['vector_score']),
                bm25_score=0.0
            )
        
        for r in bm25_results:
            if r['id'] in merged:
                merged[r['id']].bm25_score = r.get('bm25_score_norm', r['bm25_score'])
            else:
                merged[r['id']] = SearchResult(
                    id=r['id'],
                    content=r['content'],
                    item_type=r['item_type'],
                    source_file_type=r['source_file_type'],
                    importance=r['importance'],
                    tags=r['tags'],
                    created_at=r['created_at'],
                    last_accessed_at=r['last_accessed_at'],
                    access_count=r['access_count'],
                    source_id=r.get('source_id'),  # 添加source_id
                    vector_score=0.0,
                    bm25_score=r.get('bm25_score_norm', r['bm25_score'])
                )
        
        # 计算混合分数
        for result in merged.values():
            result.hybrid_score = (
                config.vector_weight * result.vector_score +
                config.bm25_weight * result.bm25_score
            )
        
        # 按混合分数排序
        results = list(merged.values())
        results.sort(key=lambda x: x.hybrid_score, reverse=True)
        
        return results
    
    def _apply_quality_threshold(
        self,
        results: List[SearchResult],
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        应用质量门槛过滤
        
        过滤条件：
        - hybrid_score >= min_hybrid_score
        - importance >= min_importance
        """
        filtered = []
        for r in results:
            if r.hybrid_score < config.min_hybrid_score:
                continue
            if r.importance < config.min_importance:
                continue
            filtered.append(r)
        
        return filtered
    
    def _apply_mmr(
        self,
        results: List[SearchResult],
        top_k: int,
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        应用MMR多样性重排
        
        复用现有的 MMRReranker
        """
        # 转换为MMR输入格式
        candidates = []
        for r in results:
            candidates.append({
                'id': r.id,
                'content': r.content,
                'score': r.hybrid_score,
                'importance': r.importance,
                'tags': r.tags
            })
        
        # MMR重排
        reranked = mmr_reranker.rerank(
            candidates=candidates,
            relevance_key='score',
            content_key='content',
            top_k=top_k
        )
        
        # 转换回SearchResult
        mmr_results = []
        id_to_result = {r.id: r for r in results}
        
        for item in reranked:
            original = id_to_result.get(item['id'])
            if original:
                original.mmr_rank = item.get('mmr_rank')
                mmr_results.append(original)
        
        return mmr_results
    
    def _apply_time_decay(
        self,
        results: List[SearchResult],
        config: SearchConfig
    ) -> List[SearchResult]:
        """
        应用时间衰减加权
        
        最终分数 = hybrid_score × time_decay_factor
        """
        now = datetime.now()
        
        for r in results:
            decay = self.time_decay.calculate_with_heat(
                last_accessed_at=r.last_accessed_at,
                created_at=r.created_at,
                access_count=r.access_count,
                current_time=now
            )
            r.time_decay_factor = decay
            r.final_score = r.hybrid_score * decay
        
        return results
    
    def _refresh_access(
        self,
        results: List[SearchResult],
        session: DBSession
    ):
        """
        LRU刷新：更新访问记录
        
        对返回的结果更新：
        - last_accessed_at = NOW()
        - access_count += 1
        """
        if not results:
            return
        
        ids = [r.id for r in results]
        
        try:
            session.execute(text("""
                UPDATE knowledge_items
                SET last_accessed_at = NOW(),
                    access_count = access_count + 1
                WHERE id = ANY(:ids)
            """), {'ids': ids})
            session.commit()
            
            logger.info(f"[LRU] 刷新 {len(ids)} 条记忆的访问记录")
        except Exception as e:
            logger.error(f"[LRU] 刷新访问记录失败: {e}")
            session.rollback()
    
    async def search_by_type(
        self,
        query: str,
        session: DBSession,
        item_type: str,
        top_k: int = 10
    ) -> List[SearchResult]:
        """
        按类型检索
        
        Args:
            query: 查询文本
            session: 数据库会话
            item_type: 条目类型
            top_k: 返回数量
        """
        config = SearchConfig(filter_item_types=[item_type])
        return await self.search(query, session, top_k, config)
    
    async def search_by_tags(
        self,
        query: str,
        session: DBSession,
        tags: List[str],
        top_k: int = 10
    ) -> List[SearchResult]:
        """
        按标签检索
        
        Args:
            query: 查询文本
            session: 数据库会话
            tags: 标签列表
            top_k: 返回数量
        """
        config = SearchConfig(filter_tags=tags)
        return await self.search(query, session, top_k, config)
    
    def _record_retrieval_metrics(
        self,
        query: str,
        top_k: int,
        results: List[SearchResult],
        elapsed_ms: float
    ):
        """
        记录检索指标
        
        Args:
            query: 查询文本
            top_k: 请求的数量
            results: 检索结果
            elapsed_ms: 耗时（毫秒）
        """
        try:
            from services.monitoring import metrics_collector, RetrievalMetrics
            
            # 计算分数统计
            scores = [r.final_score for r in results]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            max_score = max(scores) if scores else 0.0
            min_score = min(scores) if scores else 0.0
            
            metrics = RetrievalMetrics(
                timestamp=datetime.now(),
                query=query,
                top_k=top_k,
                result_count=len(results),
                avg_score=avg_score,
                max_score=max_score,
                min_score=min_score,
                total_time_ms=elapsed_ms
            )
            
            metrics_collector.record_retrieval(metrics)
            logger.debug(f"[MemorySearchEngine] 记录检索指标: {elapsed_ms:.2f}ms, {len(results)} results")
        except Exception as e:
            logger.warning(f"[MemorySearchEngine] 记录检索指标失败: {e}")


# 创建全局实例
memory_search_engine = MemorySearchEngine()


__all__ = [
    'MemorySearchEngine',
    'SearchConfig',
    'SearchResult',
    'TimeDecayCalculator',
    'memory_search_engine'
]
