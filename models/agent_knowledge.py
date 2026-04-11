"""
Agent 自我进化知识库模型

根据 agent-self-evolution-knowledge-base-design.md 文档实现：
1. KnowledgeFile - 知识文件表（SOUL/USER/AGENTS/TOOLS/MEMORY）
2. KnowledgeItem - 知识条目表（RAG检索核心表）
3. AgentMistake - 踩坑记录表
4. AgentRule - 行为规则表
5. UserProfileField - 用户画像字段表

注意：向量字段使用 TEXT 类型存储 JSON，通过属性访问器进行序列化/反序列化。
实际向量索引通过原生 SQL 创建（见 init_agent_knowledge_tables.py）。
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, Index, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from models.database import Base

logger = logging.getLogger(__name__)

# 向量维度，从配置读取
VECTOR_DIMENSION = 1024


def serialize_embedding(embedding) -> Optional[str]:
    """序列化向量嵌入为JSON字符串"""
    if embedding is None:
        return None
    try:
        if hasattr(embedding, 'tolist'):
            # numpy array
            return json.dumps(embedding.tolist())
        elif isinstance(embedding, list):
            return json.dumps(embedding)
        else:
            return json.dumps(list(embedding))
    except Exception as e:
        logger.error(f"序列化向量失败: {e}")
        return None


def deserialize_embedding(embedding_str: Optional[str]) -> Optional[List[float]]:
    """反序列化JSON字符串为向量列表"""
    if embedding_str is None:
        return None
    try:
        return json.loads(embedding_str)
    except Exception as e:
        logger.error(f"反序列化向量失败: {e}")
        return None


class KnowledgeFile(Base):
    """知识文件表
    
    存储 SOUL/USER/AGENTS/TOOLS/MEMORY 五个核心知识块的整体信息。
    每个知识类型只有一条记录，用 kb_type 区分。
    
    注意：embedding 列通过原生 SQL 创建为 VECTOR 类型，
    SQLAlchemy 模型不直接管理该列。
    """
    __tablename__ = 'knowledge_files'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_type = Column(String(20), unique=True, nullable=False)  # soul, user, agents, tools, memory
    summary_content = Column(Text, nullable=True)  # 精简版内容（Bootstrap加载用）
    full_content = Column(Text, nullable=True)  # 完整内容
    version = Column(Integer, default=1)  # 版本号，追踪演化
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # embedding 列不在此定义，通过原生SQL创建VECTOR类型
    # 使用属性访问器进行读写操作
    
    def get_embedding(self, session):
        """获取向量嵌入（需要传入session）"""
        result = session.execute(text(
            f"SELECT embedding FROM knowledge_files WHERE id = {self.id}"
        )).fetchone()
        if result and result[0]:
            return deserialize_embedding(str(result[0]))
        return None
    
    def set_embedding(self, session, embedding):
        """设置向量嵌入（需要传入session）"""
        if embedding is None:
            session.execute(text(
                f"UPDATE knowledge_files SET embedding = NULL WHERE id = {self.id}"
            ))
        else:
            # 转换为PostgreSQL向量格式
            import json
            vec_str = json.dumps(list(embedding))
            session.execute(text(
                f"UPDATE knowledge_files SET embedding = '{vec_str}'::vector WHERE id = {self.id}"
            ))
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'kb_type': self.kb_type,
            'summary_content': self.summary_content,
            'full_content': self.full_content,
            'version': self.version,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class KnowledgeItem(Base):
    """知识条目表
    
    存储具体的记忆条目，是 RAG 检索的主要对象。
    核心原则：一条记忆只记录一个事实。
    
    注意：embedding 列通过原生 SQL 创建为 VECTOR 类型，
    SQLAlchemy 模型不直接管理该列。
    """
    __tablename__ = 'knowledge_items'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)  # 记忆内容（一句话一个事实）
    item_type = Column(String(30), nullable=False, index=True)  # user_info, preference, fact, lesson, rule, project
    source_file_type = Column(String(20), nullable=True, index=True)  # 来源文件类型（soul/user/agents/memory）
    source_id = Column(Integer, nullable=True)  # 来源记录ID（如踩坑记录ID）
    session_id = Column(String(100), nullable=True, index=True)  # 来源会话ID（可选，用于溯源）
    
    importance = Column(Float, default=0.5)  # 重要性分数 0-1
    access_count = Column(Integer, default=0)  # 访问次数（热度）
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    last_accessed_at = Column(DateTime, default=func.now(), nullable=True, index=True)  # LRU刷新
    
    # 多维标签系统
    tags = Column(ARRAY(Text), default=list)  # 多维标签数组
    
    # 时效性
    expires_at = Column(DateTime, nullable=True)  # 过期时间（可选）
    is_expired = Column(Boolean, default=False)  # 过期标记
    
    # 提炼相关
    is_refined = Column(Boolean, default=False)  # 是否已提炼
    
    # 预估Token数
    estimated_tokens = Column(Integer, default=30)  # 预估Token占用
    
    # 索引
    __table_args__ = (
        Index('idx_knowledge_type_created', 'item_type', 'created_at'),
        Index('idx_knowledge_importance', 'importance'),
    )
    
    # embedding 列不在此定义，通过原生SQL创建VECTOR类型
    
    def get_embedding(self, session):
        """获取向量嵌入（需要传入session）"""
        result = session.execute(text(
            f"SELECT embedding FROM knowledge_items WHERE id = {self.id}"
        )).fetchone()
        if result and result[0]:
            return deserialize_embedding(str(result[0]))
        return None
    
    def set_embedding(self, session, embedding):
        """设置向量嵌入（需要传入session）"""
        if embedding is None:
            session.execute(text(
                f"UPDATE knowledge_items SET embedding = NULL WHERE id = {self.id}"
            ))
        else:
            import json
            vec_str = json.dumps(list(embedding))
            session.execute(text(
                f"UPDATE knowledge_items SET embedding = '{vec_str}'::vector WHERE id = {self.id}"
            ))
    
    def add_tag(self, tag: str):
        """添加标签"""
        if self.tags is None:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)
    
    def remove_tag(self, tag: str):
        """移除标签"""
        if self.tags and tag in self.tags:
            self.tags.remove(tag)
    
    def has_tag(self, tag: str) -> bool:
        """检查是否包含标签"""
        return self.tags is not None and tag in self.tags
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'content': self.content,
            'item_type': self.item_type,
            'source_file_type': self.source_file_type,
            'source_id': self.source_id,
            'session_id': self.session_id,
            'importance': self.importance,
            'access_count': self.access_count,
            'tags': self.tags or [],
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired,
            'is_refined': self.is_refined,
            'estimated_tokens': self.estimated_tokens,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None
        }


class AgentMistake(Base):
    """踩坑记录表
    
    记录 Agent 犯过的错误和学到的教训。
    支持从踩坑提炼为正式规则。
    
    注意：embedding 列通过原生 SQL 创建为 VECTOR 类型。
    """
    __tablename__ = 'agent_mistakes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    mistake_type = Column(String(50), nullable=False, index=True)  # 错误分类
    context = Column(Text, nullable=False)  # 错误上下文
    lesson = Column(Text, nullable=True)  # 学到的教训
    solution = Column(Text, nullable=True)  # 解决方案
    severity = Column(String(20), default='medium')  # low, medium, high, critical
    occurrence_count = Column(Integer, default=1)  # 发生次数
    is_resolved = Column(Boolean, default=False)  # 是否已解决
    rule_generated = Column(Boolean, default=False)  # 是否已生成规则
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 来源会话
    session_id = Column(String(100), nullable=True, index=True)
    
    # embedding 列不在此定义，通过原生SQL创建VECTOR类型
    
    def get_embedding(self, session):
        """获取向量嵌入（需要传入session）"""
        result = session.execute(text(
            f"SELECT embedding FROM agent_mistakes WHERE id = {self.id}"
        )).fetchone()
        if result and result[0]:
            return deserialize_embedding(str(result[0]))
        return None
    
    def set_embedding(self, session, embedding):
        """设置向量嵌入（需要传入session）"""
        if embedding is None:
            session.execute(text(
                f"UPDATE agent_mistakes SET embedding = NULL WHERE id = {self.id}"
            ))
        else:
            import json
            vec_str = json.dumps(list(embedding))
            session.execute(text(
                f"UPDATE agent_mistakes SET embedding = '{vec_str}'::vector WHERE id = {self.id}"
            ))
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'mistake_type': self.mistake_type,
            'context': self.context,
            'lesson': self.lesson,
            'solution': self.solution,
            'severity': self.severity,
            'occurrence_count': self.occurrence_count,
            'is_resolved': self.is_resolved,
            'rule_generated': self.rule_generated,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class AgentRule(Base):
    """行为规则表
    
    从踩坑记录提炼的行为规则，或用户明确要求的规则。
    规则优先级决定注入顺序。
    
    注意：embedding 列通过原生 SQL 创建为 VECTOR 类型。
    """
    __tablename__ = 'agent_rules'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_type = Column(String(30), nullable=False, index=True)  # safety, efficiency, style, domain
    content = Column(Text, nullable=False)  # 规则内容
    priority = Column(Integer, default=50)  # 优先级 1-100，越高越优先
    source_type = Column(String(30), nullable=True)  # mistake, user_request, best_practice
    source_id = Column(Integer, nullable=True)  # 来源记录ID
    is_active = Column(Boolean, default=True)  # 是否启用
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 索引
    __table_args__ = (
        Index('idx_rules_priority', 'priority'),
    )
    
    # embedding 列不在此定义，通过原生SQL创建VECTOR类型
    
    def get_embedding(self, session):
        """获取向量嵌入（需要传入session）"""
        result = session.execute(text(
            f"SELECT embedding FROM agent_rules WHERE id = {self.id}"
        )).fetchone()
        if result and result[0]:
            return deserialize_embedding(str(result[0]))
        return None
    
    def set_embedding(self, session, embedding):
        """设置向量嵌入（需要传入session）"""
        if embedding is None:
            session.execute(text(
                f"UPDATE agent_rules SET embedding = NULL WHERE id = {self.id}"
            ))
        else:
            import json
            vec_str = json.dumps(list(embedding))
            session.execute(text(
                f"UPDATE agent_rules SET embedding = '{vec_str}'::vector WHERE id = {self.id}"
            ))
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'rule_type': self.rule_type,
            'content': self.content,
            'priority': self.priority,
            'source_type': self.source_type,
            'source_id': self.source_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class UserProfileField(Base):
    """用户画像字段表
    
    存储用户的各项属性，支持历史追踪。
    字段级别存储，便于精确更新。
    """
    __tablename__ = 'user_profile_fields'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    field_name = Column(String(50), unique=True, nullable=False, index=True)  # 字段名
    field_value = Column(Text, nullable=True)  # 字段值
    value_type = Column(String(20), default='string')  # string, list, dict
    confidence = Column(Float, default=1.0)  # 置信度 0-1
    source = Column(Text, nullable=True)  # 信息来源
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    def to_dict(self):
        """转换为字典"""
        import json
        value = self.field_value
        if self.value_type == 'list' and self.field_value:
            try:
                value = json.loads(self.field_value)
            except:
                pass
        elif self.value_type == 'dict' and self.field_value:
            try:
                value = json.loads(self.field_value)
            except:
                pass
        
        return {
            'id': self.id,
            'field_name': self.field_name,
            'field_value': value,
            'value_type': self.value_type,
            'confidence': self.confidence,
            'source': self.source,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# 导出所有模型
__all__ = [
    'KnowledgeFile',
    'KnowledgeItem', 
    'AgentMistake',
    'AgentRule',
    'UserProfileField',
    'VECTOR_DIMENSION'
]
