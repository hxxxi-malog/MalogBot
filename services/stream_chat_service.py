"""
流式对话服务模块

实现流式输出的Agent对话功能
"""
import json
from typing import Generator, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from agent.llm import get_llm
from agent.tools.bash import execute_bash, execute_confirmed_bash, DANGEROUS_COMMAND_MARKER


class StreamChatService:
    """流式对话服务类"""
    
    def __init__(self):
        """初始化流式对话服务"""
        self.llm = get_llm(streaming=True)
        self.tools = [execute_bash]
        
        # 创建支持工具调用的Agent
        self.agent = create_react_agent(self.llm, self.tools)
        
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
            包含流式数据的字典
        """
        # 获取或创建会话历史
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        
        chat_history = self._sessions[session_id]
        
        try:
            # 构建消息列表
            messages = []
            
            # 添加历史消息
            for msg in chat_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
            
            # 添加当前用户消息
            messages.append(HumanMessage(content=user_input))
            
            # 使用Agent处理(支持工具调用)
            # 注意: langgraph的agent会自动处理工具调用
            result = self.agent.invoke({"messages": messages})
            
            # 提取最终输出
            full_response = ""
            if result and "messages" in result:
                # 获取最后一条AI消息
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        full_response = msg.content
                        break
            
            # 流式输出结果(模拟流式效果)
            # 由于agent.invoke不是流式的,我们分段输出
            chunk_size = 20  # 每次输出的字符数
            accumulated = ""
            
            for i in range(0, len(full_response), chunk_size):
                chunk = full_response[i:i+chunk_size]
                accumulated += chunk
                yield {
                    "type": "content",
                    "content": chunk,
                    "accumulated": accumulated
                }
            
            # 检查是否包含危险命令标记
            if DANGEROUS_COMMAND_MARKER in full_response:
                try:
                    # 提取JSON部分
                    start_idx = full_response.find('{')
                    end_idx = full_response.rfind('}') + 1
                    
                    if start_idx != -1 and end_idx > start_idx:
                        json_str = full_response[start_idx:end_idx]
                        data = json.loads(json_str)
                        
                        if data.get("type") == DANGEROUS_COMMAND_MARKER:
                            yield {
                                "type": "dangerous_command",
                                "command": data.get("command"),
                                "reason": data.get("reason"),
                                "message": data.get("message")
                            }
                            return
                except (json.JSONDecodeError, KeyError):
                    pass
            
            # 保存对话历史
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": full_response})
            
            # 发送完成信号
            yield {
                "type": "done",
                "content": full_response
            }
            
        except Exception as e:
            yield {
                "type": "error",
                "content": f"执行出错: {str(e)}"
            }
    
    def confirm_dangerous_command(
        self, 
        command: str, 
        session_id: str = "default"
    ) -> str:
        """
        执行用户确认的危险命令
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            
        Returns:
            命令执行结果
        """
        return execute_confirmed_bash(command)
    
    def get_history(self, session_id: str = "default") -> list:
        """获取对话历史"""
        return self._sessions.get(session_id, [])
    
    def clear_history(self, session_id: str = "default") -> None:
        """清空对话历史"""
        if session_id in self._sessions:
            del self._sessions[session_id]


# 创建全局实例
stream_chat_service = StreamChatService()


# 导出
__all__ = ['StreamChatService', 'stream_chat_service']
