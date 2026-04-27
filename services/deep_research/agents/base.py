"""
专家型 Agent 基类

定义专家型 Agent 的通用接口和行为。
所有专家型 Agent 都继承自 BaseExpertAgent。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError

from agent.llm import get_llm
from services.deep_research.models import Learning, Source
from services.deep_research.track import ResearchTrack

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Agent 类型"""
    EXPLORER = "explorer"      # 探索型
    ANALYZER = "analyzer"       # 分析型
    SYNTHESIZER = "synthesizer" # 总结型


@dataclass
class AgentResult:
    """
    Agent 执行结果
    
    统一的执行结果结构，用于各类型 Agent 返回。
    """
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    learnings: list[Learning] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "learnings": [l.to_dict() for l in self.learnings],
            "sources": [s.to_dict() for s in self.sources],
            "metadata": self.metadata,
        }


@dataclass
class AgentContext:
    """
    Agent 执行上下文
    
    包含 Agent 执行所需的全部上下文信息。
    """
    # 基本信息
    task_id: str = ""
    track_id: str = ""
    session_id: str = ""
    
    # 研究信息
    query: str = ""                    # 用户原始问题
    topic: str = ""                    # 当前研究方向主题
    direction_keywords: list[str] = field(default_factory=list)
    
    # 已有信息
    existing_learnings: list[Learning] = field(default_factory=list)
    existing_sources: list[Source] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)
    searched_queries: set[str] = field(default_factory=set)
    
    # 用户输入（深度研究模式）
    clarification_answers: list[str] = field(default_factory=list)
    
    # 自定义数据
    custom_data: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "track_id": self.track_id,
            "session_id": self.session_id,
            "query": self.query,
            "topic": self.topic,
            "direction_keywords": self.direction_keywords,
            "existing_learnings": [l.to_dict() for l in self.existing_learnings],
            "existing_sources": [s.to_dict() for s in self.existing_sources],
            "visited_urls": list(self.visited_urls),
            "searched_queries": list(self.searched_queries),
            "clarification_answers": self.clarification_answers,
            "custom_data": self.custom_data,
        }


