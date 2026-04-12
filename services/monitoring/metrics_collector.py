"""
监控指标收集器

收集知识库系统的关键指标：
1. Bootstrap 加载指标
2. 检索质量指标
3. 知识库状态指标
4. 踩坑重复率

设计理念：
- 轻量级：使用内存存储，定期持久化
- 非阻塞：指标收集不影响主流程
- 可观测：支持导出为 Prometheus 格式
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from collections import deque
import json

logger = logging.getLogger(__name__)


# ==================== 指标数据结构 ====================

@dataclass
class BootstrapMetrics:
    """Bootstrap 加载指标"""
    timestamp: datetime
    used_tokens: int
    budget: int
    usage_ratio: float
    
    # 各知识块 Token 分布
    soul_tokens: int = 0
    user_tokens: int = 0
    agents_tokens: int = 0
    memory_tokens: int = 0
    dynamic_tokens: int = 0
    
    # 质量指标
    avg_score: float = 0.0
    total_items: int = 0
    filtered_count: int = 0
    
    # 会话信息
    session_type: str = "main_agent"
    user_query_hash: str = ""  # 查询的哈希值（用于聚合分析）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "used_tokens": self.used_tokens,
            "budget": self.budget,
            "usage_ratio": self.usage_ratio,
            "soul_tokens": self.soul_tokens,
            "user_tokens": self.user_tokens,
            "agents_tokens": self.agents_tokens,
            "memory_tokens": self.memory_tokens,
            "dynamic_tokens": self.dynamic_tokens,
            "avg_score": self.avg_score,
            "total_items": self.total_items,
            "filtered_count": self.filtered_count,
            "session_type": self.session_type
        }


@dataclass
class RetrievalMetrics:
    """检索质量指标"""
    timestamp: datetime
    query: str
    top_k: int
    
    # 结果统计
    result_count: int = 0
    avg_score: float = 0.0
    max_score: float = 0.0
    min_score: float = 0.0
    
    # 时间统计
    vector_time_ms: float = 0.0  # 向量检索耗时
    bm25_time_ms: float = 0.0   # BM25 检索耗时
    total_time_ms: float = 0.0  # 总耗时
    
    # 过滤统计
    filtered_by_threshold: int = 0  # 被门槛过滤的数量
    filtered_by_mmr: int = 0        # 被 MMR 过滤的数量
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "query": self.query[:50],  # 截断查询
            "top_k": self.top_k,
            "result_count": self.result_count,
            "avg_score": self.avg_score,
            "max_score": self.max_score,
            "min_score": self.min_score,
            "total_time_ms": self.total_time_ms
        }


@dataclass
class KnowledgeMetrics:
    """知识库状态指标"""
    timestamp: datetime
    
    # 条目统计
    total_items: int = 0
    user_items: int = 0
    memory_items: int = 0
    agent_rules: int = 0
    agent_mistakes: int = 0
    
    # 质量统计
    avg_importance: float = 0.0
    expired_items: int = 0
    unrefined_items: int = 0  # 未提炼的记忆
    
    # 访问统计
    total_access_count: int = 0
    never_accessed: int = 0  # 从未被访问的条目
    
    # 踩坑统计
    unresolved_mistakes: int = 0  # 未解决的踩坑
    repeat_mistakes: int = 0      # 重复发生的踩坑
    mistake_repeat_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_items": self.total_items,
            "user_items": self.user_items,
            "memory_items": self.memory_items,
            "agent_rules": self.agent_rules,
            "agent_mistakes": self.agent_mistakes,
            "avg_importance": self.avg_importance,
            "expired_items": self.expired_items,
            "unrefined_items": self.unrefined_items,
            "total_access_count": self.total_access_count,
            "never_accessed": self.never_accessed,
            "unresolved_mistakes": self.unresolved_mistakes,
            "repeat_mistakes": self.repeat_mistakes,
            "mistake_repeat_rate": self.mistake_repeat_rate
        }


# ==================== 指标收集器 ====================

class MetricsCollector:
    """监控指标收集器
    
    收集和管理知识库系统的各类指标，支持：
    1. 实时指标记录
    2. 时间窗口聚合统计
    3. 告警规则检查
    4. Prometheus 格式导出
    
    使用示例：
        collector = MetricsCollector()
        
        # 记录 Bootstrap 加载指标
        collector.record_bootstrap(metrics)
        
        # 记录检索指标
        collector.record_retrieval(metrics)
        
        # 获取聚合统计
        stats = collector.get_bootstrap_stats(hours=24)
    """
    
    # 告警阈值配置
    ALERT_THRESHOLDS = {
        "bootstrap_usage_high": 0.9,      # Bootstrap 使用率 > 90%
        "bootstrap_usage_low": 0.3,       # Bootstrap 使用率 < 30%
        "avg_score_low": 0.4,             # 平均分数 < 0.4
        "retrieval_time_high_ms": 500,    # 检索耗时 > 500ms
        "mistake_repeat_rate_high": 0.2,  # 踩坑重复率 > 20%
    }
    
    def __init__(self, max_records: int = 1000):
        """
        初始化指标收集器
        
        Args:
            max_records: 每类指标最大保留记录数
        """
        self.max_records = max_records
        
        # 使用 deque 实现固定大小的环形缓冲区
        self._bootstrap_metrics: deque = deque(maxlen=max_records)
        self._retrieval_metrics: deque = deque(maxlen=max_records)
        self._knowledge_metrics: deque = deque(maxlen=100)  # 状态指标保留少一些
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 告警记录
        self._alerts: deque = deque(maxlen=100)
        
        logger.info(f"[MetricsCollector] 初始化完成，最大记录数: {max_records}")
    
    # ==================== 记录指标 ====================
    
    def record_bootstrap(self, metrics: BootstrapMetrics) -> List[Dict]:
        """
        记录 Bootstrap 加载指标
        
        Args:
            metrics: Bootstrap 指标数据
            
        Returns:
            触发的告警列表
        """
        alerts = []
        
        with self._lock:
            self._bootstrap_metrics.append(metrics)
            
            # 检查告警条件
            if metrics.usage_ratio > self.ALERT_THRESHOLDS["bootstrap_usage_high"]:
                alert = self._create_alert(
                    level="warning",
                    type="bootstrap_usage_high",
                    message=f"Bootstrap 使用率过高: {metrics.usage_ratio:.1%}",
                    details=metrics.to_dict()
                )
                alerts.append(alert)
                self._alerts.append(alert)
                
            elif metrics.usage_ratio < self.ALERT_THRESHOLDS["bootstrap_usage_low"]:
                alert = self._create_alert(
                    level="info",
                    type="bootstrap_usage_low",
                    message=f"Bootstrap 使用率过低: {metrics.usage_ratio:.1%}，可能知识库内容不足",
                    details=metrics.to_dict()
                )
                alerts.append(alert)
                self._alerts.append(alert)
            
            if metrics.avg_score < self.ALERT_THRESHOLDS["avg_score_low"] and metrics.total_items > 0:
                alert = self._create_alert(
                    level="warning",
                    type="low_quality",
                    message=f"Bootstrap 加载质量过低: avg_score={metrics.avg_score:.2f}",
                    details=metrics.to_dict()
                )
                alerts.append(alert)
                self._alerts.append(alert)
        
        if alerts:
            for alert in alerts:
                logger.warning(f"[MetricsCollector] 告警: {alert['message']}")
        
        return alerts
    
    def record_retrieval(self, metrics: RetrievalMetrics) -> List[Dict]:
        """
        记录检索指标
        
        Args:
            metrics: 检索指标数据
            
        Returns:
            触发的告警列表
        """
        alerts = []
        
        with self._lock:
            self._retrieval_metrics.append(metrics)
            
            # 检查检索耗时告警
            if metrics.total_time_ms > self.ALERT_THRESHOLDS["retrieval_time_high_ms"]:
                alert = self._create_alert(
                    level="warning",
                    type="retrieval_slow",
                    message=f"检索耗时过长: {metrics.total_time_ms:.0f}ms",
                    details=metrics.to_dict()
                )
                alerts.append(alert)
                self._alerts.append(alert)
        
        return alerts
    
    def record_knowledge(self, metrics: KnowledgeMetrics) -> List[Dict]:
        """
        记录知识库状态指标
        
        Args:
            metrics: 知识库状态指标
            
        Returns:
            触发的告警列表
        """
        alerts = []
        
        with self._lock:
            self._knowledge_metrics.append(metrics)
            
            # 检查踩坑重复率告警
            if metrics.mistake_repeat_rate > self.ALERT_THRESHOLDS["mistake_repeat_rate_high"]:
                alert = self._create_alert(
                    level="warning",
                    type="high_mistake_repeat",
                    message=f"踩坑重复率过高: {metrics.mistake_repeat_rate:.1%}",
                    details=metrics.to_dict()
                )
                alerts.append(alert)
                self._alerts.append(alert)
        
        return alerts
    
    # ==================== 聚合统计 ====================
    
    def get_bootstrap_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取 Bootstrap 加载的聚合统计
        
        Args:
            hours: 统计时间窗口（小时）
            
        Returns:
            聚合统计数据
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            recent = [m for m in self._bootstrap_metrics if m.timestamp >= cutoff]
        
        if not recent:
            return {
                "count": 0,
                "time_range_hours": hours,
                "message": "无数据"
            }
        
        # 计算聚合指标
        total_count = len(recent)
        avg_usage_ratio = sum(m.usage_ratio for m in recent) / total_count
        avg_used_tokens = sum(m.used_tokens for m in recent) / total_count
        avg_avg_score = sum(m.avg_score for m in recent if m.avg_score > 0) / max(1, sum(1 for m in recent if m.avg_score > 0))
        avg_items = sum(m.total_items for m in recent) / total_count
        
        # Token 分布统计
        token_dist = {
            "soul": sum(m.soul_tokens for m in recent) / total_count,
            "user": sum(m.user_tokens for m in recent) / total_count,
            "agents": sum(m.agents_tokens for m in recent) / total_count,
            "memory": sum(m.memory_tokens for m in recent) / total_count,
            "dynamic": sum(m.dynamic_tokens for m in recent) / total_count
        }
        
        return {
            "count": total_count,
            "time_range_hours": hours,
            "avg_usage_ratio": round(avg_usage_ratio, 3),
            "avg_used_tokens": round(avg_used_tokens),
            "avg_avg_score": round(avg_avg_score, 3),
            "avg_items": round(avg_items, 1),
            "token_distribution": {k: round(v, 0) for k, v in token_dist.items()},
            "max_usage_ratio": round(max(m.usage_ratio for m in recent), 3),
            "min_usage_ratio": round(min(m.usage_ratio for m in recent), 3)
        }
    
    def get_retrieval_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        获取检索的聚合统计
        
        Args:
            hours: 统计时间窗口（小时）
            
        Returns:
            聚合统计数据
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        with self._lock:
            recent = [m for m in self._retrieval_metrics if m.timestamp >= cutoff]
        
        if not recent:
            return {
                "count": 0,
                "time_range_hours": hours,
                "message": "无数据"
            }
        
        total_count = len(recent)
        avg_time = sum(m.total_time_ms for m in recent) / total_count
        avg_score = sum(m.avg_score for m in recent) / total_count
        avg_result_count = sum(m.result_count for m in recent) / total_count
        
        return {
            "count": total_count,
            "time_range_hours": hours,
            "avg_time_ms": round(avg_time, 2),
            "avg_score": round(avg_score, 3),
            "avg_result_count": round(avg_result_count, 1),
            "max_time_ms": round(max(m.total_time_ms for m in recent), 2),
            "p95_time_ms": round(self._percentile([m.total_time_ms for m in recent], 95), 2)
        }
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """
        获取最新的知识库状态统计
        
        Returns:
            最新的知识库状态
        """
        with self._lock:
            if not self._knowledge_metrics:
                return {"message": "无数据"}
            latest = self._knowledge_metrics[-1]
        
        return latest.to_dict()
    
    def get_alerts(self, limit: int = 20) -> List[Dict]:
        """
        获取最近的告警记录
        
        Args:
            limit: 返回数量限制
            
        Returns:
            告警记录列表
        """
        with self._lock:
            return list(self._alerts)[-limit:]
    
    # ==================== Prometheus 导出 ====================
    
    def export_prometheus(self) -> str:
        """
        导出 Prometheus 格式的指标
        
        Returns:
            Prometheus 格式的指标文本
        """
        lines = []
        
        # Bootstrap 指标
        bootstrap_stats = self.get_bootstrap_stats(hours=1)
        if bootstrap_stats.get("count", 0) > 0:
            lines.append("# HELP bootstrap_loads_total Total bootstrap loads in the last hour")
            lines.append("# TYPE bootstrap_loads_total gauge")
            lines.append(f"bootstrap_loads_total {bootstrap_stats['count']}")
            
            lines.append("# HELP bootstrap_usage_ratio_avg Average bootstrap usage ratio")
            lines.append("# TYPE bootstrap_usage_ratio_avg gauge")
            lines.append(f"bootstrap_usage_ratio_avg {bootstrap_stats.get('avg_usage_ratio', 0)}")
            
            lines.append("# HELP bootstrap_avg_score Average quality score")
            lines.append("# TYPE bootstrap_avg_score gauge")
            lines.append(f"bootstrap_avg_score {bootstrap_stats.get('avg_avg_score', 0)}")
        
        # 检索指标
        retrieval_stats = self.get_retrieval_stats(hours=1)
        if retrieval_stats.get("count", 0) > 0:
            lines.append("# HELP retrieval_requests_total Total retrieval requests")
            lines.append("# TYPE retrieval_requests_total gauge")
            lines.append(f"retrieval_requests_total {retrieval_stats['count']}")
            
            lines.append("# HELP retrieval_time_ms_avg Average retrieval time in ms")
            lines.append("# TYPE retrieval_time_ms_avg gauge")
            lines.append(f"retrieval_time_ms_avg {retrieval_stats.get('avg_time_ms', 0)}")
        
        # 知识库指标 - 自动收集
        try:
            from services.db_manager import db_manager
            with db_manager.get_session() as db_session:
                from services.monitoring.metrics_collector import collect_knowledge_metrics
                collect_knowledge_metrics(db_session)
        except Exception as e:
            pass  # 忽略收集错误
        
        knowledge_stats = self.get_knowledge_stats()
        if "total_items" in knowledge_stats:
            lines.append("# HELP knowledge_items_total Total knowledge items")
            lines.append("# TYPE knowledge_items_total gauge")
            lines.append(f"knowledge_items_total {knowledge_stats['total_items']}")
            
            lines.append("# HELP mistake_repeat_rate Mistake repeat rate")
            lines.append("# TYPE mistake_repeat_rate gauge")
            lines.append(f"mistake_repeat_rate {knowledge_stats.get('mistake_repeat_rate', 0)}")
        
        return "\n".join(lines) if lines else "# No metrics available"
    
    # ==================== 辅助方法 ====================
    
    def _create_alert(
        self,
        level: str,
        type: str,
        message: str,
        details: Dict
    ) -> Dict:
        """创建告警记录"""
        return {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "type": type,
            "message": message,
            "details": details
        }
    
    def _percentile(self, values: List[float], p: int) -> float:
        """计算百分位数"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]


