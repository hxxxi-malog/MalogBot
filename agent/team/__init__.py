"""
多Agent团队协作系统

实现Leader-Follower模式：
- Leader Agent：意图识别、任务拆解、DAG构建、监控、结果整合
- Follower Agent：任务执行、结果汇报

核心组件：
1. LeaderAgent：负责规划和协调
2. TaskBoard：任务看板，DAG依赖管理
3. FollowerPool：Follower池管理
4. AgentsTeam：团队编排器

使用方式：
```python
from agent.team import AgentsTeam, get_agents_team

# 创建团队编排器
team = get_agents_team(
    session_id="session_123",
    tools=available_tools,
    session_store=session_store
)

# 处理请求（自动路由）
result = team.process(user_input, chat_history)

if result["mode"] == "single_agent":
    # 单Agent模式，由外部执行
    pass
else:
    # 团队模式，已执行完成
    print(result["final_output"])
```
"""

from agent.team.types import (
    QueryCategory,
    ExecutionMode,
    AgentRole,
    TaskStatus,
    TaskPriority,
    ComplexityAssessment,
    RoutingDecision,
    SubTask,
    DAGPlan,
    FollowerInfo,
    TeamResult
)

from agent.team.router import (
    IntentRouter,
    get_router
)

from agent.team.task_board import (
    TaskBoard,
    get_task_board,
    remove_task_board
)

from agent.team.follower import (
    FollowerAgent,
    FollowerPool,
    FOLLOWER_SYSTEM_PROMPT
)

from agent.team.leader import (
    LeaderAgent,
    DECOMPOSITION_SYSTEM_PROMPT,
    INTEGRATION_SYSTEM_PROMPT
)

from agent.team.orchestrator import (
    AgentsTeam,
    get_agents_team,
    remove_agents_team
)

__all__ = [
    # Types
    'QueryCategory',
    'ExecutionMode',
    'AgentRole',
    'TaskStatus',
    'TaskPriority',
    'ComplexityAssessment',
    'RoutingDecision',
    'SubTask',
    'DAGPlan',
    'FollowerInfo',
    'TeamResult',
    
    # Router
    'IntentRouter',
    'get_router',
    
    # TaskBoard
    'TaskBoard',
    'get_task_board',
    'remove_task_board',
    
    # Follower
    'FollowerAgent',
    'FollowerPool',
    'FOLLOWER_SYSTEM_PROMPT',
    
    # Leader
    'LeaderAgent',
    'DECOMPOSITION_SYSTEM_PROMPT',
    'INTEGRATION_SYSTEM_PROMPT',
    
    # Orchestrator
    'AgentsTeam',
    'get_agents_team',
    'remove_agents_team'
]
