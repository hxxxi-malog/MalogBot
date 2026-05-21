"""
Redis STREAM 事件缓存模块

为 Deep Research 的 SSE 推送提供持久化事件缓存，支持：
- 基于 Redis STREAM 的可靠事件写入（XADD）和回放（XRANGE）
- 自动长度控制（XTRIM）和过期清理（EXPIRE/DEL）
- Redis 不可用时降级到内存 collections.deque，保证实时推送不中断
- 指数退避重试连接 Redis（1s, 2s, 4s, 8s，最多 4 次，失败抛错）
"""
import json
import logging
import threading
import time
from collections import deque
from typing import Any

from services.redis_service import redis_manager, is_redis_available

logger = logging.getLogger(__name__)

# STREAM Key 前缀，与 redis_manager.PREFIX 保持一致
_STREAM_PREFIX = "malogbot:research:events:"
# 单个 STREAM 最大事件数（近似截断）
_MAX_STREAM_LEN = 500
# STREAM 默认过期时间（秒），24 小时
_DEFAULT_TTL = 86400
# Redis 连接重试间隔（秒），指数退避：1, 2, 4, 8
_REDIS_RETRY_DELAYS = [1, 2, 4, 8]


class EventBuffer:
    """基于 Redis STREAM 的事件缓存。

    每个 task_id 对应一个独立的 Redis STREAM（key: malogbot:research:events:{task_id}），
    利用 Redis STREAM 自增 ID（形如 1716278400000-0）实现天然单调递增的事件序号。

    Redis 不可用时降级到进程内 deque，此时：
    - write() 返回空字符串（无持久化 ID）
    - replay() 返回 deque 中的内存数据
    - 不提供跨进程/重启的回放能力，但保证实时推送不中断

    Redis 连接采用指数退避重试策略：
    - 首次失败后等待 1s 重试，依次 2s、4s、8s
    - 4 次重试均失败后抛出 RuntimeError
    - 连接成功后，运行时 Redis 断开会自动降级到内存模式
    - 下次 write/replay 调用时会重新尝试连接
    """

    def __init__(self) -> None:
        self._redis = None
        self._redis_connected = False
        # 内存降级：每个 task_id 一个 deque
        self._fallback: dict[str, deque] = {}
        self._fallback_lock = threading.Lock()
        # 已设置过 expire 的 stream key 集合，避免重复调用
        self._expire_set: set[str] = set()
        self._expire_lock = threading.Lock()

    # ---- 内部工具 ----

    def _connect_redis_with_retry(self):
        """使用指数退避策略连接 Redis。

        重试间隔：1s, 2s, 4s, 8s（共 4 次重试）。
        全部失败后抛出 RuntimeError。
        """
        for attempt, delay in enumerate(_REDIS_RETRY_DELAYS, 1):
            logger.warning(
                f"[EventBuffer] Redis not available, retrying in {delay}s "
                f"(attempt {attempt}/{len(_REDIS_RETRY_DELAYS)})"
            )
            time.sleep(delay)
            if is_redis_available():
                self._redis = redis_manager.client
                self._redis_connected = True
                logger.info(f"[EventBuffer] Redis connected on attempt {attempt}, using Redis STREAM")
                return

        # 所有重试均失败
        self._redis_connected = True  # 标记已尝试过，避免无限重试初始化阶段
        raise RuntimeError(
            f"[EventBuffer] Failed to connect to Redis after {len(_REDIS_RETRY_DELAYS)} retries "
            f"(delays: {_REDIS_RETRY_DELAYS}s). Falling back to in-memory deque."
        )

    def _get_redis(self):
        """获取 Redis 客户端，不可用返回 None。

        首次调用时使用指数退避重试连接 Redis。
        运行时如果 Redis 连接失效（XADD/XRANGE 异常），会降级到内存模式，
        并在下次调用时重新尝试连接。
        """
        # 已连接成功，直接返回
        if self._redis is not None and self._redis_connected:
            return self._redis

        # 尚未尝试过连接
        if not self._redis_connected:
            if is_redis_available():
                self._redis = redis_manager.client
                self._redis_connected = True
                logger.info("[EventBuffer] Redis available, using Redis STREAM")
                return self._redis
            else:
                # 首次连接失败，使用指数退避重试
                try:
                    self._connect_redis_with_retry()
                    return self._redis
                except RuntimeError as e:
                    logger.error(str(e))
                    self._redis = None
                    return None

        # 之前连接失败过，检查 Redis 是否已恢复
        if self._redis is None and is_redis_available():
            try:
                client = redis_manager.client
                # 简单 ping 验证连接可用
                client.ping()
                self._redis = client
                logger.info("[EventBuffer] Redis recovered, switching back to Redis STREAM")
                return self._redis
            except Exception as e:
                logger.debug(f"[EventBuffer] Redis recovery check failed: {e}")
                return None

        return self._redis

    def _stream_key(self, task_id: str) -> str:
        return f"{_STREAM_PREFIX}{task_id}"

    def _get_fallback(self, task_id: str) -> deque:
        """获取或创建指定 task_id 的降级 deque。"""
        with self._fallback_lock:
            if task_id not in self._fallback:
                self._fallback[task_id] = deque(maxlen=_MAX_STREAM_LEN)
            return self._fallback[task_id]

    def _set_expire_if_first(self, redis, stream_key: str) -> None:
        """仅在首次写入时设置 EXPIRE，避免每次 write 重复调用。"""
        with self._expire_lock:
            if stream_key not in self._expire_set:
                try:
                    redis.expire(stream_key, _DEFAULT_TTL)
                    self._expire_set.add(stream_key)
                    logger.debug(f"[EventBuffer] Set EXPIRE for new stream: {stream_key}")
                except Exception as e:
                    logger.warning(f"[EventBuffer] EXPIRE failed for {stream_key}: {e}")

    # ---- 公共接口 ----

    def write(self, task_id: str, event_type: str, data: dict[str, Any]) -> str:
        """写入事件到 Redis STREAM，返回 Redis 自增 ID。

        Args:
            task_id: 任务 ID
            event_type: 事件类型
            data: 事件数据

        Returns:
            Redis STREAM ID（如 "1716278400000-0"），降级时返回空字符串
        """
        redis = self._get_redis()
        stream_key = self._stream_key(task_id)

        if redis is not None:
            try:
                # XADD 自动生成递增 ID
                seq_no = redis.xadd(
                    stream_key,
                    {"event_type": event_type, "data": json.dumps(data, ensure_ascii=False)},
                    maxlen=f"~{_MAX_STREAM_LEN}",
                    id="*",
                )
                # 仅首次写入时设置过期时间
                self._set_expire_if_first(redis, stream_key)
                logger.debug(
                    f"[EventBuffer] XADD success: task={task_id} seq_no={seq_no} event={event_type}"
                )
                # 同步写入降级 deque（双重保障：Redis 重启后 deque 仍可短期回放）
                fallback = self._get_fallback(task_id)
                seq_no_str = seq_no.decode("utf-8") if isinstance(seq_no, bytes) else str(seq_no)
                fallback.append(
                    {"seq_no": seq_no_str, "event_type": event_type, "data": data}
                )
                return seq_no_str
            except Exception as e:
                logger.warning(f"[EventBuffer] XADD failed: task={task_id} error={e}, falling back to memory")
                # 标记 Redis 连接可能已断开，下次 _get_redis 会重新尝试恢复
                self._redis = None
        else:
            logger.debug(f"[EventBuffer] Redis unavailable, writing to memory: task={task_id} event={event_type}")

        # 降级：写入内存 deque
        fallback = self._get_fallback(task_id)
        fallback.append({"seq_no": "", "event_type": event_type, "data": data})
        return ""

    def replay(self, task_id: str, after_seq_no: str = "0-0") -> list[dict]:
        """回放指定 task_id 的历史事件。

        Args:
            task_id: 任务 ID
            after_seq_no: 从此 ID 之后开始回放（开区间），"0-0" 表示从头回放

        Returns:
            事件列表，每项包含 seq_no、event_type、data
        """
        redis = self._get_redis()
        stream_key = self._stream_key(task_id)

        if redis is not None:
            try:
                # XRANGE 按 ID 范围读取，(after_seq_no 表示开区间
                raw_events = redis.xrange(stream_key, min=f"({after_seq_no}", max="+", count=_MAX_STREAM_LEN)
                events = []
                for eid, fields in raw_events:
                    seq = eid.decode("utf-8") if isinstance(eid, bytes) else str(eid)
                    evt_type = fields.get(b"event_type", fields.get("event_type", ""))
                    raw_data = fields.get(b"data", fields.get("data", "{}"))
                    if isinstance(evt_type, bytes):
                        evt_type = evt_type.decode("utf-8")
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode("utf-8")
                    events.append({
                        "seq_no": seq,
                        "event_type": evt_type,
                        "data": json.loads(raw_data) if isinstance(raw_data, str) else raw_data,
                    })
                logger.info(
                    f"[EventBuffer] XRANGE replay: task={task_id} after={after_seq_no} count={len(events)}"
                )
                return events
            except Exception as e:
                logger.warning(f"[EventBuffer] XRANGE failed: task={task_id} error={e}, falling back to memory")
                self._redis = None

        # 降级：从内存 deque 读取
        fallback = self._get_fallback(task_id)
        if after_seq_no and after_seq_no != "0-0":
            # deque 中 seq_no 为空字符串（降级写入），无法精确过滤
            # 简化处理：降级模式下跳过过滤，返回全部事件
            logger.debug(f"[EventBuffer] Memory fallback: cannot filter after {after_seq_no}, returning all events")
        result = list(fallback)
        logger.info(f"[EventBuffer] Memory replay: task={task_id} count={len(result)}")
        return result

    def get_latest_seq_no(self, task_id: str) -> str:
        """获取指定 task_id 的最新事件 ID。

        Returns:
            最新 Redis STREAM ID，降级时返回 "0-0"
        """
        redis = self._get_redis()
        stream_key = self._stream_key(task_id)

        if redis is not None:
            try:
                result = redis.xrevrange(stream_key, max="+", count=1)
                if result:
                    eid = result[0][0]
                    return eid.decode("utf-8") if isinstance(eid, bytes) else str(eid)
                return "0-0"
            except Exception as e:
                logger.warning(f"[EventBuffer] get_latest_seq_no failed: task={task_id} error={e}")
                self._redis = None

        return "0-0"

    def clear(self, task_id: str) -> None:
        """清理指定 task_id 的 STREAM 和内存缓存。"""
        redis = self._get_redis()
        stream_key = self._stream_key(task_id)

        if redis is not None:
            try:
                redis.delete(stream_key)
                logger.info(f"[EventBuffer] DEL stream: task={task_id}")
            except Exception as e:
                logger.warning(f"[EventBuffer] DEL failed: task={task_id} error={e}")
                self._redis = None

        with self._fallback_lock:
            self._fallback.pop(task_id, None)

        with self._expire_lock:
            self._expire_set.discard(stream_key)

    def clear_expired(self) -> None:
        """扫描并清理所有已过期的内存降级缓存。

        Redis STREAM 自带 EXPIRE 机制，此处仅清理内存 deque。
        对于内存 deque，当条目超过 _MAX_STREAM_LEN 时会自动淘汰旧条目。
        此方法可用于主动清理不再活跃的 task_id 缓存。
        """
        # 内存 deque 已设置 maxlen，无需主动清理
        # 此接口预留用于未来扩展（如扫描 Redis 中无 TTL 的孤立项）
        pass


# 全局单例
event_buffer = EventBuffer()
