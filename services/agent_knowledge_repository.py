"""
Agent 知识库 Repository 模块

提供各数据表的 CRUD 操作封装：
1. KnowledgeFileRepository - 知识文件表操作
2. KnowledgeItemRepository - 知识条目表操作
3. AgentMistakeRepository - 踩坑记录表操作
4. AgentRuleRepository - 行为规则表操作
5. UserProfileRepository - 用户画像表操作
"""
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from models.agent_knowledge import (
    KnowledgeFile,
    KnowledgeItem,
    AgentMistake,
    AgentRule,
    UserProfileField,
    VECTOR_DIMENSION,
    serialize_embedding,
    deserialize_embedding
)
from services.db_manager import db_manager

logger = logging.getLogger(__name__)


class BaseRepository:
    """基础 Repository 类"""
    
    def __init__(self, model_class):
        self.model_class = model_class
    
    def create(self, session: DBSession, **kwargs):
        """创建记录"""
        obj = self.model_class(**kwargs)
        session.add(obj)
        session.flush()  # 获取自增ID
        return obj
    
    def get(self, session: DBSession, id: int) -> Optional[Any]:
        """根据ID获取记录"""
        return session.query(self.model_class).filter_by(id=id).first()
    
    def get_all(self, session: DBSession, limit: int = 100) -> List[Any]:
        """获取所有记录"""
        return session.query(self.model_class).limit(limit).all()
    
    def update(self, session: DBSession, id: int, **kwargs) -> Optional[Any]:
        """更新记录"""
        obj = self.get(session, id)
        if obj:
            for key, value in kwargs.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)
            session.flush()
        return obj
    
    def delete(self, session: DBSession, id: int) -> bool:
        """删除记录"""
        obj = self.get(session, id)
        if obj:
            session.delete(obj)
            return True
        return False
    
    def count(self, session: DBSession) -> int:
        """统计记录数"""
        return session.query(self.model_class).count()


class KnowledgeFileRepository(BaseRepository):
    """知识文件 Repository"""
    
    def __init__(self):
        super().__init__(KnowledgeFile)
    
    def get_by_type(self, session: DBSession, kb_type: str) -> Optional[KnowledgeFile]:
        """根据类型获取知识文件"""
        logger.info(f"获取知识块: {kb_type}")
        return session.query(KnowledgeFile).filter_by(kb_type=kb_type).first()
    
    def update_content(self, session: DBSession, kb_type: str, 
                       summary_content: str = None, 
                       full_content: str = None) -> Optional[KnowledgeFile]:
        """更新知识文件内容"""
        logger.info(f"更新知识块内容: {kb_type}")
        kb = self.get_by_type(session, kb_type)
        if kb:
            if summary_content:
                kb.summary_content = summary_content
            if full_content:
                kb.full_content = full_content
            kb.version += 1
            session.flush()
        return kb
    
    def set_embedding(self, session: DBSession, kb_type: str, embedding: List[float]) -> bool:
        """设置知识文件的向量嵌入"""
        logger.info(f"设置知识块向量: {kb_type}")
        kb = self.get_by_type(session, kb_type)
        if kb:
            kb.set_embedding(session, embedding)
            return True
        return False


