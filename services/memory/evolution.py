"""
知识演化服务

实现 Agent 知识的自我演化和维护：
1. 记忆提炼 - 从原始记忆中提炼长期有效的知识
2. 踩坑转规则 - 将重复踩坑转化为行为规则
3. 知识质量维护 - 清理、归档、合并过时知识

设计理念：
- 定时任务触发，后台静默执行
- LLM 智能提炼，保证质量
- 自动化维护，减少人工干预
"""
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

from services.db_manager import db_manager
from services.agent_knowledge_repository import (
    knowledge_item_repo,
    knowledge_item_repo_enhanced,
    agent_mistake_repo,
    agent_rule_repo
)

logger = logging.getLogger(__name__)


# ==================== Prompt 模板 ====================

REFINE_PROMPT = """分析以下原始记忆，提炼出长期有效的知识。

原始记忆内容：
{memories}

请提炼以下类型的信息：
1. 用户相关信息 - 用户个人信息、偏好、习惯
2. 项目相关知识 - 项目配置、技术栈、关键事实
3. 行为经验 - 值得保留的教训、最佳实践

要求：
- 去除临时性内容（如"今天"、"刚才"等时间词）
- 合并重复或相似的信息
- 一条记忆只写一个事实
- 为每条提炼结果确定合适的类型

输出 JSON 格式：
{{
    "refined_memories": [
        {{
            "content": "提炼后的内容",
            "item_type": "user_info|preference|fact|lesson|project",
            "importance": 0.5-1.0,
            "tags": ["tag1", "tag2"]
        }}
    ],
    "summary": "本次提炼的简要总结"
}}

只输出 JSON，不要有其他内容。"""


MISTAKE_TO_RULE_PROMPT = """将以下踩坑记录转化为行为规则。

踩坑信息：
- 类型：{mistake_type}
- 上下文：{context}
- 教训：{lesson}
- 解决方案：{solution}
- 发生次数：{occurrence_count}

请提炼一条清晰、可执行的行为规则。规则应该：
1. 简洁明了，一句话描述
2. 指明应该做什么或不应该做什么
3. 适用于未来类似场景

输出 JSON 格式：
{{
    "rule_content": "规则内容",
    "rule_type": "safety|efficiency|style|domain",
    "reasoning": "提炼理由"
}}

只输出 JSON，不要有其他内容。"""


# ==================== 数据类 ====================

@dataclass
class RefinedMemory:
    """提炼后的记忆"""
    content: str
    item_type: str
    importance: float
    tags: List[str]


@dataclass
class RefineResult:
    """提炼结果"""
    refined_memories: List[RefinedMemory]
    summary: str
    source_count: int
    created_count: int


# ==================== 核心服务 ====================

