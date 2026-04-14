"""
子Agent工具模块

提供两种子Agent模式：
1. default模式：同进程，共享messages数组，低隔离级别，适用于简单任务委派
2. fork模式：独立进程，全新messages数组，共享文件缓存，中隔离级别，适用于研究性任务、多步实现

核心特性：
- 主Agent和子Agent都取消最大步数限制，改为最大上下文窗口限制
- 上下文超限时提示用户选择是否继续
- 每次执行任务都向目标收束，禁止发散思维
- 子Agent也支持planning工具
"""
import os
import sys
import json
import logging
import multiprocessing
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from config import Config
from agent.tools.registry import registry, ToolCategory

logger = logging.getLogger(__name__)


# ==================== 子Agent模式枚举 ====================

class SubAgentMode(str, Enum):
    """子Agent执行模式"""
    DEFAULT = "default"  # 同进程，共享messages
    FORK = "fork"        # 独立进程，全新messages


# ==================== 子Agent系统提示词 ====================

SUB_AGENT_SYSTEM_PROMPT = """你是一个专注的任务执行者。你的职责是完成分配给你的任务。

## 核心行为准则

1. **向目标收束**：每次执行任务都要向目标收束，禁止发散思维
   - 明确任务的核心目标
   - 只执行达成目标所必需的操作
   - 达成目标后立即停止，不要探索相关内容

2. **严格任务边界**：只执行任务描述中明确要求的内容，不要做任何"顺便"或"额外"的操作

3. **完成即停止**：任务完成后立即返回结果，不要继续探索或优化

4. **遇到障碍即停止**：如果无法完成，立即返回失败报告，不要尝试替代方案

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

## 上下文窗口管理

你需要注意上下文窗口的使用：
- 当上下文接近最大窗口限制时，系统会提示
- 继续执行时，系统会压缩旧消息保留最近的几条
- 重要信息请主动在回复中记录

## 可用能力

- execute_bash: 执行系统命令（读取类直接执行，修改类需确认）
- web_search: 联网搜索信息（如果可用）
- todo_manager: 管理任务列表
- planning: 任务规划工具，用于复杂任务分解

## 输出格式

任务完成后，必须按以下格式返回摘要：

执行结果：[成功/失败/部分完成]

执行过程：
1. [第一步操作] -> [结果]
2. [第二步操作] -> [结果]
...

关键信息：
[提取任务相关的关键信息，供主Agent参考]

## 注意事项

- 如果任务需要用户确认（如写入文件），执行后会等待确认
- 遇到错误时，说明错误原因和建议的解决方案
- 保持摘要简洁，不要返回过长的中间过程
- 禁止在任务完成后继续探索相关内容
"""


# ==================== 执行结果数据类 ====================

@dataclass
class SubAgentResult:
    """子Agent执行结果"""
    success: bool
    summary: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    execution_log: List[str] = field(default_factory=list)
    error: Optional[str] = None
    steps_used: int = 0
    context_overflow: bool = False  # 是否发生上下文溢出
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "summary": self.summary,
            "tool_calls": self.tool_calls,
            "execution_log": self.execution_log,
            "error": self.error,
            "steps_used": self.steps_used,
            "context_overflow": self.context_overflow
        }


# ==================== Default模式执行器 ====================

