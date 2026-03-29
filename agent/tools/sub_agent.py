"""
子Agent工具模块

提供创建子agent执行任务的能力：
1. 子agent拥有纯净的上下文，只接收任务描述
2. 子agent执行完成后返回摘要给主agent
3. 子agent不能创建子agent（防止无限递归）
4. 主agent基于返回结果更新任务状态
"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError

from agent.llm import get_llm
from config import Config


# 子Agent专用系统提示词（简洁，专注于执行）
SUB_AGENT_SYSTEM_PROMPT = """你是一个专注的任务执行者。你的职责是完成分配给你的单一任务。

## 最高优先级规则

1. 严格任务边界：只执行任务描述中明确要求的内容，不要做任何"顺便"或"额外"的操作
2. 完成即停止：任务完成后立即返回结果，不要继续探索或优化
3. 遇到障碍即停止：如果无法完成，立即返回失败报告，不要尝试替代方案

## 任务完成判断标准

在每次工具调用前，问自己：
- 这个操作是完成任务必需的吗？
- 任务的核心目标是什么？我是否已经达成？

任务完成的信号：
- 收集到了需要的信息
- 创建/修改了指定的文件
- 执行了要求的命令并得到预期结果

立即停止的信号：
- 已获取核心结果：停止并返回
- 遇到错误无法继续：停止并报告失败
- 发现需要超出任务范围的权限/资源：停止并报告

## 步数预算警告

你有最多 {max_steps} 步的执行预算。
- 每次工具调用消耗 1 步
- 在剩余 10 步时，必须开始收尾
- 在剩余 5 步时，必须立即返回当前结果

## 可用能力

- execute_bash: 执行系统命令（读取类直接执行，修改类需确认）
- web_search: 联网搜索信息（如果可用）
- todo_manager: 管理任务列表（如果需要拆分子任务）

## 执行流程（严格遵守）

1. 理解任务目标：明确任务的核心要求
2. 最小化执行：规划最少的步骤完成任务
3. 逐步执行：每一步都要问"这有必要吗？"
4. 及时返回：达成目标后立即返回

## 输出格式

任务完成后，必须按以下格式返回摘要：

```
## 执行结果
[成功/失败/部分完成]

## 执行过程
1. [第一步操作] -> [结果]
2. [第二步操作] -> [结果]
...

## 关键信息
[提取任务相关的关键信息，供主Agent参考]
```

## 注意事项

