"""
核心抽象层

提供系统的核心接口定义和类型声明，实现依赖反转。
"""
from services.core.types import (
    MessageType,
    ChatResponseType,
    MemoryType,
    ChatMessage,
    ChatResponse,
    SessionInfo,
    ContextStats,
    SearchResult,
    ConfirmationInfo,
    DEFAULT_RELEVANCE_THRESHOLD,
    DEFAULT_TOP_N,
    DEFAULT_TOP_K
)

from services.core.interfaces import (
    ISessionStore,
    IContextCompactor,
    IAgentService,
    IRAGService,
    IEmbeddingService,
    IKnowledgeBaseService,
    ILongTermMemory,
    IToolManager,
    IConversationJournal
)


__all__ = [
    # 类型
    'MessageType',
    'ChatResponseType',
    'MemoryType',
    'ChatMessage',
    'ChatResponse',
    'SessionInfo',
    'ContextStats',
    'SearchResult',
    'ConfirmationInfo',
    # 常量
    'DEFAULT_RELEVANCE_THRESHOLD',
    'DEFAULT_TOP_N',
    'DEFAULT_TOP_K',
    # 接口
    'ISessionStore',
    'IContextCompactor',
    'IAgentService',
    'IRAGService',
    'IEmbeddingService',
    'IKnowledgeBaseService',
    'ILongTermMemory',
    'IToolManager',
    'IConversationJournal'
]
