"""
Agent 工具模块

提供工具注册和使用能力。

使用 Registry 模式：
- 工具声明即注册，无需手动管理
- 新增工具只需在模块中定义并注册

快速开始：
    from agent.tools import registry, ToolCategory
    from agent.tools.registry import register_tool
    
    # 方式1：使用装饰器
    @registry.tool(category=ToolCategory.CUSTOM)
    def my_tool(input: str) -> str:
        return input
    
    # 方式2：直接注册
    register_tool(my_tool, category=ToolCategory.CUSTOM)
    
    # 获取所有工具
    tools = registry.get_tools()
"""

# 核心 Registry
from agent.tools.registry import (
    ToolRegistry,
    ToolCategory,
    ToolMeta,
    registry,
    register_tool,
    get_all_tools,
    get_tools_by_category
)

# 向后兼容：导入各个工具模块
# 注意：导入即注册，工具会自动添加到 registry

# 基础工具
from agent.tools.bash import (
    execute_bash,
    execute_confirmed_bash,
    execute_cancelled_bash,
    check_dangerous_command,
    get_command_type,
    get_bash_tool_detailed_usage,
    BASH_TOOLS,
    CONFIRMATION_REQUIRED_MARKER
)

# Todo管理工具
from agent.tools.todo_manager import (
    TodoManager,
    todo_manager,
    get_todo_status,
    complete_and_next,
    get_todo_manager,
    remove_todo_manager,
    set_current_session,
    get_current_session,
    record_task_activity,
    check_task_reminder,
    TODO_MANAGER_TOOLS
)

# 技能工具
from agent.tools.skills import (
    list_skills,
    get_skill,
    get_skill_reference,
    get_skill_template,
    SKILLS_TOOLS,
    list_available_skills,
    get_skill_path,
    parse_skill_frontmatter
)

# 记忆工具
from agent.tools.memory import (
    store_memory,
    store_memories_batch,
    MEMORY_TOOLS
)

# 任务管理工具
from agent.tools.task_manager import (
    TaskManager,
    task_create,
    task_update,
    task_get,
    task_get_ready,
    task_get_blocked,
    task_get_status,
    task_visualize,
    task_list,
    task_delete,
    task_clear,
    TASK_MANAGER_TOOLS,
    get_task_manager,
    remove_task_manager
)

# 规划工具
from agent.tools.planning import (
    planning_analyze,
    planning_execute,
    PLANNING_TOOLS
)

# 知识库工具
from agent.tools.knowledge_tools import (
    remember_user_info,
    remember_preference,
    record_mistake,
    update_environment,
    memory_search,
    get_active_rules,
    get_recent_mistakes,
    KNOWLEDGE_TOOLS
)

# 子Agent工具
from agent.tools.sub_agent import (
    SubAgentMode,
    SubAgentResult,
    DefaultSubAgentExecutor,
    ForkSubAgentExecutor,
    SubAgentManager,
    spawn_sub_agent,
    set_sub_agent_tools,
    get_sub_agent_tools,
    set_sub_agent_session,
    get_sub_agent_session,
    clear_session_tools,
    SUB_AGENT_SYSTEM_PROMPT
)


# ==================== 所有工具列表（向后兼容） ====================

ALL_TOOLS = (
    BASH_TOOLS +
    TODO_MANAGER_TOOLS +
    SKILLS_TOOLS +
    MEMORY_TOOLS +
    TASK_MANAGER_TOOLS +
    PLANNING_TOOLS +
    KNOWLEDGE_TOOLS
)

# 主Agent专用工具
MAIN_AGENT_TOOLS = [spawn_sub_agent]


# ==================== 导出 ====================

__all__ = [
    # Registry 核心
    'ToolRegistry',
    'ToolCategory',
    'ToolMeta',
    'registry',
    'register_tool',
    'get_all_tools',
    'get_tools_by_category',
    
    # 工具列表（向后兼容）
    'ALL_TOOLS',
    'MAIN_AGENT_TOOLS',
    'BASH_TOOLS',
    'TODO_MANAGER_TOOLS',
    'SKILLS_TOOLS',
    'MEMORY_TOOLS',
    'TASK_MANAGER_TOOLS',
    'PLANNING_TOOLS',
    'KNOWLEDGE_TOOLS',
    
    # 基础工具
    'execute_bash',
    'execute_confirmed_bash',
    'execute_cancelled_bash',
    'check_dangerous_command',
    'get_command_type',
    'get_bash_tool_detailed_usage',
    'CONFIRMATION_REQUIRED_MARKER',
    
    # Todo管理工具
    'TodoManager',
    'todo_manager',
    'get_todo_status',
    'complete_and_next',
    'get_todo_manager',
    'remove_todo_manager',
    'set_current_session',
    'get_current_session',
    'record_task_activity',
    'check_task_reminder',
    
    # 技能工具
    'list_skills',
    'get_skill',
    'get_skill_reference',
    'get_skill_template',
    'list_available_skills',
    'get_skill_path',
    'parse_skill_frontmatter',
    
    # 记忆工具
    'store_memory',
    'store_memories_batch',
    
    # 任务管理工具
    'TaskManager',
    'task_create',
    'task_update',
    'task_get',
    'task_get_ready',
    'task_get_blocked',
    'task_get_status',
    'task_visualize',
    'task_list',
    'task_delete',
    'task_clear',
    
    # 规划工具
    'planning_analyze',
    'planning_execute',
    
    # 知识库工具
    'remember_user_info',
    'remember_preference',
    'record_mistake',
    'update_environment',
    'memory_search',
    'get_active_rules',
    'get_recent_mistakes',
    
    # 子Agent工具
    'SubAgentMode',
    'SubAgentResult',
    'DefaultSubAgentExecutor',
    'ForkSubAgentExecutor',
    'SubAgentManager',
    'spawn_sub_agent',
    'set_sub_agent_tools',
    'get_sub_agent_tools',
    'set_sub_agent_session',
    'get_sub_agent_session',
    'clear_session_tools',
    'SUB_AGENT_SYSTEM_PROMPT',
]
