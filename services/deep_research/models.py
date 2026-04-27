"""
深度研究数据模型

定义研究任务、研究计划、研究方向、研究报告等核心数据结构。
使用 dataclass 实现轻量级数据类，支持序列化和类型安全。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid
import logging

logger = logging.getLogger(__name__)


class ResearchMode(str, Enum):
    """研究模式"""
    STANDARD = "standard"  # 标准研究：直接开始多轮搜索分析
    DEEP = "deep"  # 深度研究：先澄清问题，生成研究计划确认后执行


class ResearchStatus(str, Enum):
    """研究任务状态"""
    PENDING = "pending"  # 初始状态，等待开始
    ANALYZING = "analyzing"  # 分析用户问题（深度研究模式）
    PENDING_CLARIFICATION = "pending_clarification"  # 等待用户回答澄清问题
    RESUMED = "resumed"  # 用户已回答，准备进入下一阶段
    PLANNING = "planning"  # 生成研究计划中
    PENDING_CONFIRMATION = "pending_confirmation"  # 等待用户确认研究计划
    CONFIRMED = "confirmed"  # 用户已确认计划
    EXECUTING = "executing"  # 执行研究中
    COMPLETED = "completed"  # 研究完成
    FAILED = "failed"  # 研究失败
    CANCELLED = "cancelled"  # 用户取消


class ResearchDirectionStatus(str, Enum):
    """研究方向执行状态"""
    PENDING = "pending"  # 等待执行
    EXPLORING = "exploring"  # 探索阶段（搜索）
    ANALYZING = "analyzing"  # 分析阶段
    SYNTHESIZING = "synthesizing"  # 总结阶段
    COMPLETED = "completed"  # 完成
    FAILED = "failed"  # 失败


@dataclass
class ClarificationQuestion:
    """澄清问题"""
    question: str
    options: list[str] = field(default_factory=list)
    answer: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "options": self.options,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClarificationQuestion":
        return cls(
            question=data["question"],
            options=data.get("options", []),
            answer=data.get("answer"),
        )


@dataclass
class ResearchTask:
    """
    研究任务
    
    表示一个完整的研究任务，关联到用户会话。
    """
    # 基本信息
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    query: str = ""  # 用户原始问题
    mode: ResearchMode = ResearchMode.STANDARD
    status: ResearchStatus = ResearchStatus.PENDING

    # 澄清相关
    clarification_questions: list[ClarificationQuestion] = field(default_factory=list)

    # 执行状态
    current_step: str = ""  # 当前步骤描述
    error_message: str = ""

    # 时间戳
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "query": self.query,
            "mode": self.mode.value,
            "status": self.status.value,
            "clarification_questions": [q.to_dict() for q in self.clarification_questions],
            "current_step": self.current_step,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchTask":
        """从字典反序列化"""
        questions = [
            ClarificationQuestion.from_dict(q)
            for q in data.get("clarification_questions", [])
        ]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            session_id=data.get("session_id", ""),
            query=data.get("query", ""),
            mode=ResearchMode(data.get("mode", "standard")),
            status=ResearchStatus(data.get("status", "pending")),
            clarification_questions=questions,
            current_step=data.get("current_step", ""),
            error_message=data.get("error_message", ""),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )

    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = datetime.now()


@dataclass
class DirectionSpec:
    """
    研究方向规格
    
    定义一个研究方向的元信息，用于研究计划。
    """
    id: str = field(default_factory=lambda: f"dir_{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    priority: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DirectionSpec":
        return cls(
            id=data.get("id", f"dir_{uuid.uuid4().hex[:8]}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            keywords=data.get("keywords", []),
            priority=data.get("priority", 1),
        )


@dataclass
class ResearchPlan:
    """
    研究计划
    
    包含多个研究方向的执行计划。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    directions: list[DirectionSpec] = field(default_factory=list)
    is_confirmed: bool = False
    confirmed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "directions": [d.to_dict() for d in self.directions],
            "is_confirmed": self.is_confirmed,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchPlan":
        """从字典反序列化"""
        directions = [
            DirectionSpec.from_dict(d)
            for d in data.get("directions", [])
        ]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            directions=directions,
            is_confirmed=data.get("is_confirmed", False),
            confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None,
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )

    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = datetime.now()

    def confirm(self) -> None:
        """确认计划"""
        self.is_confirmed = True
        self.confirmed_at = datetime.now()
        logger.info(f"Research plan {self.id} confirmed with {len(self.directions)} directions")