class DefaultSubAgentExecutor:
    """
    Default模式子Agent执行器
    
    特点：
    - 同进程执行
    - 共享主Agent的messages数组
    - 低隔离级别
    - 适用于简单任务委派
    """
    
    def __init__(self, available_tools: List, shared_messages: List = None):
        """
        初始化Default模式执行器
        
        Args:
            available_tools: 可用工具列表
            shared_messages: 共享的消息列表（可选）
        """
        self.tools = available_tools
        self.shared_messages = shared_messages or []
        
    def execute(
        self, 
        task_description: str, 
        context: str = "",
        session_id: str = "default"
    ) -> SubAgentResult:
        """
        执行任务（同进程，共享messages）
        
        Args:
            task_description: 任务描述
            context: 额外上下文
            session_id: 会话ID
            
        Returns:
            执行结果
        """
        from langgraph.prebuilt import create_react_agent
        from langgraph.errors import GraphRecursionError
        from agent.llm import get_llm
        
        # 创建LLM实例
        llm = get_llm(streaming=False)
        
        # 构建消息（共享主messages）
        messages = self._build_messages(task_description, context)
        
        # 创建Agent
        sub_agent = create_react_agent(llm, self.tools)
        
        tool_calls = []
        execution_log = []
        
        try:
            # 执行（使用较大的递归限制，但不限制步数）
            result = sub_agent.invoke(
                {"messages": messages},
                config={"recursion_limit": Config.SUB_AGENT_RECURSION_LIMIT}
            )
            
            # 提取结果
            if result and "messages" in result:
                for msg in result["messages"]:
                    if isinstance(msg, AIMessage):
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_calls.append({
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {}),
                                    "id": tc.get("id", "")
                                })
                
                final_message = self._extract_final_message(result)
                steps_used = sum(1 for msg in result["messages"] if isinstance(msg, AIMessage))
                
                return SubAgentResult(
                    success=True,
                    summary=final_message,
                    tool_calls=tool_calls,
                    execution_log=execution_log,
                    steps_used=steps_used
                )
            
            return SubAgentResult(
                success=False,
                summary="未能获取执行结果",
                tool_calls=tool_calls,
                execution_log=execution_log,
                error="Empty result"
            )
            
        except GraphRecursionError:
            # 达到递归限制，但不是因为步数限制
            return SubAgentResult(
                success=False,
                summary=f"子Agent达到递归限制（{Config.SUB_AGENT_RECURSION_LIMIT}）。任务可能过于复杂。",
                tool_calls=tool_calls,
                execution_log=execution_log,
                error="Recursion limit exceeded"
            )
            
        except Exception as e:
            logger.error(f"[DefaultSubAgent] 执行出错: {e}")
            return SubAgentResult(
                success=False,
                summary=f"执行出错: {str(e)}",
                tool_calls=tool_calls,
                execution_log=execution_log,
                error=str(e)
            )
    
    def _build_messages(self, task_description: str, context: str = "") -> List:
        """构建消息列表"""
        messages = [SystemMessage(content=SUB_AGENT_SYSTEM_PROMPT)]
        
        # 共享主messages（如果有）
        if self.shared_messages:
            messages.extend(self.shared_messages[-10:])  # 只取最近10条
        
        user_content = f"""任务：{task_description}

执行提醒：
- 向目标收束，禁止发散思维
- 只执行必需的操作
- 完成后立即返回"""
        
        if context:
            user_content += f"\n\n## 上下文\n{context}"
        
        messages.append(HumanMessage(content=user_content))
        return messages
    
    def _extract_final_message(self, result: Dict) -> str:
        """提取最终消息"""
        if result and "messages" in result:
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    return msg.content
        return ""


# ==================== Fork模式执行器 ====================

def _fork_worker(
    task_description: str,
    context: str,
    tools_config: List[str],
    session_id: str
) -> Dict[str, Any]:
    """
    Fork模式的独立进程工作函数
    
    在独立进程中执行，拥有全新的messages数组
    
    Args:
        task_description: 任务描述
        context: 额外上下文
        tools_config: 工具配置（工具名称列表）
        session_id: 会话ID
        
    Returns:
        执行结果字典
    """
    from langgraph.prebuilt import create_react_agent
    from langgraph.errors import GraphRecursionError
    from agent.llm import get_llm
    
    # 重新构建工具列表
    tools = _rebuild_tools(tools_config)
    
    # 创建LLM实例
    llm = get_llm(streaming=False)
    
    # 构建全新的消息列表
    context_section = f"\n## 上下文\n{context}" if context else ""
    messages = [
        SystemMessage(content=SUB_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=f"""任务：{task_description}

执行提醒：
- 向目标收束，禁止发散思维
- 只执行必需的操作
- 完成后立即返回
- 这是独立进程，不共享主对话历史
{context_section}""")
    ]
    
    # 创建Agent
    sub_agent = create_react_agent(llm, tools)
    
    tool_calls = []
    
    try:
        result = sub_agent.invoke(
            {"messages": messages},
            config={"recursion_limit": Config.SUB_AGENT_RECURSION_LIMIT}
        )
        
        if result and "messages" in result:
            for msg in result["messages"]:
                if isinstance(msg, AIMessage):
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls.append({
                                "name": tc.get("name", "unknown"),
                                "args": tc.get("args", {}),
                                "id": tc.get("id", "")
                            })
            
            final_message = ""
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    final_message = msg.content
                    break
            
            steps_used = sum(1 for msg in result["messages"] if isinstance(msg, AIMessage))
            
            return {
                "success": True,
                "summary": final_message,
                "tool_calls": tool_calls,
                "error": None,
                "steps_used": steps_used
            }
        
        return {
            "success": False,
            "summary": "未能获取执行结果",
            "tool_calls": tool_calls,
            "error": "Empty result"
        }
        
    except GraphRecursionError:
        return {
            "success": False,
            "summary": f"子Agent达到递归限制（{Config.SUB_AGENT_RECURSION_LIMIT}）",
            "tool_calls": tool_calls,
            "error": "Recursion limit exceeded"
        }
        
    except Exception as e:
        return {
            "success": False,
            "summary": f"执行出错: {str(e)}",
            "tool_calls": tool_calls,
            "error": str(e)
        }


