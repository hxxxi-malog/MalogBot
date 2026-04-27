"""
搜索去重工具

实现分层去重机制：
1. Track 本地去重：O(1) 检查 visited_urls
2. Session 全局去重：Redis Set 共享搜索记录
3. 相似度去重：向量相似度 > 0.88 视为重复
"""
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DedupRecord:
    """去重记录"""
    query: str
    query_hash: str
    direction_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    result_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "query_hash": self.query_hash,
            "direction_id": self.direction_id,
            "timestamp": self.timestamp.isoformat(),
            "result_count": self.result_count,
        }


class Deduplicator:
    """
    搜索去重器
    
    实现三层去重机制：
    1. Track 本地去重（最快）
    2. Session 全局去重（共享）
    3. 相似度去重（最精确）
    
    使用方式：
        dedup = Deduplicator()
        
        # Track 本地去重
        if dedup.is_duplicate_local(query, track):
            return None
        
        # Session 全局去重
        if dedup.is_duplicate_global(query, session_id):
            return cached_result
        
        # 相似度去重（可选）
        if dedup.is_similar(query, session_id, threshold=0.88):
            return similar_result
    """
    
    def __init__(
        self,
        similarity_threshold: float = 0.88,
        use_redis: bool = False,
        redis_client = None,
    ):
        """
        初始化去重器
        
        Args:
            similarity_threshold: 相似度阈值
            use_redis: 是否使用 Redis 进行全局去重
            redis_client: Redis 客户端实例
        """
        self.similarity_threshold = similarity_threshold
        self.use_redis = use_redis
        self.redis_client = redis_client
        
        # 内存缓存（用于非 Redis 场景）
        self._global_cache: dict[str, list[DedupRecord]] = {}
        self._query_embeddings: dict[str, list[float]] = {}
        
        logger.info(f"Deduplicator initialized, use_redis={use_redis}, threshold={similarity_threshold}")
    
    def is_duplicate_local(self, query: str, track) -> bool:
        """
        Track 本地去重检查
        
        Args:
            query: 查询字符串
            track: ResearchTrack 实例
            
        Returns:
            是否重复
        """
        if not query:
            return False
        
        normalized_query = self._normalize_query(query)
        is_dup = track.is_searched(normalized_query)
        
        if is_dup:
            logger.debug(f"Local dedup hit for query: {query[:50]}")
        
        return is_dup
    
    def is_duplicate_global(self, query: str, session_id: str) -> tuple[bool, Optional[DedupRecord]]:
        """
        Session 全局去重检查
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            
        Returns:
            (是否重复, 去重记录)
        """
        if not query:
            return False, None
        
        query_hash = self._hash_query(query)
        
        if self.use_redis and self.redis_client:
            # Redis 实现
            key = self._get_redis_key(session_id)
            is_member = self.redis_client.sismember(key, query_hash)
            
            if is_member:
                # 获取缓存的结果
                record_key = f"{key}:records:{query_hash}"
                record_data = self.redis_client.get(record_key)
                if record_data:
                    import json
                    record = DedupRecord(**json.loads(record_data))
                    logger.debug(f"Global dedup hit (Redis) for query: {query[:50]}")
                    return True, record
            
            return False, None
        else:
            # 内存实现
            if session_id not in self._global_cache:
                return False, None
            
            records = self._global_cache[session_id]
            for record in records:
                if record.query_hash == query_hash:
                    logger.debug(f"Global dedup hit (memory) for query: {query[:50]}")
                    return True, record
            
            return False, None
    
    def is_similar(
        self,
        query: str,
        session_id: str,
        threshold: Optional[float] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        相似度去重检查
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            threshold: 相似度阈值（可选，默认使用初始化时的值）
            
        Returns:
            (是否相似, 相似的查询)
        """
        if not query:
            return False, None
        
        threshold = threshold or self.similarity_threshold
        
        # 获取当前查询的向量（如果有）
        query_embedding = self._get_embedding(query)
        if not query_embedding:
            return False, None
        
        # 获取 Session 内的所有查询向量
        if session_id not in self._query_embeddings:
            return False, None
        
        stored_queries = self._query_embeddings[session_id]
        
        # 计算相似度
        for stored_query, stored_embedding in stored_queries.items():
            similarity = self._cosine_similarity(query_embedding, stored_embedding)
            if similarity >= threshold:
                logger.debug(
                    f"Similarity dedup hit: {query[:30]} ~= {stored_query[:30]} "
                    f"(similarity={similarity:.2f})"
                )
                return True, stored_query
        
        return False, None
    
    def record_query(
        self,
        query: str,
        session_id: str,
        direction_id: str = "",
        result_count: int = 0,
    ) -> DedupRecord:
        """
        记录查询（用于后续去重）
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            direction_id: 研究方向 ID
            result_count: 结果数量
            
        Returns:
            去重记录
        """
        query_hash = self._hash_query(query)
        record = DedupRecord(
            query=query,
            query_hash=query_hash,
            direction_id=direction_id,
            result_count=result_count,
        )
        
        if self.use_redis and self.redis_client:
            # Redis 实现
            key = self._get_redis_key(session_id)
            self.redis_client.sadd(key, query_hash)
            
            # 存储记录详情
            record_key = f"{key}:records:{query_hash}"
            import json
            self.redis_client.setex(record_key, 3600, json.dumps(record.to_dict()))  # 1小时过期
        else:
            # 内存实现
            if session_id not in self._global_cache:
                self._global_cache[session_id] = []
            self._global_cache[session_id].append(record)
        
        logger.debug(f"Recorded query: {query[:50]} (session={session_id})")
        return record
    
    def record_embedding(self, query: str, session_id: str, embedding: list[float]) -> None:
        """
        记录查询向量（用于相似度去重）
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            embedding: 查询向量
        """
        if session_id not in self._query_embeddings:
            self._query_embeddings[session_id] = {}
        
        self._query_embeddings[session_id][query] = embedding
        logger.debug(f"Recorded embedding for query: {query[:30]}")
    
    def clear_session(self, session_id: str) -> None:
        """
        清除 Session 缓存
        
        Args:
            session_id: 会话 ID
        """
        if self.use_redis and self.redis_client:
            key = self._get_redis_key(session_id)
            self.redis_client.delete(key)
        else:
            if session_id in self._global_cache:
                del self._global_cache[session_id]
        
        if session_id in self._query_embeddings:
            del self._query_embeddings[session_id]
        
        logger.debug(f"Cleared dedup cache for session: {session_id}")
    
    def get_stats(self, session_id: str) -> dict:
        """
        获取去重统计信息
        
        Args:
            session_id: 会话 ID
            
        Returns:
            统计信息字典
        """
        records = self._global_cache.get(session_id, [])
        embeddings = self._query_embeddings.get(session_id, {})
        
        return {
            "session_id": session_id,
            "query_count": len(records),
            "embedding_count": len(embeddings),
            "use_redis": self.use_redis,
            "similarity_threshold": self.similarity_threshold,
        }
    
    # ============ 私有方法 ============
    
    def _normalize_query(self, query: str) -> str:
        """规范化查询字符串"""
        return query.lower().strip()
    
    def _hash_query(self, query: str) -> str:
        """计算查询哈希"""
        normalized = self._normalize_query(query)
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _get_redis_key(self, session_id: str) -> str:
        """获取 Redis 键名"""
        return f"research:dedup:{session_id}"
    
    def _get_embedding(self, query: str) -> Optional[list[float]]:
        """
        获取查询向量
        
        这里返回 None，实际使用时需要集成 embedding 服务。
        子类可以重写此方法。
        """
        return None
    
    @staticmethod
    def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """
        计算余弦相似度
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            相似度 [0, 1]
        """
        import math
        
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)


class RedisDeduplicator(Deduplicator):
    """
    Redis 支持的分布式去重器
    
    支持跨进程、跨服务的全局去重。
    """
    
    def __init__(self, redis_client, similarity_threshold: float = 0.88):
        """
        初始化 Redis 去重器
        
        Args:
            redis_client: Redis 客户端实例
            similarity_threshold: 相似度阈值
        """
        super().__init__(
            similarity_threshold=similarity_threshold,
            use_redis=True,
            redis_client=redis_client,
        )
    
    async def is_duplicate_global_async(
        self,
        query: str,
        session_id: str,
    ) -> tuple[bool, Optional[DedupRecord]]:
        """
        异步的全局去重检查
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            
        Returns:
            (是否重复, 去重记录)
        """
        # 如果使用 aioredis，可以实现异步版本
        # 这里先使用同步实现
        return self.is_duplicate_global(query, session_id)
    
    async def record_query_async(
        self,
        query: str,
        session_id: str,
        direction_id: str = "",
        result_count: int = 0,
    ) -> DedupRecord:
        """
        异步记录查询
        
        Args:
            query: 查询字符串
            session_id: 会话 ID
            direction_id: 研究方向 ID
            result_count: 结果数量
            
        Returns:
            去重记录
        """
        return self.record_query(query, session_id, direction_id, result_count)
