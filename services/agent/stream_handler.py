"""
流式处理模块

处理Agent的流式输出，包括：
1. Token级流式输出
2. 工具调用检测
3. 确认请求处理
4. 取消处理
"""
import json
import logging
from typing import Dict, Any, Optional, List, Generator

from langchain_core.messages import AIMessage

from services.core.types import ChatResponse, ChatResponseType, ConfirmationInfo

logger = logging.getLogger(__name__)

# 确认请求标记
CONFIRMATION_REQUIRED_MARKER = "__CONFIRMATION_REQUIRED__"


class StreamHandler:
    """流式处理器 - 处理Agent的流式输出"""
    
    def __init__(self):
        """初始化流式处理器"""
        pass
    
    def process_stream_chunk(
        self,
        chunk: tuple,
        full_response: str
    ) -> Optional[Dict[str, Any]]:
        """
        处理流式输出中的一个chunk
        
        Args:
            chunk: (stream_mode, data) 元组
            full_response: 当前累积的响应
            
        Returns:
            处理后的chunk字典，或None（如果不需要输出）
        """
        mode, data = chunk
        
        if mode == "messages":
            return self._process_messages_mode(data, full_response)
        elif mode == "updates":
            return self._process_updates_mode(data)
            
        return None
    
    def _process_messages_mode(
        self,
        data: tuple,
        full_response: str
    ) -> Optional[Dict[str, Any]]:
        """处理messages模式的chunk"""
        if not isinstance(data, tuple) or len(data) < 1:
            return None
            
        message = data[0]
        
        # 处理 AIMessageChunk 的 token 流
        if hasattr(message, "content") and message.content:
            token = str(message.content)
            if token:
                return {
                    "type": ChatResponseType.CONTENT.value,
                    "content": token,
                    "accumulated": full_response + token
                }
                
        return None
    
    def _process_updates_mode(self, data: dict) -> Optional[Dict[str, Any]]:
        """处理updates模式的chunk"""
        if not isinstance(data, dict) or "tools" not in data:
            return None
            
        tool_output = data["tools"].get("messages", [])
        for msg in tool_output:
            if hasattr(msg, "content"):
                # 检查是否需要确认
                confirmation_info = self.extract_confirmation_info(str(msg.content))
                if confirmation_info:
                    return {
                        "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                        **confirmation_info.to_dict()
                    }
                    
        return None
    
    def extract_confirmation_info(self, output: str) -> Optional[ConfirmationInfo]:
        """
        从输出中提取需要确认的命令信息
        
        Args:
            output: Agent输出
            
        Returns:
            确认信息，如果不需要确认则返回None
        """
        try:
            if CONFIRMATION_REQUIRED_MARKER not in output:
                return None
                
            # 提取JSON部分
            start_idx = output.find('{')
            end_idx = output.rfind('}') + 1
            
            if start_idx == -1 or end_idx <= start_idx:
                return None
                
            json_str = output[start_idx:end_idx]
            data = json.loads(json_str)
            
            if data.get("type") != CONFIRMATION_REQUIRED_MARKER:
                return None
                
            return ConfirmationInfo(
                command=data.get("command", ""),
                command_type=data.get("command_type", "execute"),
                operation=data.get("operation", "执行命令"),
                working_dir=data.get("working_dir", ""),
                is_dangerous=data.get("is_dangerous", False),
                reason=data.get("reason", ""),
                message=data.get("message", "需要用户确认")
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[StreamHandler] 解析确认信息失败: {e}")
            return None
    
    def extract_ai_message(self, result: Dict) -> str:
        """
        从Agent结果中提取AI消息
        
        Args:
            result: Agent执行结果
            
        Returns:
            AI消息内容
        """
        if not result or "messages" not in result:
            return ""
            
        # 获取最后一条AI消息
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                return msg.content
                
        return ""
    
    def simulate_stream(
        self,
        content: str,
        chunk_size: int = 10
    ) -> Generator[Dict[str, Any], None, None]:
        """
        模拟流式输出（用于非流式响应）
        
        Args:
            content: 完整内容
            chunk_size: 每个chunk的字符数
            
        Yields:
            流式数据字典
        """
        accumulated = ""
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            accumulated += chunk
            yield {
                "type": ChatResponseType.CONTENT.value,
                "content": chunk,
                "accumulated": accumulated
            }


# 创建全局实例
stream_handler = StreamHandler()

__all__ = ['StreamHandler', 'stream_handler', 'CONFIRMATION_REQUIRED_MARKER']
