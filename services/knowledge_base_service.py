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
        from sqlalchemy import text
        
        with db_manager.engine.connect() as conn:
            # 检查知识库是否存在
            result = conn.execute(text(
                "SELECT id FROM knowledge_bases WHERE id = :kb_id"
            ), {'kb_id': kb_id})
            
            if not result.fetchone():
                return False
            
            # 使用原生 SQL 删除，避免加载 vector 类型的列
            # 删除分块
            conn.execute(text(
                "DELETE FROM document_chunks WHERE knowledge_base_id = :kb_id"
            ), {'kb_id': kb_id})
            
            # 删除文档
            conn.execute(text(
                "DELETE FROM documents WHERE knowledge_base_id = :kb_id"
            ), {'kb_id': kb_id})
            
            # 删除知识库
            conn.execute(text(
                "DELETE FROM knowledge_bases WHERE id = :kb_id"
            ), {'kb_id': kb_id})
            
            conn.commit()
            return True

    def get_knowledge_base(self, kb_id: str) -> Optional[Dict]:
        """
        获取知识库信息

        Args:
            kb_id: 知识库ID

        Returns:
            知识库信息字典
        """
        from sqlalchemy import text
        
        with db_manager.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT id, name, description, user_id, created_at, updated_at, document_count, chunk_count "
                "FROM knowledge_bases WHERE id = :kb_id"
            ), {'kb_id': kb_id})
            
            row = result.fetchone()
            if not row:
                return None
            
            return {
                'id': str(row[0]),
                'name': row[1],
                'description': row[2],
                'user_id': row[3],
                'created_at': row[4].isoformat() if row[4] else None,
                'updated_at': row[5].isoformat() if row[5] else None,
                'document_count': row[6],
                'chunk_count': row[7]
            }

    def list_knowledge_bases(self, user_id: str = None) -> List[Dict]:
        """
        列出所有知识库

        Args:
            user_id: 用户ID（可选，用于用户隔离）

        Returns:
            知识库列表
        """
        from sqlalchemy import text
        
        with db_manager.engine.connect() as conn:
            if user_id:
                result = conn.execute(text(
                    "SELECT id, name, description, user_id, created_at, updated_at, document_count, chunk_count "
                    "FROM knowledge_bases WHERE user_id = :user_id ORDER BY updated_at DESC"
                ), {'user_id': user_id})
            else:
                result = conn.execute(text(
                    "SELECT id, name, description, user_id, created_at, updated_at, document_count, chunk_count "
                    "FROM knowledge_bases ORDER BY updated_at DESC"
                ))
            
            kbs = []
            for row in result.fetchall():
                kbs.append({
                    'id': str(row[0]),
                    'name': row[1],
                    'description': row[2],
                    'user_id': row[3],
                    'created_at': row[4].isoformat() if row[4] else None,
                    'updated_at': row[5].isoformat() if row[5] else None,
                    'document_count': row[6],
                    'chunk_count': row[7]
                })
            
            return kbs

    def get_documents(self, kb_id: str) -> List[Dict]:
        """
        获取知识库下的所有文档

        Args:
            kb_id: 知识库ID

        Returns:
            文档列表
        """
        from sqlalchemy import text
        
        with db_manager.engine.connect() as conn:
            result = conn.execute(text(
                "SELECT id, knowledge_base_id, filename, file_path, file_type, file_size, "
                "content, chunk_count, status, error_message, created_at, updated_at "
                "FROM documents WHERE knowledge_base_id = :kb_id ORDER BY created_at DESC"
            ), {'kb_id': kb_id})
            
            docs = []
            for row in result.fetchall():
                docs.append({
                    'id': str(row[0]),
                    'knowledge_base_id': str(row[1]),
                    'filename': row[2],
                    'file_path': row[3],
                    'file_type': row[4],
                    'file_size': row[5],
                    'content': row[6],
                    'chunk_count': row[7],
                    'status': row[8],
                    'error_message': row[9],
                    'created_at': row[10].isoformat() if row[10] else None,
                    'updated_at': row[11].isoformat() if row[11] else None
                })
            
            return docs

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
        from sqlalchemy import text
        
        with db_manager.engine.connect() as conn:
            # 统计文档数量
            result = conn.execute(text(
                "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = :kb_id"
            ), {'kb_id': kb_id})
            doc_count = result.fetchone()[0]

            # 统计分块数量
            result = conn.execute(text(
                "SELECT COUNT(*) FROM document_chunks WHERE knowledge_base_id = :kb_id"
            ), {'kb_id': kb_id})
            chunk_count = result.fetchone()[0]

            # 更新知识库统计
            conn.execute(text(
                "UPDATE knowledge_bases SET document_count = :doc_count, chunk_count = :chunk_count WHERE id = :kb_id"
            ), {'doc_count': doc_count, 'chunk_count': chunk_count, 'kb_id': kb_id})
            
            conn.commit()


# 创建全局实例
knowledge_base_service = KnowledgeBaseService()

__all__ = ['KnowledgeBaseService', 'knowledge_base_service']
