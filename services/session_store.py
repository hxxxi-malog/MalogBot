"""
会话存储服务

提供会话和消息的持久化存储，包括：
1. 会话管理（创建、删除、隔离）
2. 消息历史存储
3. 会话列表查询
"""
from typing import List, Dict, Optional
from datetime import datetime

from services.db_manager import db_manager
from models.database import Session, Message


class SessionStore:
    """会话存储服务"""
    
    # ==================== 会话管理 ====================
    
    def get_or_create_session(self, session_id: str) -> bool:
        """
        获取或创建会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否成功
        """
        with db_manager.get_session() as session:
            # 检查是否已存在
            existing = session.query(Session).filter_by(session_id=session_id).first()
            if existing:
                return True
            
            # 创建新会话，使用 Python 时间
            now = datetime.now()
            new_session = Session(
                session_id=session_id,
                created_at=now,
                updated_at=now
            )
            session.add(new_session)
            return True
    
    def delete_session(self, session_id: str) -> bool:
        """
        删除会话及其所有消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否删除成功
        """
        with db_manager.get_session() as session:
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if sess:
                session.delete(sess)
                return True
            return False
    
    def session_exists(self, session_id: str) -> bool:
        """
        检查会话是否存在
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否存在
        """
        with db_manager.get_session() as session:
            return session.query(Session).filter_by(session_id=session_id).count() > 0
    
    def get_all_sessions(self) -> List[Dict]:
        """
        获取所有会话列表
        
        Returns:
            会话列表，每个包含 session_id, created_at, updated_at, message_count
        """
        with db_manager.get_session() as session:
            # 查询所有会话，并统计消息数量
            sessions = session.query(Session).order_by(Session.updated_at.desc()).all()
            
            result = []
            for sess in sessions:
                # 统计消息数量
                msg_count = session.query(Message).filter_by(session_id=sess.session_id).count()
                
                result.append({
                    'session_id': sess.session_id,
                    'created_at': sess.created_at.isoformat() if sess.created_at else None,
                    'updated_at': sess.updated_at.isoformat() if sess.updated_at else None,
                    'message_count': msg_count
                })
            
            return result
    
    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息字典，不存在则返回None
        """
        with db_manager.get_session() as session:
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if not sess:
                return None
            
            # 统计消息数量
            msg_count = session.query(Message).filter_by(session_id=session_id).count()
            
            return {
                'session_id': sess.session_id,
                'created_at': sess.created_at.isoformat() if sess.created_at else None,
                'updated_at': sess.updated_at.isoformat() if sess.updated_at else None,
                'message_count': msg_count,
                'web_search_enabled': sess.web_search_enabled if sess.web_search_enabled is not None else False,
                'knowledge_base_id': sess.knowledge_base_id
            }
    
    # ==================== 消息历史 ====================
    
    def add_message(self, session_id: str, role: str, content: str) -> bool:
        """
        添加消息到历史
        
        Args:
            session_id: 会话ID
            role: 角色（user/assistant/system）
            content: 消息内容
            
        Returns:
            是否添加成功
        """
        with db_manager.get_session() as session:
            # 确保会话存在
            self.get_or_create_session(session_id)
            
            now = datetime.now()
            
            # 添加消息
            message = Message(
                session_id=session_id,
                role=role,
                content=content,
                timestamp=now
            )
            session.add(message)
            
            # 更新会话的 updated_at 时间
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if sess:
                sess.updated_at = now
            
            return True
    
    def get_messages(self, session_id: str, limit: Optional[int] = None) -> List[Dict]:
        """
        获取会话的消息历史
        
        Args:
            session_id: 会话ID
            limit: 最大消息数量（None表示不限制）
            
        Returns:
            消息列表（按时间正序）
        """
        with db_manager.get_session() as session:
            query = session.query(Message)\
                .filter_by(session_id=session_id)\
                .order_by(Message.timestamp.asc())
            
            if limit:
                # 获取最近N条
                query = session.query(Message)\
                    .filter_by(session_id=session_id)\
                    .order_by(Message.timestamp.desc())\
                    .limit(limit)
                messages = query.all()
                # 按时间正序返回
                return [m.to_dict() for m in reversed(messages)]
            
            messages = query.all()
            return [m.to_dict() for m in messages]
    
    def clear_messages(self, session_id: str) -> bool:
        """
        清空会话的消息历史
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否清空成功
        """
        with db_manager.get_session() as session:
            session.query(Message).filter_by(session_id=session_id).delete()
            return True
    
    def replace_messages(self, session_id: str, messages: List[Dict]) -> bool:
        """
        替换会话的所有消息（用于上下文压缩）
        
        Args:
            session_id: 会话ID
            messages: 新的消息列表
            
        Returns:
            是否替换成功
        """
        with db_manager.get_session() as session:
            # 删除旧消息
            session.query(Message).filter_by(session_id=session_id).delete()
            
            # 添加新消息
            for msg in messages:
                message = Message(
                    session_id=session_id,
                    role=msg.get('role'),
                    content=msg.get('content')
                )
                session.add(message)
            
            return True
    
    def get_message_count(self, session_id: str) -> int:
        """
        获取会话的消息数量
        
        Args:
            session_id: 会话ID
            
        Returns:
            消息数量
        """
        with db_manager.get_session() as session:
            return session.query(Message).filter_by(session_id=session_id).count()
    
    # ==================== 联网搜索设置 ====================
    
    def get_web_search_enabled(self, session_id: str) -> bool:
        """
        获取会话的联网搜索开关状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否启用联网搜索，默认为 False
        """
        with db_manager.get_session() as session:
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if not sess:
                return False
            return sess.web_search_enabled if sess.web_search_enabled is not None else False
    
    def set_web_search_enabled(self, session_id: str, enabled: bool) -> bool:
        """
        设置会话的联网搜索开关状态
        
        Args:
            session_id: 会话ID
            enabled: 是否启用联网搜索
            
        Returns:
            是否设置成功
        """
        with db_manager.get_session() as session:
            # 确保会话存在
            self.get_or_create_session(session_id)
            
            # 更新设置
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if sess:
                sess.web_search_enabled = enabled
                return True
            return False

    # ==================== 知识库设置 ====================

    def get_knowledge_base_id(self, session_id: str) -> Optional[str]:
        """
        获取会话当前选中的知识库ID
        
        Args:
            session_id: 会话ID
            
        Returns:
            知识库ID，None表示不使用知识库
        """
        with db_manager.get_session() as session:
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if not sess:
                return None
            return sess.knowledge_base_id

    def set_knowledge_base_id(self, session_id: str, kb_id: Optional[str]) -> bool:
        """
        设置会话的知识库
        
        Args:
            session_id: 会话ID
            kb_id: 知识库ID，None表示不使用知识库
            
        Returns:
            是否设置成功
        """
        with db_manager.get_session() as session:
            # 确保会话存在
            self.get_or_create_session(session_id)
            
            # 更新设置
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if sess:
                sess.knowledge_base_id = kb_id
                return True
            return False


# 创建全局实例
session_store = SessionStore()


# 导出
__all__ = ['SessionStore', 'session_store']
