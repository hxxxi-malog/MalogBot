"""
核心类型定义

定义系统中使用的核心类型和数据结构，减少模块间的类型耦合。
"""
from typing import Dict, List, Any, Optional, TypedDict, Literal
from dataclasses import dataclass, field
from enum import Enum


class MessageType(str, Enum):
    """消息类型枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatResponseType(str, Enum):
    """聊天响应类型枚举"""
    RESPONSE = "response"
    CONFIRMATION_REQUIRED = "confirmation_required"
    RECURSION_LIMIT_REACHED = "recursion_limit_reached"
    ERROR = "error"
    CANCELLED = "cancelled"
    DONE = "done"
    CONTENT = "content"
    TOOL_RESULT = "tool_result"


class MemoryType(str, Enum):
    """记忆类型枚举"""
    FACT = "fact"
    DECISION = "decision"
    PREFERENCE = "preference"
    ACTION = "action"
    SUMMARY = "summary"


@dataclass
class ChatMessage:
    """聊天消息数据类"""
    role: str
    content: str
    timestamp: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            'role': self.role,
            'content': self.content,
        }
        if self.timestamp:
            result['timestamp'] = self.timestamp
        if self.tool_call_id:
            result['tool_call_id'] = self.tool_call_id
        if self.tool_calls:
            result['tool_calls'] = self.tool_calls
        if self.tool_name:
            result['tool_name'] = self.tool_name
        return result


@dataclass
class ChatResponse:
    """聊天响应数据类"""
    type: ChatResponseType
    content: Optional[str] = None
    output: Optional[str] = None
    session_id: Optional[str] = None
    command: Optional[str] = None
    command_type: Optional[str] = None
    operation: Optional[str] = None
    working_dir: Optional[str] = None
    is_dangerous: bool = False
    reason: Optional[str] = None
    message: Optional[str] = None
    recursion_limit: Optional[int] = None
    partial_output: Optional[str] = None
    accumulated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {'type': self.type.value}
        if self.content is not None:
            result['content'] = self.content
        if self.output is not None:
            result['output'] = self.output
        if self.session_id is not None:
            result['session_id'] = self.session_id
        if self.command is not None:
            result['command'] = self.command
        if self.command_type is not None:
            result['command_type'] = self.command_type
        if self.operation is not None:
            result['operation'] = self.operation
        if self.working_dir is not None:
            result['working_dir'] = self.working_dir
        if self.is_dangerous:
            result['is_dangerous'] = self.is_dangerous
        if self.reason is not None:
            result['reason'] = self.reason
        if self.message is not None:
            result['message'] = self.message
        if self.recursion_limit is not None:
            result['recursion_limit'] = self.recursion_limit
        if self.partial_output is not None:
            result['partial_output'] = self.partial_output
        if self.accumulated is not None:
            result['accumulated'] = self.accumulated
        return result


@dataclass
class SessionInfo:
    """会话信息数据类"""
    session_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0
    web_search_enabled: bool = False
    knowledge_base_id: Optional[str] = None
    context_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'message_count': self.message_count,
            'web_search_enabled': self.web_search_enabled,
            'knowledge_base_id': self.knowledge_base_id,
            'context_stats': self.context_stats
        }


@dataclass
class ContextStats:
    """上下文统计数据类"""
    journal_messages: int = 0
    journal_tokens: int = 0
    memory_injected: bool = False
    memory_count: int = 0
    should_compact: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'journal_messages': self.journal_messages,
            'journal_tokens': self.journal_tokens,
            'memory_injected': self.memory_injected,
            'memory_count': self.memory_count,
            'should_compact': self.should_compact
        }


@dataclass
class SearchResult:
    """检索结果数据类"""
    id: str
    content: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
    document_id: Optional[str] = None
    embedding: Optional[List[float]] = None
    vector_score: float = 0.0
    bm25_score: float = 0.0
    hybrid_score: float = 0.0


@dataclass
class ConfirmationInfo:
    """命令确认信息数据类"""
    command: str
    command_type: str = "execute"
    operation: str = "执行命令"
    working_dir: str = ""
    is_dangerous: bool = False
    reason: str = ""
    message: str = "需要用户确认"


# 默认配置常量
DEFAULT_RELEVANCE_THRESHOLD = 0.65
DEFAULT_TOP_N = 10
DEFAULT_TOP_K = 3


__all__ = [
    'MessageType',
    'ChatResponseType',
    'MemoryType',
    'ChatMessage',
    'ChatResponse',
    'SessionInfo',
    'ContextStats',
    'SearchResult',
    'ConfirmationInfo',
    'DEFAULT_RELEVANCE_THRESHOLD',
    'DEFAULT_TOP_N',
    'DEFAULT_TOP_K'
]
