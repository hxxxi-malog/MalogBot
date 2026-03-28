"""
知识库管理服务

提供知识库的创建、删除、查询等功能
"""
import uuid
from typing import List, Dict, Optional
import logging

from services.db_manager import db_manager
from models.knowledge_base import KnowledgeBase, Document, DocumentChunk

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """知识库管理服务"""

    def create_knowledge_base(
        self,
        name: str,
        description: str = "",
        user_id: str = None
    ) -> Dict:
        """
        创建知识库

        Args:
            name: 知识库名称
            description: 描述
            user_id: 用户ID（可选）

        Returns:
            创建的知识库信息
        """
        with db_manager.get_session() as session:
            kb = KnowledgeBase(
                id=uuid.uuid4(),
                name=name,
                description=description,
                user_id=user_id
            )
            session.add(kb)
            session.flush()
            return kb.to_dict()

    def delete_knowledge_base(self, kb_id: str) -> bool:
        """
        删除知识库及其所有文档和分块

        Args:
            kb_id: 知识库ID

        Returns:
            是否删除成功
        """
        with db_manager.get_session() as session:
            kb = session.query(KnowledgeBase).filter_by(id=kb_id).first()
            if not kb:
                return False

            session.delete(kb)
            return True

    def get_knowledge_base(self, kb_id: str) -> Optional[Dict]:
        """
        获取知识库信息

        Args:
            kb_id: 知识库ID

        Returns:
            知识库信息字典
        """
        with db_manager.get_session() as session:
            kb = session.query(KnowledgeBase).filter_by(id=kb_id).first()
            return kb.to_dict() if kb else None

    def list_knowledge_bases(self, user_id: str = None) -> List[Dict]:
        """
        列出所有知识库

        Args:
            user_id: 用户ID（可选，用于用户隔离）

        Returns:
            知识库列表
        """
        with db_manager.get_session() as session:
            query = session.query(KnowledgeBase)
            if user_id:
                query = query.filter_by(user_id=user_id)

            kbs = query.order_by(KnowledgeBase.updated_at.desc()).all()
            return [kb.to_dict() for kb in kbs]

    def get_documents(self, kb_id: str) -> List[Dict]:
        """
        获取知识库下的所有文档

        Args:
            kb_id: 知识库ID

        Returns:
            文档列表
        """
        with db_manager.get_session() as session:
            docs = session.query(Document).filter_by(
                knowledge_base_id=kb_id
            ).order_by(Document.created_at.desc()).all()
            return [doc.to_dict() for doc in docs]

    def delete_document(self, doc_id: str) -> bool:
        """
        删除文档及其所有分块

        Args:
            doc_id: 文档ID

        Returns:
            是否删除成功
        """
        with db_manager.get_session() as session:
            doc = session.query(Document).filter_by(id=doc_id).first()
            if not doc:
                return False

            kb_id = doc.knowledge_base_id
            chunk_count = doc.chunk_count

            session.delete(doc)

            # 更新知识库统计
            kb = session.query(KnowledgeBase).filter_by(id=kb_id).first()
            if kb:
                kb.document_count -= 1
                kb.chunk_count -= chunk_count

            return True

    def get_document(self, doc_id: str) -> Optional[Dict]:
        """
        获取文档信息

        Args:
            doc_id: 文档ID

        Returns:
            文档信息字典
        """
        with db_manager.get_session() as session:
            doc = session.query(Document).filter_by(id=doc_id).first()
            return doc.to_dict() if doc else None

    def update_knowledge_base_stats(self, kb_id: str):
        """
        更新知识库统计信息

        Args:
            kb_id: 知识库ID
        """
        with db_manager.get_session() as session:
            kb = session.query(KnowledgeBase).filter_by(id=kb_id).first()
            if not kb:
                return

            # 统计文档数量
            doc_count = session.query(Document).filter_by(
                knowledge_base_id=kb_id
            ).count()

            # 统计分块数量
            chunk_count = session.query(DocumentChunk).filter_by(
                knowledge_base_id=kb_id
            ).count()

            kb.document_count = doc_count
            kb.chunk_count = chunk_count


# 创建全局实例
knowledge_base_service = KnowledgeBaseService()

__all__ = ['KnowledgeBaseService', 'knowledge_base_service']
