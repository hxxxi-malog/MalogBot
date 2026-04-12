"""
智能记忆服务

实现 Agent 自主决策 + LLM 智能分类存储：
1. Agent 只需决定"这个信息需要记住"
2. LLM 自动判断应该存到哪个分类（user/soul/agents/memory）
3. 自动检测重复并合并/更新
4. 统一存储到 knowledge_items 表

设计理念：
- Agent 决策：什么值得记忆
- LLM 判断：如何分类存储
- 自动去重：避免冗余
- RAG打分：检索时动态评分
"""
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from services.db_manager import db_manager
from services.agent_knowledge_repository import knowledge_item_repo
from models.agent_knowledge import KnowledgeItem

logger = logging.getLogger(__name__)


class MemoryCategory:
    """记忆分类"""
    USER = 'user'        # 用户信息（个人信息、偏好、习惯）
    SOUL = 'soul'        # Agent人格（身份、职责、核心价值观）
    AGENTS = 'agents'    # 行为规则（规则、踩坑、最佳实践）
    MEMORY = 'memory'    # 通用记忆（事实、项目信息、决策）


class ItemType:
    """条目类型"""
    USER_INFO = 'user_info'      # 用户个人信息
    PREFERENCE = 'preference'    # 用户偏好
    IDENTITY = 'identity'        # Agent身份
    RULE = 'rule'                # 行为规则
    MISTAKE = 'mistake'          # 踩坑经验
    FACT = 'fact'                # 事实
    DECISION = 'decision'        # 决策
    PROJECT = 'project'          # 项目信息


@dataclass
class ClassifyResult:
    """分类结果"""
    category: str           # source_file_type
    item_type: str          # item_type
    tags: List[str]         # 标签
    reasoning: str          # 分类理由


# LLM 分类 Prompt
CLASSIFY_PROMPT = """分析以下记忆内容，判断它应该归类到哪个分类：

记忆内容："{content}"

分类选项：
1. user - 用户个人信息、偏好、习惯（涉及用户自身相关，如姓名、职业、喜好等）
2. soul - Agent人格、行为准则、核心价值观（关于Agent身份和职责的定义）
3. agents - 行为规则、踩坑经验、最佳实践（应该做什么、不应该做什么、学到的教训）
4. memory - 通用记忆、项目信息、事实（项目配置、技术栈、一般性知识）

请返回 JSON 格式（不要包含其他内容）：
{{
    "category": "user|soul|agents|memory",
    "item_type": "user_info|preference|identity|rule|mistake|fact|decision|project",
    "tags": ["tag1", "tag2"],
    "reasoning": "简短的分类理由"
}}

注意：
- item_type 说明：user_info(用户信息)、preference(偏好)、identity(身份)、rule(规则)、mistake(踩坑)、fact(事实)、decision(决策)、project(项目)
- tags 应该是有意义的标签，便于后续检索
- 只返回 JSON，不要有其他文字"""


