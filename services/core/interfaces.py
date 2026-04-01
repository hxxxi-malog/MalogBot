"""
核心接口定义

定义系统中各模块的抽象接口，实现依赖反转，降低模块间耦合。

使用依赖注入模式：
- 高层模块依赖抽象接口，而非具体实现
- 具体实现通过依赖注入容器注册
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple, Generator, AsyncGenerator


class ISessionStore(ABC):
    """会话存储接口"""
    
    @abstractmethod
    def get_or_create_session(self, session_id: str) -> bool:
        """获取或创建会话"""
        pass
    
    @abstractmethod
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        pass
    
    @abstractmethod
    def get_all_sessions(self) -> List[Dict]:
        """获取所有会话列表"""
        pass
    
    @abstractmethod
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """获取会话信息"""
        pass
    
    @abstractmethod
    def add_message(self, session_id: str, role: str, content: str, 
                   tool_call_id: str = None, tool_calls: list = None,
                   tool_name: str = None) -> bool:
        """添加消息"""
        pass
    
    @abstractmethod
    def get_messages(self, session_id: str, limit: Optional[int] = None) -> List[Dict]:
        """获取消息列表"""
        pass
    
    @abstractmethod
    def get_full_context(self, session_id: str, user_query: str = "") -> Tuple[List[Dict], Dict]:
        """获取完整上下文"""
        pass
    
    @abstractmethod
    def clear_messages(self, session_id: str) -> bool:
        """清空消息"""
        pass
    
    @abstractmethod
    def get_web_search_enabled(self, session_id: str) -> bool:
        """获取联网搜索状态"""
        pass
    
    @abstractmethod
    def set_web_search_enabled(self, session_id: str, enabled: bool) -> bool:
        """设置联网搜索状态"""
        pass
    
    @abstractmethod
    def get_knowledge_base_id(self, session_id: str) -> Optional[str]:
        """获取知识库ID"""
        pass
    
    @abstractmethod
    def set_knowledge_base_id(self, session_id: str, kb_id: Optional[str]) -> bool:
        """设置知识库ID"""
        pass


class IContextCompactor(ABC):
    """上下文压缩器接口"""
    
    @abstractmethod
    def should_auto_compact(self, session_id: str) -> bool:
        """判断是否需要压缩"""
        pass
    
    @abstractmethod
    def auto_compact(self, session_id: str, llm_client: Any = None, 
                    current_query: str = "") -> Tuple[List[Dict], Optional[str]]:
        """执行自动压缩"""
        pass
    
    @abstractmethod
    def inject_context_for_chat(self, session_id: str, 
                                user_query: str) -> Tuple[List[Dict], Dict]:
        """为对话注入上下文"""
        pass


class IAgentService(ABC):
    """Agent服务接口"""
    
    @abstractmethod
    def chat(self, user_input: str, session_id: str) -> Dict[str, Any]:
        """执行对话（非流式）"""
        pass
    
    @abstractmethod
    def chat_stream(self, user_input: str, 
                   session_id: str) -> Generator[Dict[str, Any], None, None]:
        """执行对话（流式）"""
        pass
    
    @abstractmethod
    def confirm_command(self, command: str, session_id: str, 
                       user_message: str = "") -> Dict[str, Any]:
        """执行确认的命令"""
        pass
    
    @abstractmethod
    def confirm_command_stream(self, command: str, session_id: str,
                              user_message: str = "") -> Generator[Dict[str, Any], None, None]:
        """执行确认的命令（流式）"""
        pass


class IRAGService(ABC):
    """RAG检索服务接口"""
    
    @abstractmethod
    async def search(self, query: str, knowledge_base_id: str,
                    top_n: int = None, top_k: int = None,
                    use_mmr: bool = None) -> List[Dict[str, Any]]:
        """执行检索"""
        pass
    
    @abstractmethod
    async def search_with_context(self, query: str, knowledge_base_id: str,
                                  max_context_length: int = 2000) -> str:
        """检索并构建上下文"""
        pass


class IEmbeddingService(ABC):
    """向量嵌入服务接口"""
    
    @abstractmethod
    async def get_single_embedding(self, text: str) -> Optional[List[float]]:
        """获取单个文本的向量嵌入"""
        pass
    
    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取多个文本的向量嵌入"""
        pass
    
    @abstractmethod
    async def rerank(self, query: str, documents: List[str], 
                    top_k: int = None) -> List[Dict[str, Any]]:
        """重排序"""
        pass


class IKnowledgeBaseService(ABC):
    """知识库服务接口"""
    
    @abstractmethod
    def create_knowledge_base(self, name: str, description: str = "",
                             user_id: str = None) -> Dict:
        """创建知识库"""
        pass
    
    @abstractmethod
    def delete_knowledge_base(self, kb_id: str) -> bool:
        """删除知识库"""
        pass
    
    @abstractmethod
    def get_knowledge_base(self, kb_id: str) -> Optional[Dict]:
        """获取知识库信息"""
        pass
    
    @abstractmethod
    def list_knowledge_bases(self, user_id: str = None) -> List[Dict]:
        """列出所有知识库"""
        pass
    
    @abstractmethod
    def get_documents(self, kb_id: str) -> List[Dict]:
        """获取知识库下的所有文档"""
        pass
    
    @abstractmethod
    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        pass


class ILongTermMemory(ABC):
    """长期记忆服务接口"""
    
    @abstractmethod
    def store_memory(self, content: str, memory_type: str, 
                    session_id: str = None, importance: float = 0.5,
                    tags: List[str] = None) -> Dict[str, Any]:
        """存储记忆"""
        pass
    
    @abstractmethod
    def get_memories_for_context(self, query: str, session_id: str = None,
                                 max_tokens: int = 2000,
                                 relevance_threshold: float = 0.65) -> str:
        """获取相关记忆用于上下文"""
        pass


class IToolManager(ABC):
    """工具管理器接口"""
    
    @abstractmethod
    def get_tools_for_session(self, session_id: str, 
                              include_sub_agent: bool = True) -> List:
        """获取会话可用的工具列表"""
        pass
    
    @abstractmethod
    def register_tool(self, tool: Any, for_sub_agent: bool = False) -> None:
        """注册工具"""
        pass


class IConversationJournal(ABC):
    """对话日志接口"""
    
    @abstractmethod
    def append_message(self, session_id: str, role: str, content: str,
                      tool_call_id: str = None, tool_calls: list = None,
                      tool_name: str = None) -> None:
        """追加消息"""
        pass
    
    @abstractmethod
    def read_messages(self, session_id: str) -> List[Dict]:
        """读取所有消息"""
        pass
    
    @abstractmethod
    def read_messages_for_context(self, session_id: str) -> Tuple[List[Dict], int]:
        """读取消息用于上下文"""
        pass
    
    @abstractmethod
    def should_compact(self, session_id: str) -> bool:
        """判断是否需要压缩"""
        pass
    
    @abstractmethod
    def get_compaction_info(self, session_id: str) -> Dict[str, Any]:
        """获取压缩信息"""
        pass


__all__ = [
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
