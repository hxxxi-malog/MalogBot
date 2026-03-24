"""
流式对话服务模块

专门用于处理deepseek-reasoner模型的流式思考过程
注意: deepseek-reasoner不支持Function Call,因此需要单独处理
"""
import json
from typing import Generator, Dict, Any, Optional
from openai import OpenAI

from config import Config


class StreamService:
    """流式对话服务类"""
    
    def __init__(self):
        """初始化流式服务"""
        self.client = OpenAI(
            api_key=Config.DEEPSEEK_API_KEY,
            base_url=Config.DEEPSEEK_BASE_URL
        )
        self.model = Config.MODEL_NAME
        
        # MVP阶段：使用内存存储对话历史
        # key: session_id, value: 消息列表
        self._sessions: Dict[str, list] = {}
    
    def chat_stream(
        self, 
        user_input: str, 
        session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Yields:
            包含思考过程和回复内容的字典
        """
        # 获取或创建会话历史
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        
        # 构建消息列表
        messages = self._sessions[session_id].copy()
        messages.append({"role": "user", "content": user_input})
        
        try:
            # 发送流式请求
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )
            
            reasoning_content = ""
            content = ""
            
            # 流式处理响应
            for chunk in response:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # 检查是否有思考过程
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    reasoning_content += delta.reasoning_content
                    yield {
                        "type": "reasoning",
                        "content": delta.reasoning_content,
                        "accumulated": reasoning_content
                    }
                
                # 检查是否有最终回复
                if hasattr(delta, 'content') and delta.content:
                    content += delta.content
                    yield {
                        "type": "content",
                        "content": delta.content,
                        "accumulated": content
                    }
            
            # 流结束,保存对话历史
            self._sessions[session_id].append({"role": "user", "content": user_input})
            self._sessions[session_id].append({"role": "assistant", "content": content})
            
            # 发送完成信号
            yield {
                "type": "done",
                "reasoning_content": reasoning_content,
                "content": content
            }
            
        except Exception as e:
            yield {
                "type": "error",
                "content": f"执行出错: {str(e)}"
            }
    
    def get_history(self, session_id: str = "default") -> list:
        """
        获取对话历史
        
        Args:
            session_id: 会话ID
            
        Returns:
            消息历史列表
        """
        return self._sessions.get(session_id, [])
    
    def clear_history(self, session_id: str = "default") -> None:
        """
        清空对话历史
        
        Args:
            session_id: 会话ID
        """
        if session_id in self._sessions:
            del self._sessions[session_id]


# 创建全局实例
stream_service = StreamService()


# 导出
__all__ = ['StreamService', 'stream_service']
