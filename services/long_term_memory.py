"""
长期记忆服务模块

从对话中提取关键信息，向量化后存储到数据库，支持：
1. 后台线程异步处理，不阻塞主流程
2. 智能提取关键信息（决策、偏好、事实等）
3. 向量化存储，支持语义检索
4. 重要性评分和访问计数
"""
import json
import logging
import threading
import asyncio
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.db_manager import db_manager
from services.embedding_service import embedding_service
from models.database import LongTermMemory

logger = logging.getLogger(__name__)

# 后台处理线程池
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory_extractor")


class MemoryType:
    """记忆类型常量"""
    FACT = "fact"              # 事实信息：用户告诉Agent的具体信息
    DECISION = "decision"      # 决策：Agent做出的重要决策
    PREFERENCE = "preference"  # 偏好：用户的偏好设置
    ACTION = "action"          # 行动：执行的重要操作
    SUMMARY = "summary"        # 摘要：对话的总结
    CONTEXT = "context"        # 上下文：文件路径、项目结构等上下文信息


class LongTermMemoryService:
    """
    长期记忆服务
    
    核心功能：
    1. 从对话中提取关键信息
    2. 向量化存储到数据库
    3. 支持语义检索
    
    设计原则：
    - 后台异步处理，不阻塞主对话流程
    - 智能去重，避免存储重复信息
    - 支持重要性评分，优先检索重要信息
    """
    
    def __init__(self, embedding_dimension: int = 1024):
        """
        初始化长期记忆服务
        
        Args:
            embedding_dimension: 向量维度
        """
        self.embedding_dimension = embedding_dimension
        self._pending_tasks: Dict[str, bool] = {}  # 追踪待处理任务
        self._tasks_lock = threading.Lock()
    
    # ==================== 关键信息提取 ====================
    
    def extract_key_information(self, messages: List[Dict]) -> List[Dict]:
        """
        从消息列表中提取关键信息
        
        提取规则：
        1. 事实信息：包含特定关键词的陈述
        2. 决策：Agent做出的选择和决定
        3. 偏好：用户的明确偏好声明
        4. 行动：执行的文件操作、代码修改等
        5. 上下文：涉及的文件路径、项目结构
        
        Args:
            messages: 消息列表
            
        Returns:
            提取的关键信息列表
        """
        extracted = []
        
        # 关键词模式
        fact_patterns = [
            r'项目位于\s*[\'"]?([^\s\'"]+)',
            r'文件\s*[\'"]?([^\s\'"]+)\s*存在',
            r'使用\s+(\w+)\s+(?:框架|库|工具)',
            r'数据库\s*[\'"]?([^\s\'"]+)',
            r'API\s*(?:key|密钥)\s*[\'"]?([^\s\'"]+)',
            r'配置\s*[\'"]?([^\s\'"]+)\s*[=:]\s*([^\s\'"]+)',
        ]
        
        preference_patterns = [
            r'我喜欢\s+(.+)',
            r'我希望\s+(.+)',
            r'请(?:使用|用)\s+(\w+)',
            r'不要\s+(.+)',
            r'保持\s+(.+)',
        ]
        
        action_patterns = [
            r'(?:创建|修改|删除|添加|更新)\s*(?:了)?\s*文件\s*[\'"]?([^\s\'"]+)',
            r'执行\s*(?:命令|脚本)\s*[\'"]?([^\s\'"]+)',
            r'(?:安装|卸载)\s*(?:了)?\s*(\S+)',
            r'(?:运行|启动)\s*(?:了)?\s*(\S+)',
        ]
        
        context_patterns = [
            r'([/\w]+\.\w+)',  # 文件路径
            r'(?:目录|文件夹)\s*[\'"]?([^\s\'"]+)',
        ]
        
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if not content or role == 'tool':
                continue
            
            # 提取事实信息
            for pattern in fact_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    if isinstance(match, tuple):
                        match = ' '.join(match)
                    extracted.append({
                        'type': MemoryType.FACT,
                        'content': match,
                        'source_role': role,
                        'importance': 0.7
                    })
            
            # 提取偏好信息（只从用户消息）
            if role == 'user':
                for pattern in preference_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        extracted.append({
                            'type': MemoryType.PREFERENCE,
                            'content': match,
                            'source_role': role,
                            'importance': 0.8  # 偏好信息重要性较高
                        })
            
            # 提取行动信息（主要从助手消息）
            if role == 'assistant':
                for pattern in action_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        extracted.append({
                            'type': MemoryType.ACTION,
                            'content': match,
                            'source_role': role,
                            'importance': 0.6
                        })
            
            # 提取上下文信息
            for pattern in context_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # 过滤太短的路径
                    if len(match) > 5 and '/' in match:
                        extracted.append({
                            'type': MemoryType.CONTEXT,
                            'content': match,
                            'source_role': role,
                            'importance': 0.5
                        })
        
        # 去重
        seen = set()
        unique_extracted = []
        for item in extracted:
            key = (item['type'], item['content'])
            if key not in seen:
                seen.add(key)
                unique_extracted.append(item)
        
        return unique_extracted
    
    def generate_summary(self, messages: List[Dict]) -> Optional[Dict]:
        """
        从消息列表生成摘要
        
        Args:
            messages: 消息列表
            
        Returns:
            摘要信息字典
        """
        if len(messages) < 3:
            return None
        
        # 统计信息
        user_msgs = [m for m in messages if m.get('role') == 'user']
        assistant_msgs = [m for m in messages if m.get('role') == 'assistant']
        
        # 提取用户主要意图
        first_user_msg = user_msgs[0].get('content', '') if user_msgs else ''
        
        # 提取涉及的文件
        all_content = ' '.join([m.get('content', '') for m in messages])
        files = set(re.findall(r'([/\w]+\.\w+)', all_content))
        
        # 构建摘要
        summary_parts = [
            f"对话包含 {len(user_msgs)} 个用户消息和 {len(assistant_msgs)} 个助手回复",
        ]
        
        if first_user_msg:
            summary_parts.append(f"用户初始请求: {first_user_msg[:100]}...")
        
        if files:
            summary_parts.append(f"涉及的文件: {', '.join(list(files)[:5])}")
        
        return {
            'type': MemoryType.SUMMARY,
            'content': ' | '.join(summary_parts),
            'importance': 0.6,
            'metadata': {
                'message_count': len(messages),
                'files': list(files)[:10]
            }
        }
    
    # ==================== 向量化存储 ====================
    
    async def store_memory(
        self,
        content: str,
        memory_type: str,
        session_id: str = None,
        importance: float = 0.5,
        source_archive_id: str = None,
        tags: List[str] = None,
        metadata: dict = None
    ) -> Optional[int]:
        """
        存储单条记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型
            session_id: 来源会话ID
            importance: 重要性分数
            source_archive_id: 来源归档ID
            tags: 标签列表
            metadata: 额外元数据
            
        Returns:
            记忆ID，失败返回None
        """
        try:
            # 获取向量嵌入
            embedding = await embedding_service.get_single_embedding(content)
            
            with db_manager.get_session() as session:
                memory = LongTermMemory(
                    session_id=session_id,
                    memory_type=memory_type,
                    content=content,
                    embedding=json.dumps(embedding) if embedding else None,
                    source_archive_id=source_archive_id,
                    importance=importance,
                    tags=json.dumps(tags) if tags else None,
                    metadata_json=json.dumps(metadata) if metadata else None,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                session.add(memory)
                session.flush()  # 获取ID
                return memory.id
                
        except Exception as e:
            logger.error(f"[Memory] 存储记忆失败: {e}")
            return None
    
    def store_memories_batch(
        self,
        memories: List[Dict],
        session_id: str = None,
        source_archive_id: str = None
    ) -> int:
        """
        批量存储记忆（同步版本，在后台线程中调用）
        
        Args:
            memories: 记忆列表
            session_id: 来源会话ID
            source_archive_id: 来源归档ID
            
        Returns:
            成功存储的数量
        """
        if not memories:
            return 0
        
        # 创建事件循环（在后台线程中）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            stored_count = 0
            
            # 批量获取向量
            contents = [m['content'] for m in memories]
            embeddings = loop.run_until_complete(
                embedding_service.get_embeddings(contents)
            )
            
            if not embeddings:
                embeddings = [None] * len(memories)
            
            # 存储到数据库
            with db_manager.get_session() as session:
                for i, memory in enumerate(memories):
                    try:
                        db_memory = LongTermMemory(
                            session_id=session_id,
                            memory_type=memory.get('type', MemoryType.FACT),
                            content=memory['content'],
                            embedding=json.dumps(embeddings[i]) if embeddings and embeddings[i] else None,
                            source_archive_id=source_archive_id,
                            importance=memory.get('importance', 0.5),
                            tags=json.dumps(memory.get('tags', [])),
                            metadata_json=json.dumps(memory.get('metadata')),
                            created_at=datetime.now(),
                            updated_at=datetime.now()
                        )
                        session.add(db_memory)
                        stored_count += 1
                    except Exception as e:
                        logger.error(f"[Memory] 存储单条记忆失败: {e}")
            
            return stored_count
            
        finally:
            loop.close()
    
    # ==================== 后台处理 ====================
    
    def process_messages_async(
        self,
        messages: List[Dict],
        session_id: str = None,
        source_archive_id: str = None,
        on_complete: callable = None
    ):
        """
        异步处理消息，提取并存储关键信息
        
        在后台线程中执行，不阻塞主流程。
        
        Args:
            messages: 消息列表
            session_id: 来源会话ID
            source_archive_id: 来源归档ID
            on_complete: 完成回调函数
        """
        task_key = f"{session_id}_{source_archive_id}"
        
        with self._tasks_lock:
            if task_key in self._pending_tasks:
                logger.info(f"[Memory] 任务已在处理中: {task_key}")
                return
            self._pending_tasks[task_key] = True
        
        def _process():
            try:
                # 提取关键信息
                key_info = self.extract_key_information(messages)
                
                # 生成摘要
                summary = self.generate_summary(messages)
                if summary:
                    key_info.append(summary)
                
                # 去重：检查是否已存在相似记忆
                unique_memories = self._deduplicate_memories(key_info, session_id)
                
                if unique_memories:
                    # 批量存储
                    stored = self.store_memories_batch(
                        unique_memories,
                        session_id,
                        source_archive_id
                    )
                    logger.info(f"[Memory] 存储了 {stored} 条记忆")
                
                if on_complete:
                    on_complete(len(unique_memories))
                    
            except Exception as e:
                logger.error(f"[Memory] 后台处理失败: {e}")
                
            finally:
                with self._tasks_lock:
                    self._pending_tasks.pop(task_key, None)
        
        # 提交到后台线程池
        _executor.submit(_process)
        logger.info(f"[Memory] 已提交后台处理任务: {task_key}")
    
    def _deduplicate_memories(
        self,
        memories: List[Dict],
        session_id: str = None
    ) -> List[Dict]:
        """
        去重：检查是否已存在相似记忆
        
        Args:
            memories: 待检查的记忆列表
            session_id: 会话ID
            
        Returns:
            去重后的记忆列表
        """
        try:
            with db_manager.get_session() as session:
                existing = session.query(LongTermMemory).filter_by(
                    session_id=session_id
                ).all()
                
                existing_contents = {m.content for m in existing}
                
                return [
                    m for m in memories
                    if m['content'] not in existing_contents
                ]
        except:
            return memories
    
    # ==================== 检索功能 ====================
    
    def search_memories(
        self,
        query: str,
        limit: int = 10,
        memory_types: List[str] = None,
        session_id: str = None,
        min_importance: float = 0.0
    ) -> List[Dict]:
        """
        搜索相关记忆（基于向量相似度）
        
        Args:
            query: 查询文本
            limit: 返回数量限制
            memory_types: 限制记忆类型
            session_id: 限制会话ID
            min_importance: 最小重要性
            
        Returns:
            相关记忆列表
        """
        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 获取查询向量
            query_embedding = loop.run_until_complete(
                embedding_service.get_single_embedding(query)
            )
            
            if not query_embedding:
                return []
            
            # 数据库查询
            with db_manager.get_session() as session:
                query_obj = session.query(LongTermMemory)
                
                if memory_types:
                    query_obj = query_obj.filter(
                        LongTermMemory.memory_type.in_(memory_types)
                    )
                if session_id:
                    query_obj = query_obj.filter_by(session_id=session_id)
                if min_importance > 0:
                    query_obj = query_obj.filter(
                        LongTermMemory.importance >= min_importance
                    )
                
                memories = query_obj.order_by(
                    LongTermMemory.importance.desc()
                ).limit(limit * 3).all()  # 取更多候选
                
                # 计算相似度
                scored_memories = []
                for memory in memories:
                    if memory.embedding:
                        try:
                            stored_embedding = json.loads(memory.embedding)
                            similarity = self._cosine_similarity(
                                query_embedding,
                                stored_embedding
                            )
                            scored_memories.append({
                                'memory': memory.to_dict(),
                                'score': similarity
                            })
                            
                            # 更新访问计数
                            memory.access_count += 1
                        except:
                            pass
                
                # 按相似度排序
                scored_memories.sort(key=lambda x: x['score'], reverse=True)
                
                return [m['memory'] for m in scored_memories[:limit]]
                
        except Exception as e:
            logger.error(f"[Memory] 搜索失败: {e}")
            return []
            
        finally:
            loop.close()
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import math
        
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_recent_memories(
        self,
        session_id: str = None,
        limit: int = 20,
        memory_types: List[str] = None
    ) -> List[Dict]:
        """
        获取最近的记忆
        
        Args:
            session_id: 会话ID
            limit: 返回数量
            memory_types: 记忆类型过滤
            
        Returns:
            记忆列表
        """
        try:
            with db_manager.get_session() as session:
                query_obj = session.query(LongTermMemory)
                
                if session_id:
                    query_obj = query_obj.filter_by(session_id=session_id)
                if memory_types:
                    query_obj = query_obj.filter(
                        LongTermMemory.memory_type.in_(memory_types)
                    )
                
                memories = query_obj.order_by(
                    LongTermMemory.created_at.desc()
                ).limit(limit).all()
                
                return [m.to_dict() for m in memories]
        except Exception as e:
            logger.error(f"[Memory] 获取最近记忆失败: {e}")
            return []
    
    def get_memories_for_context(
        self,
        query: str,
        session_id: str = None,
        max_tokens: int = 2000
    ) -> str:
        """
        获取用于注入上下文的记忆
        
        将相关记忆格式化为上下文字符串。
        
        Args:
            query: 查询文本
            session_id: 会话ID
            max_tokens: 最大token数
            
        Returns:
            格式化的上下文字符串
        """
        # 搜索相关记忆
        memories = self.search_memories(
            query,
            limit=10,
            session_id=session_id,
            min_importance=0.3
        )
        
        if not memories:
            return ""
        
        # 格式化
        lines = ["## 长期记忆上下文\n"]
        current_tokens = 0
        
        for memory in memories:
            content = memory.get('content', '')
            memory_type = memory.get('memory_type', 'unknown')
            
            # 估算token
            tokens = len(content) // 3
            if current_tokens + tokens > max_tokens:
                break
            
            type_label = {
                MemoryType.FACT: "事实",
                MemoryType.DECISION: "决策",
                MemoryType.PREFERENCE: "偏好",
                MemoryType.ACTION: "行动",
                MemoryType.SUMMARY: "摘要",
                MemoryType.CONTEXT: "上下文"
            }.get(memory_type, memory_type)
            
            lines.append(f"- [{type_label}] {content}")
            current_tokens += tokens
        
        if len(lines) > 1:
            return '\n'.join(lines) + '\n'
        return ""


# 创建全局实例
long_term_memory = LongTermMemoryService()

# 导出
__all__ = ['LongTermMemoryService', 'long_term_memory', 'MemoryType']
