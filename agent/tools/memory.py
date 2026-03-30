"""
记忆存储工具

让 Agent 自己决定哪些信息需要存储到长期记忆。
Agent 可以在对话中识别重要信息，并调用此工具进行向量化存储。

使用场景：
1. 用户明确表达了个人信息（姓名、偏好等）
2. 用户做出了重要决定
3. 关键的项目配置或事实
4. 需要在后续对话中记住的内容
"""
import json
import logging
import threading
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.db_manager import db_manager
from services.embedding_service import embedding_service
from models.database import LongTermMemory

logger = logging.getLogger(__name__)

# 后台处理线程池
_memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory_store")


class MemoryType:
    """记忆类型"""
    USER_INFO = "user_info"        # 用户个人信息（姓名、年龄、职业等）
    USER_PREFERENCE = "preference"  # 用户偏好
    IMPORTANT_FACT = "fact"        # 重要事实
    DECISION = "decision"          # 重要决策
    PROJECT_INFO = "project"       # 项目相关信息


# 记忆类型的重要性默认值
MEMORY_IMPORTANCE = {
    MemoryType.USER_INFO: 0.95,
    MemoryType.USER_PREFERENCE: 0.85,
    MemoryType.IMPORTANT_FACT: 0.75,
    MemoryType.DECISION: 0.80,
    MemoryType.PROJECT_INFO: 0.70,
}


class StoreMemoryInput(BaseModel):
    """存储记忆工具的输入参数"""
    content: str = Field(
        description="需要存储的信息内容，应该清晰、完整地描述这个信息"
    )
    memory_type: str = Field(
        default="fact",
        description="记忆类型：user_info（用户个人信息）、preference（用户偏好）、fact（重要事实）、decision（决策）、project（项目信息）"
    )
    importance: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="重要性分数 0-1，越高越重要。用户个人信息建议 0.9+，偏好 0.85，事实 0.75，决策 0.8"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="可选的标签列表，用于分类和检索"
    )


@tool(args_schema=StoreMemoryInput)
def store_memory(
    content: str,
    memory_type: str = "fact",
    importance: float = 0.75,
    tags: Optional[List[str]] = None
) -> str:
    """
    将重要信息存储到长期记忆中。
    
    当你识别到以下类型的信息时，应该调用此工具：
    1. 用户的个人信息（姓名、年龄、职业、联系方式等）
    2. 用户的偏好（喜欢什么、不喜欢什么、习惯等）
    3. 重要的决策或选择
    4. 项目相关的关键配置或事实
    5. 用户明确表示需要记住的内容
    
    存储的信息可以在后续对话中通过语义检索被找回。
    
    Args:
        content: 需要存储的信息内容
        memory_type: 记忆类型
        importance: 重要性分数
        tags: 可选标签
        
    Returns:
        存储结果信息
    """
    # 使用默认重要性
    if memory_type in MEMORY_IMPORTANCE and importance == 0.75:
        importance = MEMORY_IMPORTANCE[memory_type]
    
    # 后台异步存储
    def _store_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 获取向量
            embedding = loop.run_until_complete(
                embedding_service.get_single_embedding(content)
            )
            
            # 存储到数据库（session_id 设为 None，表示全局记忆，跨会话共享）
            with db_manager.get_session() as session:
                memory = LongTermMemory(
                    session_id=None,  # 全局记忆，跨会话共享
                    memory_type=memory_type,
                    content=content,
                    embedding=json.dumps(embedding) if embedding else None,
                    importance=importance,
                    tags=json.dumps(tags) if tags else None,
                    metadata_json=json.dumps({
                        'stored_by': 'agent',
                        'store_time': datetime.now().isoformat()
                    }),
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                session.add(memory)
                
            logger.info(f"[MemoryTool] 已存储记忆: {content[:50]}... (类型: {memory_type}, 重要性: {importance})")
            
        except Exception as e:
            logger.error(f"[MemoryTool] 存储记忆失败: {e}")
        finally:
            loop.close()
    
    # 提交到后台线程
    _memory_executor.submit(_store_async)
    
    return f"已将信息存储到长期记忆（类型: {memory_type}, 重要性: {importance:.2f}）。后续对话中可以检索到这条信息。"


class StoreMemoryBatchInput(BaseModel):
    """批量存储记忆的输入参数"""
    memories: List[Dict[str, Any]] = Field(
        description="需要存储的记忆列表，每项包含 content, memory_type, importance"
    )


@tool(args_schema=StoreMemoryBatchInput)
def store_memories_batch(memories: List[Dict[str, Any]]) -> str:
    """
    批量存储多条重要信息到长期记忆。
    
    当你需要一次性存储多条相关信息时使用此工具。
    
    Args:
        memories: 记忆列表，每项包含:
            - content: 信息内容
            - memory_type: 记忆类型
            - importance: 重要性分数
            
    Returns:
        存储结果信息
    """
    if not memories:
        return "没有需要存储的记忆"
    
    def _store_batch_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 批量获取向量
            contents = [m.get('content', '') for m in memories]
            embeddings = loop.run_until_complete(
                embedding_service.get_embeddings(contents)
            )
            
            if not embeddings:
                embeddings = [None] * len(memories)
            
            # 批量存储（session_id 设为 None，全局记忆）
            with db_manager.get_session() as session:
                for i, mem in enumerate(memories):
                    memory_type = mem.get('memory_type', 'fact')
                    importance = mem.get('importance', MEMORY_IMPORTANCE.get(memory_type, 0.75))
                    
                    memory = LongTermMemory(
                        session_id=None,  # 全局记忆，跨会话共享
                        memory_type=memory_type,
                        content=mem.get('content', ''),
                        embedding=json.dumps(embeddings[i]) if embeddings and embeddings[i] else None,
                        importance=importance,
                        tags=json.dumps(mem.get('tags', [])),
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    session.add(memory)
            
            logger.info(f"[MemoryTool] 批量存储了 {len(memories)} 条记忆")
            
        except Exception as e:
            logger.error(f"[MemoryTool] 批量存储失败: {e}")
        finally:
            loop.close()
    
    _memory_executor.submit(_store_batch_async)
    
    return f"已将 {len(memories)} 条信息存储到长期记忆"


# 导出工具
MEMORY_TOOLS = [store_memory, store_memories_batch]

__all__ = ['store_memory', 'store_memories_batch', 'MEMORY_TOOLS', 'MemoryType']