class KnowledgeItemRepository(BaseRepository):
    """知识条目 Repository"""
    
    def __init__(self):
        super().__init__(KnowledgeItem)
    
    def get_by_type(self, session: DBSession, item_type: str, 
                    limit: int = 100) -> List[KnowledgeItem]:
        """根据类型获取知识条目"""
        logger.info(f"获取知识条目: type={item_type}, limit={limit}")
        return session.query(KnowledgeItem).filter_by(
            item_type=item_type
        ).order_by(KnowledgeItem.importance.desc()).limit(limit).all()
    
    def get_by_source_file(self, session: DBSession, source_file_type: str,
                           limit: int = 100) -> List[KnowledgeItem]:
        """根据来源文件类型获取知识条目"""
        logger.info(f"获取知识条目: source={source_file_type}")
        return session.query(KnowledgeItem).filter_by(
            source_file_type=source_file_type
        ).order_by(KnowledgeItem.importance.desc()).limit(limit).all()
    
    def get_by_tags(self, session: DBSession, tags: List[str], 
                    match_all: bool = False,
                    limit: int = 100) -> List[KnowledgeItem]:
        """根据标签获取知识条目
        
        Args:
            session: 数据库会话
            tags: 标签列表
            match_all: True 表示必须匹配所有标签，False 表示匹配任一标签
            limit: 返回数量限制
        """
        logger.info(f"按标签查询: tags={tags}, match_all={match_all}")
        
        # 构建PostgreSQL数组格式，使用ARRAY[]语法
        array_expr = "ARRAY[" + ",".join(f"'{tag}'" for tag in tags) + "]"
        
        if match_all:
            # 使用 @> 操作符：数组包含所有指定元素
            sql = text(f"""
                SELECT * FROM knowledge_items 
                WHERE tags @> {array_expr}
                ORDER BY importance DESC
                LIMIT :limit
            """)
        else:
            # 使用 && 操作符：数组包含任一指定元素
            sql = text(f"""
                SELECT * FROM knowledge_items 
                WHERE tags && {array_expr}
                ORDER BY importance DESC
                LIMIT :limit
            """)
        
        result = session.execute(sql, {'limit': limit})
        
        # 将结果转换为模型对象
        items = []
        for row in result:
            item = KnowledgeItem()
            for i, col in enumerate(row._fields):
                setattr(item, col, row[i])
            items.append(item)
        return items
    
    def search_vector(self, session: DBSession, query_embedding: List[float],
                      top_k: int = 10, min_similarity: float = 0.0) -> List[Dict]:
        """向量相似度检索
        
        Args:
            session: 数据库会话
            query_embedding: 查询向量
            top_k: 返回数量
            min_similarity: 最小相似度阈值
        
        Returns:
            包含 item 和 similarity 的字典列表
        """
        logger.info(f"向量检索: top_k={top_k}, min_similarity={min_similarity}")
        
        # 转换向量为PostgreSQL格式字符串
        vec_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
        
        # 使用 f-string 直接构建SQL，避免参数绑定问题
        sql = text(f"""
            SELECT id, content, item_type, source_file_type, importance, 
                   tags, 1 - (embedding <=> '{vec_str}'::vector) as similarity
            FROM knowledge_items
            WHERE embedding IS NOT NULL
              AND is_expired = FALSE
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {top_k}
        """)
        
        result = session.execute(sql)
        
        results = []
        for row in result:
            if row.similarity >= min_similarity:
                results.append({
                    'id': row.id,
                    'content': row.content,
                    'item_type': row.item_type,
                    'source_file_type': row.source_file_type,
                    'importance': row.importance,
                    'tags': row.tags or [],
                    'similarity': float(row.similarity)
                })
        
        logger.info(f"向量检索返回 {len(results)} 条结果")
        return results
    
    def search_bm25(self, session: DBSession, query: str,
                    top_k: int = 10) -> List[Dict]:
        """BM25 全文检索
        
        Args:
            session: 数据库会话
            query: 查询文本
            top_k: 返回数量
        
        Returns:
            包含 item 和 score 的字典列表
        """
        logger.info(f"BM25检索: query={query[:50]}, top_k={top_k}")
        
        result = session.execute(text("""
            SELECT id, content, item_type, source_file_type, importance, tags,
                   ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) as score
            FROM knowledge_items
            WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
              AND is_expired = FALSE
            ORDER BY score DESC
            LIMIT :limit
        """), {'query': query, 'limit': top_k})
        
        results = []
        for row in result:
            results.append({
                'id': row.id,
                'content': row.content,
                'item_type': row.item_type,
                'source_file_type': row.source_file_type,
                'importance': row.importance,
                'tags': row.tags or [],
                'score': float(row.score) if row.score else 0.0
            })
        
        logger.info(f"BM25检索返回 {len(results)} 条结果")
        return results
    
    def search_hybrid(self, session: DBSession, query: str, 
                      query_embedding: List[float],
                      top_k: int = 10,
                      vector_weight: float = 0.7,
                      bm25_weight: float = 0.3) -> List[Dict]:
        """混合检索（向量 + BM25）
        
        Args:
            session: 数据库会话
            query: 查询文本
            query_embedding: 查询向量
            top_k: 返回数量
            vector_weight: 向量检索权重
            bm25_weight: BM25检索权重
        """
        logger.info(f"混合检索: query={query[:50]}, top_k={top_k}")
        
        # 1. 向量检索
        vector_results = self.search_vector(session, query_embedding, top_k=top_k*2)
        
        # 2. BM25检索
        bm25_results = self.search_bm25(session, query, top_k=top_k*2)
        
        # 3. 归一化分数
        vector_max = max(r['similarity'] for r in vector_results) if vector_results else 1.0
        bm25_max = max(r['score'] for r in bm25_results) if bm25_results else 1.0
        
        # 4. 合并结果
        merged = {}
        for r in vector_results:
            merged[r['id']] = r.copy()
            merged[r['id']]['vector_score'] = r['similarity'] / max(vector_max, 0.001)
            merged[r['id']]['bm25_score'] = 0.0
        
        for r in bm25_results:
            if r['id'] in merged:
                merged[r['id']]['bm25_score'] = r['score'] / max(bm25_max, 0.001)
            else:
                merged[r['id']] = r.copy()
                merged[r['id']]['vector_score'] = 0.0
                merged[r['id']]['bm25_score'] = r['score'] / max(bm25_max, 0.001)
        
        # 5. 计算混合分数
        for item in merged.values():
            item['hybrid_score'] = (
                vector_weight * item['vector_score'] + 
                bm25_weight * item['bm25_score']
            )
        
        # 6. 排序返回
        sorted_results = sorted(merged.values(), key=lambda x: x['hybrid_score'], reverse=True)
        return sorted_results[:top_k]
    
    def update_access(self, session: DBSession, id: int) -> bool:
        """更新访问记录（LRU刷新）"""
        logger.info(f"更新访问记录: id={id}")
        item = self.get(session, id)
        if item:
            item.access_count += 1
            item.last_accessed_at = datetime.now()
            session.flush()
            return True
        return False
    
    def create_with_embedding(self, session: DBSession, 
                              content: str, 
                              item_type: str,
                              embedding: List[float],
                              **kwargs) -> KnowledgeItem:
        """创建带向量的知识条目"""
        logger.info(f"创建知识条目: type={item_type}, content={content[:50]}")
        
        # 先创建记录
        item = self.create(session, content=content, item_type=item_type, **kwargs)
        session.flush()
        
        # 设置向量
        item.set_embedding(session, embedding)
        
        return item
    
    def get_unrefined(self, session: DBSession, limit: int = 100) -> List[KnowledgeItem]:
        """获取未提炼的记忆"""
        logger.info(f"获取未提炼记忆: limit={limit}")
        return session.query(KnowledgeItem).filter_by(
            is_refined=False
        ).order_by(KnowledgeItem.created_at).limit(limit).all()