class KnowledgeEvolutionService:
    """知识演化服务"""
    
    def __init__(self, llm_client=None):
        """
        初始化知识演化服务
        
        Args:
            llm_client: LLM 客户端实例
        """
        self._llm_client = llm_client
        logger.info("[KnowledgeEvolution] 初始化完成")
    
    def _get_llm_client(self):
        """获取 LLM 客户端"""
        if self._llm_client:
            return self._llm_client
        
        try:
            from agent.llm import get_llm
            self._llm_client = get_llm(streaming=False)
            return self._llm_client
        except Exception as e:
            logger.warning(f"[KnowledgeEvolution] 无法获取 LLM 客户端: {e}")
            return None
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本向量"""
        try:
            from services.rag.embedding_service import embedding_service
            return await embedding_service.get_single_embedding(text)
        except Exception as e:
            logger.error(f"[KnowledgeEvolution] 获取向量失败: {e}")
            return None
    
    async def _call_llm(self, prompt: str) -> Optional[str]:
        """调用 LLM"""
        llm = self._get_llm_client()
        if not llm:
            return None
        
        try:
            response = await llm.ainvoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"[KnowledgeEvolution] LLM 调用失败: {e}")
            return None
    
    def _extract_json(self, text: str) -> Optional[str]:
        """从文本中提取 JSON"""
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
    
    # ==================== 记忆提炼 ====================
    
    async def refine_memories(
        self,
        batch_size: int = 20,
        max_batches: int = 5
    ) -> RefineResult:
        """
        提炼未处理的原始记忆
        
        Args:
            batch_size: 每批处理的记忆数量
            max_batches: 最大处理批数
            
        Returns:
            提炼结果统计
        """
        logger.info(f"[KnowledgeEvolution] 开始记忆提炼: batch_size={batch_size}, max_batches={max_batches}")
        
        all_refined = []
        total_source = 0
        total_created = 0
        summary_parts = []
        
        for batch_num in range(max_batches):
            # 获取未提炼的原始记忆
            with db_manager.get_session() as session:
                from sqlalchemy import text
                result = session.execute(text("""
                    SELECT id, content, session_id, created_at
                    FROM knowledge_items
                    WHERE item_type = 'daily'
                      AND is_refined = FALSE
                      AND created_at < CURRENT_DATE - INTERVAL '1 day'
                    ORDER BY created_at
                    LIMIT :limit
                """), {'limit': batch_size})
                
                rows = list(result)
                
                if not rows:
                    logger.info(f"[KnowledgeEvolution] 没有待提炼的记忆")
                    break
                
                # 收集记忆内容
                memories_text = []
                memory_ids = []
                session_map = {}
                
                for row in rows:
                    memory_ids.append(row.id)
                    memories_text.append(f"- {row.content}")
                    if row.session_id:
                        session_map[row.content] = row.session_id
                
                total_source += len(memory_ids)
                
                logger.info(f"[KnowledgeEvolution] 处理第 {batch_num + 1} 批: {len(memory_ids)} 条记忆")
            
            # 调用 LLM 提炼
            prompt = REFINE_PROMPT.format(memories="\n".join(memories_text))
            response = await self._call_llm(prompt)
            
            if not response:
                logger.warning(f"[KnowledgeEvolution] LLM 未返回结果，跳过本批")
                continue
            
            # 解析结果
            json_str = self._extract_json(response)
            if not json_str:
                logger.warning(f"[KnowledgeEvolution] 无法解析 LLM 响应")
                continue
            
            try:
                data = json.loads(json_str)
                refined_items = data.get('refined_memories', [])
                summary = data.get('summary', '')
                
                if summary:
                    summary_parts.append(summary)
                
                # 存储提炼结果
                with db_manager.get_session() as session:
                    for item in refined_items:
                        content = item.get('content', '')
                        item_type = item.get('item_type', 'fact')
                        importance = item.get('importance', 0.6)
                        tags = item.get('tags', [])
                        
                        if not content:
                            continue
                        
                        # 获取向量
                        embedding = await self._get_embedding(content)
                        
                        if embedding:
                            # 创建新的知识条目
                            knowledge_item_repo.create_with_embedding(
                                session,
                                content=content,
                                item_type=item_type,
                                embedding=embedding,
                                source_file_type='memory',
                                importance=importance,
                                tags=tags
                            )
                            total_created += 1
                            all_refined.append(RefinedMemory(
                                content=content,
                                item_type=item_type,
                                importance=importance,
                                tags=tags
                            ))
                    
                    # 标记原始记忆为已提炼
                    from sqlalchemy import text as sql_text
                    session.execute(sql_text("""
                        UPDATE knowledge_items
                        SET is_refined = TRUE
                        WHERE id = ANY(:ids)
                    """), {'ids': memory_ids})
                    
                    logger.info(f"[KnowledgeEvolution] 第 {batch_num + 1} 批提炼完成: 创建 {len(refined_items)} 条新记忆")
                    
            except json.JSONDecodeError as e:
                logger.error(f"[KnowledgeEvolution] JSON 解析失败: {e}")
                continue
        
        return RefineResult(
            refined_memories=all_refined,
            summary="; ".join(summary_parts) if summary_parts else "提炼完成",
            source_count=total_source,
            created_count=total_created
        )
    
    # ==================== 踩坑转规则 ====================
    
    async def convert_mistakes_to_rules(
        self,
        min_occurrence: int = 2,
        min_severity: str = 'medium',
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        将符合条件的踩坑转化为规则
        
        Args:
            min_occurrence: 最小发生次数
            min_severity: 最小严重程度
            limit: 最大处理数量
            
        Returns:
            转化结果列表
        """
        logger.info(f"[KnowledgeEvolution] 开始踩坑转规则: min_occurrence={min_occurrence}, min_severity={min_severity}")
        
        results = []
        
        with db_manager.get_session() as session:
            # 获取符合条件的踩坑
            mistakes = agent_mistake_repo.get_for_rule_generation(
                session,
                min_occurrence=min_occurrence,
                min_severity=min_severity
            )[:limit]
            
            if not mistakes:
                logger.info("[KnowledgeEvolution] 没有符合条件的踩坑")
                return results
            
            logger.info(f"[KnowledgeEvolution] 找到 {len(mistakes)} 条可转化的踩坑")
            
            for mistake in mistakes:
                # 调用 LLM 提炼规则
                prompt = MISTAKE_TO_RULE_PROMPT.format(
                    mistake_type=mistake.mistake_type,
                    context=mistake.context,
                    lesson=mistake.lesson or '',
                    solution=mistake.solution or '',
                    occurrence_count=mistake.occurrence_count
                )
                
                response = await self._call_llm(prompt)
                
                if not response:
                    logger.warning(f"[KnowledgeEvolution] LLM 未返回结果，跳过踩坑 {mistake.id}")
                    continue
                
                # 解析结果
                json_str = self._extract_json(response)
                if not json_str:
                    continue
                
                try:
                    data = json.loads(json_str)
                    rule_content = data.get('rule_content', '')
                    rule_type = data.get('rule_type', 'efficiency')
                    reasoning = data.get('reasoning', '')
                    
                    if not rule_content:
                        continue
                    
                    # 创建规则
                    rule = agent_rule_repo.create_from_mistake(
                        session,
                        mistake=mistake,
                        rule_content=rule_content,
                        priority=None  # 自动根据 severity 设置
                    )
                    
                    # 获取向量并设置
                    embedding = await self._get_embedding(rule_content)
                    if embedding:
                        rule.set_embedding(session, embedding)
                    
                    results.append({
                        'rule_id': rule.id,
                        'rule_content': rule_content,
                        'rule_type': rule_type,
                        'priority': rule.priority,
                        'source_mistake_id': mistake.id,
                        'reasoning': reasoning
                    })
                    
                    logger.info(f"[KnowledgeEvolution] 规则创建成功: id={rule.id}, content={rule_content[:50]}")
                    
                except json.JSONDecodeError as e:
                    logger.error(f"[KnowledgeEvolution] JSON 解析失败: {e}")
                    continue
        
        return results
    
    # ==================== 知识质量维护 ====================
    
    async def archive_cold_data(self, days: int = 180) -> int:
        """
        归档冷数据
        
        条件：access_count=0 && age > days
        
        Args:
            days: 天数阈值
            
        Returns:
            归档的记录数
        """
        logger.info(f"[KnowledgeEvolution] 开始归档冷数据: days={days}")
        
        with db_manager.get_session() as session:
            from sqlalchemy import text
            cutoff = datetime.now() - timedelta(days=days)
            
            # 查找冷数据
            result = session.execute(text("""
                SELECT COUNT(*) as cnt
                FROM knowledge_items
                WHERE access_count = 0
                  AND created_at < :cutoff
                  AND is_expired = FALSE
            """), {'cutoff': cutoff})
            
            count = result.fetchone()[0]
            
            if count == 0:
                logger.info("[KnowledgeEvolution] 没有需要归档的冷数据")
                return 0
            
            # 标记为过期（不删除，只标记）
            session.execute(text("""
                UPDATE knowledge_items
                SET is_expired = TRUE
                WHERE access_count = 0
                  AND created_at < :cutoff
                  AND is_expired = FALSE
            """), {'cutoff': cutoff})
            
            logger.info(f"[KnowledgeEvolution] 归档冷数据完成: {count} 条")
            return count
    
    async def cleanup_low_value(self, days: int = 90) -> int:
        """
        清理低价值数据
        
        条件：importance<0.3 && access_count=0 && age > days
        
        Args:
            days: 天数阈值
            
        Returns:
            删除的记录数
        """
        logger.info(f"[KnowledgeEvolution] 开始清理低价值数据: days={days}")
        
        with db_manager.get_session() as session:
            from sqlalchemy import text
            cutoff = datetime.now() - timedelta(days=days)
            
            # 查找低价值数据
            result = session.execute(text("""
                SELECT COUNT(*) as cnt
                FROM knowledge_items
                WHERE importance < 0.3
                  AND access_count = 0
                  AND created_at < :cutoff
            """), {'cutoff': cutoff})
            
            count = result.fetchone()[0]
            
            if count == 0:
                logger.info("[KnowledgeEvolution] 没有需要清理的低价值数据")
                return 0
            
            # 删除
            session.execute(text("""
                DELETE FROM knowledge_items
                WHERE importance < 0.3
                  AND access_count = 0
                  AND created_at < :cutoff
            """), {'cutoff': cutoff})
            
            logger.info(f"[KnowledgeEvolution] 清理低价值数据完成: {count} 条")
            return count
    
    async def merge_duplicates(self, similarity_threshold: float = 0.95) -> int:
        """
        合并重复记忆
        
        Args:
            similarity_threshold: 相似度阈值
            
        Returns:
            合并的记录数
        """
        logger.info(f"[KnowledgeEvolution] 开始合并重复记忆: threshold={similarity_threshold}")
        
        # 这个操作比较复杂，需要两两比较
        # 这里简化实现：只检查最近创建的记忆是否有重复
        
        with db_manager.get_session() as session:
            from sqlalchemy import text
            
            # 获取最近 100 条记忆
            result = session.execute(text("""
                SELECT id, content, importance, embedding
                FROM knowledge_items
                WHERE embedding IS NOT NULL
                  AND is_expired = FALSE
                ORDER BY created_at DESC
                LIMIT 100
            """))
            
            rows = list(result)
            merged_count = 0
            
            for i, row1 in enumerate(rows):
                if row1.embedding is None:
                    continue
                
                import numpy as np
                emb1 = np.array(json.loads(str(row1.embedding)))
                
                for row2 in rows[i+1:]:
                    if row2.embedding is None:
                        continue
                    
                    emb2 = np.array(json.loads(str(row2.embedding)))
                    
                    # 计算相似度
                    similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
                    
                    if similarity >= similarity_threshold:
                        # 保留重要性高的，删除重要性低的
                        if row1.importance >= row2.importance:
                            delete_id = row2.id
                        else:
                            delete_id = row1.id
                            break  # row1 被删除，跳出内层循环
                        
                        session.execute(text(f"DELETE FROM knowledge_items WHERE id = {delete_id}"))
                        merged_count += 1
                        logger.info(f"[KnowledgeEvolution] 合并重复记忆: 删除 id={delete_id}")
            
            logger.info(f"[KnowledgeEvolution] 合并重复记忆完成: {merged_count} 条")
            return merged_count
    
    async def mark_expired(self) -> int:
        """
        标记过期信息
        
        Returns:
            标记的记录数
        """
        logger.info("[KnowledgeEvolution] 开始标记过期信息")
        
        with db_manager.get_session() as session:
            from sqlalchemy import text
            
            result = session.execute(text("""
                UPDATE knowledge_items
                SET is_expired = TRUE
                WHERE expires_at < NOW()
                  AND is_expired = FALSE
            """))
            
            count = result.rowcount
            logger.info(f"[KnowledgeEvolution] 标记过期信息完成: {count} 条")
            return count
    
    async def run_maintenance(self) -> Dict[str, int]:
        """
        运行完整的知识维护任务
        
        Returns:
            各项维护的统计结果
        """
        logger.info("[KnowledgeEvolution] 开始运行知识维护任务")
        
        results = {
            'archived': await self.archive_cold_data(),
            'cleaned': await self.cleanup_low_value(),
            'merged': await self.merge_duplicates(),
            'expired': await self.mark_expired()
        }
        
        logger.info(f"[KnowledgeEvolution] 知识维护任务完成: {results}")
        return results
    
    # ==================== 统计信息 ====================
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        with db_manager.get_session() as session:
            from sqlalchemy import text
            
            # 总体统计
            total_result = session.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE is_expired = FALSE) as active,
                    COUNT(*) FILTER (WHERE is_refined = FALSE AND item_type = 'daily') as unrefined
                FROM knowledge_items
            """))
            total_row = total_result.fetchone()
            
            # 按类型统计
            type_result = session.execute(text("""
                SELECT item_type, COUNT(*) as cnt
                FROM knowledge_items
                WHERE is_expired = FALSE
                GROUP BY item_type
                ORDER BY cnt DESC
            """))
            type_stats = {row.item_type: row.cnt for row in type_result}
            
            # 踩坑统计
            mistake_result = session.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE rule_generated = FALSE) as unconverted,
                    COUNT(*) FILTER (WHERE severity IN ('high', 'critical')) as severe
                FROM agent_mistakes
            """))
            mistake_row = mistake_result.fetchone()
            
            # 规则统计
            rule_result = session.execute(text("""
                SELECT COUNT(*) as cnt
                FROM agent_rules
                WHERE is_active = TRUE
            """))
            active_rules = rule_result.fetchone()[0]
            
            return {
                'knowledge_items': {
                    'total': total_row.total,
                    'active': total_row.active,
                    'unrefined': total_row.unrefined,
                    'by_type': type_stats
                },
                'mistakes': {
                    'total': mistake_row.total,
                    'unconverted': mistake_row.unconverted,
                    'severe': mistake_row.severe
                },
                'rules': {
                    'active': active_rules
                }
            }


