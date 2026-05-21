"""
深度研究数据库模型

存储研究任务、计划、方向、报告等数据
"""
import uuid
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, Float, Index, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from models.database import Base


class ResearchTask(Base):
    """
    研究任务表
    
    存储研究任务的基本信息和状态
    """
    __tablename__ = 'research_tasks'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(100), ForeignKey('sessions.session_id'), nullable=False, index=True)
    query = Column(Text, nullable=False)  # 用户原始问题
    mode = Column(String(20), nullable=False, default='standard')  # standard, deep
    status = Column(String(30), nullable=False, default='pending', index=True)  # 研究状态
    
    # 澄清相关
    clarification_questions = Column(JSONB, default=list)  # 澄清问题列表
    clarification_answers = Column(JSONB, default=list)  # 用户回答列表
    
    # 执行状态
    current_step = Column(String(50), nullable=True)  # 当前步骤标识
    error_message = Column(Text, nullable=True)  # 错误信息
    
    # 时间戳
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    session = relationship("Session", back_populates="research_tasks")
    plan = relationship("ResearchPlan", back_populates="task", uselist=False, cascade="all, delete-orphan")
    directions = relationship("ResearchDirection", back_populates="task", cascade="all, delete-orphan")
    report = relationship("ResearchReport", back_populates="task", uselist=False, cascade="all, delete-orphan")
    searches = relationship("ResearchSearch", back_populates="task", cascade="all, delete-orphan")
    
    # 索引
    __table_args__ = (
        Index('idx_research_tasks_session_id', 'session_id'),
        Index('idx_research_tasks_status', 'status'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': str(self.id),
            'session_id': self.session_id,
            'query': self.query,
            'mode': self.mode,
            'status': self.status,
            'clarification_questions': self.clarification_questions or [],
            'clarification_answers': self.clarification_answers or [],
            'current_step': self.current_step,
            'error_message': self.error_message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchPlan(Base):
    """
    研究计划表
    
    存储研究方向规划
    """
    __tablename__ = 'research_plans'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False, unique=True)
    
    # 研究方向列表
    directions = Column(JSONB, default=list)  # [{id, name, description, keywords, priority}]
    
    # 确认状态
    is_confirmed = Column(Boolean, default=False, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    task = relationship("ResearchTask", back_populates="plan")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': str(self.id),
            'task_id': str(self.task_id),
            'directions': self.directions or [],
            'is_confirmed': self.is_confirmed,
            'confirmed_at': self.confirmed_at.isoformat() if self.confirmed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchDirection(Base):
    """
    研究方向执行表
    
    追踪单个研究方向的执行进度和结果
    """
    __tablename__ = 'research_directions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False)
    direction_id = Column(String(50), nullable=False)  # 方向标识
    
    # 基本信息
    name = Column(String(200), nullable=False)  # 方向名称
    status = Column(String(30), default='pending', nullable=False)  # pending, exploring, analyzing, synthesizing, completed, failed
    progress = Column(Integer, default=0)  # 进度百分比 0-100
    
    # 研究成果
    learnings = Column(JSONB, default=list)  # 阶段性学习成果
    sources = Column(JSONB, default=list)  # 信息来源列表
    summary = Column(Text, nullable=True)  # 阶段性总结
    
    # 时间戳
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    task = relationship("ResearchTask", back_populates="directions")
    
    # 索引
    __table_args__ = (
        Index('idx_research_directions_task_id', 'task_id'),
        Index('idx_research_directions_status', 'status'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': str(self.id),
            'task_id': str(self.task_id),
            'direction_id': self.direction_id,
            'name': self.name,
            'status': self.status,
            'progress': self.progress,
            'learnings': self.learnings or [],
            'sources': self.sources or [],
            'summary': self.summary,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchReport(Base):
    """
    研究报告表
    
    存储最终生成的研究报告
    """
    __tablename__ = 'research_reports'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False, unique=True)
    
    # 报告内容
    title = Column(String(500), nullable=True)
    content_markdown = Column(Text, nullable=True)  # Markdown 格式报告
    content_html = Column(Text, nullable=True)  # HTML 格式（用于 PDF）
    pdf_path = Column(String(500), nullable=True)  # PDF 文件路径
    
    # 统计
    word_count = Column(Integer, default=0)
    source_count = Column(Integer, default=0)
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    
    # 关系
    task = relationship("ResearchTask", back_populates="report")
    
    # 索引
    __table_args__ = (
        Index('idx_research_reports_task_id', 'task_id'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'id': str(self.id),
            'task_id': str(self.task_id),
            'title': self.title,
            'content_markdown': self.content_markdown,
            'content_html': self.content_html,
            'pdf_path': self.pdf_path,
            'word_count': self.word_count,
            'source_count': self.source_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ResearchSearch(Base):
    """
    研究搜索记录表
    
    用于去重和分析搜索效果
    """
    __tablename__ = 'research_searches'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey('research_tasks.id', ondelete='CASCADE'), nullable=False)
    direction_id = Column(String(50), nullable=True)  # 关联研究方向ID
    
    # 搜索信息
    query = Column(Text, nullable=False)  # 搜索关键词
    query_embedding = Column(Text, nullable=True)  # 搜索词向量（JSON 格式）
    source = Column(String(100), nullable=True)  # 搜索来源
    
    # 结果统计
    result_count = Column(Integer, default=0)
    useful_count = Column(Integer, default=0)  # 有效结果数量
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # 关系
    task = relationship("ResearchTask", back_populates="searches")
    
    # 索引
    __table_args__ = (
        Index('idx_research_searches_task_id', 'task_id'),
    )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        embedding = None
        if self.query_embedding:
            try:
                embedding = json.loads(self.query_embedding)
            except:
                pass
        
        return {
            'id': str(self.id),
            'task_id': str(self.task_id),
            'direction_id': self.direction_id,
            'query': self.query,
            'query_embedding': embedding,
            'source': self.source,
            'result_count': self.result_count,
            'useful_count': self.useful_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# 导出
__all__ = [
    'ResearchTask',
    'ResearchPlan',
    'ResearchDirection',
    'ResearchReport',
    'ResearchSearch',
]
