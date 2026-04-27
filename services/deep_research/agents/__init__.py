"""
专家型 Agent 模块

实现三类专家型 Agent，各司其职：
- ExplorerAgent: 探索型，负责搜索、发现信息、去重
- AnalyzerAgent: 分析型，负责阶段性分析单个研究方向
- SynthesizerAgent: 总结型，负责阶段性总结和全篇报告
"""

from services.deep_research.agents.base import (
    BaseExpertAgent,
    AgentResult,
    AgentContext,
)
from services.deep_research.agents.explorer_agent import ExplorerAgent
from services.deep_research.agents.analyzer_agent import AnalyzerAgent
from services.deep_research.agents.synthesizer_agent import SynthesizerAgent

__all__ = [
    # 基类
    'BaseExpertAgent',
    'AgentResult',
    'AgentContext',
    # 专家型 Agent
    'ExplorerAgent',
    'AnalyzerAgent',
    'SynthesizerAgent',
]