def _rebuild_tools(tool_names: List[str]) -> List:
    """根据工具名称重建工具列表"""
    tools = []
    
    for name in tool_names:
        try:
            if name == "execute_bash":
                from agent.tools.bash import execute_bash
                tools.append(execute_bash)
            elif name == "get_bash_tool_detailed_usage":
                from agent.tools.bash import get_bash_tool_detailed_usage
                tools.append(get_bash_tool_detailed_usage)
            elif name == "todo_manager":
                from agent.tools.todo_manager import todo_manager
                tools.append(todo_manager)
            elif name == "get_todo_status":
                from agent.tools.todo_manager import get_todo_status
                tools.append(get_todo_status)
            elif name == "complete_and_next":
                from agent.tools.todo_manager import complete_and_next
                tools.append(complete_and_next)
            elif name == "planning":
                from agent.tools.planning import planning_analyze, planning_execute
                tools.append(planning_analyze)
                tools.append(planning_execute)
            # 可以添加更多工具
        except ImportError as e:
            logger.warning(f"[ForkWorker] 无法导入工具 {name}: {e}")
    
    return tools


class ForkSubAgentExecutor:
    """
    Fork模式子Agent执行器
    
    特点：
    - 独立进程执行
    - 全新messages数组
    - 共享文件缓存（通过session_id）
    - 中隔离级别
    - 适用于研究性任务、多步实现
    - 后台运行不阻塞主对话
    """
    
    def __init__(self, available_tools: List, session_id: str = "default"):
        """
        初始化Fork模式执行器
        
        Args:
            available_tools: 可用工具列表
            session_id: 会话ID（用于共享文件缓存）
        """
        self.tools = available_tools
        self.session_id = session_id
        self.timeout = Config.SUB_AGENT_FORK_TIMEOUT
        
    def execute(
        self, 
        task_description: str, 
        context: str = ""
    ) -> SubAgentResult:
        """
        执行任务（独立进程，全新messages）
        
        Args:
            task_description: 任务描述
            context: 额外上下文
            
        Returns:
            执行结果
        """
        # 提取工具名称
        tool_names = [getattr(t, 'name', str(t)) for t in self.tools]
        
        tool_calls = []
        execution_log = ["[Fork模式] 启动独立进程执行"]
        
        try:
            # 使用进程池执行
            with ProcessPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    _fork_worker,
                    task_description,
                    context,
                    tool_names,
                    self.session_id
                )
                
                try:
                    result = future.result(timeout=self.timeout)
                    
                    return SubAgentResult(
                        success=result.get("success", False),
                        summary=result.get("summary", ""),
                        tool_calls=result.get("tool_calls", []),
                        execution_log=execution_log,
                        error=result.get("error"),
                        steps_used=result.get("steps_used", 0)
                    )
                    
                except FuturesTimeoutError:
                    execution_log.append(f"[Fork模式] 执行超时（{self.timeout}秒）")
                    return SubAgentResult(
                        success=False,
                        summary=f"子Agent执行超时（{self.timeout}秒）",
                        tool_calls=tool_calls,
                        execution_log=execution_log,
                        error="Timeout"
                    )
                    
        except Exception as e:
            logger.error(f"[ForkSubAgent] 执行出错: {e}")
            execution_log.append(f"[Fork模式] 执行出错: {str(e)}")
            return SubAgentResult(
                success=False,
                summary=f"Fork模式执行出错: {str(e)}",
                tool_calls=tool_calls,
                execution_log=execution_log,
                error=str(e)
            )


# ==================== 子Agent管理器 ====================

class SubAgentManager:
    """
    子Agent管理器
    
    统一管理两种模式的子Agent创建和执行
    """
    
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self._default_executor = None
        self._fork_executor = None
        
    def get_executor(
        self, 
        mode: SubAgentMode,
        tools: List,
        shared_messages: List = None
    ):
        """
        获取对应模式的执行器
        
        Args:
            mode: 执行模式
            tools: 可用工具列表
            shared_messages: 共享消息列表（default模式使用）
            
        Returns:
            执行器实例
        """
        if mode == SubAgentMode.DEFAULT:
            return DefaultSubAgentExecutor(tools, shared_messages)
        else:
            return ForkSubAgentExecutor(tools, self.session_id)


# ==================== 工具函数 ====================

# 会话工具配置存储
_session_tools_config: Dict[str, Dict[str, Any]] = {}
_global_sub_agent_tools: List = []


def set_sub_agent_tools(tools: List, session_id: str = "default") -> None:
    """设置指定会话的子agent可用工具列表"""
    if session_id not in _session_tools_config:
        _session_tools_config[session_id] = {}
    _session_tools_config[session_id]["tools"] = tools
    
    global _global_sub_agent_tools
    _global_sub_agent_tools = tools


