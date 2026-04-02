"""
记忆存储工具

让 Agent 自己决定哪些信息需要存储到长期记忆。
Agent 可以在对话中识别重要信息，并调用此工具进行向量化存储。

使用场景：
1. 用户明确表达了个人信息（姓名、偏好等）
2. 用户做出了重要决定
3. 关键的项目配置或事实
4. 需要在后续对话中记住的内容

特性：
- 长文本自动分块后再向量化存储
- 每个分块独立向量化和存储，支持更精确的语义检索
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
from services.chunk_service import chunk_service
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
            # 1. 对内容进行分块
            chunks = chunk_service.chunk_for_memory(content)
            
            if not chunks:
                logger.warning("[MemoryTool] 内容为空，跳过存储")
                return
            
            # 2. 批量获取所有分块的向量
            embeddings = loop.run_until_complete(
                embedding_service.get_embeddings(chunks)
            )
            
            if not embeddings:
                embeddings = [None] * len(chunks)
            
            # 3. 存储到数据库（session_id 设为 None，表示全局记忆，跨会话共享）
            with db_manager.get_session() as session:
                first_memory_id = None
                total_chunks = len(chunks)
                
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    memory = LongTermMemory(
                        session_id=None,  # 全局记忆，跨会话共享
                        memory_type=memory_type,
                        content=chunk,
                        embedding=json.dumps(embedding) if embedding else None,
                        importance=importance,
                        tags=json.dumps(tags) if tags else None,
                        metadata_json=json.dumps({
                            'stored_by': 'agent',
                            'store_time': datetime.now().isoformat(),
                            'original_length': len(content)
                        }),
                        # 分块相关字段
                        parent_id=None,
                        chunk_index=i,
                        total_chunks=total_chunks,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    session.add(memory)
                    session.flush()
                    
                    # 记录第一条记忆的ID
                    if i == 0:
                        first_memory_id = memory.id
                
                # 如果有多个分块，更新后续分块的 parent_id
                if total_chunks > 1 and first_memory_id:
                    # 查询刚插入的后续分块并更新 parent_id
                    subsequent_chunks = session.query(LongTermMemory).filter(
                        LongTermMemory.total_chunks == total_chunks,
                        LongTermMemory.chunk_index > 0,
                        LongTermMemory.session_id == None,
                        LongTermMemory.memory_type == memory_type
                    ).order_by(LongTermMemory.id.desc()).limit(total_chunks - 1).all()
                    
                    for chunk in subsequent_chunks:
                        chunk.parent_id = first_memory_id
            
            logger.info(
                f"[MemoryTool] 已存储记忆: {content[:50]}... "
                f"(类型: {memory_type}, 重要性: {importance}, 分块数: {total_chunks})"
            )
            
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
            # 1. 首先对所有记忆内容进行分块
            all_chunks = []
            chunk_info = []  # 记录每个分块对应的原始记忆信息
            
            for mem_idx, mem in enumerate(memories):
                content = mem.get('content', '')
                chunks = chunk_service.chunk_for_memory(content)
                
                for chunk_idx, chunk in enumerate(chunks):
                    all_chunks.append(chunk)
                    chunk_info.append({
                        'mem_idx': mem_idx,
                        'chunk_idx': chunk_idx,
                        'total_chunks': len(chunks),
                        'memory': mem
                    })
            
            if not all_chunks:
                logger.warning("[MemoryTool] 没有需要存储的内容")
                return
            
            logger.info(f"[MemoryTool] 批量存储: {len(memories)} 条记忆, 分块后共 {len(all_chunks)} 个分块")
            
            # 2. 批量获取所有分块的向量
            embeddings = loop.run_until_complete(
                embedding_service.get_embeddings(all_chunks)
            )
            
            if not embeddings:
                embeddings = [None] * len(all_chunks)
            
            # 3. 批量存储（session_id 设为 None，全局记忆）
            with db_manager.get_session() as session:
                # 记录每条原始记忆的第一个分块ID
                first_chunk_ids = {}  # mem_idx -> first_chunk_id
                
                for i, info in enumerate(chunk_info):
                    mem_idx = info['mem_idx']
                    memory = info['memory']
                    chunk_idx = info['chunk_idx']
                    total_chunks = info['total_chunks']
                    
                    memory_type = memory.get('memory_type', 'fact')
                    importance = memory.get('importance', MEMORY_IMPORTANCE.get(memory_type, 0.75))
                    
                    db_memory = LongTermMemory(
                        session_id=None,  # 全局记忆，跨会话共享
                        memory_type=memory_type,
                        content=all_chunks[i],
                        embedding=json.dumps(embeddings[i]) if embeddings and embeddings[i] else None,
                        importance=importance,
                        tags=json.dumps(memory.get('tags', [])),
                        metadata_json=json.dumps({
                            'stored_by': 'agent',
                            'store_time': datetime.now().isoformat(),
                            'original_length': len(memory.get('content', ''))
                        }),
                        # 分块相关字段
                        parent_id=None,
                        chunk_index=chunk_idx,
                        total_chunks=total_chunks,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    session.add(db_memory)
                    session.flush()
                    
                    # 记录第一条分块的ID
                    if chunk_idx == 0:
                        first_chunk_ids[mem_idx] = db_memory.id
            
            logger.info(f"[MemoryTool] 批量存储了 {len(memories)} 条记忆, 共 {len(all_chunks)} 个分块")
            
        except Exception as e:
            logger.error(f"[MemoryTool] 批量存储失败: {e}")
        finally:
            loop.close()
    
    _memory_executor.submit(_store_batch_async)
    
    return f"已将 {len(memories)} 条信息存储到长期记忆"


# 导出工具
MEMORY_TOOLS = [store_memory, store_memories_batch]

__all__ = ['store_memory', 'store_memories_batch', 'MEMORY_TOOLS', 'MemoryType']
