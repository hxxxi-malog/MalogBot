"""
Redis 缓存服务模块

提供分布式缓存支持，包括：
1. Redis 连接管理器 - 连接池、健康检查、重试机制
2. 会话缓存 - 取消标志、递归状态、团队结果
3. 分布式锁 - 文件编辑锁、任务锁
4. BM25 索引缓存 - 大对象缓存
5. 任务队列 - 优先级队列、竞标窗口、任务认领

使用示例：
    from services.redis_service import redis_manager, is_redis_available

    if is_redis_available():
        redis_manager.set("key", "value", ttl=60)
        value = redis_manager.get("key")
"""
import os
import json
import time
import pickle
import logging
import threading
import hashlib
from typing import Optional, Dict, Any, List, Tuple, Callable
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== Redis 配置 ====================

REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', 6379)),
    'password': os.getenv('REDIS_PASSWORD', '2153315236'),
    'username': os.getenv('REDIS_USERNAME', 'default'),
    'db': int(os.getenv('REDIS_DB', 0)),
    'decode_responses': False,  # 使用 bytes 模式，便于 pickle
    'socket_timeout': 5,
    'socket_connect_timeout': 5,
    'retry_on_timeout': True,
    'max_connections': 50,
}

# Redis 是否可用标志
_redis_available: Optional[bool] = None
_redis_client = None
_redis_lock = threading.Lock()


def get_redis_client():
    """
    获取 Redis 客户端（懒加载，单例模式）

    Returns:
        Redis 客户端实例，连接失败返回 None
    """
    global _redis_client, _redis_available

    if _redis_client is not None:
        return _redis_client

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client

        try:
            import redis
            from redis.connection import ConnectionPool

            # 创建连接池
            pool = ConnectionPool(**REDIS_CONFIG)
            _redis_client = redis.Redis(connection_pool=pool)

            # 测试连接
            _redis_client.ping()
            _redis_available = True
            logger.info(f"[RedisService] 连接成功: {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}")

        except ImportError:
            logger.warning("[RedisService] redis 包未安装，请运行: pip install redis")
            _redis_available = False
            _redis_client = None

        except Exception as e:
            logger.warning(f"[RedisService] 连接失败: {e}")
            _redis_available = False
            _redis_client = None

    return _redis_client


def is_redis_available() -> bool:
    """
    检查 Redis 是否可用

    Returns:
        True 如果 Redis 可用
    """
    global _redis_available

    if _redis_available is None:
        get_redis_client()

    return _redis_available == True


# ==================== Redis 管理器 ====================

