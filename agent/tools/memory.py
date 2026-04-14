"""
记忆存储工具

让 Agent 自己决定哪些信息需要存储到记忆中。
Agent 可以在对话中识别重要信息，并调用此工具进行向量化存储。

使用场景：
1. 用户明确表达了个人信息（姓名、偏好等）
2. 用户做出了重要决定
3. 关键的项目配置或事实
4. 踩坑经验、学到的教训
5. 需要在后续对话中记住的内容

特性：
- LLM 智能分类：自动判断应该存到哪个分类（user/soul/agents/memory）
- 自动去重：相似记忆自动合并
- 向量化存储：支持语义检索

注意：不需要手动指定分类，系统会自动判断
"""
import logging
import threading
import asyncio
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.tools.registry import registry, ToolCategory

logger = logging.getLogger(__name__)

# 后台处理线程池
_memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory_store")


class StoreMemoryInput(BaseModel):
    """存储记忆工具的输入参数"""
    content: str = Field(
        description="需要存储的信息内容，应该清晰、完整地描述这个信息"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="可选的额外标签列表，系统会自动添加标签，你也可以添加额外的标签"
    )


@tool(args_schema=StoreMemoryInput)
def store_memory(
    content: str,
    tags: Optional[List[str]] = None
) -> str:
    """
    将重要信息存储到记忆中。
    
    系统会自动判断记忆应该归类到哪个分类，你只需要提供内容即可。
    
    **什么情况应该存储**：
    1. 用户明确表达了个人信息（姓名、职业、偏好等）
    2. 发现了重要的项目配置或技术事实
    3. 犯了错误、踩了坑，学到教训
    4. 做出了重要决策
    5. 用户强调要记住的内容
    
    **什么情况不需要存储**：
    1. 简单的问候、感谢
    2. 临时性状态
    3. 已经记住的重复信息
    
    Args:
        content: 需要存储的信息内容
        tags: 可选的额外标签
        
    Returns:
        存储结果
    """
    # 后台异步存储
    def _store_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from services.smart_memory_service import smart_memory
            
            item_id = loop.run_until_complete(
                smart_memory.store(
                    content=content,
                    extra_tags=tags
                )
            )
            
            if item_id:
                logger.info(f"[MemoryTool] 存储成功: id={item_id}, content={content[:50]}...")
            else:
                logger.warning(f"[MemoryTool] 存储失败: {content[:50]}...")
                
        except Exception as e:
            logger.error(f"[MemoryTool] 存储记忆失败: {e}")
        finally:
            loop.close()
    
    # 提交到后台线程
    _memory_executor.submit(_store_async)
    
    return f"已记录该信息，系统将自动分类存储。"


class StoreMemoryBatchInput(BaseModel):
    """批量存储记忆的输入参数"""
    memories: List[str] = Field(
        description="需要存储的记忆内容列表"
    )


@tool(args_schema=StoreMemoryBatchInput)
def store_memories_batch(memories: List[str]) -> str:
    """
    批量存储多条重要信息到记忆。
    
    当你需要一次性存储多条相关信息时使用此工具。
    
    Args:
        memories: 记忆内容列表
        
    Returns:
        存储结果信息
    """
    if not memories:
        return "没有需要存储的记忆"
    
    def _store_batch_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from services.smart_memory_service import smart_memory
            
            success_count = 0
            for content in memories:
                item_id = loop.run_until_complete(
                    smart_memory.store(content=content)
                )
                if item_id:
                    success_count += 1
            
            logger.info(f"[MemoryTool] 批量存储完成: {success_count}/{len(memories)}")
            
        except Exception as e:
            logger.error(f"[MemoryTool] 批量存储失败: {e}")
        finally:
            loop.close()
    
    _memory_executor.submit(_store_batch_async)
    
    return f"已提交 {len(memories)} 条信息进行存储。"


# ==================== 注册工具到 Registry ====================

for _tool in [store_memory, store_memories_batch]:
    registry.register(
        _tool,
        category=ToolCategory.MEMORY,
        for_sub_agent=True,
        priority=50,
        module=__name__
    )


# 导出工具（向后兼容）
MEMORY_TOOLS = [store_memory, store_memories_batch]

__all__ = ['store_memory', 'store_memories_batch', 'MEMORY_TOOLS']
