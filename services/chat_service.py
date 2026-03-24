"""
对话服务模块

统一的对话服务，支持：
1. 流式输出（token-by-token）
2. 工具调用（Bash执行）
3. 命令确认机制（所有执行类命令需要用户确认）
4. 会话历史管理
"""
import json
from typing import Generator, Dict, Any, Optional, List

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from agent.llm import get_llm
from agent.tools.bash import (
    execute_bash,
    execute_confirmed_bash,
    execute_cancelled_bash,
    CONFIRMATION_REQUIRED_MARKER
)


class ChatService:
    """统一的对话服务类"""

    def __init__(self):
        """初始化对话服务"""
        # 使用流式LLM
        self.llm = get_llm(streaming=True)
        self.tools = [execute_bash]

        # 创建支持工具调用的Agent
        self.agent = create_react_agent(self.llm, self.tools)

        # MVP阶段：使用内存存储对话历史
        # key: session_id, value: 消息列表
        self._sessions: Dict[str, List[Dict]] = {}

    def chat(
            self,
            user_input: str,
            session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        非流式执行对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Returns:
            包含输出和状态的字典：
            - type: "response" | "confirmation_required" | "error"
            - output: 助手回复（正常情况）
            - command: 需要确认的命令
            - operation: 操作类型
            - working_dir: 执行路径
        """
        # 获取或创建会话历史
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        chat_history = self._sessions[session_id]

        try:
            # 构建消息列表
            messages = self._build_messages(chat_history, user_input)

            # 使用Agent处理
            result = self.agent.invoke({"messages": messages})

            # 提取最终输出
            output = self._extract_ai_message(result)

            # 检查是否包含需要确认的命令标记
            confirmation_info = self._extract_confirmation_required(output)

            if confirmation_info:
                return {
                    "type": "confirmation_required",
                    "command": confirmation_info["command"],
                    "command_type": confirmation_info.get("command_type", "execute"),
                    "operation": confirmation_info.get("operation", "执行命令"),
                    "working_dir": confirmation_info.get("working_dir", ""),
                    "is_dangerous": confirmation_info.get("is_dangerous", False),
                    "reason": confirmation_info.get("reason", ""),
                    "message": confirmation_info.get("message", "需要用户确认"),
                    "session_id": session_id
                }

            # 保存对话历史
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": output})

            return {
                "type": "response",
                "output": output,
                "session_id": session_id
            }

        except Exception as e:
            return {
                "type": "error",
                "output": f"执行出错: {str(e)}",
                "session_id": session_id
            }

    def chat_stream(
            self,
            user_input: str,
            session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行对话（token-by-token）
        
        使用多种 stream_mode 组合实现流式输出：
        - "messages": 获取 token 级别的流式输出
        - "updates": 获取节点级别的更新
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Yields:
            包含流式数据的字典：
            - type: "content" | "tool_start" | "tool_end" | "confirmation_required" | "done" | "error"
            - content: 当前token内容
            - accumulated: 累积内容
        """
        # 获取或创建会话历史
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        chat_history = self._sessions[session_id]

        try:
            # 构建消息列表
            messages = self._build_messages(chat_history, user_input)

            # 收集完整响应
            full_response = ""

            # 使用多种 stream_mode
            for chunk in self.agent.stream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"]
            ):
                # chunk 是 (stream_mode, data) 元组
                if isinstance(chunk, tuple):
                    mode, data = chunk
                else:
                    continue

                if mode == "messages":
                    # messages 模式: (AIMessageChunk, metadata)
                    if isinstance(data, tuple) and len(data) >= 1:
                        message = data[0]

                        # 处理 AIMessageChunk 的 token 流
                        if hasattr(message, "content") and message.content:
                            token = str(message.content)
                            if token:
                                full_response += token
                                yield {
                                    "type": "content",
                                    "content": token,
                                    "accumulated": full_response
                                }

                elif mode == "updates":
                    # updates 模式: {node_name: node_output}
                    if isinstance(data, dict):
                        # 检查工具节点输出
                        if "tools" in data:
                            tool_output = data["tools"].get("messages", [])
                            for msg in tool_output:
                                if hasattr(msg, "content"):
                                    # 检查是否需要确认
                                    confirmation_info = self._extract_confirmation_required(str(msg.content))
                                    if confirmation_info:
                                        yield {
                                            "type": "confirmation_required",
                                            "command": confirmation_info["command"],
                                            "command_type": confirmation_info.get("command_type", "execute"),
                                            "operation": confirmation_info.get("operation", "执行命令"),
                                            "working_dir": confirmation_info.get("working_dir", ""),
                                            "is_dangerous": confirmation_info.get("is_dangerous", False),
                                            "reason": confirmation_info.get("reason", ""),
                                            "message": confirmation_info.get("message", "需要用户确认")
                                        }
                                        return

            # 如果没有获取到内容，使用 invoke 作为备用
            if not full_response:
                result = self.agent.invoke({"messages": messages})
                full_response = self._extract_ai_message(result)

                # 检查是否需要确认
                confirmation_info = self._extract_confirmation_required(full_response)
                if confirmation_info:
                    yield {
                        "type": "confirmation_required",
                        "command": confirmation_info["command"],
                        "command_type": confirmation_info.get("command_type", "execute"),
                        "operation": confirmation_info.get("operation", "执行命令"),
                        "working_dir": confirmation_info.get("working_dir", ""),
                        "is_dangerous": confirmation_info.get("is_dangerous", False),
                        "reason": confirmation_info.get("reason", ""),
                        "message": confirmation_info.get("message", "需要用户确认")
                    }
                    return

                # 模拟流式输出
                chunk_size = 10
                accumulated = ""
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    accumulated += chunk
                    yield {
                        "type": "content",
                        "content": chunk,
                        "accumulated": accumulated
                    }
            else:
                # 最终检查是否需要确认
                confirmation_info = self._extract_confirmation_required(full_response)
                if confirmation_info:
                    yield {
                        "type": "confirmation_required",
                        "command": confirmation_info["command"],
                        "command_type": confirmation_info.get("command_type", "execute"),
                        "operation": confirmation_info.get("operation", "执行命令"),
                        "working_dir": confirmation_info.get("working_dir", ""),
                        "is_dangerous": confirmation_info.get("is_dangerous", False),
                        "reason": confirmation_info.get("reason", ""),
                        "message": confirmation_info.get("message", "需要用户确认")
                    }
                    return

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

    def confirm_command(
            self,
            command: str,
            session_id: str = "default",
            user_message: str = ""
    ) -> Dict[str, Any]:
        """
        执行用户确认的命令
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息（用于继续对话）
            
        Returns:
            执行结果
        """
        try:
            # 直接执行命令
            result = execute_confirmed_bash(command)

            # 如果有用户消息，继续对话
            if user_message:
                chat_history = self._sessions.get(session_id, [])
                # 将工具执行结果添加到历史
                chat_history.append({
                    "role": "tool",
                    "content": f"命令已执行: {command}\n结果: {result}"
                })

                # 继续Agent处理
                messages = self._build_messages(chat_history, user_message)
                agent_result = self.agent.invoke({"messages": messages})
                output = self._extract_ai_message(agent_result)

                # 更新历史
                chat_history.append({"role": "assistant", "content": output})

                return {
                    "type": "response",
                    "output": output,
                    "session_id": session_id
                }

            return {
                "type": "response",
                "output": f"命令已执行:\n```\n{command}\n```\n\n结果:\n{result}",
                "session_id": session_id
            }

        except Exception as e:
            return {
                "type": "error",
                "output": f"执行命令失败: {str(e)}",
                "session_id": session_id
            }

    def confirm_command_stream(
            self,
            command: str,
            session_id: str = "default",
            user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行用户确认的命令
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息（用于继续对话）
            
        Yields:
            流式数据字典
        """
        try:
            # 直接执行命令
            result = execute_confirmed_bash(command)

            yield {
                "type": "tool_result",
                "content": f"✅ 命令已执行: `{command}`\n\n**结果:**\n```\n{result}\n```"
            }

            # 如果有用户消息，继续对话
            if user_message:
                chat_history = self._sessions.get(session_id, [])
                
                # 构建上下文消息，告诉 LLM 命令执行结果
                exec_context = f"命令已执行成功。\n执行的命令: {command}\n执行结果: {result}\n\n请根据执行结果继续处理用户的请求。"
                
                messages = self._build_messages_for_cancel(chat_history, exec_context)
                full_response = ""

                for chunk in self.agent.stream(
                        {"messages": messages},
                        stream_mode=["messages", "updates"]
                ):
                    if isinstance(chunk, tuple):
                        mode, data = chunk

                        if mode == "messages":
                            if isinstance(data, tuple) and len(data) >= 1:
                                message = data[0]
                                if hasattr(message, "content") and message.content:
                                    token = str(message.content)
                                    if token:
                                        full_response += token
                                        yield {
                                            "type": "content",
                                            "content": token,
                                            "accumulated": full_response
                                        }

                if full_response:
                    # 保存原始用户消息和响应
                    chat_history.append({"role": "user", "content": user_message})
                    chat_history.append({"role": "assistant", "content": full_response})

                yield {
                    "type": "done",
                    "content": full_response
                }
            else:
                yield {
                    "type": "done",
                    "content": f"命令已执行:\n```\n{command}\n```\n\n结果:\n{result}"
                }

        except Exception as e:
            yield {
                "type": "error",
                "content": f"执行命令失败: {str(e)}"
            }

    def cancel_command_stream(
            self,
            command: str,
            session_id: str = "default",
            user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        处理用户取消的命令，返回上下文给 LLM 继续处理
        
        Args:
            command: 用户取消的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Yields:
            流式数据字典
        """
        try:
            chat_history = self._sessions.get(session_id, [])

            # 如果有用户消息，让 LLM 继续处理
            # 注意：不再使用 tool 角色消息，而是构建一个新的用户消息告诉 LLM 取消情况
            if user_message:
                # 构建新的用户消息，告诉 LLM 用户取消了命令
                cancel_context = f"用户取消了之前请求执行的命令。\n取消的命令: {command}\n\n请根据这个情况，给用户提供其他建议或替代方案。"
                
                messages = self._build_messages_for_cancel(chat_history, cancel_context)
                full_response = ""

                for chunk in self.agent.stream(
                        {"messages": messages},
                        stream_mode=["messages", "updates"]
                ):
                    if isinstance(chunk, tuple):
                        mode, data = chunk

                        if mode == "messages":
                            if isinstance(data, tuple) and len(data) >= 1:
                                message = data[0]
                                if hasattr(message, "content") and message.content:
                                    token = str(message.content)
                                    if token:
                                        full_response += token
                                        yield {
                                            "type": "content",
                                            "content": token,
                                            "accumulated": full_response
                                        }

                if full_response:
                    # 保存原始用户消息和取消后的响应
                    chat_history.append({"role": "user", "content": user_message})
                    chat_history.append({"role": "assistant", "content": full_response})

                yield {
                    "type": "done",
                    "content": full_response
                }
            else:
                # 没有原始消息，返回取消信息
                yield {
                    "type": "done",
                    "content": "❌ 用户已取消命令执行。"
                }

        except Exception as e:
            yield {
                "type": "error",
                "content": f"处理取消失败: {str(e)}"
            }

    def get_history(self, session_id: str = "default") -> List[Dict]:
        """获取对话历史"""
        return self._sessions.get(session_id, [])

    def clear_history(self, session_id: str = "default") -> None:
        """清空对话历史"""
        if session_id in self._sessions:
            del self._sessions[session_id]

    # ==================== 私有方法 ====================

    def _build_messages(
            self,
            chat_history: List[Dict],
            user_input: str
    ) -> List:
        """
        构建LangChain消息列表
        
        Args:
            chat_history: 对话历史
            user_input: 当前用户输入
            
        Returns:
            LangChain消息对象列表
        """
        messages = []

        # 添加历史消息
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
            # 注意：不再处理 tool 角色，因为它需要前置的 tool_calls

        # 添加当前用户消息
        messages.append(HumanMessage(content=user_input))

        return messages

    def _build_messages_for_cancel(
            self,
            chat_history: List[Dict],
            cancel_context: str
    ) -> List:
        """
        为取消场景构建消息列表
        
        不包含当前用户消息（因为还没保存到历史），直接使用取消上下文
        
        Args:
            chat_history: 对话历史
            cancel_context: 取消上下文消息
            
        Returns:
            LangChain消息对象列表
        """
        messages = []

        # 添加历史消息（只包含 user 和 assistant）
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))

        # 添加取消上下文作为新的用户消息
        messages.append(HumanMessage(content=cancel_context))

        return messages

    def _extract_ai_message(self, result: Dict) -> str:
        """
        从Agent结果中提取AI消息
        
        Args:
            result: Agent执行结果
            
        Returns:
            AI消息内容
        """
        if result and "messages" in result:
            # 获取最后一条AI消息
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    return msg.content
        return ""

    def _extract_confirmation_required(self, output: str) -> Optional[Dict]:
        """
        从输出中提取需要确认的命令信息
        
        Args:
            output: Agent输出
            
        Returns:
            如果包含需要确认的命令标记，返回命令信息；否则返回None
        """
        try:
            if CONFIRMATION_REQUIRED_MARKER in output:
                # 提取JSON部分
                start_idx = output.find('{')
                end_idx = output.rfind('}') + 1

                if start_idx != -1 and end_idx > start_idx:
                    json_str = output[start_idx:end_idx]
                    data = json.loads(json_str)

                    if data.get("type") == CONFIRMATION_REQUIRED_MARKER:
                        return {
                            "command": data.get("command"),
                            "command_type": data.get("command_type", "execute"),
                            "operation": data.get("operation", "执行命令"),
                            "working_dir": data.get("working_dir", ""),
                            "is_dangerous": data.get("is_dangerous", False),
                            "reason": data.get("reason", ""),
                            "message": data.get("message", "需要用户确认")
                        }
        except (json.JSONDecodeError, KeyError):
            pass

        return None


# 创建全局实例
chat_service = ChatService()

# 导出
__all__ = ['ChatService', 'chat_service']