class RedisManager:
    """
    Redis 缓存管理器

    提供统一的缓存操作接口，支持：
    - 基本的 get/set/delete 操作
    - TTL 过期时间
    - 批量操作
    - 模式匹配删除
    - 序列化/反序列化（pickle）
    """

    # 键前缀
    PREFIX = "malogbot:"

    def __init__(self):
        """初始化管理器"""
        self._client = None
        self._local_cache = {}  # 本地缓存回退
        self._local_lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def client(self):
        """获取 Redis 客户端"""
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    def _make_key(self, key: str) -> str:
        """生成完整键名"""
        return f"{self.PREFIX}{key}"

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值

        Args:
            key: 缓存键
            default: 默认值

        Returns:
            缓存值，不存在返回 default
        """
        full_key = self._make_key(key)

        # 尝试 Redis
        if self.client:
            try:
                data = self.client.get(full_key)
                if data is not None:
                    self._hits += 1
                    logger.debug(f"[RedisManager] 命中: {key}")
                    return pickle.loads(data)
            except Exception as e:
                logger.warning(f"[RedisManager] 获取失败: {e}")

        # 回退到本地缓存
        with self._local_lock:
            entry = self._local_cache.get(full_key)
            if entry and not entry.get('_expired', False):
                if entry.get('_expire_at', float('inf')) > time.time():
                    self._hits += 1
                    logger.debug(f"[RedisManager] 本地缓存命中: {key}")
                    return entry.get('value', default)

        self._misses += 1
        return default

    def set(self, key: str, value: Any, ttl: int = 300):
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），默认 5 分钟
        """
        full_key = self._make_key(key)

        # 尝试 Redis
        if self.client:
            try:
                data = pickle.dumps(value)
                self.client.setex(full_key, ttl, data)
                logger.debug(f"[RedisManager] 设置: {key}, TTL: {ttl}s")
                return
            except Exception as e:
                logger.warning(f"[RedisManager] 设置失败: {e}")

        # 回退到本地缓存
        with self._local_lock:
            self._local_cache[full_key] = {
                'value': value,
                '_expire_at': time.time() + ttl,
                '_expired': False
            }

    def delete(self, key: str):
        """
        删除缓存

        Args:
            key: 缓存键
        """
        full_key = self._make_key(key)

        if self.client:
            try:
                self.client.delete(full_key)
                logger.debug(f"[RedisManager] 删除: {key}")
            except Exception as e:
                logger.warning(f"[RedisManager] 删除失败: {e}")

        with self._local_lock:
            self._local_cache.pop(full_key, None)

    def delete_pattern(self, pattern: str):
        """
        删除匹配模式的所有键

        Args:
            pattern: 键模式（不含前缀）
        """
        full_pattern = self._make_key(pattern)

        if self.client:
            try:
                keys = self.client.keys(f"{full_pattern}*")
                if keys:
                    self.client.delete(*keys)
                    logger.debug(f"[RedisManager] 批量删除: {len(keys)} 条")
            except Exception as e:
                logger.warning(f"[RedisManager] 批量删除失败: {e}")

        with self._local_lock:
            keys_to_delete = [k for k in self._local_cache.keys()
                            if k.startswith(full_pattern)]
            for k in keys_to_delete:
                del self._local_cache[k]

    def exists(self, key: str) -> bool:
        """
        检查键是否存在

        Args:
            key: 缓存键

        Returns:
            True 如果存在
        """
        full_key = self._make_key(key)

        if self.client:
            try:
                return self.client.exists(full_key) > 0
            except Exception as e:
                logger.warning(f"[RedisManager] 检查存在失败: {e}")

        with self._local_lock:
            entry = self._local_cache.get(full_key)
            if entry:
                return entry.get('_expire_at', float('inf')) > time.time()
        return False

    def ttl(self, key: str) -> int:
        """
        获取键的剩余 TTL

        Args:
            key: 缓存键

        Returns:
            剩余秒数，-1 表示永不过期，-2 表示不存在
        """
        full_key = self._make_key(key)

        if self.client:
            try:
                return self.client.ttl(full_key)
            except Exception as e:
                logger.warning(f"[RedisManager] 获取 TTL 失败: {e}")

        with self._local_lock:
            entry = self._local_cache.get(full_key)
            if entry:
                remaining = entry.get('_expire_at', float('inf')) - time.time()
                return max(0, int(remaining))
        return -2

    def incr(self, key: str, amount: int = 1) -> int:
        """
        递增计数器

        Args:
            key: 缓存键
            amount: 递增量

        Returns:
            递增后的值
        """
        full_key = self._make_key(key)

        if self.client:
            try:
                return self.client.incrby(full_key, amount)
            except Exception as e:
                logger.warning(f"[RedisManager] 递增失败: {e}")

        # 本地回退
        with self._local_lock:
            current = self._local_cache.get(full_key, {}).get('value', 0)
            new_value = current + amount
            self._local_cache[full_key] = {
                'value': new_value,
                '_expire_at': float('inf')
            }
            return new_value

    def expire(self, key: str, ttl: int):
        """
        设置键的过期时间

        Args:
            key: 缓存键
            ttl: 过期秒数
        """
        full_key = self._make_key(key)

        if self.client:
            try:
                self.client.expire(full_key, ttl)
            except Exception as e:
                logger.warning(f"[RedisManager] 设置过期失败: {e}")

        with self._local_lock:
            if full_key in self._local_cache:
                self._local_cache[full_key]['_expire_at'] = time.time() + ttl

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "available": is_redis_available(),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / (self._hits + self._misses), 3)
            if (self._hits + self._misses) > 0 else 0.0,
        }

        if self.client:
            try:
                info = self.client.info('memory')
                stats['used_memory'] = info.get('used_memory_human', 'unknown')
                stats['connected_clients'] = self.client.info('clients').get('connected_clients', 0)
            except Exception:
                pass

        return stats

    def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态信息
        """
        result = {
            "status": "unknown",
            "latency_ms": None,
            "error": None
        }

        if not self.client:
            result["status"] = "unavailable"
            result["error"] = "Redis client not initialized"
            return result

        try:
            start = time.time()
            self.client.ping()
            latency = (time.time() - start) * 1000

            result["status"] = "healthy"
            result["latency_ms"] = round(latency, 2)

        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)

        return result


# 全局实例
redis_manager = RedisManager()


# ==================== 会话缓存 ====================

class SessionCache:
    """
    会话级缓存

    用于存储会话相关的临时状态：
    - 取消标志：用户取消操作
    - 递归状态：递归调用状态保持
    - 团队结果：团队协作结果
    """

    # 会话 TTL（1 小时）
    SESSION_TTL = 3600

    def _make_session_key(self, session_id: str, suffix: str) -> str:
        """生成会话键"""
        return f"session:{session_id}:{suffix}"

    def set_cancel_flag(self, session_id: str):
        """设置取消标志"""
        key = self._make_session_key(session_id, "cancelled")
        redis_manager.set(key, True, ttl=self.SESSION_TTL)
        logger.info(f"[SessionCache] 设置取消标志: {session_id}")

    def is_cancelled(self, session_id: str) -> bool:
        """检查是否已取消"""
        key = self._make_session_key(session_id, "cancelled")
        return redis_manager.get(key, False)

    def clear_cancel_flag(self, session_id: str):
        """清除取消标志"""
        key = self._make_session_key(session_id, "cancelled")
        redis_manager.delete(key)
        logger.info(f"[SessionCache] 清除取消标志: {session_id}")

    def set_recursion_state(self, session_id: str, state: Dict[str, Any]):
        """设置递归状态"""
        key = self._make_session_key(session_id, "recursion_state")
        redis_manager.set(key, state, ttl=self.SESSION_TTL)
        logger.debug(f"[SessionCache] 设置递归状态: {session_id}")

    def get_recursion_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取递归状态"""
        key = self._make_session_key(session_id, "recursion_state")
        return redis_manager.get(key)

    def set_team_result(self, session_id: str, result: Dict[str, Any]):
        """设置团队结果"""
        key = self._make_session_key(session_id, "team_result")
        redis_manager.set(key, result, ttl=self.SESSION_TTL)
        logger.debug(f"[SessionCache] 设置团队结果: {session_id}")

    def get_team_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取团队结果"""
        key = self._make_session_key(session_id, "team_result")
        return redis_manager.get(key)

    def clear_session(self, session_id: str):
        """清除会话所有数据"""
        pattern = f"session:{session_id}:"
        redis_manager.delete_pattern(pattern)
        logger.info(f"[SessionCache] 清除会话: {session_id}")


# 全局实例
session_cache = SessionCache()


# ==================== 分布式锁 ====================

class DistributedLock:
    """
    分布式锁

    用于防止多个实例同时操作同一资源：
    - 文件编辑锁
    - 任务执行锁
    - 资源访问锁

    使用示例：
        with distributed_lock.acquire("file.py", timeout=10) as acquired:
            if acquired:
                # 执行需要锁保护的操作
                pass
    """

    # 锁前缀
    LOCK_PREFIX = "lock:"

    # 默认锁超时（30 秒）
    DEFAULT_TIMEOUT = 30

    def __init__(self):
        """初始化分布式锁"""
        self._lock = threading.Lock()
        self._local_locks: Dict[str, str] = {}  # 本地锁回退
        self._tokens: Dict[str, str] = {}  # 存储每个锁的 token

    def _make_lock_key(self, name: str) -> str:
        """生成锁键"""
        # 对文件名进行 hash，避免特殊字符问题
        name_hash = hashlib.md5(name.encode()).hexdigest()[:16]
        return f"{self.LOCK_PREFIX}{name_hash}:{name}"

    def _generate_token(self) -> str:
        """生成唯一 token"""
        import uuid
        return str(uuid.uuid4())

    def try_acquire(self, name: str, timeout: int = None, token: str = None) -> bool:
        """
        尝试获取锁（非阻塞）

        Args:
            name: 锁名称
            timeout: 锁超时时间（秒）
            token: 可选的 token，不提供则自动生成

        Returns:
            True 如果成功获取锁
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        lock_key = self._make_lock_key(name)
        token = token or self._generate_token()

        # 尝试 Redis 锁
        if redis_manager.client:
            try:
                # 使用 SETNX 实现分布式锁
                acquired = redis_manager.client.set(
                    lock_key, token, nx=True, ex=timeout
                )
                if acquired:
                    # 存储 token 用于释放
                    with self._lock:
                        self._tokens[name] = token
                    logger.debug(f"[DistributedLock] 获取锁成功: {name}")
                    return True
                logger.debug(f"[DistributedLock] 锁被占用: {name}")
                return False
            except Exception as e:
                logger.warning(f"[DistributedLock] Redis 锁失败: {e}")

        # 回退到本地锁
        with self._lock:
            if lock_key in self._local_locks:
                return False
            self._local_locks[lock_key] = token
            self._tokens[name] = token
            logger.debug(f"[DistributedLock] 本地锁获取成功: {name}")
            return True

    def acquire(self, name: str, timeout: int = None, blocking_timeout: float = 5.0):
        """
        获取锁（可阻塞）

        Args:
            name: 锁名称
            timeout: 锁超时时间（秒）
            blocking_timeout: 阻塞等待超时（秒）

        Returns:
            上下文管理器
        """
        return _LockContext(self, name, timeout, blocking_timeout)

    def release(self, name: str, token: str = None) -> bool:
        """
        释放锁

        Args:
            name: 锁名称
            token: 锁 token（可选，不提供则使用存储的 token）

        Returns:
            True 如果成功释放
        """
        lock_key = self._make_lock_key(name)

        # 获取 token
        if token is None:
            with self._lock:
                token = self._tokens.pop(name, None)

        # 释放 Redis 锁
        if redis_manager.client:
            try:
                if token:
                    # 使用 Lua 脚本保证原子性
                    lua_script = """
                    if redis.call("get", KEYS[1]) == ARGV[1] then
                        return redis.call("del", KEYS[1])
                    else
                        return 0
                    end
                    """
                    redis_manager.client.eval(lua_script, 1, lock_key, token)
                else:
                    redis_manager.client.delete(lock_key)
                logger.debug(f"[DistributedLock] 释放锁: {name}")
                return True
            except Exception as e:
                logger.warning(f"[DistributedLock] 释放锁失败: {e}")

        # 释放本地锁
        with self._lock:
            if lock_key in self._local_locks:
                del self._local_locks[lock_key]
                self._tokens.pop(name, None)
                logger.debug(f"[DistributedLock] 释放本地锁: {name}")
                return True
        return False

    def is_locked(self, name: str) -> bool:
        """
        检查是否被锁定

        Args:
            name: 锁名称

        Returns:
            True 如果被锁定
        """
        lock_key = self._make_lock_key(name)

        if redis_manager.client:
            try:
                return redis_manager.client.exists(lock_key) > 0
            except Exception as e:
                logger.warning(f"[DistributedLock] 检查锁状态失败: {e}")

        with self._lock:
            return lock_key in self._local_locks


