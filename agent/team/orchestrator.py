"""
团队编排器模块

统一管理Leader-Follower协作流程：
1. 接收用户请求
2. 路由决策
3. 单Agent模式或团队模式执行
4. 返回结果
"""
import logging
from typing import Dict, Any, List, Optional, Generator
from dataclasses import asdict

from agent.team.types import (
    ExecutionMode,
    TeamResult,
    RoutingDecision
)
from agent.team.router import IntentRouter
from agent.team.leader import LeaderAgent
from agent.team.task_board import TaskBoard

logger = logging.getLogger(__name__)


class AgentsTeam:
    """
    AgentsTeam - 多Agent团队编排器
    
    核心流程：
    1. 意图识别与路由（Leader Agent）
    2. 单Agent模式 -> 直接执行
    3. 团队模式 -> Leader拆解任务 -> Followers执行 -> Leader整合
    """
    
    def __init__(
        self,
        session_id: str,
        tools: List,
        session_store=None,
        max_followers: int = 3
    ):
        """
        初始化团队编排器
        
        Args:
            session_id: 会话ID
            tools: 可用工具列表
            session_store: 会话存储
            max_followers: 最大Follower数量
        """
        self.session_id = session_id
        self.tools = tools
        self.session_store = session_store
        self.max_followers = max_followers
        
        # Leader Agent
        self.leader = LeaderAgent(
            session_id=session_id,
            tools=tools,
            session_store=session_store,
            max_followers=max_followers
        )
        
        # 执行状态
        self._current_mode: Optional[ExecutionMode] = None
        self._last_decision: Optional[RoutingDecision] = None
    
    def process(
        self,
        user_input: str,
        chat_history: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        处理用户请求
        
        自动选择单Agent或团队模式执行
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            
        Returns:
            执行结果
        """
        logger.info(f"[AgentsTeam] 处理请求: {user_input[:50]}...")
        
        # 1. 意图识别与路由
        decision = self.leader.route(user_input, chat_history)
        self._last_decision = decision
        self._current_mode = decision.mode
        
        logger.info(f"[AgentsTeam] 路由决策: {decision.mode.value}, 复杂度: {decision.complexity.score}")
        
        # 2. 根据模式执行
        if decision.mode == ExecutionMode.SINGLE_AGENT:
            # 单Agent模式 - 返回特殊标记，由外部执行
            return {
                "mode": "single_agent",
                "decision": {
                    "category": decision.category.value,
                    "complexity_score": decision.complexity.score,
                    "reasoning": decision.reasoning
                },
                "should_delegate": True
            }
        
        else:
            # 团队模式
            return self._execute_team_mode(user_input, chat_history, decision)
    
    def process_stream(
        self,
        user_input: str,
        chat_history: List[Dict] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式处理用户请求，实时推送进度
        
        自动选择单Agent或团队模式执行
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            
        Yields:
            执行进度或结果
        """
        logger.info(f"[AgentsTeam] 流式处理请求: {user_input[:50]}...")
        
        # 1. 意图识别与路由
        decision = self.leader.route(user_input, chat_history)
        self._last_decision = decision
        self._current_mode = decision.mode
        
        logger.info(f"[AgentsTeam] 路由决策: {decision.mode.value}, 复杂度: {decision.complexity.score}")
        
        # 发送路由决策
        yield {
            "type": "routing_decision",
            "mode": decision.mode.value,
            "complexity_score": decision.complexity.score,
            "reasoning": decision.reasoning
        }
        
        # 2. 根据模式执行
        if decision.mode == ExecutionMode.SINGLE_AGENT:
            # 单Agent模式 - 返回特殊标记
            yield {
                "type": "single_agent_mode",
                "decision": {
                    "category": decision.category.value,
                    "complexity_score": decision.complexity.score,
                    "reasoning": decision.reasoning
                },
                "should_delegate": True
            }
        
        else:
            # 团队模式 - 流式执行
            yield from self._execute_team_mode_stream(user_input, chat_history, decision)
    
    def _execute_team_mode_stream(
        self,
        user_input: str,
        chat_history: List[Dict],
        decision: RoutingDecision
    ) -> Generator[Dict[str, Any], None, None]:
        """流式执行团队模式"""
        logger.info(f"[AgentsTeam] 进入团队模式(流式)")
        
        try:
            # 1. 任务拆解
            yield {"type": "task_decomposition", "message": "正在拆解任务..."}
            context = self._build_context(chat_history)
            plan = self.leader.decompose_task(user_input, context)
            
            # 2. 流式执行团队任务
            parallel = decision.complexity.parallelizable
            for progress in self.leader.execute_team_stream(parallel=parallel):
                yield progress
            
        except Exception as e:
            logger.error(f"[AgentsTeam] 流式团队执行失败: {e}")
            yield {
                "type": "team_error",
                "error": str(e)
            }
    
    def _execute_team_mode(
        self,
        user_input: str,
        chat_history: List[Dict],
        decision: RoutingDecision
    ) -> Dict[str, Any]:
        """
        执行团队模式
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            decision: 路由决策
            
        Returns:
            执行结果
        """
        logger.info(f"[AgentsTeam] 进入团队模式")
        
        try:
            # 1. 任务拆解
            context = self._build_context(chat_history)
            plan = self.leader.decompose_task(user_input, context)
            
            # 2. 执行团队任务
            parallel = decision.complexity.parallelizable
            result = self.leader.execute_team(parallel=parallel)
            
            # 3. 返回结果
            return {
                "mode": "team_mode",
                "success": result.success,
                "goal": result.goal,
                "final_output": result.final_output,
                "subtask_results": result.subtask_results,
                "execution_log": result.execution_log,
                "stats": {
                    "total_time": result.total_time,
                    "followers_used": result.followers_used,
                    "parallelism_achieved": result.parallelism_achieved,
                    "total_tasks": len(plan.subtasks),
                    "completed_tasks": sum(
                        1 for t in plan.subtasks.values()
                        if t.status.value == "completed"
                    )
                },
                "decision": {
                    "category": decision.category.value,
                    "complexity_score": decision.complexity.score,
                    "reasoning": decision.reasoning
                }
            }
            
        except Exception as e:
            logger.error(f"[AgentsTeam] 团队模式执行失败: {e}")
            return {
                "mode": "team_mode",
                "success": False,
                "error": str(e),
                "final_output": f"团队执行失败: {str(e)}"
            }
    
    def _build_context(self, chat_history: List[Dict]) -> str:
        """构建上下文"""
        if not chat_history:
            return ""
        
        # 取最近3轮对话
        recent = chat_history[-6:] if len(chat_history) > 6 else chat_history
        context_parts = []
        
        for msg in recent:
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]
            context_parts.append(f"{role}: {content}")
        
        return "\n".join(context_parts)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取当前状态
        
        Returns:
            状态信息
        """
        status = {
            "session_id": self.session_id,
            "current_mode": self._current_mode.value if self._current_mode else None,
            "last_decision": asdict(self._last_decision) if self._last_decision else None,
            "task_board": self.leader.task_board.get_progress()
        }
        
        return status
    
    def get_task_board_view(self) -> str:
        """
        获取任务看板视图
        
        Returns:
            格式化的任务看板字符串
        """
        return self.leader.task_board.render()


# ==================== 会话级管理 ====================

_teams: Dict[str, AgentsTeam] = {}


def get_agents_team(
    session_id: str,
    tools: List,
    session_store=None,
    max_followers: int = 3
) -> AgentsTeam:
    """
    获取或创建会话的AgentsTeam
    """
    if session_id not in _teams:
        _teams[session_id] = AgentsTeam(
            session_id=session_id,
            tools=tools,
            session_store=session_store,
            max_followers=max_followers
        )
    return _teams[session_id]


def remove_agents_team(session_id: str):
    """删除会话的AgentsTeam"""
    if session_id in _teams:
        del _teams[session_id]


# 导出
__all__ = [
    'AgentsTeam',
    'get_agents_team',
    'remove_agents_team'
]