def get_sub_agent_tools(session_id: str = "default") -> List:
    """获取指定会话的子agent可用工具列表"""
    config = _session_tools_config.get(session_id, {})
    tools = config.get("tools", [])
    
    if not tools:
        tools = _global_sub_agent_tools
    
    return tools


def set_sub_agent_session(session_id: str) -> None:
    """设置当前会话ID"""
    pass


def get_sub_agent_session() -> str:
    """获取当前会话ID"""
    return "default"


def clear_session_tools(session_id: str) -> None:
    """清除指定会话的工具配置"""
    if session_id in _session_tools_config:
        del _session_tools_config[session_id]


# ==================== 工具定义 ====================

@tool
def spawn_sub_agent(
    task: str, 
    context: str = "",
    mode: str = "default"
) -> str:
    """
    创建一个子Agent来执行特定任务。
    
    **两种模式：**
    - default：同进程，共享messages数组，低隔离，适用于简单任务委派
    - fork：独立进程，全新messages数组，中隔离，适用于研究性任务、多步实现，后台运行不阻塞主对话
    
    **适用场景：**
    - 需要执行任务清单中的某个具体任务
    - 需要在纯净上下文中执行一系列操作
    - 希望隔离执行过程，避免上下文膨胀
    
    **使用规则：**
    - 子Agent执行完成后会返回执行摘要
    - 子Agent不能创建子Agent（防止无限递归）
    - 子Agent也会向目标收束，禁止发散思维
    
    **推荐使用时机：**
    - 简单任务委派 → 使用 default 模式
    - 研究性任务、多步实现 → 使用 fork 模式
    - 需要保持主上下文简洁时
    - 任务相对独立，不需要主agent的完整历史记录
    
    Args:
        task: 要执行的任务描述（清晰、具体）
        context: 额外的上下文信息（如文件路径、前置条件等），可选
        mode: 执行模式，"default" 或 "fork"，默认为 "default"
        
    Returns:
        执行结果摘要
    """
    # 解析模式
    try:
        agent_mode = SubAgentMode(mode.lower())
    except ValueError:
        agent_mode = SubAgentMode.DEFAULT
    
    # 获取可用工具
    available_tools = get_sub_agent_tools()
    
    if not available_tools:
        return "错误：未配置子Agent可用工具。请确保会话已正确初始化。"
    
    # 创建管理器并获取执行器
    manager = SubAgentManager()
    executor = manager.get_executor(agent_mode, available_tools)
    
    # 执行任务
    result = executor.execute(task, context)
    
    # 格式化返回结果
    output_lines = ["[子Agent执行报告]", ""]
    
    # 模式信息
    output_lines.append(f"执行模式：{agent_mode.value}")
    output_lines.append(f"步数使用：{result.steps_used}")
    
    # 状态
    if result.success:
        output_lines.append("")
        output_lines.append("执行状态：成功")
        status_hint = "任务已成功完成，可以标记为 completed"
    else:
        output_lines.append("")
        output_lines.append("执行状态：失败")
        status_hint = "任务执行失败，请勿标记为 completed！需要重试或调整方案"
    
    # 失败原因
    if not result.success and result.error:
        output_lines.append(f"失败原因：{result.error}")
    
    # 上下文溢出警告
    if result.context_overflow:
        output_lines.append("")
        output_lines.append("警告：执行过程中发生了上下文溢出，部分历史已被压缩")
    
    # 工具调用摘要
    if result.tool_calls:
        output_lines.append("")
        output_lines.append("工具调用记录：")
        for i, tc in enumerate(result.tool_calls[:10], 1):
            args_str = ", ".join(f"{k}={v}" for k, v in tc["args"].items())
            output_lines.append(f"  {i}. {tc['name']}({args_str})")
        if len(result.tool_calls) > 10:
            output_lines.append(f"  ... 还有 {len(result['tool_calls']) - 10} 个工具调用")
    
    # 执行摘要
    output_lines.append("")
    output_lines.append("执行摘要：")
    output_lines.append(result.summary)
    
    # 下一步指引
    output_lines.append("")
    output_lines.append("---")
    output_lines.append(f"下一步操作：{status_hint}")
    
    return "\n".join(output_lines)


# ==================== 注册工具到 Registry ====================

# spawn_sub_agent 只给主Agent使用，子Agent不能创建子Agent
registry.register(
    spawn_sub_agent,
    category=ToolCategory.SUB_AGENT,
    for_sub_agent=False,  # 子Agent不可用
    priority=5,
    module=__name__
)


# ==================== 导出 ====================

__all__ = [
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
    'SUB_AGENT_SYSTEM_PROMPT'
]