@dataclass
class Source:
    """
    信息来源
    
    记录引用的来源信息。
    """
    url: str
    title: str = ""
    snippet: str = ""  # 摘要片段
    source_type: str = "web"  # web, pdf, api
    credibility_score: float = 0.5  # 可信度评分 0-1
    accessed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source_type": self.source_type,
            "credibility_score": self.credibility_score,
            "accessed_at": self.accessed_at.isoformat() if self.accessed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            snippet=data.get("snippet", ""),
            source_type=data.get("source_type", "web"),
            credibility_score=data.get("credibility_score", 0.5),
            accessed_at=datetime.fromisoformat(data["accessed_at"]) if data.get("accessed_at") else datetime.now(),
        )


@dataclass
class Learning:
    """
    阶段性学习成果
    
    记录从研究中提取的结构化知识。
    """
    content: str  # 学习内容摘要
    confidence: float = 0.5  # 置信度 0-1
    sources: list[str] = field(default_factory=list)  # 来源 URL 列表
    keywords: list[str] = field(default_factory=list)  # 相关关键词
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "confidence": self.confidence,
            "sources": self.sources,
            "keywords": self.keywords,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Learning":
        return cls(
            content=data.get("content", ""),
            confidence=data.get("confidence", 0.5),
            sources=data.get("sources", []),
            keywords=data.get("keywords", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )


@dataclass
class ResearchDirection:
    """
    研究方向执行状态
    
    追踪单个研究方向的执行进度和结果。
    """
    id: str = field(default_factory=lambda: f"dir_{uuid.uuid4().hex[:8]}")
    task_id: str = ""
    direction_id: str = ""  # 对应 ResearchPlan 中的 DirectionSpec.id
    name: str = ""
    status: ResearchDirectionStatus = ResearchDirectionStatus.PENDING
    progress: int = 0  # 进度百分比 0-100

    # 研究成果
    learnings: list[Learning] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    summary: str = ""  # 阶段性总结

    # 时间戳
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "direction_id": self.direction_id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "learnings": [l.to_dict() for l in self.learnings],
            "sources": [s.to_dict() for s in self.sources],
            "summary": self.summary,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchDirection":
        """从字典反序列化"""
        learnings = [Learning.from_dict(l) for l in data.get("learnings", [])]
        sources = [Source.from_dict(s) for s in data.get("sources", [])]
        return cls(
            id=data.get("id", f"dir_{uuid.uuid4().hex[:8]}"),
            task_id=data.get("task_id", ""),
            direction_id=data.get("direction_id", ""),
            name=data.get("name", ""),
            status=ResearchDirectionStatus(data.get("status", "pending")),
            progress=data.get("progress", 0),
            learnings=learnings,
            sources=sources,
            summary=data.get("summary", ""),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )

    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = datetime.now()

    def add_learning(self, learning: Learning) -> None:
        """添加学习成果"""
        self.learnings.append(learning)
        self.update_timestamp()
        logger.debug(f"Added learning to direction {self.id}: {learning.content[:50]}...")

    def add_source(self, source: Source) -> None:
        """添加信息来源"""
        self.sources.append(source)
        self.update_timestamp()


@dataclass
class ResearchReport:
    """
    研究报告
    
    存储最终生成的研究报告内容。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    title: str = ""
    content_markdown: str = ""
    content_html: str = ""
    pdf_path: str = ""
    word_count: int = 0
    source_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "title": self.title,
            "content_markdown": self.content_markdown,
            "content_html": self.content_html,
            "pdf_path": self.pdf_path,
            "word_count": self.word_count,
            "source_count": self.source_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResearchReport":
        """从字典反序列化"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            title=data.get("title", ""),
            content_markdown=data.get("content_markdown", ""),
            content_html=data.get("content_html", ""),
            pdf_path=data.get("pdf_path", ""),
            word_count=data.get("word_count", 0),
            source_count=data.get("source_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )

    def update_timestamp(self) -> None:
        """更新时间戳"""
        self.updated_at = datetime.now()

    def calculate_word_count(self) -> int:
        """计算字数"""
        self.word_count = len(self.content_markdown)
        return self.word_count


@dataclass
class SearchRecord:
    """
    搜索记录
    
    用于去重和分析搜索效果。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    direction_id: str = ""
    query: str = ""
    query_embedding: list[float] = field(default_factory=list)
    source: str = ""  # 搜索来源：duckduckgo, baidu 等
    result_count: int = 0
    useful_count: int = 0  # 有效结果数量
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "direction_id": self.direction_id,
            "query": self.query,
            "query_embedding": self.query_embedding,
            "source": self.source,
            "result_count": self.result_count,
            "useful_count": self.useful_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchRecord":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            direction_id=data.get("direction_id", ""),
            query=data.get("query", ""),
            query_embedding=data.get("query_embedding", []),
            source=data.get("source", ""),
            result_count=data.get("result_count", 0),
            useful_count=data.get("useful_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )
