"""
对话服务模块

统一的对话服务，支持：
1. 流式输出（token-by-token）
2. 工具调用（Bash执行）
3. 命令确认机制（所有执行类命令需要用户确认）
4. 会话历史管理（数据库持久化）
5. 递归限制处理（达到限制时让用户决定是否继续）
"""
import json
import uuid
from typing import Generator, Dict, Any, Optional, List

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError

from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT
from agent.tools.bash import (
    execute_bash,
    get_bash_tool_detailed_usage,
    execute_confirmed_bash,
    CONFIRMATION_REQUIRED_MARKER
)
from agent.tools.todo_manager import (
    todo_manager,
    get_todo_status,
    get_todo_manager,
    remove_todo_manager,
    set_current_session
)
from agent.tools.sub_agent import (
    spawn_sub_agent,
    set_sub_agent_tools,
    set_sub_agent_session,
    clear_session_tools
)
from mcp.adapters import get_web_search_tool
from services.context_manager import context_manager
from services.session_store import session_store
from config import Config


# 递归限制确认标记
RECURSION_LIMIT_MARKER = "__RECURSION_LIMIT_REACHED__"


class ChatService:
    """统一的对话服务类（使用数据库存储会话）"""

    def __init__(self):
        """初始化对话服务"""
        # 使用流式LLM
        self.llm = get_llm(streaming=True)
        
        # 基础工具（始终可用）
        # 包含 todo_manager 和 get_todo_status 用于任务管理
        # 包含 spawn_sub_agent 用于创建子agent执行任务
        self.base_tools = [
            execute_bash,
            get_bash_tool_detailed_usage,
            todo_manager,
            get_todo_status,
            spawn_sub_agent  # 主agent可以创建子agent
        ]
        
        # 子agent可用的工具（不包含 spawn_sub_agent，防止无限递归）
        self.sub_agent_tools = [
            execute_bash,
            get_bash_tool_detailed_usage,
            todo_manager,
            get_todo_status
        ]
        
        # 创建支持工具调用的Agent（使用基础工具）
        self.agent = create_react_agent(self.llm, self.base_tools)
        
        # 缓存 Web 搜索工具
        self._web_search_tool = None

        # 存储每个会话的取消状态
        # key: session_id, value: 是否已取消
        self._cancel_flags: Dict[str, bool] = {}
        
        # 存储每个会话的 Agent（根据工具配置动态创建）
        # key: session_id, value: agent
        self._session_agents: Dict[str, Any] = {}
        
        # 存储每个会话因递归限制中断时的状态（用于继续执行）
        # key: session_id, value: {"messages": [...], "last_user_input": "..."}
        self._recursion_pause_states: Dict[str, Dict[str, Any]] = {}
    
    def _get_tools_for_session(self, session_id: str, include_sub_agent: bool = True) -> List:
        """
        获取会话可用的工具列表
        
        根据会话的联网搜索设置，动态返回可用的工具
        
        Args:
            session_id: 会话ID
            include_sub_agent: 是否包含 spawn_sub_agent 工具（子agent不包含）
            
        Returns:
            工具列表
        """
        # 根据是否是子agent选择基础工具集
        if include_sub_agent:
            tools = list(self.base_tools)  # 主agent：包含 spawn_sub_agent
        else:
            tools = list(self.sub_agent_tools)  # 子agent：不包含 spawn_sub_agent
        
        # 检查会话是否启用联网搜索
        web_search_enabled = session_store.get_web_search_enabled(session_id)
        
        if web_search_enabled:
            # 懒加载 Web 搜索工具
            if self._web_search_tool is None:
                self._web_search_tool = get_web_search_tool()
            
            if self._web_search_tool:
                tools.append(self._web_search_tool)
        
        return tools
    
    def _get_agent_for_session(self, session_id: str) -> Any:
        """
        获取或创建会话的 Agent
        
        根据会话的工具配置，返回对应的 Agent
        如果工具配置发生变化，会重新创建 Agent
        
        Args:
            session_id: 会话ID
            
        Returns:
            Agent 实例
        """
        # 获取主agent的工具（包含spawn_sub_agent）
        current_tools = self._get_tools_for_session(session_id, include_sub_agent=True)
        
        # 直接创建新的 Agent（确保工具配置正确）
        return create_react_agent(self.llm, current_tools)

    # ==================== 会话管理 ====================

    def create_session(self) -> str:
        """
        创建新会话
        
        Returns:
            新会话的ID
        """
        session_id = str(uuid.uuid4())
        session_store.get_or_create_session(session_id)
        return session_id

    def ensure_session_exists(self, session_id: str) -> bool:
        """
        确保会话存在于数据库中
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否成功
        """
        return session_store.get_or_create_session(session_id)

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话及其所有消息
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否删除成功
        """
        # 清理会话的 TodoManager
        remove_todo_manager(session_id)
        # 清理会话的子Agent工具配置
        clear_session_tools(session_id)
        return session_store.delete_session(session_id)

    def get_all_sessions(self) -> List[Dict]:
        """
        获取所有会话列表
        
        Returns:
            会话列表，每个包含 session_id, created_at, updated_at, message_count
        """
        return session_store.get_all_sessions()

    def get_session_info(self, session_id: str) -> Optional[Dict]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息字典，不存在则返回None
        """
        return session_store.get_session_info(session_id)

    # ==================== 对话功能 ====================

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
        # 获取会话历史
        chat_history = self._get_chat_history(session_id)
        
        # 检查是否需要压缩上下文
        if context_manager.should_compress(chat_history):
            chat_history = context_manager.compress_history(
                chat_history, 
                llm_client=self.llm
            )
            # 数据库模式下，压缩后需要更新数据库
            self._compress_history_in_db(session_id, chat_history)

        try:
            # 设置当前会话ID（供工具使用）
            set_current_session(session_id)
            set_sub_agent_session(session_id)
            
            # 设置子agent可用的工具（不包含spawn_sub_agent）
            sub_tools = self._get_tools_for_session(session_id, include_sub_agent=False)
            set_sub_agent_tools(sub_tools, session_id)  # 传入session_id
            
            # 检查是否需要注入任务提醒（问责机制）
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息列表
            messages = self._build_messages(chat_history, user_input, reminder)

            # 获取会话特定的 Agent（根据联网搜索设置动态创建）
            agent = self._get_agent_for_session(session_id)
            
            # 使用Agent处理（带递归限制配置）
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            )

            # 提取最终输出
            output = self._extract_ai_message(result)
            
            # 增加任务管理器的轮次计数（用于问责机制）
            todo_mgr.increment_turn()

            # 检查是否包含需要确认的命令标记
            confirmation_info = self._extract_confirmation_required(output)

            if confirmation_info:
                # 保存用户消息到历史，以便确认后继续处理
                self._save_message(session_id, "user", user_input)
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
            self._save_message(session_id, "user", user_input)
            self._save_message(session_id, "assistant", output)

            return {
                "type": "response",
                "output": output,
                "session_id": session_id
            }

        except GraphRecursionError:
            # 达到递归限制，保存当前状态并请求用户确认
            self._recursion_pause_states[session_id] = {
                "chat_history": chat_history,
                "user_input": user_input,
                "last_output": None  # 无法获取部分输出
            }
            
            # 保存用户消息到历史
            self._save_message(session_id, "user", user_input)
            
            return {
                "type": "recursion_limit_reached",
                "message": f"已达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。任务可能还未完成。",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
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
            - type: "content" | "tool_start" | "tool_end" | "confirmation_required" | "done" | "error" | "cancelled"
            - content: 当前token内容
            - accumulated: 累积内容
        """
        # 清除之前的取消标志
        self.clear_cancel_flag(session_id)
        
        # 获取会话历史
        chat_history = self._get_chat_history(session_id)
        
        # 检查是否需要压缩上下文
        if context_manager.should_compress(chat_history):
            chat_history = context_manager.compress_history(
                chat_history, 
                llm_client=self.llm
            )
            # 数据库模式下，压缩后需要更新数据库
            self._compress_history_in_db(session_id, chat_history)

        try:
            # 设置当前会话ID（供工具使用）
            set_current_session(session_id)
            set_sub_agent_session(session_id)
            
            # 设置子agent可用的工具（不包含spawn_sub_agent）
            sub_tools = self._get_tools_for_session(session_id, include_sub_agent=False)
            set_sub_agent_tools(sub_tools, session_id)  # 传入session_id
            
            # 检查是否需要注入任务提醒（问责机制）
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息列表
            messages = self._build_messages(chat_history, user_input, reminder)

            # 获取会话特定的 Agent（根据联网搜索设置动态创建）
            agent = self._get_agent_for_session(session_id)
            
            # 收集完整响应
            full_response = ""

            # 使用多种 stream_mode（带递归限制配置）
            for chunk in agent.stream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"],
                    config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            ):
                # 检查是否被取消
                if self.is_cancelled(session_id):
                    # 保存已输出的部分到历史
                    if full_response:
                        self._save_message(session_id, "user", user_input)
                        self._save_message(session_id, "assistant", full_response)
                    yield {
                        "type": "cancelled",
                        "content": full_response
                    }
                    return
                
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
                                        # 保存用户消息到历史，以便确认后继续处理
                                        self._save_message(session_id, "user", user_input)
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
                # 获取会话特定的 Agent
                agent = self._get_agent_for_session(session_id)
                result = agent.invoke({"messages": messages})
                full_response = self._extract_ai_message(result)

                # 检查是否需要确认
                confirmation_info = self._extract_confirmation_required(full_response)
                if confirmation_info:
                    # 保存用户消息到历史，以便确认后继续处理
                    self._save_message(session_id, "user", user_input)
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
                    # 保存用户消息到历史，以便确认后继续处理
                    self._save_message(session_id, "user", user_input)
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
            self._save_message(session_id, "user", user_input)
            self._save_message(session_id, "assistant", full_response)
            
            # 增加任务管理器的轮次计数（用于问责机制）
            todo_mgr.increment_turn()

            # 发送完成信号
            yield {
                "type": "done",
                "content": full_response
            }

        except GraphRecursionError:
            # 达到递归限制，保存当前状态并请求用户确认
            self._recursion_pause_states[session_id] = {
                "chat_history": chat_history,
                "user_input": user_input,
                "last_output": full_response if full_response else None
            }
            
            # 保存用户消息和已有的输出到历史
            self._save_message(session_id, "user", user_input)
            if full_response:
                self._save_message(session_id, "assistant", full_response)
            
            yield {
                "type": "recursion_limit_reached",
                "message": f"已达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。任务可能还未完成。",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "partial_output": full_response
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
        执行用户确认的命令（非流式）
        
        支持多步骤工具调用：执行命令后，如果LLM决定调用更多工具，
        会继续处理直到所有任务完成或需要用户确认。
        
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
                chat_history = self._get_chat_history(session_id)
                
                # 构建上下文消息，告诉 LLM 命令执行结果并提醒继续处理
                # 注意：用户消息已经在 chat 方法中保存到历史了，这里不需要重复保存
                exec_context = f"上一步命令已执行成功。\n执行的命令: {command}\n执行结果: {result}\n\n请继续完成用户的原始请求，执行剩余的步骤。如果还有未完成的任务，请继续执行。"
                
                # 使用 Agent 处理，支持多步骤工具调用
                messages = self._build_messages_for_cancel(chat_history, exec_context)
                # 获取会话特定的 Agent
                agent = self._get_agent_for_session(session_id)
                agent_result = agent.invoke({"messages": messages})
                output = self._extract_ai_message(agent_result)

                # 检查是否需要确认下一个命令
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

                # 保存助手响应到历史（用户消息已经在 chat 方法中保存了）
                if output:
                    self._save_message(session_id, "assistant", output)

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
        
        支持多步骤工具调用：执行命令后，如果LLM决定调用更多工具，
        会继续处理直到所有任务完成或需要用户确认。
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息（用于继续对话）
            
        Yields:
            流式数据字典
        """
        # 清除之前的取消标志
        self.clear_cancel_flag(session_id)
        
        try:
            # 直接执行命令
            result = execute_confirmed_bash(command)

            yield {
                "type": "tool_result",
                "content": f"命令已执行: `{command}`\n\n**结果:**\n```\n{result}\n```"
            }

            # 如果有用户消息，继续对话
            if user_message:
                chat_history = self._get_chat_history(session_id)
                
                # 构建上下文消息，告诉 LLM 命令执行结果并提醒继续处理
                # 注意：用户消息已经在 chat_stream 中保存到历史了，这里不需要重复保存
                exec_context = f"上一步命令已执行成功。\n执行的命令: {command}\n执行结果: {result}\n\n请继续完成用户的原始请求，执行剩余的步骤。如果还有未完成的任务，请继续执行。"
                
                # 使用循环支持多步骤工具调用
                full_response = ""
                for chunk in self._execute_agent_loop(chat_history, exec_context, session_id):
                    if chunk["type"] == "content":
                        full_response = chunk.get("accumulated", full_response)
                        yield chunk
                    elif chunk["type"] == "confirmation_required":
                        # 需要确认，直接传递给前端
                        yield chunk
                        return
                    elif chunk["type"] == "cancelled":
                        yield chunk
                        return
                    elif chunk["type"] == "done":
                        full_response = chunk.get("content", full_response)
                        # 不在这里 yield done，继续处理
                
                # 保存助手响应到历史（用户消息已经在 chat_stream 中保存了）
                if full_response:
                    self._save_message(session_id, "assistant", full_response)
                
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
        # 清除之前的取消标志
        self.clear_cancel_flag(session_id)
        
        try:
            chat_history = self._get_chat_history(session_id)

            # 如果有用户消息，让 LLM 继续处理
            # 注意：不再使用 tool 角色消息，而是构建一个新的用户消息告诉 LLM 取消情况
            if user_message:
                # 构建新的用户消息，告诉 LLM 用户取消了命令
                cancel_context = f"用户取消了之前请求执行的命令。\n取消的命令: {command}\n\n请根据这个情况，给用户提供其他建议或替代方案。"
                
                messages = self._build_messages_for_cancel(chat_history, cancel_context)
                full_response = ""

                # 获取会话特定的 Agent
                agent = self._get_agent_for_session(session_id)

                for chunk in agent.stream(
                        {"messages": messages},
                        stream_mode=["messages", "updates"]
                ):
                    # 检查是否被取消
                    if self.is_cancelled(session_id):
                        if full_response:
                            self._save_message(session_id, "user", user_message)
                            self._save_message(session_id, "assistant", full_response)
                        yield {
                            "type": "cancelled",
                            "content": full_response
                        }
                        return
                    
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
                    self._save_message(session_id, "user", user_message)
                    self._save_message(session_id, "assistant", full_response)

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

    # ==================== 递归限制继续执行 ====================

    def continue_task(
            self,
            session_id: str = "default"
    ) -> Dict[str, Any]:
        """
        继续执行因递归限制暂停的任务（非流式）
        
        Args:
            session_id: 会话ID
            
        Returns:
            执行结果
        """
        # 获取暂停状态
        pause_state = self._recursion_pause_states.pop(session_id, None)
        
        if not pause_state:
            return {
                "type": "error",
                "output": "没有找到暂停的任务状态",
                "session_id": session_id
            }
        
        try:
            # 设置当前会话ID
            set_current_session(session_id)
            
            # 获取当前对话历史（已经包含了之前的消息）
            chat_history = self._get_chat_history(session_id)
            
            # 构建继续执行的上下文消息
            continue_context = (
                f"任务执行已继续（之前达到了 {Config.AGENT_RECURSION_LIMIT} 步限制）。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            # 检查任务提醒
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息
            messages = self._build_messages_for_cancel(chat_history, continue_context)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
            
            # 获取 Agent
            agent = self._get_agent_for_session(session_id)
            
            # 使用新的递归限制执行
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            )
            
            output = self._extract_ai_message(result)
            
            # 检查是否需要确认命令
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
            
            # 保存输出
            self._save_message(session_id, "assistant", output)
            
            return {
                "type": "response",
                "output": output,
                "session_id": session_id
            }
            
        except GraphRecursionError:
            # 再次达到限制，保存状态并请求确认
            self._recursion_pause_states[session_id] = {
                "chat_history": self._get_chat_history(session_id),
                "user_input": pause_state.get("user_input", ""),
                "last_output": None
            }
            
            return {
                "type": "recursion_limit_reached",
                "message": f"再次达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。是否继续执行？",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": "error",
                "output": f"继续执行失败: {str(e)}",
                "session_id": session_id
            }

    def continue_task_stream(
            self,
            session_id: str = "default"
    ) -> Generator[Dict[str, Any], None, None]:
        """
        继续执行因递归限制暂停的任务（流式）
        
        Args:
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        # 清除取消标志
        self.clear_cancel_flag(session_id)
        
        # 获取暂停状态
        pause_state = self._recursion_pause_states.pop(session_id, None)
        
        if not pause_state:
            yield {
                "type": "error",
                "content": "没有找到暂停的任务状态"
            }
            return
        
        try:
            # 设置当前会话ID
            set_current_session(session_id)
            
            # 获取当前对话历史
            chat_history = self._get_chat_history(session_id)
            
            # 构建继续执行的上下文消息
            continue_context = (
                f"任务执行已继续（之前达到了 {Config.AGENT_RECURSION_LIMIT} 步限制）。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            # 检查任务提醒
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息
            messages = self._build_messages_for_cancel(chat_history, continue_context)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
            
            # 获取 Agent
            agent = self._get_agent_for_session(session_id)
            
            full_response = ""
            
            # 流式执行
            for chunk in agent.stream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"],
                    config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            ):
                # 检查是否被取消
                if self.is_cancelled(session_id):
                    if full_response:
                        self._save_message(session_id, "assistant", full_response)
                    yield {
                        "type": "cancelled",
                        "content": full_response
                    }
                    return
                
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
                    
                    elif mode == "updates":
                        if isinstance(data, dict) and "tools" in data:
                            tool_output = data["tools"].get("messages", [])
                            for msg in tool_output:
                                if hasattr(msg, "content"):
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
            
            # 保存输出
            if full_response:
                self._save_message(session_id, "assistant", full_response)
            
            yield {
                "type": "done",
                "content": full_response
            }
            
        except GraphRecursionError:
            # 再次达到限制
            self._recursion_pause_states[session_id] = {
                "chat_history": self._get_chat_history(session_id),
                "user_input": pause_state.get("user_input", ""),
                "last_output": full_response if full_response else None
            }
            
            if full_response:
                self._save_message(session_id, "assistant", full_response)
            
            yield {
                "type": "recursion_limit_reached",
                "message": f"再次达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。是否继续执行？",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "partial_output": full_response
            }
            
        except Exception as e:
            yield {
                "type": "error",
                "content": f"继续执行失败: {str(e)}"
            }

    def get_history(self, session_id: str = "default") -> List[Dict]:
        """获取对话历史"""
        return self._get_chat_history(session_id)

    def clear_history(self, session_id: str = "default") -> None:
        """清空对话历史"""
        session_store.clear_messages(session_id)
    
    def request_cancel(self, session_id: str = "default") -> None:
        """请求取消当前会话的流式输出"""
        self._cancel_flags[session_id] = True
    
    def is_cancelled(self, session_id: str = "default") -> bool:
        """检查会话是否已被取消"""
        return self._cancel_flags.get(session_id, False)
    
    def clear_cancel_flag(self, session_id: str = "default") -> None:
        """清除取消标志"""
        if session_id in self._cancel_flags:
            del self._cancel_flags[session_id]
    
    # ==================== 联网搜索设置 ====================
    
    def get_web_search_status(self, session_id: str) -> bool:
        """
        获取会话的联网搜索状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否启用联网搜索
        """
        return session_store.get_web_search_enabled(session_id)
    
    def set_web_search_enabled(self, session_id: str, enabled: bool) -> None:
        """
        设置会话的联网搜索开关
        
        Args:
            session_id: 会话ID
            enabled: 是否启用联网搜索
        """
        session_store.set_web_search_enabled(session_id, enabled)

    # ==================== 私有方法 ====================

    def _get_chat_history(self, session_id: str) -> List[Dict]:
        """
        获取会话历史（从数据库）
        
        Args:
            session_id: 会话ID
            
        Returns:
            消息列表
        """
        return session_store.get_messages(session_id, limit=100)
    
    def _save_message(self, session_id: str, role: str, content: str):
        """
        保存消息到数据库
        
        Args:
            session_id: 会话ID
            role: 角色
            content: 消息内容
        """
        session_store.add_message(session_id, role, content)

    def _compress_history_in_db(self, session_id: str, compressed_history: List[Dict]):
        """
        在数据库中压缩历史记录
        
        Args:
            session_id: 会话ID
            compressed_history: 压缩后的历史记录
        """
        session_store.replace_messages(session_id, compressed_history)

    def _build_messages(
            self,
            chat_history: List[Dict],
            user_input: str,
            todo_reminder: str = ""
    ) -> List:
        """
        构建LangChain消息列表
        
        Args:
            chat_history: 对话历史
            user_input: 当前用户输入
            todo_reminder: 任务提醒消息（问责机制触发时注入）
            
        Returns:
            LangChain消息对象列表
        """
        messages = []

        # 添加系统提示（始终在第一位）
        messages.append(SystemMessage(content=SYSTEM_PROMPT))

        # 添加历史消息
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                # 系统消息已经处理过了，跳过
                pass
            # 注意：不再处理 tool 角色，因为它需要前置的 tool_calls

        # 如果有任务提醒，作为系统消息注入
        if todo_reminder:
            messages.append(SystemMessage(content=todo_reminder))

        # 添加当前用户消息
        messages.append(HumanMessage(content=user_input))

        return messages

    def _execute_agent_loop(
            self,
            chat_history: List[Dict],
            context_message: str,
            session_id: str = "default",
            max_iterations: int = 10
    ) -> Generator[Dict[str, Any], None, None]:
        """
        执行 Agent 循环，支持多步骤工具调用
        
        这个方法会持续运行 Agent 直到：
        1. Agent 不再调用工具（返回最终响应）
        2. 需要用户确认命令
        3. 用户取消
        4. 达到最大迭代次数
        
        这是一个生成器，会 yield 流式输出和确认请求。
        
        Args:
            chat_history: 对话历史
            context_message: 上下文消息（包含命令执行结果）
            session_id: 会话ID
            max_iterations: 最大迭代次数，防止无限循环
            
        Yields:
            流式数据字典，包括 content 和 confirmation_required 类型
        """
        full_response = ""
        messages = self._build_messages_for_cancel(chat_history, context_message)
        
        # 获取会话特定的 Agent
        agent = self._get_agent_for_session(session_id)
        
        for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"]
        ):
            # 检查是否被取消
            if self.is_cancelled(session_id):
                yield {
                    "type": "cancelled",
                    "content": full_response
                }
                return
            
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

                elif mode == "updates":
                    # 检查工具节点输出
                    if isinstance(data, dict) and "tools" in data:
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
        
        yield {
            "type": "done",
            "content": full_response
        }

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

        # 添加系统提示（始终在第一位）
        messages.append(SystemMessage(content=SYSTEM_PROMPT))

        # 添加历史消息（只包含 user 和 assistant）
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                # 系统消息已经处理过了，跳过
                pass

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