# 创建全局实例
knowledge_evolution = KnowledgeEvolutionService()


# ==================== 定时任务 ====================

class KnowledgeEvolutionScheduler:
    """知识演化定时任务调度器"""
    
    def __init__(self):
        self._running = False
        self._task = None
    
    async def run_refinement_job(self):
        """执行记忆提炼任务"""
        logger.info("[Scheduler] 开始执行记忆提炼任务")
        try:
            result = await knowledge_evolution.refine_memories(
                batch_size=20,
                max_batches=5
            )
            logger.info(f"[Scheduler] 记忆提炼完成: source={result.source_count}, created={result.created_count}")
            return result
        except Exception as e:
            logger.error(f"[Scheduler] 记忆提炼任务失败: {e}")
            return None
    
    async def run_rule_conversion_job(self):
        """执行踩坑转规则任务"""
        logger.info("[Scheduler] 开始执行踩坑转规则任务")
        try:
            results = await knowledge_evolution.convert_mistakes_to_rules(
                min_occurrence=2,
                min_severity='medium',
                limit=10
            )
            logger.info(f"[Scheduler] 踩坑转规则完成: {len(results)} 条规则")
            return results
        except Exception as e:
            logger.error(f"[Scheduler] 踩坑转规则任务失败: {e}")
            return None
    
    async def run_maintenance_job(self):
        """执行知识维护任务"""
        logger.info("[Scheduler] 开始执行知识维护任务")
        try:
            results = await knowledge_evolution.run_maintenance()
            logger.info(f"[Scheduler] 知识维护完成: {results}")
            return results
        except Exception as e:
            logger.error(f"[Scheduler] 知识维护任务失败: {e}")
            return None
    
    async def run_all_jobs(self):
        """执行所有定时任务"""
        logger.info("[Scheduler] 开始执行所有知识演化任务")
        
        await self.run_refinement_job()
        await self.run_rule_conversion_job()
        await self.run_maintenance_job()
        
        # 打印统计信息
        stats = knowledge_evolution.get_statistics()
        logger.info(f"[Scheduler] 当前知识库状态: {stats}")


# 创建全局调度器
knowledge_scheduler = KnowledgeEvolutionScheduler()


# ==================== 导出 ====================

__all__ = [
    'KnowledgeEvolutionService',
    'KnowledgeEvolutionScheduler',
    'knowledge_evolution',
    'knowledge_scheduler'
]
