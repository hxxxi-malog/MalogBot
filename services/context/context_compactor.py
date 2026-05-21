"""
三层上下文压缩模块

实现三层渐进式上下文压缩策略：
1. 第一层（Journal层）：原始消息实时存储到JSONL，支持完整恢复
2. 第二层（Memory层）：Agent主动存储关键信息，使用Rerank检索
3. 第三层（Summary层）：上下文摘要，减少当前窗口占用

工作流程：
1. 每条消息实时追加到JSONL文件（Journal服务）
2. 当JSONL达到阈值（如80%上下文窗口），触发压缩
3. 压缩时：
   a. 后台线程提取关键信息向量化存储（Memory服务）
   b. LLM生成摘要替换旧消息
   c. 保留最近的几条消息
4. Agent可以主动调用工具存储重要信息到长期记忆
5. 对话时通过RAG检索相关记忆，使用Rerank过滤高相关性结果
"""
import json
import logging
import os
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from config import Config
from services.db_manager import db_manager
from services.context.session_store import session_store
from services.context.conversation_journal import conversation_journal
from services.context.long_term_memory import long_term_memory, MemoryType, DEFAULT_RELEVANCE_THRESHOLD

logger = logging.getLogger(__name__)


# ==================== 配置常量 ====================

# 微观压缩：保留最近的 N 个 tool_result（默认3个，更节省上下文）
KEEP_RECENT_TOOL_RESULTS = int(os.getenv('KEEP_RECENT_TOOL_RESULTS', '3'))

# 压缩后保留的最近消息数
KEEP_RECENT_MESSAGES = int(os.getenv('KEEP_RECENT_MESSAGES', '10'))

# 是否启用长期记忆
ENABLE_LONG_TERM_MEMORY = os.getenv('ENABLE_LONG_TERM_MEMORY', 'true').lower() == 'true'

# 长期记忆注入的token预算
MEMORY_TOKEN_BUDGET = int(os.getenv('MEMORY_TOKEN_BUDGET', '2000'))

# 相关性阈值（Rerank 分数阈值）
MEMORY_RELEVANCE_THRESHOLD = float(os.getenv('MEMORY_RELEVANCE_THRESHOLD', str(DEFAULT_RELEVANCE_THRESHOLD)))