# ==================== 全局实例 ====================

metrics_collector = MetricsCollector()


# ==================== 便捷函数 ====================

def record_bootstrap_from_result(result, session_type: str = "main_agent"):
    """
    从 BootstrapResult 记录指标
    
    Args:
        result: BootstrapResult 对象
        session_type: 会话类型
    """
    metrics = BootstrapMetrics(
        timestamp=datetime.now(),
        used_tokens=result.used_tokens,
        budget=result.budget,
        usage_ratio=result.usage_ratio,
        soul_tokens=result.stats.soul_tokens,
        user_tokens=result.stats.user_tokens,
        agents_tokens=result.stats.agents_tokens,
        memory_tokens=result.stats.memory_tokens,
        dynamic_tokens=result.stats.dynamic_tokens,
        avg_score=result.stats.avg_score,
        total_items=result.stats.total_items_count,
        filtered_count=result.stats.filtered_count,
        session_type=session_type
    )
    return metrics_collector.record_bootstrap(metrics)


def collect_knowledge_metrics(db_session) -> KnowledgeMetrics:
    """
    收集知识库状态指标
    
    Args:
        db_session: 数据库会话
        
    Returns:
        KnowledgeMetrics 对象
    """
    from services.agent_knowledge_repository import (
        knowledge_item_repo_enhanced,
        agent_rule_repo,
        agent_mistake_repo
    )
    from sqlalchemy import func
    
    # 收集各类统计
    now = datetime.now()
    
    # 知识条目统计
    total_items = knowledge_item_repo_enhanced.count(db_session)
    user_items = knowledge_item_repo_enhanced.count_by_source(db_session, 'user')
    memory_items = knowledge_item_repo_enhanced.count_by_source(db_session, 'memory')
    
    # 规则统计
    agent_rules = agent_rule_repo.count_active(db_session)
    
    # 踩坑统计
    agent_mistakes = agent_mistake_repo.count(db_session)
    unresolved_mistakes = agent_mistake_repo.count_unresolved(db_session)
    repeat_mistakes = agent_mistake_repo.count_repeat(db_session)
    
    # 计算踩坑重复率
    mistake_repeat_rate = repeat_mistakes / agent_mistakes if agent_mistakes > 0 else 0.0
    
    # 其他统计（简化版本，实际可能需要更复杂的查询）
    metrics = KnowledgeMetrics(
        timestamp=now,
        total_items=total_items,
        user_items=user_items,
        memory_items=memory_items,
        agent_rules=agent_rules,
        agent_mistakes=agent_mistakes,
        unresolved_mistakes=unresolved_mistakes,
        repeat_mistakes=repeat_mistakes,
        mistake_repeat_rate=mistake_repeat_rate
    )
    
    # 记录到收集器
    metrics_collector.record_knowledge(metrics)
    
    return metrics