class BaseExpertAgent(ABC):
    """
    专家型 Agent 基类
    
    所有专家型 Agent 的抽象基类，定义通用接口和行为。
    
    设计原则：
    - 单一职责：每个 Agent 只负责一类任务
    - 统一接口：所有 Agent 实现 execute() 方法
    - 结果标准化：所有 Agent 返回 AgentResult
    
    使用方式：
        agent = ExplorerAgent(tools=[search_tool])
        result = agent.execute(context)
    """
    
    def __init__(
        self,
        agent_type: AgentType,
        tools: list = None,
        recursion_limit: int = 500,
    ):
        """
        初始化专家型 Agent
        
        Args:
            agent_type: Agent 类型
            tools: 可用工具列表
            recursion_limit: LangGraph 递归限制
        """
        self.agent_type = agent_type
        self.tools = tools or []
        self.recursion_limit = recursion_limit
        
        # LLM 和 Agent 实例（延迟初始化）
        self._llm = None
        self._agent = None
        self._initialized = False
        self._init_error: Optional[str] = None  # 初始化错误信息
        
        # 执行统计
        self._total_executions = 0
        self._successful_executions = 0
        
        logger.debug(f"Created {agent_type.value} agent")
    
    def _ensure_initialized(self) -> bool:
        """
        确保 Agent 已初始化
        
        Returns:
            是否初始化成功
        """
        if self._initialized:
            # 如果之前初始化失败，返回 False
            return self._init_error is None
        
        try:
            self._llm = get_llm(streaming=False)
            
            if self.tools:
                self._agent = create_react_agent(self._llm, self.tools)
            else:
                # 无工具的 Agent 只使用 LLM
                self._agent = None
            
            self._initialized = True
            logger.debug(f"{self.agent_type.value} agent initialized with {len(self.tools)} tools")
            return True
            
        except Exception as e:
            self._init_error = str(e)
            self._initialized = True  # 标记为已尝试初始化
            logger.error(f"{self.agent_type.value} agent initialization failed: {e}")
            return False
    
    @property
    def system_prompt(self) -> str:
        """
        系统提示词
        
        子类必须实现此属性，返回特定于 Agent 类型的系统提示词。
        """
        raise NotImplementedError("Subclasses must implement system_prompt")
    
    @abstractmethod
    def execute(self, context: AgentContext, track: Optional[ResearchTrack] = None) -> AgentResult:
        """
        执行 Agent 任务
        
        子类必须实现此方法，定义具体的执行逻辑。
        
        Args:
            context: 执行上下文
            track: 研究轨道（可选，用于 SSE 推送）
            
        Returns:
            AgentResult 执行结果
        """
        pass
    
    def get_tools(self) -> list:
        """
        获取可用工具列表
        
        Returns:
            工具实例列表
        """
        return self.tools
    
    def get_tool_names(self) -> list[str]:
        """
        获取工具名称列表
        
        Returns:
            工具名称列表
        """
        return [getattr(t, 'name', getattr(t, '__name__', str(id(t)))) for t in self.tools]
    
    def _build_messages(self, context: AgentContext, user_message: str) -> list:
        """
        构建消息列表
        
        Args:
            context: 执行上下文
            user_message: 用户消息内容
            
        Returns:
            消息列表
        """
        messages = [SystemMessage(content=self.system_prompt)]
        
        # 添加上下文信息
        context_info = self._build_context_info(context)
        if context_info:
            messages.append(HumanMessage(content=context_info))
        
        # 添加用户消息
        messages.append(HumanMessage(content=user_message))
        
        return messages
    
    def _build_context_info(self, context: AgentContext) -> str:
        """
        构建上下文信息
        
        Args:
            context: 执行上下文
            
        Returns:
            格式化的上下文信息
        """
        parts = []
        
        if context.query:
            parts.append(f"用户原始问题: {context.query}")
        
        if context.topic:
            parts.append(f"当前研究方向: {context.topic}")
        
        if context.direction_keywords:
            parts.append(f"研究方向关键词: {', '.join(context.direction_keywords)}")
        
        if context.existing_learnings:
            parts.append(f"已有学习成果: {len(context.existing_learnings)} 条")
        
        if context.existing_sources:
            parts.append(f"已有信息来源: {len(context.existing_sources)} 个")
        
        if context.visited_urls:
            parts.append(f"已访问 URL 数: {len(context.visited_urls)} 个")
        
        if context.searched_queries:
            parts.append(f"已执行查询数: {len(context.searched_queries)} 个")
        
        if context.clarification_answers:
            parts.append(f"用户澄清回答: {'; '.join(context.clarification_answers)}")
        
        return "\n".join(parts) if parts else ""
    
    def _invoke_agent(self, messages: list) -> tuple[bool, dict[str, Any]]:
        """
        调用 LangGraph Agent
        
        Args:
            messages: 消息列表
            
        Returns:
            (是否成功, 结果字典)
        """
        # 检查初始化状态
        if not self._ensure_initialized():
            error_msg = self._init_error or "Agent 初始化失败"
            logger.error(f"{self.agent_type.value} agent not initialized: {error_msg}")
            return False, {"error": error_msg, "error_type": "initialization_error"}
        
        if not self._agent:
            # 无工具 Agent，直接调用 LLM
            return self._invoke_llm(messages)
        
        try:
            result = self._agent.invoke(
                {"messages": messages},
                config={"recursion_limit": self.recursion_limit}
            )
            
            # 提取最终消息
            final_message = self._extract_final_message(result)
            
            # 提取工具调用信息
            tool_calls = self._extract_tool_calls(result)
            
            return True, {
                "final_message": final_message,
                "tool_calls": tool_calls,
                "steps_used": len([m for m in result.get("messages", []) if hasattr(m, 'content')]),
            }
            
        except GraphRecursionError:
            # P1-1: 区分递归限制错误
            logger.error(f"{self.agent_type.value} agent reached recursion limit")
            return False, {
                "error": f"达到递归限制（{self.recursion_limit}），任务过于复杂",
                "error_type": "recursion_limit",
            }
        
        except ImportError as e:
            # P1-1: 区分导入错误
            logger.error(f"{self.agent_type.value} agent import error: {e}")
            return False, {
                "error": f"模块导入失败: {e}",
                "error_type": "import_error",
            }
        
        except ValueError as e:
            # P1-1: 区分参数错误
            logger.error(f"{self.agent_type.value} agent invalid argument: {e}")
            return False, {
                "error": f"参数错误: {e}",
                "error_type": "value_error",
            }
        
        except RuntimeError as e:
            # P1-1: 区分运行时错误
            logger.error(f"{self.agent_type.value} agent runtime error: {e}")
            return False, {
                "error": f"运行时错误: {e}",
                "error_type": "runtime_error",
            }
        
        except Exception as e:
            # P1-1: 其他未预期错误，记录完整堆栈
            logger.error(f"{self.agent_type.value} agent unexpected error: {e}", exc_info=True)
            return False, {
                "error": str(e),
                "error_type": "unexpected_error",
            }
    
    def _invoke_llm(self, messages: list) -> tuple[bool, dict[str, Any]]:
        """
        直接调用 LLM（无工具）
        
        Args:
            messages: 消息列表
            
        Returns:
            (是否成功, 结果字典)
        """
        # 检查初始化状态
        if not self._ensure_initialized():
            error_msg = self._init_error or "Agent 初始化失败"
            logger.error(f"{self.agent_type.value} agent not initialized: {error_msg}")
            return False, {"error": error_msg, "error_type": "initialization_error"}
        
        try:
            response = self._llm.invoke(messages)
            return True, {
                "final_message": response.content,
                "steps_used": 1,
            }
        except ImportError as e:
            # P1-1: 区分导入错误
            logger.error(f"{self.agent_type.value} LLM import error: {e}")
            return False, {
                "error": f"模块导入失败: {e}",
                "error_type": "import_error",
            }
        except ValueError as e:
            # P1-1: 区分参数错误
            logger.error(f"{self.agent_type.value} LLM invalid argument: {e}")
            return False, {
                "error": f"参数错误: {e}",
                "error_type": "value_error",
            }
        except Exception as e:
            # P1-1: 其他未预期错误，记录完整堆栈
            logger.error(f"{self.agent_type.value} LLM unexpected error: {e}", exc_info=True)
            return False, {
                "error": str(e),
                "error_type": "unexpected_error",
            }
    
    def _extract_final_message(self, result: dict) -> str:
        """
        从 Agent 结果中提取最终消息
        
        Args:
            result: Agent 执行结果
            
        Returns:
            最终消息内容
        """
        from langchain_core.messages import AIMessage
        
        if result and "messages" in result:
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    return msg.content
        return ""
    
    def _extract_tool_calls(self, result: dict) -> list[dict]:
        """
        从 Agent 结果中提取工具调用信息
        
        Args:
            result: Agent 执行结果
            
        Returns:
            工具调用列表
        """
        from langchain_core.messages import AIMessage
        
        tool_calls = []
        
        if result and "messages" in result:
            for msg in result["messages"]:
                if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls"):
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "name": tc.get("name", "unknown"),
                            "args": tc.get("args", {}),
                        })
        
        return tool_calls
    
    def get_stats(self) -> dict:
        """
        获取执行统计
        
        Returns:
            统计信息字典
        """
        return {
            "agent_type": self.agent_type.value,
            "total_executions": self._total_executions,
            "successful_executions": self._successful_executions,
            "success_rate": self._successful_executions / max(1, self._total_executions),
            "tools_count": len(self.tools),
            "tool_names": self.get_tool_names(),
        }


# ============ 通用系统提示词片段 ============

BASE_SYSTEM_PROMPT = """你是一个专注于研究任务的专家型 Agent。

## 核心行为准则

1. **向目标收束**：每次执行任务都要向研究目标收束，禁止发散思维
   - 明确任务的核心目标
   - 只执行达成目标所必需的操作
   - 达成目标后立即停止

2. **严格任务边界**：只执行任务描述中明确要求的内容，不要做任何"顺便"或"额外"的操作

3. **完成即停止**：任务完成后立即返回结果摘要

4. **遇到障碍即报告**：如果无法完成，立即返回失败报告，说明原因

## 输出格式

执行完成后，请按以下格式返回：

执行结果：[成功/失败]

关键产出：
- [产出的关键信息/文件/结果]

执行摘要：
[简要描述执行过程和结果]
"""