class ContextCompactor:
    """
    三层上下文压缩器
    
    整合三种存储层级：
    - Journal（JSONL）：完整原始对话，可恢复
    - Memory（向量数据库）：Agent主动存储的关键信息，RAG检索+Rerank过滤
    - Summary（当前上下文）：压缩摘要，轻量级
    
    新增功能：
    - 上下文窗口超限检测
    - 紧急压缩机制：保留最近n条消息并生成摘要
    """
    
    def __init__(
        self,
        keep_recent_tools: int = KEEP_RECENT_TOOL_RESULTS,
        keep_recent_messages: int = KEEP_RECENT_MESSAGES,
        enable_long_term_memory: bool = ENABLE_LONG_TERM_MEMORY,
        memory_relevance_threshold: float = MEMORY_RELEVANCE_THRESHOLD,
        emergency_keep_messages: int = None,
        context_warning_threshold: float = None
    ):
        """
        初始化上下文压缩器
        
        Args:
            keep_recent_tools: 微观压缩时保留的最近 tool_result 数量
            keep_recent_messages: 压缩后保留的最近消息数量
            enable_long_term_memory: 是否启用长期记忆功能
            memory_relevance_threshold: 记忆相关性阈值（Rerank分数）
            emergency_keep_messages: 紧急压缩时保留的消息数
            context_warning_threshold: 上下文警告阈值比例
        """
        self.keep_recent_tools = keep_recent_tools
        self.keep_recent_messages = keep_recent_messages
        self.enable_long_term_memory = enable_long_term_memory
        self.memory_relevance_threshold = memory_relevance_threshold
        
        # 紧急压缩配置
        self.emergency_keep_messages = emergency_keep_messages or Config.EMERGENCY_COMPACT_KEEP_MESSAGES
        self.context_warning_threshold = context_warning_threshold or Config.CONTEXT_WARNING_THRESHOLD
        
        # 模型上下文窗口
        self.max_context_tokens = Config.MAX_CONTEXT_TOKENS
        self.compact_threshold = int(self.max_context_tokens * Config.COMPACT_THRESHOLD_RATIO)
    
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
    ):
        """
        追加消息到Journal（JSONL文件）
        
        这是入口方法，每条消息都会实时存储。
        Agent可以通过调用 store_memory 工具主动存储重要信息。
        
        Args:
            session_id: 会话ID
            role: 角色
            content: 消息内容
            tool_call_id: 工具调用ID
            tool_calls: 工具调用列表
            tool_name: 工具名称
            metadata: 额外元数据（如 research_task_id 标记）
        """
        conversation_journal.append_message(
            session_id=session_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            tool_name=tool_name,
            metadata=metadata
        )
    
    # ==================== 上下文窗口超限检测 ====================
    
    def check_context_overflow(self, session_id: str) -> Dict[str, Any]:
        """
        检查上下文窗口是否超限
        
        Args:
            session_id: 会话ID
            
        Returns:
            包含超限信息的字典：
            - is_overflow: 是否超限
            - is_warning: 是否接近超限
            - token_count: 当前token数
            - max_tokens: 最大token数
            - usage_ratio: 使用比例
        """
        token_count = conversation_journal.get_token_count(session_id)
        usage_ratio = token_count / self.max_context_tokens
        
        is_overflow = usage_ratio >= 1.0
        is_warning = usage_ratio >= self.context_warning_threshold
        
        return {
            "is_overflow": is_overflow,
            "is_warning": is_warning,
            "token_count": token_count,
            "max_tokens": self.max_context_tokens,
            "usage_ratio": usage_ratio,
            "tokens_remaining": max(0, self.max_context_tokens - token_count)
        }
    
    def emergency_compact(
        self,
        session_id: str,
        llm_client: Optional[Any] = None,
        keep_messages: int = None
    ) -> Dict[str, Any]:
        """
        紧急压缩：保留最近n条消息并生成摘要
        
        当用户选择继续任务时调用此方法，最大化压缩上下文
        
        Args:
            session_id: 会话ID
            llm_client: LLM客户端（用于生成摘要）
            keep_messages: 保留的消息数（默认使用配置）
            
        Returns:
            压缩结果
        """
        keep_messages = keep_messages or self.emergency_keep_messages
        
        # 读取所有消息
        all_messages = conversation_journal.read_messages(session_id)
        
        if len(all_messages) <= keep_messages:
            return {
                "success": False,
                "message": "消息数量不足，无需紧急压缩",
                "original_count": len(all_messages),
                "compressed_count": len(all_messages)
            }
        
        # 归档当前Journal
        archive_id = conversation_journal.archive_journal(session_id)
        
        # 分离消息
        old_messages = all_messages[:-keep_messages]
        recent_messages = all_messages[-keep_messages:]
        
        # 生成紧急摘要
        summary = ""
        if llm_client and old_messages:
            summary = self._generate_emergency_summary(old_messages, llm_client)
        else:
            summary = self._simple_summary(old_messages)
        
        # 存储关键信息到长期记忆
        if self.enable_long_term_memory and archive_id:
            long_term_memory.process_messages_async(
                messages=all_messages,
                session_id=session_id,
                source_archive_id=archive_id
            )
        
        # 构建压缩后的消息
        compressed = []
        
        # 系统消息（紧急摘要）
        system_content = f"""## 紧急上下文压缩

由于上下文窗口接近限制，系统已执行紧急压缩。

### 历史摘要
{summary}

### 注意事项
- 完整对话已归档（ID: {archive_id}）
- 请专注于当前任务目标，向目标收束
- 禁止发散思维，只执行必需的操作
"""
        compressed.append({
            'role': 'system',
            'content': system_content
        })
        
        # 最近消息
        compressed.extend(recent_messages)
        
        logger.info(f"[emergency_compact] 紧急压缩完成，从 {len(all_messages)} 条压缩到 {len(compressed)} 条")
        
        return {
            "success": True,
            "archive_id": archive_id,
            "original_count": len(all_messages),
            "compressed_count": len(compressed),
            "summary": summary,
            "message": f"紧急压缩完成：保留最近 {keep_messages} 条消息"
        }
    
    def _generate_emergency_summary(self, messages: List[Dict], llm_client: Any) -> str:
        """
        生成紧急摘要
        
        强调向目标收束，提取关键决策和待完成任务
        """
        conversation_text = "\n".join([
            f"{msg.get('role', 'unknown')}: {str(msg.get('content', ''))[:300]}"
            for msg in messages[:30]  # 限制处理数量
        ])
        
        summary_prompt = f"""请为以下对话生成紧急摘要，要求：
1. 极其简洁（不超过200字）
2. 明确核心目标和当前进度
3. 列出已完成的操作
4. 列出待完成的关键步骤
5. 提取关键文件路径和决策

对话内容：
{conversation_text}

摘要："""
        
        try:
            if hasattr(llm_client, 'invoke'):
                response = llm_client.invoke(summary_prompt)
                return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"[emergency_compact] 摘要生成失败: {e}")
        
        return self._simple_summary(messages)
    
    # ==================== 第一层：微观压缩 ====================
    
    def micro_compact(self, messages: List) -> List:
        """
        微观压缩：将旧的 tool result 替换为简洁占位符
        
        在每次 LLM 调用前执行，减少 tool_result 占用的上下文空间。
        格式：[tool: tool_name] - 简洁明了，只保留工具名称。
        
        注意：这只是临时压缩，原始数据仍保留在Journal中。
        
        Args:
            messages: LangChain 消息列表
            
        Returns:
            压缩后的消息列表
        """
        if not messages:
            return messages
        
        import re
        
        # 收集所有 tool_result 位置及其工具名称
        tool_results = []
        
        for i, msg in enumerate(messages):
            # 处理 ToolMessage 类型
            if isinstance(msg, ToolMessage):
                tool_name = self._extract_tool_name(msg, messages, i)
                tool_results.append((i, msg, tool_name))
            # 处理包含 tool_result 的消息（兼容多种格式）
            elif hasattr(msg, 'content') and isinstance(msg.content, list):
                for j, part in enumerate(msg.content):
                    if isinstance(part, dict) and part.get('type') == 'tool_result':
                        tool_name = part.get('name', 'unknown')
                        tool_results.append((i, msg, j, part, tool_name))
        
        if len(tool_results) <= self.keep_recent_tools:
            return messages
        
        # 创建消息的副本（避免修改原始消息）
        result_messages = list(messages)
        
        # 旧结果替换为简洁占位符
        old_results = tool_results[:-self.keep_recent_tools]
        
        for item in old_results:
            if len(item) == 3:
                # ToolMessage 类型 (i, msg, tool_name)
                i, msg, tool_name = item
                tool_call_id = getattr(msg, 'tool_call_id', None)
                placeholder = self._create_tool_placeholder(tool_name, tool_call_id)
                result_messages[i] = placeholder
            elif len(item) == 5:
                # 嵌套在 content 中的 tool_result (i, msg, j, part, tool_name)
                i, msg, j, part, tool_name = item
                part['content'] = f"[tool: {tool_name}]"
        
        logger.info(f"[micro_compact] 压缩了 {len(old_results)} 个旧的 tool_result，保留最近 {self.keep_recent_tools} 个")
        return result_messages
    
    def _extract_tool_name(self, tool_msg: ToolMessage, messages: List, current_index: int) -> str:
        """
        从 ToolMessage 中提取工具名称
        
        优先级：
        1. ToolMessage.name 属性
        2. 从前面的 AIMessage 中查找对应的 tool_calls
        3. 从 content 中解析
        
        Args:
            tool_msg: ToolMessage 实例
            messages: 消息列表
            current_index: 当前消息索引
            
        Returns:
            工具名称
        """
        import re
        
        # 1. 检查 ToolMessage.name 属性
        tool_name = getattr(tool_msg, 'name', None)
        if tool_name:
            return tool_name
        
        # 2. 从前面的 AIMessage 中查找对应的 tool_calls
        tool_call_id = getattr(tool_msg, 'tool_call_id', None)
        if tool_call_id:
            # 向前搜索 AIMessage
            for j in range(current_index - 1, max(-1, current_index - 10), -1):
                prev_msg = messages[j]
                if isinstance(prev_msg, AIMessage) and hasattr(prev_msg, 'tool_calls'):
                    for tc in (prev_msg.tool_calls or []):
                        if tc.get('id') == tool_call_id:
                            return tc.get('name', 'tool')
        
        # 3. 从 content 中解析
        content_str = str(tool_msg.content)
        
        # 尝试匹配常见模式
        patterns = [
            r'tool_name[:\s]+([\w_]+)',
            r'工具[：:]\s*([\w_]+)',
            r'\[([\w_]+)\]',
        ]
        for pattern in patterns:
            match = re.search(pattern, content_str, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return 'tool'
    
    def _create_tool_placeholder(self, tool_name: str, tool_call_id: str = None) -> ToolMessage:
        """
        创建简洁的工具调用占位符
        
        格式：[tool: tool_name]
        这种简洁格式让模型知道曾经调用过什么工具，但不占用过多上下文。
        
        Args:
            tool_name: 工具名称
            tool_call_id: 工具调用ID
            
        Returns:
            ToolMessage 占位符
        """
        placeholder_content = f"[tool: {tool_name}]"
        return ToolMessage(content=placeholder_content, tool_call_id=tool_call_id or "compressed")
    
    # ==================== 第二层：自动压缩（核心） ====================
    
    def should_auto_compact(self, session_id: str) -> bool:
        """判断是否需要触发自动压缩"""
        return conversation_journal.should_compact(session_id)
    
    def get_context_stats(self, session_id: str) -> Dict[str, Any]:
        """获取上下文统计信息"""
        return conversation_journal.get_compaction_info(session_id)
    
    def auto_compact(
        self,
        session_id: str,
        llm_client: Optional[Any] = None,
        current_query: str = ""
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        自动压缩：当token达到阈值时触发
        
        完整流程：
        1. 从Journal读取所有消息
        2. 后台提取关键信息存储到长期记忆
        3. LLM生成摘要
        4. 保留最近消息 + 摘要 + 长期记忆上下文
        
        Args:
            session_id: 会话ID
            llm_client: LLM 客户端（用于生成摘要）
            current_query: 当前用户查询（用于检索相关记忆）
            
        Returns:
            (压缩后的消息字典列表, 归档ID)
        """
        # 1. 从Journal读取所有消息
        all_messages = conversation_journal.read_messages(session_id)
        
        if len(all_messages) <= self.keep_recent_messages:
            return all_messages, None
        
        # 2. 归档当前Journal
        archive_id = conversation_journal.archive_journal(session_id)
        
        # 3. 后台提取关键信息存储到长期记忆
        if self.enable_long_term_memory and archive_id:
            long_term_memory.process_messages_async(
                messages=all_messages,
                session_id=session_id,
                source_archive_id=archive_id
            )
        
        # 4. 分离旧消息和最近消息
        old_messages = all_messages[:-self.keep_recent_messages]
        recent_messages = all_messages[-self.keep_recent_messages:]
        
        # 5. LLM生成摘要
        summary = ""
        if llm_client and old_messages:
            summary = self._generate_summary_with_llm(old_messages, llm_client)
        else:
            summary = self._simple_summary(old_messages)
        
        # 6. 检索相关长期记忆
        memory_context = ""
        if self.enable_long_term_memory and current_query:
            memory_context = long_term_memory.get_memories_for_context(
                query=current_query,
                session_id=session_id,
                max_tokens=MEMORY_TOKEN_BUDGET,
                relevance_threshold=self.memory_relevance_threshold
            )
        
        # 7. 构建压缩后的消息
        compressed = []
        
        # 系统消息（摘要 + 长期记忆）
        system_content = self._build_compacted_system_message(
            summary=summary,
            memory_context=memory_context,
            archive_id=archive_id
        )
        compressed.append({
            'role': 'system',
            'content': system_content
        })
        
        # 最近消息
        compressed.extend(recent_messages)
        
        logger.info(f"[auto_compact] 压缩完成，归档ID: {archive_id}")
        return compressed, archive_id
    
    def _build_compacted_system_message(
        self,
        summary: str,
        memory_context: str,
        archive_id: str
    ) -> str:
        """构建压缩后的系统消息"""
        parts = ["## 对话历史压缩摘要\n"]
        
        if summary:
            parts.append(summary)
        
        if memory_context:
            parts.append("\n" + memory_context)
        
        parts.append(f"\n---\n注：完整对话已归档，归档ID: {archive_id}")
        parts.append("如需查看完整历史，可使用 compact_context 工具恢复。")
        
        return '\n'.join(parts)
    
    def _generate_summary_with_llm(self, messages: List[Dict], llm_client: Any) -> str:
        """使用 LLM 生成对话摘要"""
        conversation_text = "\n".join([
            f"{msg.get('role', 'unknown')}: {str(msg.get('content', ''))[:500]}"
            for msg in messages[:20]
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
    
    def _simple_summary(self, messages: List[Dict]) -> str:
        """简单摘要方法（不依赖 LLM）"""
        user_messages = [msg for msg in messages if msg.get('role') == 'user']
        assistant_messages = [msg for msg in messages if msg.get('role') == 'assistant']
        tool_messages = [msg for msg in messages if msg.get('role') == 'tool']
        
        # 提取关键信息
        files_mentioned = set()
        for msg in messages:
            content = str(msg.get('content', ''))
            import re
            file_patterns = [
                r'/Users/[\w/]+\.\w+',
                r'/home/[\w/]+\.\w+',
                r'C:\\[\w\\]+\.\w+',
            ]
            for pattern in file_patterns:
                files_mentioned.update(re.findall(pattern, content))
        
        summary_parts = [
            f"对话包含 {len(user_messages)} 个用户消息, {len(assistant_messages)} 个助手回复, {len(tool_messages)} 个工具调用。",
        ]
        
        if files_mentioned:
            summary_parts.append(f"涉及的文件: {', '.join(list(files_mentioned)[:5])}")
        
        if user_messages:
            first_user_msg = str(user_messages[0].get('content', ''))[:100]
            summary_parts.append(f"用户初始请求: {first_user_msg}...")
        
        return "\n".join(summary_parts)
    
    # ==================== 第三层：手动压缩 ====================
    
    def manual_compact(
        self,
        session_id: str,
        llm_client: Optional[Any] = None,
        compact_all: bool = False,
        current_query: str = ""
    ) -> Dict[str, Any]:
        """手动压缩：通过工具按需触发"""
        journal_info = conversation_journal.get_compaction_info(session_id)
        
        if journal_info['message_count'] == 0:
            return {
                "success": False,
                "message": "没有可压缩的对话历史"
            }
        
        compressed, archive_id = self.auto_compact(
            session_id, llm_client, current_query
        )
        
        if not compressed:
            return {
                "success": False,
                "message": "压缩失败"
            }
        
        session_store.replace_messages(session_id, compressed)
        
        return {
            "success": True,
            "archive_id": archive_id,
            "original_count": journal_info['message_count'],
            "compressed_count": len(compressed),
            "message": f"成功压缩 {journal_info['message_count']} 条消息为 {len(compressed)} 条"
        }
    
    # ==================== 上下文注入 ====================
    
    def inject_context_for_chat(
        self,
        session_id: str,
        user_query: str
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        为对话准备上下文
        
        整合三层数据：
        1. 从Journal读取消息（控制token预算）
        2. 注入相关长期记忆（RAG检索 + Rerank过滤）
        3. 返回统计信息
        
        Args:
            session_id: 会话ID
            user_query: 用户查询
            
        Returns:
            (消息列表, 统计信息)
        """
        stats = {
            'journal_messages': 0,
            'journal_tokens': 0,
            'memory_injected': False,
            'memory_count': 0,
            'should_compact': False
        }
        
        # 1. 检查是否需要压缩
        stats['should_compact'] = self.should_auto_compact(session_id)
        
        # 2. 从Journal读取消息
        messages, tokens = conversation_journal.read_messages_for_context(session_id)
        stats['journal_messages'] = len(messages)
        stats['journal_tokens'] = tokens
        
        # 3. 注入长期记忆（使用 Rerank 过滤）
        if self.enable_long_term_memory and user_query:
            memory_context = long_term_memory.get_memories_for_context(
                query=user_query,
                session_id=session_id,
                max_tokens=MEMORY_TOKEN_BUDGET,
                relevance_threshold=self.memory_relevance_threshold
            )
            
            if memory_context:
                messages.insert(0, {
                    'role': 'system',
                    'content': memory_context
                })
                stats['memory_injected'] = True
                stats['memory_count'] = memory_context.count('- [')
        
        return messages, stats
    
    # ==================== 恢复功能 ====================
    
    def restore_from_archive(self, archive_id: str) -> Optional[List[Dict]]:
        """从归档恢复对话历史"""
        return conversation_journal.get_archive_messages(archive_id)
    
    def list_archives(self, session_id: str, limit: int = 10) -> List[Dict]:
        """列出归档记录"""
        return conversation_journal.list_archives(session_id)[:limit]
    
    # ==================== 工具方法 ====================
    
    def _message_to_dict(self, msg: Any) -> Dict:
        """将 LangChain 消息转换为字典"""
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
    
    def _dict_to_messages(self, message_dicts: List[Dict]) -> List:
        """将字典列表转换为 LangChain 消息列表"""
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
    
    def clear_session(self, session_id: str):
        """清理会话资源"""
        conversation_journal.cleanup_session(session_id)


# ==================== 全局实例 ====================

context_compactor = ContextCompactor()


# ==================== 便捷函数 ====================

def micro_compact(messages: List) -> List:
    """微观压缩便捷函数"""
    return context_compactor.micro_compact(messages)


def should_auto_compact(session_id: str) -> bool:
    """判断是否需要自动压缩"""
    return context_compactor.should_auto_compact(session_id)


def auto_compact(
    session_id: str,
    llm_client: Any = None,
    current_query: str = ""
) -> Tuple[List[Dict], Optional[str]]:
    """自动压缩便捷函数"""
    return context_compactor.auto_compact(session_id, llm_client, current_query)


def manual_compact(
    session_id: str,
    llm_client: Any = None
) -> Dict[str, Any]:
    """手动压缩便捷函数"""
    return context_compactor.manual_compact(session_id, llm_client)


def check_context_overflow(session_id: str) -> Dict[str, Any]:
    """检查上下文窗口是否超限"""
    return context_compactor.check_context_overflow(session_id)


def emergency_compact(
    session_id: str,
    llm_client: Any = None,
    keep_messages: int = None
) -> Dict[str, Any]:
    """紧急压缩便捷函数"""
    return context_compactor.emergency_compact(session_id, llm_client, keep_messages)


# 导出
__all__ = [
    'ContextCompactor',
    'context_compactor',
    'micro_compact',
    'should_auto_compact',
    'auto_compact',
    'manual_compact',
    'check_context_overflow',
    'emergency_compact',
    'KEEP_RECENT_TOOL_RESULTS',
    'KEEP_RECENT_MESSAGES',
    'ENABLE_LONG_TERM_MEMORY',
    'MEMORY_TOKEN_BUDGET',
    'MEMORY_RELEVANCE_THRESHOLD'
]