- 如果任务需要用户确认（如写入文件），执行后会等待确认
- 遇到错误时，说明错误原因和建议的解决方案
- 保持摘要简洁，不要返回过长的中间过程
- 禁止在任务完成后继续探索相关内容
"""


class SubAgentExecutor:
    """
    子Agent执行器
    
    管理子agent的创建和执行，确保：
    1. 子agent拥有纯净上下文
    2. 子agent不能创建子agent
    3. 执行结果被正确摘要返回
    4. 每个子agent实例有独立的步数限制
    """
    
    # 子agent的最大递归限制（每个子agent实例独立计数）
    SUB_AGENT_RECURSION_LIMIT = 30
    
    # 子agent执行超时限制（防止无限执行）
    MAX_EXECUTION_TIME = 180  # 秒
    
    def __init__(self, available_tools: List):
        """
        初始化子Agent执行器
        
        Args:
            available_tools: 子agent可用的工具列表（不包含spawn_sub_agent）
        """
        self.tools = available_tools
        # 创建子agent专用的LLM实例（非流式，因为是内部执行）
        self.llm = get_llm(streaming=False)
    
    def execute(self, task_description: str, context: str = "") -> Dict[str, Any]:
        """
        执行任务并返回结果摘要
        
        Args:
            task_description: 任务描述
            context: 额外的上下文信息（如文件路径、前置条件等）
            
        Returns:
            包含执行结果的字典：
            - success: 是否成功
            - summary: 执行摘要
            - tool_calls: 工具调用列表
            - error: 错误信息（如果失败）
        """
        # 构建纯净的消息列表
        messages = self._build_messages(task_description, context)
        
        # 创建子agent（不带spawn_sub_agent工具）
        sub_agent = create_react_agent(self.llm, self.tools)
        
        # 收集执行信息
        tool_calls = []
        execution_log = []
        
        try:
            # 执行子agent（使用简单的 invoke）
            result = sub_agent.invoke(
                {"messages": messages},
                config={"recursion_limit": self.SUB_AGENT_RECURSION_LIMIT}
            )
            
            # 提取AI消息和工具调用
            if result and "messages" in result:
                for msg in result["messages"]:
                    if isinstance(msg, AIMessage):
                        # 检查是否有工具调用
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_calls.append({
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {}),
                                    "id": tc.get("id", "")
                                })
                
                # 获取最终的AI消息
                final_message = self._extract_final_message(result)
                
                # 计算实际使用的步数（AI 响应次数）
                steps_used = sum(1 for msg in result["messages"] if isinstance(msg, AIMessage))
                
                return {
                    "success": True,
                    "summary": final_message,
                    "tool_calls": tool_calls,
                    "execution_log": execution_log,
                    "error": None,
                    "steps_used": steps_used
                }
            
            return {
                "success": False,
                "summary": "未能获取执行结果",
                "tool_calls": tool_calls,
                "execution_log": execution_log,
                "error": "Empty result from sub-agent",
                "steps_used": 0
            }
            
        except GraphRecursionError:
            return {
                "success": False,
                "summary": f"子Agent达到最大执行步数限制（{self.SUB_AGENT_RECURSION_LIMIT}步）。任务可能过于复杂，建议拆分为更小的子任务。",
                "tool_calls": tool_calls,
                "execution_log": execution_log,
                "error": "Recursion limit exceeded",
                "steps_used": len(tool_calls)
            }
            
        except Exception as e:
            return {
                "success": False,
                "summary": f"执行出错: {str(e)}",
                "tool_calls": tool_calls,
                "execution_log": execution_log,
                "error": str(e),
                "steps_used": len(tool_calls)
            }
    
    def _build_messages(self, task_description: str, context: str = "") -> List:
        """
        构建子agent的消息列表（纯净上下文）
        
        Args:
            task_description: 任务描述
            context: 额外上下文
            
        Returns:
            消息列表
        """
        # 填充步数预算到系统提示词
        system_prompt = SUB_AGENT_SYSTEM_PROMPT.format(
            max_steps=self.SUB_AGENT_RECURSION_LIMIT
        )
        
        messages = [
            SystemMessage(content=system_prompt)
        ]
        
        # 构建用户消息，添加任务边界提醒
        user_content = f"""## 任务
{task_description}

## 执行提醒
- 你的执行预算: {self.SUB_AGENT_RECURSION_LIMIT} 步（每次工具调用消耗 1 步）
- 严格限定在任务范围内，不要扩展
- 完成后立即返回，不要继续探索
- 剩余步数少于 10 步时，系统会强制你返回结果

