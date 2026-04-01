"""
Agent服务模块

提供Agent的核心执行逻辑，包括：
1. 消息构建
2. Agent执行
3. 递归限制处理
4. 会话状态管理
"""
import json
import logging
import asyncio
import threading
from typing import Dict, Any, Optional, List, Generator

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError

from config import Config
from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT
from agent.tools.bash import execute_confirmed_bash
from agent.tools.todo_manager import get_todo_manager, remove_todo_manager
from agent.tools.task_manager import remove_task_manager
from agent.tools.sub_agent import clear_session_tools
from agent.tools.skills import SKILLS_TOOLS
from agent.tools.memory import MEMORY_TOOLS

from services.core.types import ChatResponse, ChatResponseType
from services.agent.stream_handler import stream_handler, CONFIRMATION_REQUIRED_MARKER
from services.agent.tool_manager import tool_manager

logger = logging.getLogger(__name__)


class AgentService:
    """Agent服务 - 管理Agent的执行和状态"""
    
    def __init__(self, session_store, context_compactor):
        """
        初始化Agent服务
        
        Args:
            session_store: 会话存储服务
            context_compactor: 上下文压缩服务
        """
        self.session_store = session_store
        self.context_compactor = context_compactor
        
        # 使用流式LLM
        self.llm = get_llm(streaming=True)
        
        # 存储每个会话的取消状态
        self._cancel_flags: Dict[str, bool] = {}
        
        # 存储每个会话因递归限制中断时的状态
        self._recursion_pause_states: Dict[str, Dict[str, Any]] = {}
        
    def _get_agent_for_session(self, session_id: str):
        """
        获取或创建会话的Agent
        
        Args:
            session_id: 会话ID
            
        Returns:
            Agent实例
        """
        # 获取工具
        tools = tool_manager.get_tools_for_session(
            session_id, 
            self.session_store, 
            include_sub_agent=True
        )
        
        # 创建Agent
        return create_react_agent(self.llm, tools)
    
    def _build_messages(
        self,
        chat_history: List[Dict],
        user_input: str,
        todo_reminder: str = "",
        session_id: str = None
    ) -> List:
        """
        构建LangChain消息列表
        
        Args:
            chat_history: 对话历史
            user_input: 当前用户输入
            todo_reminder: 任务提醒消息
            session_id: 会话ID
            
        Returns:
            LangChain消息对象列表
        """
        messages = []
        
        # 构建系统提示
        system_prompt = SYSTEM_PROMPT
        
        # 如果有选中的知识库，进行RAG检索并注入上下文
        if session_id:
            kb_id = self.session_store.get_knowledge_base_id(session_id)
            if kb_id:
                # 传递对话历史用于指代消解
                context = self._run_async_rag_search(user_input, kb_id, chat_history)
                if context:
                    knowledge_prompt = f"""\n\n## 知识库上下文\n\n以下是知识库中检索到的相关信息，请优先参考这些信息回答用户问题：\n\n{context}\n\n---\n请在回答时适当引用知识库中的相关信息。\n"""
                    system_prompt += knowledge_prompt
        
        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))
        
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
                
        # 添加任务提醒
        if todo_reminder:
            messages.append(SystemMessage(content=todo_reminder))
            
        # 添加当前用户消息
        messages.append(HumanMessage(content=user_input))
        
        return messages
    
    def _build_messages_for_cancel(
        self,
        chat_history: List[Dict],
        context_message: str
    ) -> List:
        """
        为取消/确认场景构建消息列表
        
        Args:
            chat_history: 对话历史
            context_message: 上下文消息
            
        Returns:
            LangChain消息对象列表
        """
        messages = []
        
        # 添加系统提示
        messages.append(SystemMessage(content=SYSTEM_PROMPT))
        
        # 添加历史消息
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            # 跳过system角色
                
        # 添加上下文消息
        messages.append(HumanMessage(content=context_message))
        
        return messages
    
    def _run_async_rag_search(
        self, 
        query: str, 
        kb_id: str, 
        chat_history: List[Dict] = None
    ) -> str:
        """
        同步执行异步RAG检索（支持查询优化）
        
        Args:
            query: 查询文本
            kb_id: 知识库ID
            chat_history: 对话历史（用于指代消解）
            
        Returns:
            检索到的上下文
        """
        result = [""]
        error = [None]
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # 判断是否启用增强版 RAG
                if Config.ENABLE_ENHANCED_RAG:
                    from services.rag.enhanced_rag_service import get_enhanced_rag_service
                    enhanced_rag = get_enhanced_rag_service(llm_client=self.llm)
                    
                    # 使用增强版检索（带查询优化）
                    search_result = loop.run_until_complete(
                        enhanced_rag.search_with_optimization(
                            query=query,
                            knowledge_base_id=kb_id,
                            chat_history=chat_history
                        )
                    )
                    result[0] = search_result.integrated_context
                    
                    # 打印优化统计
                    stats = enhanced_rag.get_optimization_stats(search_result)
                    logger.info(f"[AgentService] RAG查询优化统计:")
                    logger.info(f"  复杂度: {stats['complexity']}")
                    logger.info(f"  优化步骤: {' -> '.join(stats['optimization_steps'])}")
                    logger.info(f"  检索查询数: {stats['total_search_queries']}")
                    logger.info(f"  总结果数: {stats['total_results']}")
                else:
                    # 使用基础 RAG 服务
                    from services.rag.rag_service import rag_service
                    result[0] = loop.run_until_complete(
                        rag_service.search_with_context(query, kb_id)
                    )
            except Exception as e:
                error[0] = e
                logger.error(f"[AgentService] RAG检索失败: {e}")
            finally:
                loop.close()
                
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        
        return result[0] or ""
    
    def chat(self, user_input: str, session_id: str) -> Dict[str, Any]:
        """
        非流式执行对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Returns:
            响应字典
        """
        # 获取会话历史
        chat_history, context_stats = self.session_store.get_full_context(session_id, user_input)
        
        # 检查是否需要压缩上下文
        if context_stats.get('should_compact', False):
            chat_history, _ = self.context_compactor.auto_compact(
                session_id=session_id,
                llm_client=self.llm,
                current_query=user_input
            )
            self.session_store.replace_messages(session_id, chat_history)
            
        try:
            # 设置会话工具
            self._setup_session_tools(session_id)
            
            # 检查任务提醒
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息
            messages = self._build_messages(chat_history, user_input, reminder, session_id)
            
            # 获取Agent
            agent = self._get_agent_for_session(session_id)
            
            # 执行
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            )
            
            # 提取输出
            output = stream_handler.extract_ai_message(result)
            
            # 增加任务管理器轮次
            todo_mgr.increment_turn()
            
            # 检查确认请求
            confirmation_info = stream_handler.extract_confirmation_info(output)
            if confirmation_info:
                self.session_store.add_message(session_id, "user", user_input)
                return {
                    "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                    "command": confirmation_info.command,
                    "command_type": confirmation_info.command_type,
                    "operation": confirmation_info.operation,
                    "working_dir": confirmation_info.working_dir,
                    "is_dangerous": confirmation_info.is_dangerous,
                    "reason": confirmation_info.reason,
                    "message": confirmation_info.message,
                    "session_id": session_id
                }
                
            # 保存对话历史
            self.session_store.add_message(session_id, "user", user_input)
            self.session_store.add_message(session_id, "assistant", output)
            
            return {
                "type": ChatResponseType.RESPONSE.value,
                "output": output,
                "session_id": session_id
            }
            
        except GraphRecursionError:
            # 达到递归限制
            self._recursion_pause_states[session_id] = {
                "chat_history": chat_history,
                "user_input": user_input,
                "last_output": None
            }
            
            self.session_store.add_message(session_id, "user", user_input)
            
            return {
                "type": ChatResponseType.RECURSION_LIMIT_REACHED.value,
                "message": f"已达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。任务可能还未完成。",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": ChatResponseType.ERROR.value,
                "output": f"执行出错: {str(e)}",
                "session_id": session_id
            }
    
    def chat_stream(
        self,
        user_input: str,
        session_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        # 清除取消标志
        self.clear_cancel_flag(session_id)
        
        # 获取会话历史
        chat_history, context_stats = self.session_store.get_full_context(session_id, user_input)
        
        # 检查是否需要压缩
        if context_stats.get('should_compact', False):
            chat_history, _ = self.context_compactor.auto_compact(
                session_id=session_id,
                llm_client=self.llm,
                current_query=user_input
            )
            self.session_store.replace_messages(session_id, chat_history)
            
        try:
            # 设置会话工具
            self._setup_session_tools(session_id)
            
            # 检查任务提醒
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            # 构建消息
            messages = self._build_messages(chat_history, user_input, reminder, session_id)
            
            # 获取Agent
            agent = self._get_agent_for_session(session_id)
            
            # 收集完整响应
            full_response = ""
            
            # 流式执行
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            ):
                # 检查取消
                if self.is_cancelled(session_id):
                    if full_response:
                        self.session_store.add_message(session_id, "user", user_input)
                        self.session_store.add_message(session_id, "assistant", full_response)
                    yield {
                        "type": ChatResponseType.CANCELLED.value,
                        "content": full_response
                    }
                    return
                    
                # 处理chunk
                if isinstance(chunk, tuple):
                    processed = stream_handler.process_stream_chunk(chunk, full_response)
                    if processed:
                        if processed.get("type") == ChatResponseType.CONTENT.value:
                            full_response = processed.get("accumulated", full_response)
                        elif processed.get("type") == ChatResponseType.CONFIRMATION_REQUIRED.value:
                            self.session_store.add_message(session_id, "user", user_input)
                            yield processed
                            return
                        yield processed
                        
            # 如果没有获取到内容，使用invoke作为备用
            if not full_response:
                agent = self._get_agent_for_session(session_id)
                result = agent.invoke({"messages": messages})
                full_response = stream_handler.extract_ai_message(result)
                
                # 检查确认请求
                confirmation_info = stream_handler.extract_confirmation_info(full_response)
                if confirmation_info:
                    self.session_store.add_message(session_id, "user", user_input)
                    yield {
                        "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                        "command": confirmation_info.command,
                        "command_type": confirmation_info.command_type,
                        "operation": confirmation_info.operation,
                        "working_dir": confirmation_info.working_dir,
                        "is_dangerous": confirmation_info.is_dangerous,
                        "reason": confirmation_info.reason,
                        "message": confirmation_info.message
                    }
                    return
                    
                # 模拟流式输出
                for chunk_data in stream_handler.simulate_stream(full_response):
                    yield chunk_data
            else:
                # 最终检查确认请求
                confirmation_info = stream_handler.extract_confirmation_info(full_response)
                if confirmation_info:
                    self.session_store.add_message(session_id, "user", user_input)
                    yield {
                        "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                        "command": confirmation_info.command,
                        "command_type": confirmation_info.command_type,
                        "operation": confirmation_info.operation,
                        "working_dir": confirmation_info.working_dir,
                        "is_dangerous": confirmation_info.is_dangerous,
                        "reason": confirmation_info.reason,
                        "message": confirmation_info.message
                    }
                    return
                    
            # 保存对话历史
            self.session_store.add_message(session_id, "user", user_input)
            self.session_store.add_message(session_id, "assistant", full_response)
            
            # 增加任务管理器轮次
            todo_mgr.increment_turn()
            
            # 发送完成信号
            yield {
                "type": ChatResponseType.DONE.value,
                "content": full_response
            }
            
        except GraphRecursionError:
            # 达到递归限制
            self._recursion_pause_states[session_id] = {
                "chat_history": chat_history,
                "user_input": user_input,
                "last_output": full_response if full_response else None
            }
            
            self.session_store.add_message(session_id, "user", user_input)
            if full_response:
                self.session_store.add_message(session_id, "assistant", full_response)
                
            yield {
                "type": ChatResponseType.RECURSION_LIMIT_REACHED.value,
                "message": f"已达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。任务可能还未完成。",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "partial_output": full_response
            }
            
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"执行出错: {str(e)}"
            }
    
    def confirm_command(
        self,
        command: str,
        session_id: str,
        user_message: str = ""
    ) -> Dict[str, Any]:
        """
        执行用户确认的命令（非流式）
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Returns:
            执行结果
        """
        try:
            # 执行命令
            result = execute_confirmed_bash(command)
            
            if user_message:
                chat_history = self.session_store.get_messages(session_id)
                
                exec_context = f"上一步命令已执行成功。\n执行的命令: {command}\n执行结果: {result}\n\n请继续完成用户的原始请求。"
                
                messages = self._build_messages_for_cancel(chat_history, exec_context)
                agent = self._get_agent_for_session(session_id)
                agent_result = agent.invoke({"messages": messages})
                output = stream_handler.extract_ai_message(agent_result)
                
                # 检查下一个确认请求
                confirmation_info = stream_handler.extract_confirmation_info(output)
                if confirmation_info:
                    return {
                        "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                        "command": confirmation_info.command,
                        "command_type": confirmation_info.command_type,
                        "operation": confirmation_info.operation,
                        "working_dir": confirmation_info.working_dir,
                        "is_dangerous": confirmation_info.is_dangerous,
                        "reason": confirmation_info.reason,
                        "message": confirmation_info.message,
                        "session_id": session_id
                    }
                    
                if output:
                    self.session_store.add_message(session_id, "assistant", output)
                    
                return {
                    "type": ChatResponseType.RESPONSE.value,
                    "output": output,
                    "session_id": session_id
                }
                
            return {
                "type": ChatResponseType.RESPONSE.value,
                "output": f"命令已执行:\n```\n{command}\n```\n\n结果:\n{result}",
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": ChatResponseType.ERROR.value,
                "output": f"执行命令失败: {str(e)}",
                "session_id": session_id
            }
    
    def confirm_command_stream(
        self,
        command: str,
        session_id: str,
        user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        执行用户确认的命令（流式）
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Yields:
            流式数据字典
        """
        self.clear_cancel_flag(session_id)
        
        try:
            # 执行命令
            result = execute_confirmed_bash(command)
            
            yield {
                "type": ChatResponseType.TOOL_RESULT.value,
                "content": f"命令已执行: `{command}`\n\n**结果:**\n```\n{result}\n```"
            }
            
            if user_message:
                chat_history = self.session_store.get_messages(session_id)
                
                exec_context = f"上一步命令已执行成功。\n执行的命令: {command}\n执行结果: {result}\n\n请继续完成用户的原始请求。"
                
                full_response = ""
                messages = self._build_messages_for_cancel(chat_history, exec_context)
                agent = self._get_agent_for_session(session_id)
                
                for chunk in agent.stream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"]
                ):
                    if self.is_cancelled(session_id):
                        if full_response:
                            self.session_store.add_message(session_id, "assistant", full_response)
                        yield {
                            "type": ChatResponseType.CANCELLED.value,
                            "content": full_response
                        }
                        return
                        
                    if isinstance(chunk, tuple):
                        processed = stream_handler.process_stream_chunk(chunk, full_response)
                        if processed:
                            if processed.get("type") == ChatResponseType.CONTENT.value:
                                full_response = processed.get("accumulated", full_response)
                                yield processed
                            elif processed.get("type") == ChatResponseType.CONFIRMATION_REQUIRED.value:
                                yield processed
                                return
                                
                if full_response:
                    self.session_store.add_message(session_id, "assistant", full_response)
                    
                yield {
                    "type": ChatResponseType.DONE.value,
                    "content": full_response
                }
            else:
                yield {
                    "type": ChatResponseType.DONE.value,
                    "content": f"命令已执行:\n```\n{command}\n```\n\n结果:\n{result}"
                }
                
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"执行命令失败: {str(e)}"
            }
    
    def cancel_command_stream(
        self,
        command: str,
        session_id: str,
        user_message: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        处理用户取消的命令
        
        Args:
            command: 用户取消的命令
            session_id: 会话ID
            user_message: 用户原始消息
            
        Yields:
            流式数据字典
        """
        self.clear_cancel_flag(session_id)
        
        try:
            chat_history = self.session_store.get_messages(session_id)
            
            if user_message:
                cancel_context = f"用户取消了之前请求执行的命令。\n取消的命令: {command}\n\n请根据这个情况，给用户提供其他建议或替代方案。"
                
                messages = self._build_messages_for_cancel(chat_history, cancel_context)
                full_response = ""
                
                agent = self._get_agent_for_session(session_id)
                
                for chunk in agent.stream(
                    {"messages": messages},
                    stream_mode=["messages", "updates"]
                ):
                    if self.is_cancelled(session_id):
                        if full_response:
                            self.session_store.add_message(session_id, "user", user_message)
                            self.session_store.add_message(session_id, "assistant", full_response)
                        yield {
                            "type": ChatResponseType.CANCELLED.value,
                            "content": full_response
                        }
                        return
                        
                    if isinstance(chunk, tuple):
                        processed = stream_handler.process_stream_chunk(chunk, full_response)
                        if processed and processed.get("type") == ChatResponseType.CONTENT.value:
                            full_response = processed.get("accumulated", full_response)
                            yield processed
                            
                if full_response:
                    self.session_store.add_message(session_id, "user", user_message)
                    self.session_store.add_message(session_id, "assistant", full_response)
                    
                yield {
                    "type": ChatResponseType.DONE.value,
                    "content": full_response
                }
            else:
                yield {
                    "type": ChatResponseType.DONE.value,
                    "content": "用户已取消命令执行。"
                }
                
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"处理取消失败: {str(e)}"
            }
    
    def continue_task(self, session_id: str) -> Dict[str, Any]:
        """继续执行因递归限制暂停的任务（非流式）"""
        pause_state = self._recursion_pause_states.pop(session_id, None)
        
        if not pause_state:
            return {
                "type": ChatResponseType.ERROR.value,
                "output": "没有找到暂停的任务状态",
                "session_id": session_id
            }
            
        try:
            from agent.tools.todo_manager import set_current_session
            set_current_session(session_id)
            
            chat_history = self.session_store.get_messages(session_id)
            
            continue_context = (
                f"任务执行已继续（之前达到了 {Config.AGENT_RECURSION_LIMIT} 步限制）。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            messages = self._build_messages_for_cancel(chat_history, continue_context)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
                
            agent = self._get_agent_for_session(session_id)
            
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            )
            
            output = stream_handler.extract_ai_message(result)
            
            confirmation_info = stream_handler.extract_confirmation_info(output)
            if confirmation_info:
                return {
                    "type": ChatResponseType.CONFIRMATION_REQUIRED.value,
                    "command": confirmation_info.command,
                    "command_type": confirmation_info.command_type,
                    "operation": confirmation_info.operation,
                    "working_dir": confirmation_info.working_dir,
                    "is_dangerous": confirmation_info.is_dangerous,
                    "reason": confirmation_info.reason,
                    "message": confirmation_info.message,
                    "session_id": session_id
                }
                
            self.session_store.add_message(session_id, "assistant", output)
            
            return {
                "type": ChatResponseType.RESPONSE.value,
                "output": output,
                "session_id": session_id
            }
            
        except GraphRecursionError:
            self._recursion_pause_states[session_id] = {
                "chat_history": self.session_store.get_messages(session_id),
                "user_input": pause_state.get("user_input", ""),
                "last_output": None
            }
            
            return {
                "type": ChatResponseType.RECURSION_LIMIT_REACHED.value,
                "message": f"再次达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。是否继续执行？",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": ChatResponseType.ERROR.value,
                "output": f"继续执行失败: {str(e)}",
                "session_id": session_id
            }
    
    def continue_task_stream(
        self,
        session_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        """继续执行因递归限制暂停的任务（流式）"""
        self.clear_cancel_flag(session_id)
        
        pause_state = self._recursion_pause_states.pop(session_id, None)
        
        if not pause_state:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": "没有找到暂停的任务状态"
            }
            return
            
        try:
            from agent.tools.todo_manager import set_current_session
            set_current_session(session_id)
            
            chat_history = self.session_store.get_messages(session_id)
            
            continue_context = (
                f"任务执行已继续（之前达到了 {Config.AGENT_RECURSION_LIMIT} 步限制）。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            messages = self._build_messages_for_cancel(chat_history, continue_context)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
                
            agent = self._get_agent_for_session(session_id)
            
            full_response = ""
            
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": Config.AGENT_RECURSION_LIMIT}
            ):
                if self.is_cancelled(session_id):
                    if full_response:
                        self.session_store.add_message(session_id, "assistant", full_response)
                    yield {
                        "type": ChatResponseType.CANCELLED.value,
                        "content": full_response
                    }
                    return
                    
                if isinstance(chunk, tuple):
                    processed = stream_handler.process_stream_chunk(chunk, full_response)
                    if processed:
                        if processed.get("type") == ChatResponseType.CONTENT.value:
                            full_response = processed.get("accumulated", full_response)
                            yield processed
                        elif processed.get("type") == ChatResponseType.CONFIRMATION_REQUIRED.value:
                            yield processed
                            return
                            
            if full_response:
                self.session_store.add_message(session_id, "assistant", full_response)
                
            yield {
                "type": ChatResponseType.DONE.value,
                "content": full_response
            }
            
        except GraphRecursionError:
            self._recursion_pause_states[session_id] = {
                "chat_history": self.session_store.get_messages(session_id),
                "user_input": pause_state.get("user_input", ""),
                "last_output": full_response if full_response else None
            }
            
            if full_response:
                self.session_store.add_message(session_id, "assistant", full_response)
                
            yield {
                "type": ChatResponseType.RECURSION_LIMIT_REACHED.value,
                "message": f"再次达到最大执行步数限制（{Config.AGENT_RECURSION_LIMIT}步）。是否继续执行？",
                "recursion_limit": Config.AGENT_RECURSION_LIMIT,
                "partial_output": full_response
            }
            
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"继续执行失败: {str(e)}"
            }
    
    def _setup_session_tools(self, session_id: str):
        """设置会话工具"""
        from agent.tools.todo_manager import set_current_session
        set_current_session(session_id)
        tool_manager.setup_sub_agent_tools(session_id, self.session_store)
    
    def request_cancel(self, session_id: str) -> None:
        """请求取消当前会话的流式输出"""
        self._cancel_flags[session_id] = True
    
    def is_cancelled(self, session_id: str) -> bool:
        """检查会话是否已被取消"""
        return self._cancel_flags.get(session_id, False)
    
    def clear_cancel_flag(self, session_id: str) -> None:
        """清除取消标志"""
        if session_id in self._cancel_flags:
            del self._cancel_flags[session_id]


__all__ = ['AgentService']
