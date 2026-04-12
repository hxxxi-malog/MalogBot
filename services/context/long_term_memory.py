"""
长期记忆服务模块

从对话中提取关键信息，向量化后存储到数据库，支持：
1. Agent 主动存储重要信息（通过工具调用）
2. 长文本自动分块后再向量化存储
3. 向量化存储，支持语义检索
4. 使用 Rerank 模型对检索结果进行相关性打分
5. MMR多样性重排序，避免重复内容
6. 只返回相关性高于阈值的信息
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
from services.rag.embedding_service import embedding_service
from services.rag.mmr_reranker import mmr_reranker
from services.chunk_service import chunk_service
from models.database import LongTermMemory

logger = logging.getLogger(__name__)

# 后台处理线程池
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory_extractor")


class MemoryType:
    """记忆类型常量"""
    USER_INFO = "user_info"        # 用户个人信息
    PREFERENCE = "preference"      # 用户偏好
    FACT = "fact"                  # 重要事实
    DECISION = "decision"          # 重要决策
    SUMMARY = "summary"            # 对话摘要
    PROJECT = "project"            # 项目信息


# 默认相关性阈值（Rerank 分数）
DEFAULT_RELEVANCE_THRESHOLD = 0.65


class LongTermMemoryService:
    """
    长期记忆服务
    
    核心功能：
    1. 存储重要信息（Agent 主动调用工具存储）
    2. 长文本自动分块后再向量化存储
    3. 向量化存储，支持语义检索
    4. 使用 Rerank 模型对检索结果打分
    5. MMR多样性重排序，避免重复内容
    
    设计原则：
    - Agent 决定什么信息重要
    - 长文本必须分块后再向量化
    - Rerank 决定检索结果的相关性
    - MMR保证结果多样性
    - 只返回高相关性的记忆
    """
    
    def __init__(
        self, 
        embedding_dimension: int = 1024,
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        mmr_alpha: float = 0.7
    ):
        """
        初始化长期记忆服务
        
        Args:
            embedding_dimension: 向量维度
            relevance_threshold: 相关性阈值（Rerank 分数）
            mmr_alpha: MMR相关性权重（默认0.7）
        """
        self.embedding_dimension = embedding_dimension
        self.relevance_threshold = relevance_threshold
        self.mmr_alpha = mmr_alpha
        self._pending_tasks: Dict[str, bool] = {}
        self._tasks_lock = threading.Lock()
    
    # ==================== 存储功能 ====================
    
    async def store_memory(
        self,
        content: str,
        memory_type: str = MemoryType.FACT,
        session_id: str = None,
        importance: float = 0.5,
        source_archive_id: str = None,
        tags: List[str] = None,
        metadata: dict = None
    ) -> Optional[int]:
        """
        存储单条记忆（支持长文本自动分块）
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型
            session_id: 来源会话ID
            importance: 重要性分数
            source_archive_id: 来源归档ID
            tags: 标签列表
            metadata: 额外元数据
            
        Returns:
            第一条记忆ID（分块时返回第一条的ID），失败返回None
        """
        try:
            # 对内容进行分块
            chunks = chunk_service.chunk_for_memory(content)
            
            if not chunks:
                logger.warning("[Memory] 内容为空，跳过存储")
                return None
            
            # 批量获取向量嵌入
            embeddings = await embedding_service.get_embeddings(chunks)
            
            if not embeddings or len(embeddings) != len(chunks):
                logger.error("[Memory] 向量化失败")
                return None
            
            with db_manager.get_session() as session:
                first_memory_id = None
                total_chunks = len(chunks)
                
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    memory = LongTermMemory(
                        session_id=session_id,
                        memory_type=memory_type,
                        content=chunk,
                        embedding=json.dumps(embedding) if embedding else None,
                        source_archive_id=source_archive_id,
                        importance=importance,
                        tags=json.dumps(tags) if tags else None,
                        metadata_json=json.dumps(metadata) if metadata else None,
                        # 分块相关字段
                        parent_id=None,  # 第一条记忆的 parent_id 为 None
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
                    for memory in session.query(LongTermMemory).filter(
                        LongTermMemory.id != first_memory_id,
                        LongTermMemory.total_chunks == total_chunks,
                        LongTermMemory.session_id == session_id,
                        LongTermMemory.memory_type == memory_type,
                        LongTermMemory.chunk_index > 0
                    ).order_by(LongTermMemory.id.desc()).limit(total_chunks - 1).all():
                        memory.parent_id = first_memory_id
                
                logger.info(
                    f"[Memory] 存储记忆成功: 原长度 {len(content)}, "
                    f"分块数 {total_chunks}, 类型: {memory_type}, 重要性: {importance}"
                )
                
                return first_memory_id
                
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
        
        每条记忆都会先进行分块处理，然后再向量化存储
        
        Args:
            memories: 记忆列表
            session_id: 来源会话ID
            source_archive_id: 来源归档ID
            
        Returns:
            成功存储的分块数量
        """
        if not memories:
            return 0
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            stored_count = 0
            
            # 1. 首先对所有记忆内容进行分块
            all_chunks = []
            chunk_info = []  # 记录每个分块对应的原始记忆索引
            
            for mem_idx, memory in enumerate(memories):
                content = memory.get('content', '')
                chunks = chunk_service.chunk_for_memory(content)
                
                for chunk_idx, chunk in enumerate(chunks):
                    all_chunks.append(chunk)
                    chunk_info.append({
                        'mem_idx': mem_idx,
                        'chunk_idx': chunk_idx,
                        'total_chunks': len(chunks),
                        'memory': memory
                    })
            
            if not all_chunks:
                logger.warning("[Memory] 没有需要存储的内容")
                return 0
            
            logger.info(f"[Memory] 批量存储: {len(memories)} 条记忆, 分块后共 {len(all_chunks)} 个分块")
            
            # 2. 批量获取所有分块的向量
            embeddings = loop.run_until_complete(
                embedding_service.get_embeddings(all_chunks)
            )
            
            if not embeddings:
                embeddings = [None] * len(all_chunks)
            
            # 3. 存储到数据库
            with db_manager.get_session() as session:
                # 记录每条原始记忆的第一个分块ID
                first_chunk_ids = {}  # mem_idx -> first_chunk_id
                
                for i, info in enumerate(chunk_info):
                    mem_idx = info['mem_idx']
                    memory = info['memory']
                    chunk_idx = info['chunk_idx']
                    total_chunks = info['total_chunks']
                    
                    try:
                        db_memory = LongTermMemory(
                            session_id=session_id,
                            memory_type=memory.get('type', MemoryType.FACT),
                            content=all_chunks[i],
                            embedding=json.dumps(embeddings[i]) if embeddings and embeddings[i] else None,
                            source_archive_id=source_archive_id,
                            importance=memory.get('importance', 0.5),
                            tags=json.dumps(memory.get('tags', [])),
                            metadata_json=json.dumps(memory.get('metadata')),
                            # 分块相关字段
                            parent_id=None,  # 暂时为None，后面更新
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
                        
                        stored_count += 1
                    except Exception as e:
                        logger.error(f"[Memory] 存储单条记忆失败: {e}")
                
                # 4. 更新后续分块的 parent_id
                for i, info in enumerate(chunk_info):
                    mem_idx = info['mem_idx']
                    chunk_idx = info['chunk_idx']
                    
                    if chunk_idx > 0 and mem_idx in first_chunk_ids:
                        # 找到对应的数据库记录并更新
                        # 通过 session_id, memory_type, chunk_index 等定位
                        pass  # 这里简化处理，实际可以批量更新
            
            logger.info(f"[Memory] 批量存储完成: 成功存储 {stored_count} 个分块")
            
            return stored_count
            
        finally:
            loop.close()
    
    # ==================== RAG 检索（使用 Rerank） ====================
    
    def search_memories_with_rerank(
        self,
        query: str,
        session_id: str = None,
        top_n: int = 10,
        relevance_threshold: float = None,
        memory_types: List[str] = None,
        cross_session: bool = True,  # 是否跨会话检索（默认跨会话）
        use_mmr: bool = True  # 是否使用MMR多样性重排序
    ) -> List[Dict]:
        """
        使用向量检索 + Rerank 模型进行记忆检索
        
        流程：
        1. 向量检索获取候选记忆
        2. 使用 Rerank 模型计算相关性分数
        3. 过滤掉相关性低于阈值的记忆
        4. MMR多样性重排序（可选）
        5. 返回高相关性记忆
        
        Args:
            query: 查询文本
            session_id: 会话ID（仅当 cross_session=False 时用于过滤）
            top_n: 返回的最大数量
            relevance_threshold: 相关性阈值（默认使用实例阈值）
            memory_types: 限制记忆类型
            cross_session: 是否跨会话检索（默认 True，检索所有会话的记忆）
            use_mmr: 是否使用MMR多样性重排序
            
        Returns:
            带相关性分数的记忆列表
        """
        threshold = relevance_threshold or self.relevance_threshold
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 1. 获取查询向量
            query_embedding = loop.run_until_complete(
                embedding_service.get_single_embedding(query)
            )
            
            if not query_embedding:
                logger.warning("[Memory] 无法获取查询向量")
                return []
            
            # 2. 向量检索获取候选
            with db_manager.get_session() as session:
                query_obj = session.query(LongTermMemory)
                
                if memory_types:
                    query_obj = query_obj.filter(
                        LongTermMemory.memory_type.in_(memory_types)
                    )
                
                # 跨会话检索时不限制 session_id
                if not cross_session and session_id:
                    query_obj = query_obj.filter_by(session_id=session_id)
                
                # 获取候选记忆（多取一些用于MMR筛选）
                candidates = query_obj.order_by(
                    LongTermMemory.importance.desc()
                ).limit(top_n * 3).all()
                
                if not candidates:
                    return []
                
                # 3. 计算向量相似度，筛选有向量的记忆
                valid_candidates = []
                for memory in candidates:
                    if memory.embedding:
                        try:
                            stored_embedding = json.loads(memory.embedding)
                            similarity = self._cosine_similarity(
                                query_embedding, stored_embedding
                            )
                            # 更新访问计数
                            memory.access_count += 1
                            
                            valid_candidates.append({
                                'memory': memory,
                                'embedding': stored_embedding,
                                'similarity': similarity
                            })
                        except:
                            pass
                
                if not valid_candidates:
                    return []
                
                # 4. 取相似度最高的作为候选文档
                valid_candidates.sort(key=lambda x: x['similarity'], reverse=True)
                top_candidates = valid_candidates[:top_n * 2]
                
                # 5. 使用 Rerank 模型进行精确打分
                documents = [c['memory'].content for c in top_candidates]
                
                rerank_results = loop.run_until_complete(
                    embedding_service.rerank(query, documents, top_k=len(documents))
                )
                
                # 6. 合并 Rerank 分数并过滤
                results = []
                for item in rerank_results:
                    idx = item['index']
                    relevance_score = item['relevance_score']
                    
                    if relevance_score >= threshold:
                        mem_dict = top_candidates[idx]['memory'].to_dict()
                        mem_dict['relevance_score'] = relevance_score
                        mem_dict['embedding'] = top_candidates[idx]['embedding']
                        results.append(mem_dict)
                
                logger.info(
                    f"[Memory] RAG检索: 候选 {len(candidates)} 条, "
                    f"Rerank后达标 {len(results)} 条 (阈值 {threshold})"
                )
                
                # 7. MMR多样性重排序
                if use_mmr and len(results) > top_n:
                    mmr_reranker.alpha = self.mmr_alpha
                    results = mmr_reranker.rerank(
                        results,
                        relevance_key='relevance_score',
                        content_key='content',
                        embedding_key='embedding',
                        top_k=top_n
                    )
                    logger.info(f"[Memory] MMR重排序完成, 返回 {len(results)} 条多样化记忆")
                else:
                    results = results[:top_n]
                
                return results
                
        except Exception as e:
            logger.error(f"[Memory] RAG检索失败: {e}")
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
    
    # ==================== 上下文注入 ====================
    
    def get_memories_for_context(
        self,
        query: str,
        session_id: str = None,
        max_tokens: int = 2000,
        relevance_threshold: float = None
    ) -> str:
        """
        获取用于注入上下文的记忆（使用新的记忆检索引擎）
        
        从 knowledge_items 表检索，支持混合检索 + MMR重排
        
        Args:
            query: 查询文本
            session_id: 会话ID（暂未使用，保留兼容）
            max_tokens: 最大token数
            relevance_threshold: 相关性阈值（暂未使用，由检索引擎配置控制）
            
        Returns:
            格式化的上下文字符串
        """
        try:
            # 使用新的记忆检索引擎
            from services.memory_search_engine import memory_search_engine, SearchConfig
            
            # 配置检索参数
            config = SearchConfig(
                min_hybrid_score=relevance_threshold or 0.3,
                use_mmr=True,
                use_time_decay=True
            )
            
            # 执行异步检索
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                with db_manager.get_session() as session:
                    results = loop.run_until_complete(
                        memory_search_engine.search(
                            query=query,
                            session=session,
                            top_k=15,
                            config=config
                        )
                    )
            finally:
                loop.close()
            
            if not results:
                return ""
            
            # 格式化输出
            lines = ["## 长期记忆上下文\n"]
            current_tokens = 0
            
            # 类型标签映射（新字段名）
            type_label_map = {
                'user_info': '用户信息',
                'preference': '偏好',
                'fact': '事实',
                'decision': '决策',
                'summary': '摘要',
                'project': '项目',
                'identity': '身份',
                'rule': '规则',
                'mistake': '踩坑'
            }
            
            for result in results:
                content = result.content
                item_type = result.item_type or 'unknown'
                final_score = result.final_score
                
                # 估算token
                tokens = len(content) // 3
                if current_tokens + tokens > max_tokens:
                    break
                
                type_label = type_label_map.get(item_type, item_type)
                
                lines.append(f"- [{type_label}] {content} (相关性: {final_score:.2f})")
                current_tokens += tokens
            
            if len(lines) > 1:
                return '\n'.join(lines) + '\n'
            return ""
            
        except Exception as e:
            logger.error(f"[Memory] 获取上下文记忆失败: {e}")
            return ""
    
    # ==================== 辅助方法 ====================
    
    def get_recent_memories(
        self,
        session_id: str = None,
        limit: int = 20,
        memory_types: List[str] = None
    ) -> List[Dict]:
        """获取最近的记忆"""
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


# 创建全局实例
long_term_memory = LongTermMemoryService()

# 导出
__all__ = ['LongTermMemoryService', 'long_term_memory', 'MemoryType', 'DEFAULT_RELEVANCE_THRESHOLD']
