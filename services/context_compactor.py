"""
三层上下文压缩模块

实现三层渐进式上下文压缩策略：
1. micro_compact（微观压缩）：每次 LLM 调用前，将旧的 tool result 替换为占位符
2. auto_compact（自动压缩）：Token 超过阈值时触发 LLM 摘要
3. manual_compact（手动压缩）：通过 compact 工具按需触发摘要

所有原始上下文归档到数据库，支持恢复。
"""
import json
import time
import logging
import os
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from config import Config
from services.db_manager import db_manager
from services.session_store import session_store

logger = logging.getLogger(__name__)


# ==================== 配置常量 ====================

# 微观压缩：保留最近的 N 个 tool_result
KEEP_RECENT_TOOL_RESULTS = int(os.getenv('KEEP_RECENT_TOOL_RESULTS', '5'))

# 自动压缩：Token 阈值（字符数近似）
AUTO_COMPACT_THRESHOLD = int(os.getenv('AUTO_COMPACT_THRESHOLD', '50000'))

# 压缩后保留的最近消息数
KEEP_RECENT_MESSAGES = int(os.getenv('KEEP_RECENT_MESSAGES', '10'))

# 归档文件存储目录
TRANSCRIPT_DIR = Path(__file__).parent.parent / 'archives' / 'transcripts'
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)


