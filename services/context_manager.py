"""
上下文管理模块

提供对话历史的压缩和摘要功能，防止上下文过长导致：
1. Token消耗过大
2. Agent重复执行相同任务
3. 对话质量下降
"""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime


class ContextManager:
    """上下文管理器"""
    
    def __init__(self, max_history_length: int = 50, max_summary_length: int = 10):
        """
        初始化上下文管理器
        
        Args:
            max_history_length: 最大历史消息数量
            max_summary_length: 触发摘要的历史消息阈值
        """
        self.max_history_length = max_history_length
        self.max_summary_length = max_summary_length
    
    def should_compress(self, chat_history: List[Dict]) -> bool:
        """
        判断是否需要压缩上下文
        
        Args:
            chat_history: 对话历史
            
        Returns:
            是否需要压缩
        """
        return len(chat_history) > self.max_history_length
    
    def compress_history(
        self, 
        chat_history: List[Dict],
        llm_client: Optional[Any] = None
    ) -> List[Dict]:
        """
        压缩对话历史
        
        策略：
        1. 保留最近的N条消息
        2. 对早期消息生成摘要
        3. 保留关键信息（文件路径、任务状态等）
        
        Args:
            chat_history: 对话历史
            llm_client: LLM客户端（用于生成摘要）
            
        Returns:
            压缩后的对话历史
        """
        if len(chat_history) <= self.max_summary_length:
            return chat_history
        
        # 保留最近的N条消息
        recent_messages = chat_history[-self.max_summary_length:]
        old_messages = chat_history[:-self.max_summary_length]
        
        # 提取关键信息
        key_info = self._extract_key_information(old_messages)
        
        # 生成摘要（如果有LLM客户端）
        summary = ""
        if llm_client and old_messages:
            summary = self._generate_summary(old_messages, llm_client)
        
        # 构建压缩后的历史
        compressed = []
        
        # 添加摘要作为系统消息（如果有）
        if summary or key_info:
            summary_content = "## 对话历史摘要\n\n"
            if summary:
                summary_content += f"{summary}\n\n"
            if key_info:
                summary_content += "## 关键信息\n"
                summary_content += self._format_key_info(key_info)
            
            compressed.append({
                "role": "system",
                "content": summary_content,
                "timestamp": datetime.now().isoformat()
            })
        
        # 添加最近的消息
        compressed.extend(recent_messages)
        
        return compressed
    
    def _extract_key_information(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        从消息中提取关键信息
        
        Args:
            messages: 消息列表
            
        Returns:
            关键信息字典
        """
        key_info = {
            "files_accessed": set(),      # 访问过的文件
            "commands_executed": set(),   # 执行过的命令
            "tasks_completed": [],        # 已完成的任务
            "current_state": {}           # 当前状态
        }
        
        for msg in messages:
            content = msg.get("content", "")
            
            # 提取文件路径
            import re
            # 匹配常见文件路径模式
            file_patterns = [
                r'/Users/[\w/]+\.\w+',     # macOS路径
                r'/home/[\w/]+\.\w+',      # Linux路径
                r'C:\\[\w\\]+\.\w+',       # Windows路径
            ]
            
            for pattern in file_patterns:
                matches = re.findall(pattern, content)
                key_info["files_accessed"].update(matches)
        
        # 转换set为list以便JSON序列化
        key_info["files_accessed"] = list(key_info["files_accessed"])
        key_info["commands_executed"] = list(key_info["commands_executed"])
        
        return key_info
    
    def _format_key_info(self, key_info: Dict[str, Any]) -> str:
        """
        格式化关键信息
        
        Args:
            key_info: 关键信息字典
            
        Returns:
            格式化后的字符串
        """
        lines = []
        
        if key_info.get("files_accessed"):
            lines.append("### 访问过的文件:")
            for file_path in key_info["files_accessed"]:
                lines.append(f"- {file_path}")
        
        if key_info.get("tasks_completed"):
            lines.append("\n### 已完成的任务:")
            for task in key_info["tasks_completed"]:
                lines.append(f"- {task}")
        
        return "\n".join(lines)
    
    def _generate_summary(self, messages: List[Dict], llm_client: Any) -> str:
        """
        使用LLM生成对话摘要
        
        Args:
            messages: 消息列表
            llm_client: LLM客户端
            
        Returns:
            摘要文本
        """
        # 构建摘要请求
        conversation_text = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" 
            for msg in messages
        ])
        
        summary_prompt = f"""请总结以下对话的关键内容，要求：
1. 简洁明了（不超过200字）
2. 保留重要的文件路径和操作
3. 说明已完成和未完成的任务

对话内容：
{conversation_text}

摘要："""
        
        try:
            # 调用LLM生成摘要
            # 注意：这里需要确保llm_client有正确的接口
            if hasattr(llm_client, 'invoke'):
                response = llm_client.invoke(summary_prompt)
                return response.content if hasattr(response, 'content') else str(response)
            else:
                # 如果没有LLM客户端，使用简单的截断策略
                return self._simple_summary(messages)
        except Exception as e:
            # 出错时使用简单摘要
            return self._simple_summary(messages)
    
    def _simple_summary(self, messages: List[Dict]) -> str:
        """
        简单摘要方法（不依赖LLM）
        
        Args:
            messages: 消息列表
            
        Returns:
            摘要文本
        """
        # 提取用户的主要请求
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        
        if user_messages:
            # 取第一条和最后一条用户消息
            if len(user_messages) > 2:
                return f"对话包含了{len(user_messages)}个用户请求，从'{user_messages[0]['content'][:50]}...'开始"
            else:
                return f"用户请求: {user_messages[0]['content'][:100]}"
        
        return f"对话历史包含{len(messages)}条消息"
    
    def extract_task_state(self, chat_history: List[Dict]) -> Dict[str, Any]:
        """
        提取任务状态
        
        分析对话历史，提取当前任务的状态：
        - 已完成的步骤
        - 正在进行的步骤
        - 待完成的步骤
        
        Args:
            chat_history: 对话历史
            
        Returns:
            任务状态字典
        """
        task_state = {
            "completed_steps": [],
            "current_step": None,
            "pending_steps": [],
            "context": {}
        }
        
        # 简单的状态提取逻辑
        # 可以根据实际需求扩展
        
        return task_state


# 创建全局实例
context_manager = ContextManager()


# 导出
__all__ = ['ContextManager', 'context_manager']