class AgentMistakeRepository(BaseRepository):
    """踩坑记录 Repository"""
    
    def __init__(self):
        super().__init__(AgentMistake)
    
    def get_by_type(self, session: DBSession, mistake_type: str,
                    limit: int = 100) -> List[AgentMistake]:
        """根据类型获取踩坑记录"""
        logger.info(f"获取踩坑记录: type={mistake_type}")
        return session.query(AgentMistake).filter_by(
            mistake_type=mistake_type
        ).order_by(AgentMistake.severity.desc()).limit(limit).all()
    
    def get_unresolved(self, session: DBSession, limit: int = 100) -> List[AgentMistake]:
        """获取未解决的踩坑"""
        logger.info(f"获取未解决踩坑")
        return session.query(AgentMistake).filter_by(
            is_resolved=False
        ).order_by(AgentMistake.severity.desc()).limit(limit).all()
    
    def get_for_rule_generation(self, session: DBSession,
                                 min_occurrence: int = 2,
                                 min_severity: str = 'medium') -> List[AgentMistake]:
        """获取可转化为规则的踩坑
        
        条件：
        - 发生次数 >= min_occurrence
        - 严重程度 >= min_severity
        - 尚未生成规则
        """
        logger.info(f"获取可转化规则的踩坑: min_occurrence={min_occurrence}")
        
        severity_order = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
        min_level = severity_order.get(min_severity, 2)
        
        result = session.execute(text("""
            SELECT * FROM agent_mistakes
            WHERE occurrence_count >= :min_occurrence
              AND rule_generated = FALSE
              AND is_resolved = TRUE
            ORDER BY 
                CASE severity 
                    WHEN 'critical' THEN 4 
                    WHEN 'high' THEN 3 
                    WHEN 'medium' THEN 2 
                    ELSE 1 
                END DESC,
                occurrence_count DESC
        """), {'min_occurrence': min_occurrence})
        
        # 过滤严重程度
        items = []
        for row in result:
            item = AgentMistake()
            for i, col in enumerate(row._fields):
                setattr(item, col, row[i])
            if severity_order.get(item.severity, 0) >= min_level:
                items.append(item)
        
        return items
    
    def increment_occurrence(self, session: DBSession, id: int) -> bool:
        """增加发生次数"""
        logger.info(f"增加踩坑发生次数: id={id}")
        item = self.get(session, id)
        if item:
            item.occurrence_count += 1
            session.flush()
            return True
        return False
    
    def get_recent(self, session: DBSession, days: int = 30, 
                   limit: int = 20) -> List[AgentMistake]:
        """获取近期的踩坑记录
        
        用于 Bootstrap 加载时获取近期踩坑，提醒 Agent 避免重复犯错。
        
        Args:
            session: 数据库会话
            days: 最近多少天，默认 30 天
            limit: 返回数量限制，默认 20 条
        
        Returns:
            按严重程度和创建时间排序的踩坑记录列表
        """
        from datetime import datetime, timedelta
        
        cutoff = datetime.now() - timedelta(days=days)
        
        logger.info(f"获取近期踩坑: days={days}, limit={limit}")
        
        return session.query(AgentMistake).filter(
            AgentMistake.created_at >= cutoff
        ).order_by(
            AgentMistake.severity.desc(),
            AgentMistake.created_at.desc()
        ).limit(limit).all()
    
    def create_with_embedding(self, session: DBSession,
                              mistake_type: str,
                              context: str,
                              embedding: List[float],
                              **kwargs) -> AgentMistake:
        """创建带向量的踩坑记录"""
        logger.info(f"创建踩坑记录: type={mistake_type}")
        
        item = self.create(session, mistake_type=mistake_type, context=context, **kwargs)
        session.flush()
        item.set_embedding(session, embedding)
        
        return item