class SmartMemoryService:
    """
    智能记忆服务
    
    核心功能：
    1. LLM 智能分类：根据内容自动判断 category 和 item_type
    2. 重复检测：向量化后检查相似记忆
    3. 自动合并：高度相似的记忆自动合并/更新
    4. 统一存储：所有记忆存入 knowledge_items 表
    
    注意：不预设重要性，检索时由 RAG 统一打分
    """
    
    def __init__(
        self,
        similarity_threshold: float = 0.85,  # 相似度阈值（认为相似）
        merge_threshold: float = 0.92,       # 合并阈值（认为相同）
        llm_client = None                    # LLM 客户端
    ):
        """
        初始化智能记忆服务
        
        Args:
            similarity_threshold: 相似度阈值，超过此值认为相似
            merge_threshold: 合并阈值，超过此值认为是同一条记忆
            llm_client: LLM 客户端实例
        """
        self.similarity_threshold = similarity_threshold
        self.merge_threshold = merge_threshold
        self._llm_client = llm_client
        logger.info(f"[SmartMemory] 初始化完成: similarity={similarity_threshold}, merge={merge_threshold}")
    
    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client:
            return self._llm_client
        
        # 延迟导入，避免循环依赖
        try:
            # 方式1：使用 agent/llm.py 的 get_llm
            from agent.llm import get_llm
            self._llm_client = get_llm(streaming=False)
            logger.info("[SmartMemory] 使用 agent.llm.get_llm 作为 LLM 客户端")
            return self._llm_client
        except ImportError:
            logger.warning("[SmartMemory] 无法导入 agent.llm.get_llm")
        
        try:
            # 方式2：使用 config 直接创建
            from config import Config
            from langchain_openai import ChatOpenAI
            self._llm_client = ChatOpenAI(
                model=Config.MODEL_NAME,
                openai_api_base=Config.DEEPSEEK_BASE_URL,
                openai_api_key=Config.DEEPSEEK_API_KEY,
                temperature=0.3,
                streaming=False
            )
            logger.info("[SmartMemory] 使用 config 直接创建 LLM 客户端")
            return self._llm_client
        except Exception as e:
            logger.error(f"[SmartMemory] 无法创建 LLM 客户端: {e}")
            return None
    
    async def classify_by_llm(
        self, 
        content: str
    ) -> ClassifyResult:
        """
        使用 LLM 进行智能分类
        
        Args:
            content: 记忆内容
        
        Returns:
            ClassifyResult: 分类结果
        """
        llm_client = self._get_llm_client()
        
        if not llm_client:
            # 如果没有 LLM 客户端，使用默认分类
            logger.warning("[SmartMemory] LLM 客户端不可用，使用默认分类")
            return ClassifyResult(
                category=MemoryCategory.MEMORY,
                item_type=ItemType.FACT,
                tags=['fact'],
                reasoning="LLM不可用，使用默认分类"
            )
        
        try:
            # 构建 prompt
            prompt = CLASSIFY_PROMPT.format(content=content)
            
            logger.info(f"[SmartMemory] LLM 分类中: {content[:50]}...")
            
            # 调用 LLM
            response = await llm_client.ainvoke(prompt)
            
            # 解析响应
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # 提取 JSON
            json_str = self._extract_json(response_text)
            
            if json_str:
                data = json.loads(json_str)
                result = ClassifyResult(
                    category=data.get('category', MemoryCategory.MEMORY),
                    item_type=data.get('item_type', ItemType.FACT),
                    tags=data.get('tags', []),
                    reasoning=data.get('reasoning', '')
                )
                logger.info(f"[SmartMemory] LLM 分类结果: {result.category}/{result.item_type}, 理由: {result.reasoning}")
                return result
            else:
                logger.warning(f"[SmartMemory] 无法解析 LLM 响应: {response_text[:100]}")
                return ClassifyResult(
                    category=MemoryCategory.MEMORY,
                    item_type=ItemType.FACT,
                    tags=['fact'],
                    reasoning="无法解析LLM响应"
                )
                
        except Exception as e:
            logger.error(f"[SmartMemory] LLM 分类失败: {e}")
            return ClassifyResult(
                category=MemoryCategory.MEMORY,
                item_type=ItemType.FACT,
                tags=['fact'],
                reasoning=f"LLM分类失败: {str(e)}"
            )
    
    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON"""
        # 尝试直接解析
        text = text.strip()
        if text.startswith('{') and text.endswith('}'):
            return text
        
        # 尝试从 markdown 代码块中提取
        if '```json' in text:
            start = text.find('```json') + 7
            end = text.find('```', start)
            if end > start:
                return text[start:end].strip()
        elif '```' in text:
            start = text.find('```') + 3
            end = text.find('```', start)
            if end > start:
                return text[start:end].strip()
        
        # 尝试找到 JSON 对象
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            return text[start:end+1]
        
        return None
    
    async def check_duplicate(
        self,
        content: str,
        embedding: List[float] = None
    ) -> Optional[Dict]:
        """
        检查是否存在相似记忆
        
        Args:
            content: 记忆内容
            embedding: 向量嵌入（可选，如果不提供则自动获取）
        
        Returns:
            相似记忆信息，或 None
        """
        # 获取向量嵌入
        if embedding is None:
            try:
                from services.rag.embedding_service import embedding_service
                embedding = await embedding_service.get_single_embedding(content)
            except Exception as e:
                logger.error(f"[SmartMemory] 获取向量失败: {e}")
                return None
        
        if embedding is None:
            return None
        
        # 向量检索相似记忆
        with db_manager.get_session() as session:
            results = knowledge_item_repo.search_vector(
                session,
                query_embedding=embedding,
                top_k=5,
                min_similarity=self.similarity_threshold
            )
            
            if results:
                return results[0]
        
        return None
    
    async def store(
        self,
        content: str,
        session_id: str = None,
        extra_tags: List[str] = None
    ) -> Optional[int]:
        """
        智能存储记忆
        
        流程：
        1. LLM 智能分类
        2. 检查重复
        3. 存储或更新
        
        Args:
            content: 记忆内容
            session_id: 来源会话ID
            extra_tags: 额外标签
        
        Returns:
            记忆ID，失败返回 None
        """
        try:
            logger.info(f"[SmartMemory] 开始存储: {content[:50]}...")
            
            # 1. LLM 智能分类
            classify_result = await self.classify_by_llm(content)
            
            category = classify_result.category
            item_type = classify_result.item_type
            tags = classify_result.tags
            
            # 合并额外标签
            if extra_tags:
                tags = list(set(tags + extra_tags))
            
            logger.info(f"[SmartMemory] 分类完成: category={category}, type={item_type}, tags={tags}")
            
            # 2. 获取向量嵌入
            try:
                from services.rag.embedding_service import embedding_service
                embedding = await embedding_service.get_single_embedding(content)
            except Exception as e:
                logger.error(f"[SmartMemory] 获取向量失败: {e}")
                return None
            
            if embedding is None:
                logger.warning("[SmartMemory] 向量化失败")
                return None
            
            # 3. 检查重复
            similar = await self.check_duplicate(content, embedding)
            
            with db_manager.get_session() as session:
                if similar and similar['similarity'] >= self.merge_threshold:
                    # 高度相似，更新现有记录
                    logger.info(f"[SmartMemory] 发现相似记忆(id={similar['id']}, sim={similar['similarity']:.2f})，更新而非新建")
                    
                    # 直接使用 session 执行更新
                    from sqlalchemy import text
                    session.execute(text("""
                        UPDATE knowledge_items
                        SET last_accessed_at = :time
                        WHERE id = :id
                    """), {'time': datetime.now(), 'id': similar['id']})
                    session.flush()
                    
                    return similar['id']
                
                # 4. 创建新记忆
                item = knowledge_item_repo.create_with_embedding(
                    session,
                    content=content,
                    item_type=item_type,
                    embedding=embedding,
                    source_file_type=category,
                    session_id=session_id,
                    importance=0.5,  # 默认值，检索时动态打分
                    tags=tags
                )
                
                logger.info(f"[SmartMemory] 创建新记忆成功: id={item.id}, category={category}, type={item_type}")
                return item.id
                
        except Exception as e:
            logger.error(f"[SmartMemory] 存储失败: {e}")
            return None
    
    def get_memories_by_category(
        self,
        category: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        按分类获取记忆
        
        Args:
            category: 分类 (user/soul/agents/memory)
            limit: 返回数量限制
        
        Returns:
            记忆列表
        """
        with db_manager.get_session() as session:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT id, content, item_type, tags, created_at, last_accessed_at, access_count
                FROM knowledge_items
                WHERE source_file_type = :category
                  AND is_expired = FALSE
                ORDER BY created_at DESC
                LIMIT :limit
            """), {'category': category, 'limit': limit})
            
            return [dict(row._mapping) for row in result]
    
    async def search(
        self,
        query: str,
        top_k: int = 10
    ) -> List[Dict]:
        """
        搜索记忆
        
        Args:
            query: 查询文本
            top_k: 返回数量
        
        Returns:
            搜索结果列表
        """
        try:
            # 获取查询向量
            from services.rag.embedding_service import embedding_service
            query_embedding = await embedding_service.get_single_embedding(query)
            
            if query_embedding is None:
                logger.warning("[SmartMemory] 无法获取查询向量")
                return []
            
            # 混合检索
            with db_manager.get_session() as session:
                results = knowledge_item_repo.search_hybrid(
                    session,
                    query=query,
                    query_embedding=query_embedding,
                    top_k=top_k
                )
                
                logger.info(f"[SmartMemory] 搜索返回 {len(results)} 条结果")
                return results
                
        except Exception as e:
            logger.error(f"[SmartMemory] 搜索失败: {e}")
            return []


# 全局实例
smart_memory = SmartMemoryService()


# 导出
__all__ = [
    'SmartMemoryService',
    'smart_memory',
    'MemoryCategory',
    'ItemType',
    'ClassifyResult'
]