class ContextCompactor:
    """
    三层上下文压缩器
    
    实现渐进式压缩策略，在保证上下文完整性的同时节省 token。
    """
    
    def __init__(
        self,
        keep_recent_tools: int = KEEP_RECENT_TOOL_RESULTS,
        auto_compact_threshold: int = AUTO_COMPACT_THRESHOLD,
        keep_recent_messages: int = KEEP_RECENT_MESSAGES
    ):
        """
        初始化上下文压缩器
        
        Args:
            keep_recent_tools: 微观压缩时保留的最近 tool_result 数量
            auto_compact_threshold: 自动压缩的字符数阈值
            keep_recent_messages: 压缩后保留的最近消息数量
        """
        self.keep_recent_tools = keep_recent_tools
        self.auto_compact_threshold = auto_compact_threshold
        self.keep_recent_messages = keep_recent_messages
    
    # ==================== 第一层：微观压缩 ====================
    
    def micro_compact(self, messages: List) -> List:
        """
        微观压缩：将旧的 tool result 替换为占位符
        
        在每次 LLM 调用前执行，减少 tool_result 占用的上下文空间。
        
        Args:
            messages: LangChain 消息列表
            
        Returns:
            压缩后的消息列表
        """
        if not messages:
            return messages
        
        # 收集所有 tool_result 位置
        tool_results = []
        
        for i, msg in enumerate(messages):
            # 处理 ToolMessage 类型
            if isinstance(msg, ToolMessage):
                tool_results.append((i, msg))
            # 处理包含 tool_result 的消息（兼容多种格式）
            elif hasattr(msg, 'content') and isinstance(msg.content, list):
                for j, part in enumerate(msg.content):
                    if isinstance(part, dict) and part.get('type') == 'tool_result':
                        tool_results.append((i, msg, j, part))
        
        if len(tool_results) <= self.keep_recent_tools:
            return messages
        
        # 创建消息的深拷贝（避免修改原始消息）
        result_messages = list(messages)
        
        # 旧结果替换为占位符
        old_results = tool_results[:-self.keep_recent_tools]
        
        for item in old_results:
            if len(item) == 2:
                # ToolMessage 类型
                i, msg = item
                tool_name = getattr(msg, 'name', 'unknown')
                placeholder = self._create_tool_placeholder(tool_name, msg.content)
                result_messages[i] = placeholder
            elif len(item) == 4:
                # 嵌套在 content 中的 tool_result
                i, msg, j, part = item
                tool_name = part.get('name', 'unknown')
                part['content'] = f"[Previous: used {tool_name}]"
        
        logger.info(f"[micro_compact] 压缩了 {len(old_results)} 个旧的 tool_result")
        return result_messages
    
    def _create_tool_placeholder(self, tool_name: str, original_content: Any) -> HumanMessage:
        """
        创建工具调用占位符
        
        Args:
            tool_name: 工具名称
            original_content: 原始内容
            
        Returns:
            占位符消息
        """
        content_preview = ""
        if isinstance(original_content, str) and len(original_content) > 100:
            content_preview = f" (内容长度: {len(original_content)} 字符)"
        
        placeholder_content = f"[压缩的工具调用: {tool_name}]{content_preview}"
        return HumanMessage(content=placeholder_content)
    
    # ==================== 第二层：自动压缩 ====================
    
    def should_auto_compact(self, messages: List) -> bool:
        """
        判断是否需要触发自动压缩
        
        Args:
            messages: 消息列表
            
        Returns:
            是否需要压缩
        """
        total_chars = self._estimate_tokens(messages)
        return total_chars > self.auto_compact_threshold
    
    def _estimate_tokens(self, messages: List) -> int:
        """
        估算消息列表的 token 数量（使用字符数近似）
        
        Args:
            messages: 消息列表
            
        Returns:
            估算的 token 数量
        """
        total_chars = 0
        for msg in messages:
            if hasattr(msg, 'content'):
                content = msg.content
                if isinstance(content, str):
                    total_chars += len(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            total_chars += len(str(part.get('content', '')))
                        else:
                            total_chars += len(str(part))
        return total_chars
    
    def auto_compact(
        self,
        messages: List,
        session_id: str,
        llm_client: Optional[Any] = None
    ) -> Tuple[List, Optional[str]]:
        """
        自动压缩：Token 超过阈值时触发 LLM 摘要
        
        流程：
        1. 保存完整对话到磁盘（可恢复）
        2. 归档到数据库
        3. LLM 生成摘要
        4. 替换为压缩后的消息
        
        Args:
            messages: 消息列表
            session_id: 会话ID
            llm_client: LLM 客户端（用于生成摘要）
            
        Returns:
            (压缩后的消息列表, 归档ID)
        """
        if len(messages) <= self.keep_recent_messages:
            return messages, None
        
        # 1. 保存完整对话到磁盘
        archive_id, transcript_path = self._save_transcript_to_disk(messages, session_id)
        
        # 2. 归档到数据库
        self._archive_to_database(messages, session_id, archive_id, transcript_path)
        
        # 3. 分离旧消息和最近消息
        old_messages = messages[:-self.keep_recent_messages]
        recent_messages = messages[-self.keep_recent_messages:]
        
        # 4. LLM 生成摘要
        summary = ""
        if llm_client and old_messages:
            summary = self._generate_summary_with_llm(old_messages, llm_client)
        else:
            summary = self._simple_summary(old_messages)
        
        # 5. 构建压缩后的消息
        compressed = [
            SystemMessage(content=f"""## 对话历史压缩摘要

{summary}

---
注：完整对话已归档，归档ID: {archive_id}
如需查看完整历史，可使用 compact 工具恢复。
""")
        ]
        compressed.extend(recent_messages)
        
        logger.info(f"[auto_compact] 压缩完成，归档ID: {archive_id}")
        return compressed, archive_id
    
    def _save_transcript_to_disk(self, messages: List, session_id: str) -> Tuple[str, Path]:
        """
        保存完整对话到磁盘
        
        Args:
            messages: 消息列表
            session_id: 会话ID
            
        Returns:
            (归档ID, 文件路径)
        """
        archive_id = f"archive_{session_id}_{int(time.time())}"
        transcript_path = TRANSCRIPT_DIR / f"{archive_id}.jsonl"
        
        with open(transcript_path, 'w', encoding='utf-8') as f:
            for msg in messages:
                msg_dict = self._message_to_dict(msg)
                f.write(json.dumps(msg_dict, ensure_ascii=False, default=str) + '\n')
        
        logger.info(f"[auto_compact] 对话已保存到: {transcript_path}")
        return archive_id, transcript_path
    
    def _message_to_dict(self, msg: Any) -> Dict:
        """
        将 LangChain 消息转换为字典
        
        Args:
            msg: LangChain 消息对象
            
        Returns:
            消息字典
        """
        if isinstance(msg, HumanMessage):
            return {"role": "user", "content": str(msg.content)}
        elif isinstance(msg, AIMessage):
            result = {"role": "assistant", "content": str(msg.content)}
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                result['tool_calls'] = [
                    {"name": tc.get('name'), "args": tc.get('args'), "id": tc.get('id')}
                    for tc in msg.tool_calls
                ]
            return result
        elif isinstance(msg, SystemMessage):
            return {"role": "system", "content": str(msg.content)}
        elif isinstance(msg, ToolMessage):
            return {"role": "tool", "content": str(msg.content), "tool_call_id": msg.tool_call_id}
        else:
            return {"role": "unknown", "content": str(msg.content) if hasattr(msg, 'content') else str(msg)}
    
    def _archive_to_database(
        self,
        messages: List,
        session_id: str,
        archive_id: str,
        transcript_path: Path
    ) -> bool:
        """
        归档到数据库
        
        Args:
            messages: 消息列表
            session_id: 会话ID
            archive_id: 归档ID
            transcript_path: 归档文件路径
            
        Returns:
            是否成功
        """
        try:
            # 导入归档模型（动态导入避免循环依赖）
            from models.database import ContextArchive
            
            messages_json = json.dumps(
                [self._message_to_dict(msg) for msg in messages],
                ensure_ascii=False
            )
            
            with db_manager.get_session() as session:
                archive = ContextArchive(
                    archive_id=archive_id,
                    session_id=session_id,
                    messages=messages_json,
                    file_path=str(transcript_path),
                    message_count=len(messages),
                    created_at=datetime.now()
                )
                session.add(archive)
            
            logger.info(f"[auto_compact] 已归档到数据库: {archive_id}")
            return True
        except Exception as e:
            logger.error(f"[auto_compact] 归档失败: {e}")
            return False
    
    def _generate_summary_with_llm(self, messages: List, llm_client: Any) -> str:
        """
        使用 LLM 生成对话摘要
        
        Args:
            messages: 消息列表
            llm_client: LLM 客户端
            
        Returns:
            摘要文本
        """
        # 构建对话文本
        conversation_text = "\n".join([
            f"{self._message_to_dict(msg).get('role', 'unknown')}: {self._message_to_dict(msg).get('content', '')[:500]}"
            for msg in messages[:20]  # 限制长度
        ])
        
        summary_prompt = f"""请总结以下对话的关键内容，要求：
1. 简洁明了（不超过300字）
2. 保留重要的文件路径和操作
3. 说明已完成和未完成的任务
4. 保留关键决策和结论

对话内容：
{conversation_text}

摘要："""
        
        try:
            if hasattr(llm_client, 'invoke'):
                response = llm_client.invoke(summary_prompt)
                return response.content if hasattr(response, 'content') else str(response)
            else:
                return self._simple_summary(messages)
        except Exception as e:
            logger.error(f"[auto_compact] LLM 摘要生成失败: {e}")
            return self._simple_summary(messages)
    
    def _simple_summary(self, messages: List) -> str:
        """
        简单摘要方法（不依赖 LLM）
        
        Args:
            messages: 消息列表
            
        Returns:
            摘要文本
        """
        user_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        ai_messages = [msg for msg in messages if isinstance(msg, AIMessage)]
        tool_messages = [msg for msg in messages if isinstance(msg, ToolMessage)]
        
        # 提取关键信息
        files_mentioned = set()
        for msg in messages:
            content = str(msg.content) if hasattr(msg, 'content') else ''
            import re
            # 提取文件路径
            file_patterns = [
                r'/Users/[\w/]+\.\w+',
                r'/home/[\w/]+\.\w+',
                r'C:\\[\w\\]+\.\w+',
            ]
            for pattern in file_patterns:
                files_mentioned.update(re.findall(pattern, content))
        
        summary_parts = [
            f"对话包含 {len(user_messages)} 个用户消息, {len(ai_messages)} 个助手回复, {len(tool_messages)} 个工具调用。",
        ]
        
        if files_mentioned:
            summary_parts.append(f"涉及的文件: {', '.join(list(files_mentioned)[:5])}")
        
        if user_messages:
            first_user_msg = str(user_messages[0].content)[:100]
            summary_parts.append(f"用户初始请求: {first_user_msg}...")
        
        return "\n".join(summary_parts)
    
    # ==================== 第三层：手动压缩 ====================
    
    def manual_compact(
        self,
        session_id: str,
        llm_client: Optional[Any] = None,
        compact_all: bool = False
    ) -> Dict[str, Any]:
        """
        手动压缩：通过 compact 工具按需触发
        
        Args:
            session_id: 会话ID
            llm_client: LLM 客户端
            compact_all: 是否压缩所有历史（包括最近的）
            
        Returns:
            压缩结果信息
        """
        # 获取当前会话的消息历史
        history = session_store.get_messages(session_id)
        
        if not history:
            return {
                "success": False,
                "message": "没有可压缩的对话历史"
            }
        
        # 转换为 LangChain 消息格式
        messages = self._dict_to_messages(history)
        
        # 执行压缩
        if compact_all:
            # 压缩所有历史
            compressed, archive_id = self.auto_compact(
                messages, session_id, llm_client
            )
        else:
            # 保留最近的几条消息
            if len(messages) <= self.keep_recent_messages:
                return {
                    "success": False,
                    "message": f"对话历史较短（{len(messages)}条），无需压缩"
                }
            compressed, archive_id = self.auto_compact(
                messages, session_id, llm_client
            )
        
        # 更新数据库中的消息
        compressed_dicts = [self._message_to_dict(msg) for msg in compressed]
        session_store.replace_messages(session_id, compressed_dicts)
        
        return {
            "success": True,
            "archive_id": archive_id,
            "original_count": len(messages),
            "compressed_count": len(compressed),
            "message": f"成功压缩 {len(messages)} 条消息为 {len(compressed)} 条"
        }
    
    def _dict_to_messages(self, message_dicts: List[Dict]) -> List:
        """
        将字典列表转换为 LangChain 消息列表
        
        Args:
            message_dicts: 消息字典列表
            
        Returns:
            LangChain 消息列表
        """
        messages = []
        for msg_dict in message_dicts:
            role = msg_dict.get('role')
            content = msg_dict.get('content', '')
            
            if role == 'user':
                messages.append(HumanMessage(content=content))
            elif role == 'assistant':
                messages.append(AIMessage(content=content))
            elif role == 'system':
                messages.append(SystemMessage(content=content))
            elif role == 'tool':
                messages.append(ToolMessage(content=content, tool_call_id=msg_dict.get('tool_call_id', '')))
        
        return messages
    
    # ==================== 恢复功能 ====================
    
    def restore_from_archive(self, archive_id: str) -> Optional[List[Dict]]:
        """
        从归档恢复对话历史
        
        Args:
            archive_id: 归档ID
            
        Returns:
            恢复的消息列表，失败返回 None
        """
        try:
            from models.database import ContextArchive
            
            with db_manager.get_session() as session:
                archive = session.query(ContextArchive).filter_by(archive_id=archive_id).first()
                
                if not archive:
                    return None
                
                messages = json.loads(archive.messages)
                logger.info(f"[restore] 从归档 {archive_id} 恢复了 {len(messages)} 条消息")
                return messages
        except Exception as e:
            logger.error(f"[restore] 恢复失败: {e}")
            return None
    
    def list_archives(self, session_id: str = None, limit: int = 10) -> List[Dict]:
        """
        列出归档记录
        
        Args:
            session_id: 会话ID（可选，不指定则列出所有）
            limit: 最大返回数量
            
        Returns:
            归档记录列表
        """
        try:
            from models.database import ContextArchive
            
            with db_manager.get_session() as session:
                query = session.query(ContextArchive)
                
                if session_id:
                    query = query.filter_by(session_id=session_id)
                
                archives = query.order_by(ContextArchive.created_at.desc()).limit(limit).all()
                
                return [
                    {
                        "archive_id": a.archive_id,
                        "session_id": a.session_id,
                        "message_count": a.message_count,
                        "created_at": a.created_at.isoformat() if a.created_at else None
                    }
                    for a in archives
                ]
        except Exception as e:
            logger.error(f"[list_archives] 查询失败: {e}")
            return []


# ==================== 全局实例 ====================

context_compactor = ContextCompactor()


# ==================== 便捷函数 ====================

def micro_compact(messages: List) -> List:
    """
    微观压缩便捷函数
    
    Args:
        messages: 消息列表
        
    Returns:
        压缩后的消息列表
    """
    return context_compactor.micro_compact(messages)


def should_auto_compact(messages: List) -> bool:
    """
    判断是否需要自动压缩
    
    Args:
        messages: 消息列表
        
    Returns:
        是否需要压缩
    """
    return context_compactor.should_auto_compact(messages)


def auto_compact(messages: List, session_id: str, llm_client: Any = None) -> Tuple[List, Optional[str]]:
    """
    自动压缩便捷函数
    
    Args:
        messages: 消息列表
        session_id: 会话ID
        llm_client: LLM 客户端
        
    Returns:
        (压缩后的消息列表, 归档ID)
    """
    return context_compactor.auto_compact(messages, session_id, llm_client)


def manual_compact(session_id: str, llm_client: Any = None) -> Dict[str, Any]:
    """
    手动压缩便捷函数
    
    Args:
        session_id: 会话ID
        llm_client: LLM 客户端
        
    Returns:
        压缩结果
    """
    return context_compactor.manual_compact(session_id, llm_client)


# 导出
__all__ = [
    'ContextCompactor',
    'context_compactor',
    'micro_compact',
    'should_auto_compact',
    'auto_compact',
    'manual_compact',
    'KEEP_RECENT_TOOL_RESULTS',
    'AUTO_COMPACT_THRESHOLD',
    'KEEP_RECENT_MESSAGES'
]