class AgentRuleRepository(BaseRepository):
    """行为规则 Repository"""
    
    def __init__(self):
        super().__init__(AgentRule)
    
    def get_active(self, session: DBSession, limit: int = 100) -> List[AgentRule]:
        """获取启用的规则，按优先级排序"""
        logger.info(f"获取启用的规则")
        return session.query(AgentRule).filter_by(
            is_active=True
        ).order_by(AgentRule.priority.desc()).limit(limit).all()
    
    def get_by_type(self, session: DBSession, rule_type: str,
                    limit: int = 100) -> List[AgentRule]:
        """根据类型获取规则"""
        logger.info(f"获取规则: type={rule_type}")
        return session.query(AgentRule).filter_by(
            rule_type=rule_type,
            is_active=True
        ).order_by(AgentRule.priority.desc()).limit(limit).all()
    
    def create_from_mistake(self, session: DBSession,
                            mistake: AgentMistake,
                            rule_content: str,
                            priority: int = None) -> AgentRule:
        """从踩坑记录创建规则"""
        logger.info(f"从踩坑创建规则: mistake_id={mistake.id}")
        
        # 根据严重程度设置优先级
        if priority is None:
            severity_priority = {
                'critical': 90,
                'high': 70,
                'medium': 50,
                'low': 30
            }
            priority = severity_priority.get(mistake.severity, 50)
        
        rule = self.create(
            session,
            rule_type=mistake.mistake_type,
            content=rule_content,
            priority=priority,
            source_type='mistake',
            source_id=mistake.id
        )
        
        # 标记踩坑已生成规则
        mistake.rule_generated = True
        session.flush()
        
        return rule
    
    def deactivate(self, session: DBSession, id: int) -> bool:
        """停用规则"""
        logger.info(f"停用规则: id={id}")
        return self.update(session, id, is_active=False) is not None


