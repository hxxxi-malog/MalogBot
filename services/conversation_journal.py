"""
对话日志服务模块

管理原始对话消息的JSONL格式存储，支持：
1. 实时追加消息到JSONL文件
2. 从JSONL文件读取消息注入上下文
3. 统计token数量，触发压缩阈值检测
4. 与数据库记录同步
"""
import json
import os
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from services.db_manager import db_manager
from models.database import ConversationJournal
from config import Config

logger = logging.getLogger(__name__)

# JSONL存储根目录
JOURNAL_ROOT_DIR = Path(__file__).parent.parent / 'archives' / 'journals'
JOURNAL_ROOT_DIR.mkdir(parents=True, exist_ok=True)

# 默认值（如果配置文件中没有设置）
DEFAULT_MAX_CONTEXT_TOKENS = 128000
DEFAULT_COMPACT_THRESHOLD_RATIO = 0.8


class ConversationJournalService:
    """
    对话日志服务
    
    负责原始消息的持久化存储，是上下文管理的核心组件。
    所有用户和Agent的原始消息都会实时追加到JSONL文件。
    """
    
    def __init__(self, max_context_tokens: int = None):
        """
        初始化对话日志服务
        
        Args:
            max_context_tokens: 模型的最大上下文窗口token数（默认从配置读取）
        """
        # 从配置读取参数
        self.max_context_tokens = max_context_tokens or getattr(Config, 'MAX_CONTEXT_TOKENS', DEFAULT_MAX_CONTEXT_TOKENS)
        threshold_ratio = getattr(Config, 'COMPACT_THRESHOLD_RATIO', DEFAULT_COMPACT_THRESHOLD_RATIO)
        self.compact_threshold = int(self.max_context_tokens * threshold_ratio)
        
        # 会话级别的文件锁，防止并发写入冲突
        self._file_locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()  # 保护 _file_locks 的锁
    
    def _get_lock(self, session_id: str) -> threading.Lock:
        """获取会话级别的文件锁"""
        with self._locks_lock:
            if session_id not in self._file_locks:
                self._file_locks[session_id] = threading.Lock()
            return self._file_locks[session_id]
    
    def _get_journal_path(self, session_id: str) -> Path:
        """获取会话的JSONL文件路径"""
        return JOURNAL_ROOT_DIR / f"{session_id}.jsonl"
    
    # ==================== 消息追加 ====================
    
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_call_id: str = None,
        tool_calls: list = None,
        tool_name: str = None,
        metadata: dict = None
    ) -> bool:
        """
        追加单条消息到JSONL文件
        
        这是核心写入方法，每条消息都会实时追加。
        
        Args:
            session_id: 会话ID
            role: 角色（user/assistant/system/tool）
            content: 消息内容
            tool_call_id: 工具调用ID
            tool_calls: 工具调用列表
            tool_name: 工具名称
            metadata: 额外元数据
            
        Returns:
            是否成功
        """
        lock = self._get_lock(session_id)
        
        with lock:
            try:
                journal_path = self._get_journal_path(session_id)
                
                # 构建消息记录
                message_record = {
                    'role': role,
                    'content': content,
                    'timestamp': datetime.now().isoformat()
                }
                
                if tool_call_id:
                    message_record['tool_call_id'] = tool_call_id
                if tool_calls:
                    message_record['tool_calls'] = tool_calls
                if tool_name:
                    message_record['tool_name'] = tool_name
                if metadata:
                    message_record['metadata'] = metadata
                
                # 追加到JSONL文件
                with open(journal_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(message_record, ensure_ascii=False) + '\n')
                
                # 更新数据库记录
                self._update_journal_record(session_id, journal_path)
                
                return True
                
            except Exception as e:
                logger.error(f"[Journal] 追加消息失败: {e}")
                return False
    
    def append_messages_batch(self, session_id: str, messages: List[Dict]) -> bool:
        """
        批量追加消息到JSONL文件
        
        Args:
            session_id: 会话ID
            messages: 消息列表
            
        Returns:
            是否成功
        """
        if not messages:
            return True
            
        lock = self._get_lock(session_id)
        
        with lock:
            try:
                journal_path = self._get_journal_path(session_id)
                
                # 批量追加
                with open(journal_path, 'a', encoding='utf-8') as f:
                    for msg in messages:
                        # 确保有时间戳
                        if 'timestamp' not in msg:
                            msg['timestamp'] = datetime.now().isoformat()
                        f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                
                # 更新数据库记录
                self._update_journal_record(session_id, journal_path)
                
                return True
                
            except Exception as e:
                logger.error(f"[Journal] 批量追加消息失败: {e}")
                return False
    
    def _update_journal_record(self, session_id: str, journal_path: Path):
        """更新数据库中的日志记录"""
        try:
            # 统计消息数量和token数
            message_count = 0
            token_estimate = 0
            start_time = None
            end_time = None
            
            if journal_path.exists():
                with open(journal_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            message_count += 1
                            try:
                                msg = json.loads(line)
                                # 粗略估算token数（中文约1.5字符/token，英文约4字符/token）
                                content = msg.get('content', '')
                                token_estimate += len(content) // 3
                                
                                # 更新时间范围
                                msg_time = msg.get('timestamp')
                                if msg_time:
                                    if start_time is None:
                                        start_time = msg_time
                                    end_time = msg_time
                            except:
                                pass
            
            with db_manager.get_session() as session:
                # 查找或创建记录
                record = session.query(ConversationJournal).filter_by(
                    session_id=session_id,
                    is_active=True
                ).first()
                
                if record:
                    record.message_count = message_count
                    record.token_count = token_estimate
                    record.journal_file = str(journal_path)
                    if start_time:
                        try:
                            record.start_time = datetime.fromisoformat(start_time)
                        except:
                            pass
                    if end_time:
                        try:
                            record.end_time = datetime.fromisoformat(end_time)
                        except:
                            pass
                else:
                    new_record = ConversationJournal(
                        session_id=session_id,
                        journal_file=str(journal_path),
                        message_count=message_count,
                        token_count=token_estimate,
                        start_time=datetime.fromisoformat(start_time) if start_time else None,
                        end_time=datetime.fromisoformat(end_time) if end_time else None,
                        is_active=True
                    )
                    session.add(new_record)
                    
        except Exception as e:
            logger.error(f"[Journal] 更新数据库记录失败: {e}")
    
    # ==================== 消息读取 ====================
    
    def read_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[Dict]:
        """
        从JSONL文件读取消息
        
        Args:
            session_id: 会话ID
            limit: 最大读取数量，None表示全部
            offset: 跳过前N条消息
            
        Returns:
            消息列表（按时间正序）
        """
        lock = self._get_lock(session_id)
        
        with lock:
            journal_path = self._get_journal_path(session_id)
            
            if not journal_path.exists():
                return []
            
            messages = []
            try:
                with open(journal_path, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                    
                # 解析所有消息
                for line in all_lines:
                    if line.strip():
                        try:
                            messages.append(json.loads(line))
                        except:
                            continue
                
                # 应用offset和limit
                if offset > 0:
                    messages = messages[offset:]
                if limit is not None:
                    messages = messages[-limit:] if len(messages) > limit else messages
                    
            except Exception as e:
                logger.error(f"[Journal] 读取消息失败: {e}")
                
            return messages
    
    def read_messages_for_context(
        self,
        session_id: str,
        max_tokens: Optional[int] = None
    ) -> Tuple[List[Dict], int]:
        """
        读取消息用于注入上下文
        
        智能读取消息，确保不超过token限制。
        优先保留最近的消息。
        
        Args:
            session_id: 会话ID
            max_tokens: 最大token限制，None使用默认值
            
        Returns:
            (消息列表, 实际token数)
        """
        max_tokens = max_tokens or self.compact_threshold
        
        lock = self._get_lock(session_id)
        
        with lock:
            journal_path = self._get_journal_path(session_id)
            
            if not journal_path.exists():
                return [], 0
            
            messages = []
            total_tokens = 0
            
            try:
                with open(journal_path, 'r', encoding='utf-8') as f:
                    all_lines = f.readlines()
                
                # 从后往前读取，确保最近的消息优先
                for line in reversed(all_lines):
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            msg_tokens = len(msg.get('content', '')) // 3
                            
                            if total_tokens + msg_tokens > max_tokens:
                                break
                            
                            messages.insert(0, msg)  # 保持时间正序
                            total_tokens += msg_tokens
                            
                        except:
                            continue
                            
            except Exception as e:
                logger.error(f"[Journal] 读取上下文消息失败: {e}")
                
            return messages, total_tokens
    
    # ==================== Token 统计和压缩检测 ====================
    
    def get_token_count(self, session_id: str) -> int:
        """
        获取当前会话的token数量估算
        
        Args:
            session_id: 会话ID
            
        Returns:
            token数量估算
        """
        try:
            with db_manager.get_session() as session:
                record = session.query(ConversationJournal).filter_by(
                    session_id=session_id,
                    is_active=True
                ).first()
                
                if record:
                    return record.token_count
        except:
            pass
        
        # 如果数据库记录不存在，从文件计算
        messages = self.read_messages(session_id)
        return sum(len(msg.get('content', '')) // 3 for msg in messages)
    
    def should_compact(self, session_id: str) -> bool:
        """
        检查是否需要执行上下文压缩
        
        当token数量达到阈值（默认80%上下文窗口）时返回True
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否需要压缩
        """
        token_count = self.get_token_count(session_id)
        return token_count >= self.compact_threshold
    
    def get_compaction_info(self, session_id: str) -> Dict[str, Any]:
        """
        获取压缩相关信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            包含token统计和压缩建议的字典
        """
        token_count = self.get_token_count(session_id)
        message_count = len(self.read_messages(session_id))
        
        return {
            'session_id': session_id,
            'token_count': token_count,
            'message_count': message_count,
            'max_context_tokens': self.max_context_tokens,
            'compact_threshold': self.compact_threshold,
            'usage_ratio': token_count / self.max_context_tokens,
            'should_compact': token_count >= self.compact_threshold,
            'tokens_until_compact': max(0, self.compact_threshold - token_count)
        }
    
    # ==================== 日志管理 ====================
    
    def archive_journal(self, session_id: str) -> Optional[str]:
        """
        归档当前日志文件（压缩时调用）
        
        将当前活跃的日志文件重命名为归档文件，
        并创建新的空日志文件。
        
        Args:
            session_id: 会话ID
            
        Returns:
            归档ID（用于后续恢复）
        """
        lock = self._get_lock(session_id)
        
        with lock:
            try:
                journal_path = self._get_journal_path(session_id)
                
                if not journal_path.exists():
                    return None
                
                # 生成归档ID
                archive_id = f"archive_{session_id}_{int(datetime.now().timestamp())}"
                
                # 重命名为归档文件
                archive_path = JOURNAL_ROOT_DIR / f"{archive_id}.jsonl"
                journal_path.rename(archive_path)
                
                # 更新数据库记录
                with db_manager.get_session() as session:
                    # 将当前活跃记录标记为非活跃
                    record = session.query(ConversationJournal).filter_by(
                        session_id=session_id,
                        is_active=True
                    ).first()
                    
                    if record:
                        record.is_active = False
                        record.journal_file = str(archive_path)
                
                return archive_id
                
            except Exception as e:
                logger.error(f"[Journal] 归档失败: {e}")
                return None
    
    def clear_journal(self, session_id: str) -> bool:
        """
        清空会话的日志文件
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否成功
        """
        lock = self._get_lock(session_id)
        
        with lock:
            try:
                journal_path = self._get_journal_path(session_id)
                
                if journal_path.exists():
                    journal_path.unlink()
                
                # 更新数据库记录
                with db_manager.get_session() as session:
                    session.query(ConversationJournal).filter_by(
                        session_id=session_id
                    ).delete()
                
                return True
                
            except Exception as e:
                logger.error(f"[Journal] 清空失败: {e}")
                return False
    
    def list_archives(self, session_id: str) -> List[Dict]:
        """
        列出会话的所有归档
        
        Args:
            session_id: 会话ID
            
        Returns:
            归档列表
        """
        try:
            with db_manager.get_session() as session:
                records = session.query(ConversationJournal).filter_by(
                    session_id=session_id,
                    is_active=False
                ).order_by(ConversationJournal.created_at.desc()).all()
                
                return [r.to_dict() for r in records]
        except:
            return []
    
    def get_archive_messages(self, archive_id: str) -> List[Dict]:
        """
        读取归档文件中的消息
        
        Args:
            archive_id: 归档ID
            
        Returns:
            消息列表
        """
        archive_path = JOURNAL_ROOT_DIR / f"{archive_id}.jsonl"
        
        if not archive_path.exists():
            return []
        
        messages = []
        try:
            with open(archive_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        messages.append(json.loads(line))
        except Exception as e:
            logger.error(f"[Journal] 读取归档失败: {e}")
            
        return messages
    
    def cleanup_session(self, session_id: str):
        """
        清理会话资源
        
        Args:
            session_id: 会话ID
        """
        with self._locks_lock:
            if session_id in self._file_locks:
                del self._file_locks[session_id]


# 创建全局实例
conversation_journal = ConversationJournalService()

# 导出
__all__ = ['ConversationJournalService', 'conversation_journal', 'JOURNAL_ROOT_DIR']
