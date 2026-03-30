"""
会话存储服务（重构版）

提供会话和消息的持久化存储，集成新的三层上下文管理：
1. 会话管理（创建、删除、隔离）
2. 消息历史存储（数据库 + JSONL双重存储）
3. 会话列表查询
4. 上下文压缩触发
"""
import json
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from services.db_manager import db_manager
from models.database import Session, Message

logger = logging.getLogger(__name__)


class SessionStore:
    """会话存储服务"""
    
    def __init__(self):
        """初始化会话存储服务"""
        # 延迟导入避免循环依赖
        self._conversation_journal = None
        self._context_compactor = None
    
    @property
    def conversation_journal(self):
        """延迟获取 conversation_journal 实例"""
        if self._conversation_journal is None:
            from services.conversation_journal import conversation_journal
            self._conversation_journal = conversation_journal
        return self._conversation_journal
    
    @property
    def context_compactor(self):
        """延迟获取 context_compactor 实例"""
        if self._context_compactor is None:
            from services.context_compactor import context_compactor
            self._context_compactor = context_compactor
        return self._context_compactor
    
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
        # 先获取数据库会话信息
        with db_manager.get_session() as db_sess:
            sess = db_sess.query(Session).filter_by(session_id=session_id).first()
            if not sess:
                return None
            
            # 在会话内提取所有需要的值
            session_id_val = sess.session_id
            created_at_val = sess.created_at.isoformat() if sess.created_at else None
            updated_at_val = sess.updated_at.isoformat() if sess.updated_at else None
            web_search_enabled_val = sess.web_search_enabled if sess.web_search_enabled is not None else False
            knowledge_base_id_val = sess.knowledge_base_id
            
            # 统计消息数量
            msg_count = db_sess.query(Message).filter_by(session_id=session_id).count()
        
        # 数据库会话关闭后，再获取上下文统计（这会开启新的数据库连接）
        try:
            context_stats = self.conversation_journal.get_compaction_info(session_id)
        except Exception as e:
            logger.error(f"[session_store] 获取上下文统计失败: {e}")
            context_stats = {}
            
        return {
            'session_id': session_id_val,
            'created_at': created_at_val,
            'updated_at': updated_at_val,
            'message_count': msg_count,
            'web_search_enabled': web_search_enabled_val,
            'knowledge_base_id': knowledge_base_id_val,
            'context_stats': context_stats
        }
    
    # ==================== 消息历史 ====================
    
    def add_message(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        tool_call_id: str = None,
        tool_calls: list = None,
        tool_name: str = None
    ) -> bool:
        """
        添加消息到历史（双重存储：数据库 + JSONL）
        
        同时写入：
        1. 数据库（用于快速查询）
        2. JSONL文件（用于完整上下文恢复和压缩）
        
        Args:
            session_id: 会话ID
            role: 角色（user/assistant/system/tool）
            content: 消息内容
            tool_call_id: 工具调用ID（用于 tool 角色）
            tool_calls: 工具调用列表（用于 assistant 角色）
            tool_name: 工具名称（用于 tool 角色）
            
        Returns:
            是否添加成功
        """
        # 1. 写入数据库
        with db_manager.get_session() as session:
            # 确保会话存在
            self.get_or_create_session(session_id)
            
            now = datetime.now()
            
            # 添加消息
            message = Message(
                session_id=session_id,
                role=role,
                content=content,
                timestamp=now,
                tool_call_id=tool_call_id,
                tool_calls=json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                tool_name=tool_name
            )
            session.add(message)
            
            # 更新会话的 updated_at 时间
            sess = session.query(Session).filter_by(session_id=session_id).first()
            if sess:
                sess.updated_at = now
        
        # 2. 写入JSONL文件（通过conversation_journal）
        self.conversation_journal.append_message(
            session_id=session_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            tool_name=tool_name
        )
        
        return True
    
    def get_messages(self, session_id: str, limit: Optional[int] = None) -> List[Dict]:
        """
        获取会话的消息历史（从数据库读取）
        
        注意：对于完整上下文恢复，应使用 get_full_context()
        
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
    
    def get_full_context(
        self,
        session_id: str,
        user_query: str = ""
    ) -> Tuple[List[Dict], Dict[str, any]]:
        """
        获取完整的上下文（整合三层数据）
        
        这是对话时应该使用的方法，整合：
        1. 从JSONL读取的消息（带token控制）
        2. 长期记忆注入
        3. 压缩检测
        
        Args:
            session_id: 会话ID
            user_query: 用户当前查询（用于检索相关记忆）
            
        Returns:
            (消息列表, 统计信息)
        """
        return self.context_compactor.inject_context_for_chat(session_id, user_query)
    
    def should_compact(self, session_id: str) -> bool:
        """
        检查是否需要执行上下文压缩
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否需要压缩
        """
        return self.context_compactor.should_auto_compact(session_id)
    
    def get_context_stats(self, session_id: str) -> Dict:
        """
        获取上下文统计信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            统计信息字典
        """
        return self.conversation_journal.get_compaction_info(session_id)
    
    def clear_messages(self, session_id: str) -> bool:
        """
        清空会话的消息历史
        
        同时清空数据库和JSONL文件。
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否清空成功
        """
        # 1. 清空数据库
        with db_manager.get_session() as session:
            session.query(Message).filter_by(session_id=session_id).delete()
        
        # 2. 清空JSONL文件
        self.conversation_journal.clear_journal(session_id)
        
        return True
    
    def replace_messages(self, session_id: str, messages: List[Dict]) -> bool:
        """
        替换会话的所有消息（用于上下文压缩后）
        
        只更新数据库，JSONL保持不变（用于完整恢复）。
        
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
                tool_calls = msg.get('tool_calls')
                message = Message(
                    session_id=session_id,
                    role=msg.get('role'),
                    content=msg.get('content'),
                    tool_call_id=msg.get('tool_call_id'),
                    tool_calls=json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    tool_name=msg.get('tool_name'),
                    timestamp=datetime.now()
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
    
    def get_token_count(self, session_id: str) -> int:
        """
        获取会话的token数量估算
        
        Args:
            session_id: 会话ID
            
        Returns:
            token数量估算
        """
        return self.conversation_journal.get_token_count(session_id)
    
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
    
    # ==================== 资源清理 ====================
    
    def cleanup_session(self, session_id: str):
        """
        清理会话资源
        
        Args:
            session_id: 会话ID
        """
        self.context_compactor.clear_session(session_id)


# 创建全局实例
session_store = SessionStore()


# 导出
__all__ = ['SessionStore', 'session_store']
