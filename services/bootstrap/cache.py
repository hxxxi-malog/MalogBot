"""
Bootstrap 缓存模块

提供知识块缓存，减少重复数据库查询和向量计算：

缓存策略：
1. SOUL 缓存：固定内容，长时间缓存（TTL: 1小时）
2. USER 缓存：用户画像变化不频繁，中等时间缓存（TTL: 10分钟）
3. AGENTS 缓存：规则和踩坑可能变化，短时间缓存（TTL: 5分钟）
4. 检索结果缓存：基于查询hash，短时间缓存（TTL: 3分钟）

缓存失效触发：
- 知识更新时主动失效
- TTL 到期自动失效
- 内存压力大时 LRU 淘汰
"""
import logging
import threading
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from functools import wraps

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    created_at: datetime
    ttl_seconds: int
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > self.ttl_seconds
    
    def remaining_ttl(self) -> int:
        """获取剩余TTL（秒）"""
        age = (datetime.now() - self.created_at).total_seconds()
        return max(0, self.ttl_seconds - int(age))


class BootstrapCache:
    """Bootstrap 缓存管理器
    
    使用内存缓存减少数据库查询和计算开销
    
    使用示例：
        cache = BootstrapCache()
        
        # 缓存 SOUL 内容
        cache.set_soul("soul_content_here")
        soul = cache.get_soul()
        
        # 缓存检索结果
        cache_key = cache.make_retrieval_key("用户查询", top_k=10)
        cache.set_retrieval(cache_key, results)
        results = cache.get_retrieval(cache_key)
    """
    
    # 默认 TTL 配置（秒）
    DEFAULT_TTLS = {
        'soul': 3600,       # 1小时
        'user': 600,        # 10分钟
        'agents': 300,      # 5分钟
        'retrieval': 180,   # 3分钟
        'token_count': 3600 # 1小时（Token计数）
    }
    
    # 最大缓存条目数
    MAX_CACHE_SIZE = 1000
    
    def __init__(self, ttls: Dict[str, int] = None):
        """
        初始化缓存管理器
        
        Args:
            ttls: 自定义 TTL 配置
        """
        self.ttls = {**self.DEFAULT_TTLS, **(ttls or {})}
        
        # 缓存存储
        self._cache: Dict[str, CacheEntry] = {}
        
        # 统计信息
        self._hits = 0
        self._misses = 0
        
        # 线程锁
        self._lock = threading.RLock()
        
        logger.info(f"[BootstrapCache] 初始化完成，TTL配置: {self.ttls}")
    
    # ==================== 通用缓存方法 ====================
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，不存在或过期返回 None
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                # 过期，删除并返回 None
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            logger.debug(f"[BootstrapCache] 命中: {key}, 剩余TTL: {entry.remaining_ttl()}s")
            return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: int):
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl_seconds: TTL（秒）
        """
        with self._lock:
            # 检查容量，必要时淘汰
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                self._evict_expired()
                if len(self._cache) >= self.MAX_CACHE_SIZE:
                    # 仍然满，删除最老的
                    self._evict_oldest()
            
            self._cache[key] = CacheEntry(
                value=value,
                created_at=datetime.now(),
                ttl_seconds=ttl_seconds
            )
            logger.debug(f"[BootstrapCache] 设置: {key}, TTL: {ttl_seconds}s")
    
    def invalidate(self, key: str):
        """
        使缓存失效
        
        Args:
            key: 缓存键
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"[BootstrapCache] 失效: {key}")
    
    def invalidate_pattern(self, pattern: str):
        """
        使匹配模式的缓存失效
        
        Args:
            pattern: 键前缀模式
        """
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(pattern)]
            for key in keys_to_delete:
                del self._cache[key]
            if keys_to_delete:
                logger.debug(f"[BootstrapCache] 批量失效: {len(keys_to_delete)} 条 (pattern: {pattern})")
    
    # ==================== 知识块专用方法 ====================
    
    def get_soul(self) -> Optional[Tuple[str, int]]:
        """获取 SOUL 缓存"""
        return self.get('soul:content')
    
    def set_soul(self, content: str, tokens: int):
        """设置 SOUL 缓存"""
        self.set('soul:content', (content, tokens), self.ttls['soul'])
    
    def invalidate_soul(self):
        """使 SOUL 缓存失效"""
        self.invalidate('soul:content')
    
    def get_user(self) -> Optional[Tuple[str, int, int]]:
        """获取 USER 缓存"""
        return self.get('user:content')
    
    def set_user(self, content: str, tokens: int, items_count: int):
        """设置 USER 缓存"""
        self.set('user:content', (content, tokens, items_count), self.ttls['user'])
    
    def invalidate_user(self):
        """使 USER 缓存失效"""
        self.invalidate('user:content')
    
    def get_agents(self) -> Optional[Tuple[str, int, int, int]]:
        """获取 AGENTS 缓存"""
        return self.get('agents:content')
    
    def set_agents(self, content: str, tokens: int, rules_count: int, mistakes_count: int):
        """设置 AGENTS 缓存"""
        self.set('agents:content', (content, tokens, rules_count, mistakes_count), self.ttls['agents'])
    
    def invalidate_agents(self):
        """使 AGENTS 缓存失效"""
        self.invalidate('agents:content')
    
    # ==================== 检索结果缓存 ====================
    
    def make_retrieval_key(self, query: str, top_k: int, **filters) -> str:
        """
        生成检索缓存键
        
        Args:
            query: 查询文本
            top_k: 返回数量
            **filters: 过滤条件
            
        Returns:
            缓存键
        """
        # 使用查询hash作为键的一部分
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        filter_str = ",".join(f"{k}={v}" for k, v in sorted(filters.items()) if v is not None)
        return f"retrieval:{query_hash}:k{top_k}:{filter_str}"
    
    def get_retrieval(self, key: str) -> Optional[Any]:
        """获取检索结果缓存"""
        return self.get(key)
    
    def set_retrieval(self, key: str, results: Any):
        """设置检索结果缓存"""
        self.set(key, results, self.ttls['retrieval'])
    
    # ==================== Token 计数缓存 ====================
    
    def get_token_count(self, text_hash: str) -> Optional[int]:
        """获取 Token 计数缓存"""
        return self.get(f"tokens:{text_hash}")
    
    def set_token_count(self, text_hash: str, count: int):
        """设置 Token 计数缓存"""
        self.set(f"tokens:{text_hash}", count, self.ttls['token_count'])
    
    def make_text_hash(self, text: str) -> str:
        """生成文本hash"""
        return hashlib.md5(text.encode()).hexdigest()[:16]
    
    # ==================== 维护方法 ====================
    
    def _evict_expired(self):
        """淘汰所有过期条目"""
        expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
        for key in expired_keys:
            del self._cache[key]
        if expired_keys:
            logger.debug(f"[BootstrapCache] 淘汰过期: {len(expired_keys)} 条")
    
    def _evict_oldest(self):
        """淘汰最老的条目"""
        if not self._cache:
            return
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]
        logger.debug(f"[BootstrapCache] 淘汰最老: {oldest_key}")
    
    def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
            logger.info("[BootstrapCache] 缓存已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "size": len(self._cache),
                "max_size": self.MAX_CACHE_SIZE,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 3),
                "ttls": self.ttls
            }
    
    def cleanup(self):
        """清理过期缓存（可定时调用）"""
        self._evict_expired()


# ==================== 装饰器 ====================

def cached(key_func, ttl_seconds: int):
    """
    通用缓存装饰器
    
    Args:
        key_func: 生成缓存键的函数
        ttl_seconds: TTL（秒）
    """
    def decorator(func):
        _cache = {}
        _lock = threading.RLock()
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = key_func(*args, **kwargs)
            
            with _lock:
                entry = _cache.get(cache_key)
                if entry and not entry.is_expired():
                    return entry.value
            
            # 计算结果
            result = func(*args, **kwargs)
            
            with _lock:
                _cache[cache_key] = CacheEntry(
                    value=result,
                    created_at=datetime.now(),
                    ttl_seconds=ttl_seconds
                )
            
            return result
        
        return wrapper
    return decorator


# ==================== 全局实例 ====================

bootstrap_cache = BootstrapCache()


__all__ = [
    'BootstrapCache',
    'bootstrap_cache',
    'cached'
]
