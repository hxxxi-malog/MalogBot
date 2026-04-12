"""
Bootstrap 数据结构定义

定义：
1. SessionType - 会话类型枚举
2. BootstrapConfig - Bootstrap 加载配置
3. BootstrapResult - Bootstrap 加载结果
4. BootstrapStats - 加载统计信息
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class SessionType(Enum):
    """会话类型枚举
    
    不同会话类型有不同的默认 Token 预算
    """
    MAIN_AGENT = "main_agent"          # 主 Agent，完整预算 15000 tokens
    SUB_AGENT = "sub_agent"            # 子 Agent，精简预算 3000 tokens
    BACKGROUND_TASK = "background"     # 后台任务，最小预算 500 tokens


@dataclass
class BootstrapStats:
    """Bootstrap 加载统计信息
    
    记录各知识块的加载详情
    """
    # 各知识块 Token 使用量
    soul_tokens: int = 0
    user_tokens: int = 0
    agents_tokens: int = 0
    memory_tokens: int = 0
    dynamic_tokens: int = 0
    
    # 各知识块加载条目数
    user_items_count: int = 0
    agents_rules_count: int = 0
    agents_mistakes_count: int = 0
    memory_items_count: int = 0
    dynamic_items_count: int = 0
    
    # 质量统计
    avg_score: float = 0.0
    filtered_count: int = 0  # 被质量门槛过滤的数量
    
    # 告警信息
    warnings: List[str] = field(default_factory=list)
    
    def add_warning(self, warning: str):
        """添加告警信息"""
        self.warnings.append(warning)
    
    @property
    def total_items_count(self) -> int:
        """总加载条目数"""
        return (
            self.user_items_count + 
            self.agents_rules_count + 
            self.agents_mistakes_count +
            self.memory_items_count + 
            self.dynamic_items_count
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'soul_tokens': self.soul_tokens,
            'user_tokens': self.user_tokens,
            'agents_tokens': self.agents_tokens,
            'memory_tokens': self.memory_tokens,
            'dynamic_tokens': self.dynamic_tokens,
            'user_items_count': self.user_items_count,
            'agents_rules_count': self.agents_rules_count,
            'agents_mistakes_count': self.agents_mistakes_count,
            'memory_items_count': self.memory_items_count,
            'dynamic_items_count': self.dynamic_items_count,
            'total_items_count': self.total_items_count,
            'avg_score': self.avg_score,
            'filtered_count': self.filtered_count,
            'warnings': self.warnings
        }


@dataclass
class BootstrapConfig:
    """Bootstrap 加载配置
    
    控制 Token 预算分配和质量门槛
    
    使用示例：
        # 使用默认配置
        config = BootstrapConfig()
        
        # 指定预算
        config = BootstrapConfig(knowledge_budget=10000)
        
        # 子 Agent 配置
        config = BootstrapConfig(session_type=SessionType.SUB_AGENT)
    """
    # 会话类型
    session_type: SessionType = SessionType.MAIN_AGENT
    
    # 知识库总预算（None 则使用会话类型默认值）
    knowledge_budget: Optional[int] = None
    
    # 质量门槛
    min_hybrid_score: float = 0.3    # 动态检索最低相关度
    min_importance: float = 0.5       # 知识条目最低重要性
    
    # 各知识块预算上限（按优先级顺序）
    soul_budget: int = 500            # SOUL 不可截断
    user_budget: int = 1000           # USER 可截断
    agents_budget: int = 2000         # AGENTS 可截断
    memory_budget: int = 8000         # MEMORY 可截断
    dynamic_budget: int = 3000        # 动态检索可截断
    
    # 是否启用各知识块
    enable_user: bool = True
    enable_agents: bool = True
    enable_memory: bool = True
    enable_dynamic: bool = True
    
    # 动态检索参数
    recall_multiplier: int = 3        # 召回倍数
    max_recall: int = 100             # 最大召回数量
    min_recall: int = 10              # 最小召回数量
    
    # 会话类型默认预算
    BUDGET_DEFAULTS = {
        SessionType.MAIN_AGENT: 15000,
        SessionType.SUB_AGENT: 3000,
        SessionType.BACKGROUND_TASK: 500
    }
    
    def get_total_budget(self) -> int:
        """
        获取总预算
        
        优先使用传入的 knowledge_budget，否则使用会话类型默认值
        
        Returns:
            总 Token 预算
        """
        if self.knowledge_budget is not None:
            return self.knowledge_budget
        return self.BUDGET_DEFAULTS.get(self.session_type, 15000)
    
    def calculate_recall_k(self, remaining_budget: int) -> int:
        """
        计算动态检索召回量
        
        Args:
            remaining_budget: 剩余 Token 预算
        
        Returns:
            召回数量
        """
        # 平均每条记忆约 30 tokens
        avg_memory_tokens = 30
        
        # 估算可容纳条数
        estimated_capacity = remaining_budget / avg_memory_tokens
        
        # 召回量 = 容量 × 召回倍数
        recall_k = int(estimated_capacity * self.recall_multiplier)
        
        # 限制范围
        recall_k = max(self.min_recall, min(recall_k, self.max_recall))
        
        return recall_k
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_type': self.session_type.value,
            'knowledge_budget': self.knowledge_budget,
            'total_budget': self.get_total_budget(),
            'min_hybrid_score': self.min_hybrid_score,
            'min_importance': self.min_importance,
            'soul_budget': self.soul_budget,
            'user_budget': self.user_budget,
            'agents_budget': self.agents_budget,
            'memory_budget': self.memory_budget,
            'dynamic_budget': self.dynamic_budget,
            'enable_user': self.enable_user,
            'enable_agents': self.enable_agents,
            'enable_memory': self.enable_memory,
            'enable_dynamic': self.enable_dynamic
        }


@dataclass
class BootstrapResult:
    """Bootstrap 加载结果
    
    包含组装好的系统提示词和详细统计信息
    
    使用示例：
        result = await bootstrap_service.load(config, user_query, session)
        
        print(f"System Prompt: {result.system_prompt}")
        print(f"Used Tokens: {result.used_tokens}/{result.budget}")
        print(f"Loaded Items: {result.stats.total_items_count}")
    """
    # 核心输出
    system_prompt: str
    used_tokens: int
    budget: int
    
    # 统计信息
    stats: BootstrapStats = field(default_factory=BootstrapStats)
    
    # 各知识块内容（用于调试）
    soul_content: str = ""
    user_content: str = ""
    agents_content: str = ""
    memory_content: str = ""
    dynamic_content: str = ""
    
    @property
    def remaining_tokens(self) -> int:
        """剩余 Token 预算"""
        return max(0, self.budget - self.used_tokens)
    
    @property
    def usage_ratio(self) -> float:
        """预算使用率"""
        if self.budget == 0:
            return 0.0
        return self.used_tokens / self.budget
    
    @property
    def is_within_budget(self) -> bool:
        """是否在预算内"""
        return self.used_tokens <= self.budget
    
    @property
    def has_warnings(self) -> bool:
        """是否有告警"""
        return len(self.stats.warnings) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'system_prompt': self.system_prompt[:500] + '...' if len(self.system_prompt) > 500 else self.system_prompt,
            'used_tokens': self.used_tokens,
            'budget': self.budget,
            'remaining_tokens': self.remaining_tokens,
            'usage_ratio': f"{self.usage_ratio:.1%}",
            'is_within_budget': self.is_within_budget,
            'has_warnings': self.has_warnings,
            'stats': self.stats.to_dict()
        }
    
    def get_debug_info(self) -> Dict[str, Any]:
        """获取调试信息（包含完整内容）"""
        return {
            'used_tokens': self.used_tokens,
            'budget': self.budget,
            'usage_ratio': self.usage_ratio,
            'stats': self.stats.to_dict(),
            'soul_content_length': len(self.soul_content),
            'user_content_length': len(self.user_content),
            'agents_content_length': len(self.agents_content),
            'memory_content_length': len(self.memory_content),
            'dynamic_content_length': len(self.dynamic_content)
        }


__all__ = [
    'SessionType',
    'BootstrapConfig',
    'BootstrapResult',
    'BootstrapStats'
]