## 任务完成标准
请明确以下问题后再开始执行：
1. 任务的核心目标是什么？
2. 最少需要几个步骤完成？
3. 什么情况算"完成"？"""
        
        if context:
            user_content += f"\n\n## 上下文\n{context}"
        
        messages.append(HumanMessage(content=user_content))
        
        return messages
    
    def _extract_final_message(self, result: Dict) -> str:
        """
        从结果中提取最终消息
        
        Args:
            result: Agent执行结果
            
        Returns:
            最终的AI消息内容
        """
        if result and "messages" in result:
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    return msg.content
        return ""


# ==================== 工具函数 ====================

# 使用全局变量存储会话工具配置
# key: session_id, value: {"tools": [...]}
_session_tools_config: Dict[str, Dict[str, Any]] = {}

# 全局默认工具列表（当无法确定会话时使用）
_global_sub_agent_tools: List = []


def set_sub_agent_tools(tools: List, session_id: str = "default") -> None:
    """
    设置指定会话的子agent可用工具列表
    
    Args:
        tools: 工具列表
        session_id: 会话ID
    """
    if session_id not in _session_tools_config:
        _session_tools_config[session_id] = {}
    _session_tools_config[session_id]["tools"] = tools
    
    # 同时更新全局默认工具（确保在任何情况下都能获取到工具）
    global _global_sub_agent_tools
    _global_sub_agent_tools = tools


def get_sub_agent_tools(session_id: str = "default") -> List:
    """
    获取指定会话的子agent可用工具列表
    
    Args:
        session_id: 会话ID
        
    Returns:
        工具列表
    """
    # 优先从会话配置获取
    config = _session_tools_config.get(session_id, {})
    tools = config.get("tools", [])
    
    # 如果会话配置中没有，尝试使用全局默认
    if not tools:
        tools = _global_sub_agent_tools
    
    return tools


def set_sub_agent_session(session_id: str) -> None:
    """
    设置当前会话ID（用于兼容旧代码）
    
    Args:
        session_id: 会话ID
    """
    # 不再使用线程本地存储，此函数保留用于兼容
    pass


def get_sub_agent_session() -> str:
    """获取当前会话ID（用于兼容旧代码）"""
    return "default"


def clear_session_tools(session_id: str) -> None:
    """
    清除指定会话的工具配置
    
    Args:
        session_id: 会话ID
    """
    if session_id in _session_tools_config:
        del _session_tools_config[session_id]


@tool
def spawn_sub_agent(task: str, context: str = "") -> str:
    """
    创建一个子Agent来执行特定任务。
    
    **适用场景：**
    - 需要执行任务清单中的某个具体任务
    - 需要在纯净上下文中执行一系列操作
    - 希望隔离执行过程，避免上下文膨胀
    
    **使用规则：**
    - 子Agent拥有纯净上下文，只知道任务描述和上下文信息
    - 子Agent执行完成后会返回执行摘要
    - 子Agent不能创建子Agent（防止无限递归）
    
    **推荐使用时机：**
    - 执行复杂的多步骤任务（如代码重构、文件操作、调试等）
    - 需要保持主上下文简洁时
    - 任务相对独立，不需要主agent的完整历史记录
    
    Args:
        task: 要执行的任务描述（清晰、具体）
        context: 额外的上下文信息（如文件路径、前置条件等），可选
        
    Returns:
        执行结果摘要，包含：
        - 任务执行状态
        - 工具调用列表
        - 执行结果详情
    """
    # 直接使用全局工具列表（不依赖线程本地变量）
    available_tools = get_sub_agent_tools()
    
    if not available_tools:
        return "错误：未配置子Agent可用工具。请确保会话已正确初始化。"
    
    # 创建子Agent执行器
    executor = SubAgentExecutor(available_tools)
    
    # 执行任务
    result = executor.execute(task, context)
    
    # 格式化返回结果 - 状态必须非常明确
    output_lines = ["## 子Agent执行报告", ""]
    
    # 步数使用情况
    steps_used = result.get("steps_used", 0)
    max_steps = SubAgentExecutor.SUB_AGENT_RECURSION_LIMIT
    output_lines.append(f"步数使用: {steps_used}/{max_steps}")
    
    # 状态标识（使用醒目的格式）
    if result["success"]:
        output_lines.append("## 执行状态: 成功")
        status_hint = "任务已成功完成，可以标记为 completed"
    else:
        output_lines.append("## 执行状态: 失败")
        status_hint = "任务执行失败，请勿标记为 completed！需要重试或调整方案"
    
    # 失败原因（如果有）
    if not result["success"] and result.get("error"):
        output_lines.append("")
        output_lines.append(f"失败原因: {result.get('error')}")
    
    # 工具调用摘要（最多显示前10个）
    if result["tool_calls"]:
        output_lines.append("")
        output_lines.append("### 工具调用记录")
        for i, tc in enumerate(result["tool_calls"][:10], 1):
            args_str = ", ".join(f"{k}={v}" for k, v in tc["args"].items())
            output_lines.append(f"{i}. `{tc['name']}`({args_str})")
        if len(result["tool_calls"]) > 10:
            output_lines.append(f"   ... 还有 {len(result['tool_calls']) - 10} 个工具调用")
    
    # 执行摘要
    output_lines.append("")
    output_lines.append("### 执行摘要")
    output_lines.append(result["summary"])
    
    # 添加明确的下一步指引
    output_lines.append("")
    output_lines.append("---")
    output_lines.append(f"下一步操作: {status_hint}")
    if result["success"]:
        output_lines.append("- 调用 todo_manager 或 task_update 将当前任务标记为 completed")
        output_lines.append("- 继续执行下一个任务")
    else:
        output_lines.append("- 不要将当前任务标记为 completed")
        output_lines.append("- 考虑重试、拆分任务或使用替代方案")
        output_lines.append("- 如果无法完成，向用户报告问题")
    
    return "\n".join(output_lines)


# ==================== 导出 ====================

__all__ = [
    'SubAgentExecutor',
    'spawn_sub_agent',
    'set_sub_agent_tools',
    'get_sub_agent_tools',
    'set_sub_agent_session',
    'get_sub_agent_session',
    'clear_session_tools',
    'SUB_AGENT_SYSTEM_PROMPT'
]