class _LockContext:
    """锁上下文管理器"""

    def __init__(self, lock: DistributedLock, name: str,
                 timeout: int, blocking_timeout: float):
        self.lock = lock
        self.name = name
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.acquired = False
        self.token = None
        self._start_time = None

    def __enter__(self):
        self._start_time = time.time()
        self.token = self.lock._generate_token()

        # 尝试获取锁
        while True:
            if self.lock.try_acquire(self.name, self.timeout, token=self.token):
                self.acquired = True
                return self.acquired

            # 检查是否超时
            elapsed = time.time() - self._start_time
            if elapsed >= self.blocking_timeout:
                logger.warning(f"[DistributedLock] 获取锁超时: {self.name}")
                return False

            # 等待重试
            time.sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            self.lock.release(self.name, self.token)
        return False


# 全局实例
distributed_lock = DistributedLock()


# ==================== BM25 索引缓存 ====================

class BM25Cache:
    """
    BM25 索引缓存

    用于缓存大型 BM25 索引对象：
    - 索引数据缓存
    - 统计信息缓存
    - 支持大对象序列化
    """

    # 索引 TTL（2 小时）
    INDEX_TTL = 7200

    # 统计 TTL（10 分钟）
    STATS_TTL = 600

    def _make_index_key(self, kb_id: str) -> str:
        """生成索引键"""
        return f"bm25:index:{kb_id}"

    def _make_stats_key(self, kb_id: str) -> str:
        """生成统计键"""
        return f"bm25:stats:{kb_id}"

    def set_index(self, kb_id: str, index_data: Dict[str, Any]):
        """
        设置 BM25 索引缓存

        Args:
            kb_id: 知识库 ID
            index_data: 索引数据（包含 corpus_tokens, chunk_ids, chunk_data 等）
        """
        key = self._make_index_key(kb_id)

        # 分离不可序列化的对象
        serializable_data = {}
        for k, v in index_data.items():
            if k == 'bm25_index':
                # BM25 对象需要特殊处理
                try:
                    import pickle
                    serializable_data[k] = pickle.dumps(v)
                except Exception as e:
                    logger.warning(f"[BM25Cache] BM25 对象序列化失败: {e}")
                    serializable_data[k] = None
            else:
                serializable_data[k] = v

        redis_manager.set(key, serializable_data, ttl=self.INDEX_TTL)
        logger.info(f"[BM25Cache] 设置索引缓存: {kb_id}")

        # 更新统计
        stats = {
            'chunk_count': len(index_data.get('chunk_ids', [])),
            'created_at': datetime.now().isoformat(),
            'kb_id': kb_id
        }
        redis_manager.set(self._make_stats_key(kb_id), stats, ttl=self.STATS_TTL)

    def get_index(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 BM25 索引缓存

        Args:
            kb_id: 知识库 ID

        Returns:
            索引数据，不存在返回 None
        """
        key = self._make_index_key(kb_id)
        data = redis_manager.get(key)

        if data:
            # 反序列化 BM25 对象
            if 'bm25_index' in data and data['bm25_index']:
                try:
                    import pickle
                    data['bm25_index'] = pickle.loads(data['bm25_index'])
                except Exception as e:
                    logger.warning(f"[BM25Cache] BM25 对象反序列化失败: {e}")
                    data['bm25_index'] = None

            logger.debug(f"[BM25Cache] 获取索引缓存: {kb_id}")
            return data

        return None

    def has_index(self, kb_id: str) -> bool:
        """
        检查索引是否存在

        Args:
            kb_id: 知识库 ID

        Returns:
            True 如果存在
        """
        key = self._make_index_key(kb_id)
        return redis_manager.exists(key)

    def get_stats(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """
        获取索引统计信息

        Args:
            kb_id: 知识库 ID

        Returns:
            统计信息
        """
        key = self._make_stats_key(kb_id)
        return redis_manager.get(key)

    def clear_index(self, kb_id: str):
        """
        清除索引缓存

        Args:
            kb_id: 知识库 ID
        """
        redis_manager.delete(self._make_index_key(kb_id))
        redis_manager.delete(self._make_stats_key(kb_id))
        logger.info(f"[BM25Cache] 清除索引缓存: {kb_id}")

    def clear_all(self):
        """清除所有 BM25 缓存"""
        redis_manager.delete_pattern("bm25:")
        logger.info("[BM25Cache] 清除所有缓存")


# 全局实例
bm25_cache = BM25Cache()


# ==================== 任务队列 ====================

class TaskQueue:
    """
    任务队列

    提供：
    - 优先级队列
    - 竞标窗口（用于 Agent 竞标）
    - 任务认领（用于分布式任务分配）
    """

    # 队列前缀
    QUEUE_PREFIX = "queue:"

    # 竞标窗口前缀
    BID_PREFIX = "bid:"

    # 任务认领前缀
    CLAIM_PREFIX = "claim:"

    # 竞标窗口默认持续时间（秒）
    DEFAULT_BID_WINDOW = 5.0

    def _make_queue_key(self, queue_name: str) -> str:
        """生成队列键"""
        return f"{self.QUEUE_PREFIX}{queue_name}"

    def push_task(self, queue_name: str, task: Dict[str, Any], priority: int = 0):
        """
        推送任务到队列

        Args:
            queue_name: 队列名称
            task: 任务数据
            priority: 优先级（数值越大优先级越高）
        """
        key = self._make_queue_key(queue_name)
        score = -priority  # 负数使高优先级排在前面

        if redis_manager.client:
            try:
                redis_manager.client.zadd(key, {json.dumps(task): score})
                logger.debug(f"[TaskQueue] 推送任务: {queue_name}, priority={priority}")
                return
            except Exception as e:
                logger.warning(f"[TaskQueue] 推送任务失败: {e}")

        # 本地回退（简单列表）
        # 这里简化处理，不支持优先级
        local_key = f"local:{key}"
        tasks = redis_manager.get(local_key, [])
        tasks.append(task)
        redis_manager.set(local_key, tasks)

    def pop_task(self, queue_name: str) -> Optional[Dict[str, Any]]:
        """
        弹出优先级最高的任务

        Args:
            queue_name: 队列名称

        Returns:
            任务数据，队列为空返回 None
        """
        key = self._make_queue_key(queue_name)

        if redis_manager.client:
            try:
                # 使用 ZPOPMIN 获取分数最小（优先级最高）的任务
                result = redis_manager.client.zpopmin(key)
                if result:
                    task_json, _ = result[0]
                    logger.debug(f"[TaskQueue] 弹出任务: {queue_name}")
                    return json.loads(task_json)
                return None
            except Exception as e:
                logger.warning(f"[TaskQueue] 弹出任务失败: {e}")

        # 本地回退
        local_key = f"local:{key}"
        tasks = redis_manager.get(local_key, [])
        if tasks:
            task = tasks.pop(0)
            redis_manager.set(local_key, tasks)
            return task
        return None

    def get_task_count(self, queue_name: str) -> int:
        """
        获取队列任务数

        Args:
            queue_name: 队列名称

        Returns:
            任务数量
        """
        key = self._make_queue_key(queue_name)

        if redis_manager.client:
            try:
                return redis_manager.client.zcard(key)
            except Exception as e:
                logger.warning(f"[TaskQueue] 获取任务数失败: {e}")

        local_key = f"local:{key}"
        return len(redis_manager.get(local_key, []))

    # ==================== 竞标窗口 ====================

    def start_bid_window(self, task_id: str, window_duration: float = None):
        """
        开启竞标窗口

        Args:
            task_id: 任务 ID
            window_duration: 窗口持续时间（秒）
        """
        duration = window_duration or self.DEFAULT_BID_WINDOW
        key = f"{self.BID_PREFIX}{task_id}:window"

        redis_manager.set(key, {
            'start_time': time.time(),
            'duration': duration,
            'status': 'open'
        }, ttl=int(duration) + 10)

        logger.info(f"[TaskQueue] 开启竞标窗口: {task_id}, duration={duration}s")

    def is_bid_window_open(self, task_id: str) -> bool:
        """
        检查竞标窗口是否开启

        Args:
            task_id: 任务 ID

        Returns:
            True 如果窗口开启
        """
        key = f"{self.BID_PREFIX}{task_id}:window"
        window = redis_manager.get(key)

        if not window:
            return False

        elapsed = time.time() - window['start_time']
        return elapsed < window['duration']

    def submit_bid(self, task_id: str, agent_id: str, score: float, message: str = ""):
        """
        提交竞标

        Args:
            task_id: 任务 ID
            agent_id: Agent ID
            score: 竞标分数
            message: 竞标消息
        """
        key = f"{self.BID_PREFIX}{task_id}:bids"

        bid_data = {
            'agent_id': agent_id,
            'score': score,
            'message': message,
            'timestamp': time.time()
        }

        if redis_manager.client:
            try:
                # 使用 ZADD 按分数排序
                redis_manager.client.zadd(key, {json.dumps(bid_data): -score})
                logger.debug(f"[TaskQueue] 提交竞标: {task_id} <- {agent_id}, score={score}")
                return
            except Exception as e:
                logger.warning(f"[TaskQueue] 提交竞标失败: {e}")

        # 本地回退
        local_bids = redis_manager.get(key, [])
        local_bids.append(bid_data)
        redis_manager.set(key, local_bids)

    def get_bids(self, task_id: str) -> List[Dict[str, Any]]:
        """
        获取所有竞标

        Args:
            task_id: 任务 ID

        Returns:
            竞标列表（按分数降序）
        """
        key = f"{self.BID_PREFIX}{task_id}:bids"

        if redis_manager.client:
            try:
                results = redis_manager.client.zrange(key, 0, -1)
                return [json.loads(r) for r in results]
            except Exception as e:
                logger.warning(f"[TaskQueue] 获取竞标失败: {e}")

        return redis_manager.get(key, [])

    def select_winner(self, task_id: str) -> Optional[str]:
        """
        选择获胜者（分数最高）

        Args:
            task_id: 任务 ID

        Returns:
            获胜者 Agent ID
        """
        bids = self.get_bids(task_id)
        if not bids:
            return None

        # 分数最高的获胜
        winner = max(bids, key=lambda b: b.get('score', 0))
        logger.info(f"[TaskQueue] 竞标获胜: {task_id} -> {winner['agent_id']}")
        return winner['agent_id']

    def clear_bids(self, task_id: str):
        """
        清除竞标数据

        Args:
            task_id: 任务 ID
        """
        redis_manager.delete(f"{self.BID_PREFIX}{task_id}:window")
        redis_manager.delete(f"{self.BID_PREFIX}{task_id}:bids")
        logger.debug(f"[TaskQueue] 清除竞标数据: {task_id}")

    # ==================== 任务认领 ====================

    def claim_task(self, task_id: str, agent_id: str, ttl: int = 300) -> bool:
        """
        认领任务

        Args:
            task_id: 任务 ID
            agent_id: Agent ID
            ttl: 认领超时（秒）

        Returns:
            True 如果认领成功
        """
        key = f"{self.CLAIM_PREFIX}{task_id}"

        if redis_manager.client:
            try:
                # 添加前缀，确保与 redis_manager 一致
                full_key = redis_manager._make_key(key)
                # 序列化 agent_id
                import pickle
                data = pickle.dumps(agent_id)
                # 使用 SETNX 保证原子性
                acquired = redis_manager.client.set(
                    full_key, data, nx=True, ex=ttl
                )
                if acquired:
                    logger.info(f"[TaskQueue] 认领任务: {task_id} -> {agent_id}")
                    return True
                logger.debug(f"[TaskQueue] 任务已被认领: {task_id}")
                return False
            except Exception as e:
                logger.warning(f"[TaskQueue] 认领任务失败: {e}")

        # 本地回退
        existing = redis_manager.get(key)
        if existing:
            return False
        redis_manager.set(key, agent_id, ttl=ttl)
        return True

    def get_task_owner(self, task_id: str) -> Optional[str]:
        """
        获取任务持有者

        Args:
            task_id: 任务 ID

        Returns:
            持有者 Agent ID
        """
        key = f"{self.CLAIM_PREFIX}{task_id}"
        return redis_manager.get(key)

    def release_task(self, task_id: str):
        """
        释放任务

        Args:
            task_id: 任务 ID
        """
        key = f"{self.CLAIM_PREFIX}{task_id}"
        redis_manager.delete(key)
        logger.info(f"[TaskQueue] 释放任务: {task_id}")


# 全局实例
task_queue = TaskQueue()


# ==================== 导出 ====================

__all__ = [
    # 核心组件
    'redis_manager',
    'is_redis_available',

    # 专用缓存
    'session_cache',
    'distributed_lock',
    'bm25_cache',
    'task_queue',

    # 配置
    'REDIS_CONFIG',
]