class UserProfileRepository(BaseRepository):
    """用户画像 Repository"""
    
    def __init__(self):
        super().__init__(UserProfileField)
    
    def get_field(self, session: DBSession, field_name: str) -> Optional[UserProfileField]:
        """获取指定字段"""
        logger.info(f"获取用户字段: {field_name}")
        return session.query(UserProfileField).filter_by(field_name=field_name).first()
    
    def set_field(self, session: DBSession, field_name: str, 
                  field_value: Any, confidence: float = 1.0,
                  source: str = None) -> UserProfileField:
        """设置用户字段值"""
        logger.info(f"设置用户字段: {field_name}={field_value}")
        
        field = self.get_field(session, field_name)
        
        # 根据值的类型确定 value_type
        if isinstance(field_value, list):
            value_type = 'list'
            value_str = json.dumps(field_value)
        elif isinstance(field_value, dict):
            value_type = 'dict'
            value_str = json.dumps(field_value)
        else:
            value_type = 'string'
            value_str = str(field_value)
        
        if field:
            # 更新现有字段
            field.field_value = value_str
            field.value_type = value_type
            field.confidence = confidence
            if source:
                field.source = source
        else:
            # 创建新字段
            field = self.create(
                session,
                field_name=field_name,
                field_value=value_str,
                value_type=value_type,
                confidence=confidence,
                source=source
            )
        
        return field
    
    def get_all_fields(self, session: DBSession) -> Dict[str, Any]:
        """获取所有用户字段"""
        logger.info("获取所有用户字段")
        fields = session.query(UserProfileField).all()
        result = {}
        for field in fields:
            result[field.field_name] = field.to_dict()['field_value']
        return result
    
    def get_high_confidence(self, session: DBSession, 
                            min_confidence: float = 0.7) -> Dict[str, Any]:
        """获取高置信度的用户字段"""
        logger.info(f"获取高置信度字段: min={min_confidence}")
        fields = session.query(UserProfileField).filter(
            UserProfileField.confidence >= min_confidence
        ).all()
        result = {}
        for field in fields:
            result[field.field_name] = field.to_dict()['field_value']
        return result


class KnowledgeItemRepositoryEnhanced(KnowledgeItemRepository):
    """增强版知识条目 Repository
    
    提供分层召回策略和批量操作
    """
    
    def __init__(self):
        super().__init__()
    
    def search_with_tag_filter(
        self,
        session: DBSession,
        query_embedding: List[float],
        tags: List[str],
        match_all_tags: bool = False,
        top_k: int = 10
    ) -> List[Dict]:
        """
        分层召回：先标签过滤，再向量检索
        
        这是文档中提到的分层召回策略：
        1. 低维标签过滤缩小候选集
        2. 在过滤结果上进行向量检索
        
        Args:
            session: 数据库会话
            query_embedding: 查询向量
            tags: 标签列表
            match_all_tags: True表示必须匹配所有标签，False表示匹配任一标签
            top_k: 返回数量
            
        Returns:
            检索结果列表
        """
        logger.info(f"分层召回: tags={tags}, match_all={match_all_tags}, top_k={top_k}")
        
        # 构建标签条件
        array_expr = "ARRAY[" + ",".join(f"'{tag}'" for tag in tags) + "]"
        tag_op = "@>" if match_all_tags else "&&"
        
        # 转换向量为PostgreSQL格式
        vec_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
        
        # SQL：先标签过滤，再向量检索
        sql = text(f"""
            SELECT id, content, item_type, source_file_type, importance, 
                   tags, created_at, last_accessed_at, access_count,
                   1 - (embedding <=> '{vec_str}'::vector) as similarity
            FROM knowledge_items
            WHERE embedding IS NOT NULL
              AND is_expired = FALSE
              AND tags {tag_op} {array_expr}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {top_k}
        """)
        
        result = session.execute(sql)
        
        results = []
        for row in result:
            results.append({
                'id': row.id,
                'content': row.content,
                'item_type': row.item_type,
                'source_file_type': row.source_file_type,
                'importance': row.importance,
                'tags': row.tags or [],
                'created_at': row.created_at,
                'last_accessed_at': row.last_accessed_at,
                'access_count': row.access_count or 0,
                'similarity': float(row.similarity)
            })
        
        logger.info(f"分层召回返回 {len(results)} 条结果")
        return results
    
    def search_with_filters(
        self,
        session: DBSession,
        query_embedding: List[float],
        item_types: List[str] = None,
        tags: List[str] = None,
        min_importance: float = None,
        source_file_type: str = None,
        exclude_expired: bool = True,
        top_k: int = 10
    ) -> List[Dict]:
        """
        支持多过滤条件的向量检索
        
        Args:
            session: 数据库会话
            query_embedding: 查询向量
            item_types: 条目类型列表
            tags: 标签列表
            min_importance: 最小重要性
            source_file_type: 来源文件类型
            exclude_expired: 是否排除过期记忆
            top_k: 返回数量
            
        Returns:
            检索结果列表
        """
        logger.info(f"多条件检索: types={item_types}, tags={tags}, top_k={top_k}")
        
        # 构建WHERE条件
        where_clauses = ["embedding IS NOT NULL"]
        
        if exclude_expired:
            where_clauses.append("is_expired = FALSE")
        
        if item_types:
            types_str = "','".join(item_types)
            where_clauses.append(f"item_type IN ('{types_str}')")
        
        if tags:
            tags_str = "','".join(tags)
            where_clauses.append(f"tags && ARRAY['{tags_str}']")
        
        if min_importance is not None:
            where_clauses.append(f"importance >= {min_importance}")
        
        if source_file_type:
            where_clauses.append(f"source_file_type = '{source_file_type}'")
        
        where_clause = " AND ".join(where_clauses)
        
        # 转换向量
        vec_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
        
        sql = text(f"""
            SELECT id, content, item_type, source_file_type, importance, 
                   tags, created_at, last_accessed_at, access_count,
                   1 - (embedding <=> '{vec_str}'::vector) as similarity
            FROM knowledge_items
            WHERE {where_clause}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {top_k}
        """)
        
        result = session.execute(sql)
        
        results = []
        for row in result:
            results.append({
                'id': row.id,
                'content': row.content,
                'item_type': row.item_type,
                'source_file_type': row.source_file_type,
                'importance': row.importance,
                'tags': row.tags or [],
                'created_at': row.created_at,
                'last_accessed_at': row.last_accessed_at,
                'access_count': row.access_count or 0,
                'similarity': float(row.similarity)
            })
        
        logger.info(f"多条件检索返回 {len(results)} 条结果")
        return results
    
    def batch_update_access(
        self,
        session: DBSession,
        ids: List[int]
    ) -> int:
        """
        批量更新访问记录（LRU刷新）
        
        Args:
            session: 数据库会话
            ids: 记录ID列表
            
        Returns:
            更新的记录数
        """
        if not ids:
            return 0
        
        logger.info(f"批量刷新访问记录: {len(ids)} 条")
        
        try:
            result = session.execute(text("""
                UPDATE knowledge_items
                SET last_accessed_at = NOW(),
                    access_count = access_count + 1
                WHERE id = ANY(:ids)
            """), {'ids': ids})
            
            session.flush()
            return result.rowcount
        except Exception as e:
            logger.error(f"批量刷新失败: {e}")
            return 0
    
    def get_by_importance(
        self,
        session: DBSession,
        min_importance: float = 0.5,
        item_type: str = None,
        limit: int = 100
    ) -> List[KnowledgeItem]:
        """
        按重要性获取记忆
        
        Args:
            session: 数据库会话
            min_importance: 最小重要性
            item_type: 条目类型（可选）
            limit: 返回数量
        """
        logger.info(f"按重要性查询: min={min_importance}, type={item_type}")
        
        query = session.query(KnowledgeItem).filter(
            KnowledgeItem.importance >= min_importance,
            KnowledgeItem.is_expired == False
        )
        
        if item_type:
            query = query.filter(KnowledgeItem.item_type == item_type)
        
        return query.order_by(
            KnowledgeItem.importance.desc()
        ).limit(limit).all()
    
    def get_recently_accessed(
        self,
        session: DBSession,
        days: int = 30,
        limit: int = 100
    ) -> List[KnowledgeItem]:
        """
        获取最近访问的记忆
        
        Args:
            session: 数据库会话
            days: 最近多少天
            limit: 返回数量
        """
        logger.info(f"获取最近访问: days={days}")
        
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        
        return session.query(KnowledgeItem).filter(
            KnowledgeItem.last_accessed_at >= cutoff,
            KnowledgeItem.is_expired == False
        ).order_by(
            KnowledgeItem.last_accessed_at.desc()
        ).limit(limit).all()


# 创建全局实例
knowledge_file_repo = KnowledgeFileRepository()
knowledge_item_repo = KnowledgeItemRepository()
knowledge_item_repo_enhanced = KnowledgeItemRepositoryEnhanced()
agent_mistake_repo = AgentMistakeRepository()
agent_rule_repo = AgentRuleRepository()
user_profile_repo = UserProfileRepository()


# 导出
__all__ = [
    'BaseRepository',
    'KnowledgeFileRepository',
    'KnowledgeItemRepository',
    'KnowledgeItemRepositoryEnhanced',
    'AgentMistakeRepository',
    'AgentRuleRepository',
    'UserProfileRepository',
    'knowledge_file_repo',
    'knowledge_item_repo',
    'knowledge_item_repo_enhanced',
    'agent_mistake_repo',
    'agent_rule_repo',
    'user_profile_repo'
]
