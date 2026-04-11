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
from agent.prompts import build_system_prompt, get_system_prompt
from agent.tools.bash import execute_confirmed_bash
from agent.tools.todo_manager import (
    get_todo_manager, 
    remove_todo_manager,
    check_task_reminder,
    record_task_activity
)
from agent.tools.task_manager import remove_task_manager
from agent.tools.sub_agent import clear_session_tools
from agent.tools.skills import SKILLS_TOOLS
from agent.tools.memory import MEMORY_TOOLS

from services.core.types import ChatResponse, ChatResponseType
from services.agent.stream_handler import stream_handler, CONFIRMATION_REQUIRED_MARKER
from services.agent.tool_manager import tool_manager
from services.context.context_compactor import check_context_overflow, emergency_compact
from services.onboarding_service import onboarding_service
from services.db_manager import db_manager

# 导入团队模式
from agent.team import (
    AgentsTeam,
    get_agents_team,
    remove_agents_team,
    ExecutionMode
)

logger = logging.getLogger(__name__)


class AgentService:
    """Agent服务 - 管理Agent的执行和状态"""
    
    # 团队模式配置
    TEAM_MODE_ENABLED = True  # 启用团队模式（支持实时进度推送）
    MAX_FOLLOWERS = 3  # 最大Follower数量
    
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
        
        # 存储上下文超限状态
        self._context_overflow_states: Dict[str, Dict[str, Any]] = {}
        
        # 存储团队执行结果（用于前端展示）
        self._team_results: Dict[str, Dict[str, Any]] = {}
        
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
        planning_prompt: str = "",
        session_id: str = None
    ) -> List:
        """
        构建LangChain消息列表
        
        采用分层提示词构建策略：
        1. 核心规则 + 工具索引（常驻）
        2. 场景指南（按需加载）
        3. 动态上下文（记忆、知识库、任务状态）
        
        注意：工具调用结果会在 LLM 调用前通过 micro_compact 进行压缩。
        
        Args:
            chat_history: 对话历史
            user_input: 当前用户输入
            todo_reminder: 任务提醒消息
            planning_prompt: 规划提示词
            session_id: 会话ID
            
        Returns:
            LangChain消息对象列表
        """
        messages = []
        
        # 获取当前会话可用的工具列表（用于工具感知）
        available_tools = self._get_available_tool_names(session_id)
        
        # 获取知识库上下文（如果启用）
        knowledge_context = None
        if session_id:
            kb_id = self.session_store.get_knowledge_base_id(session_id)
            if kb_id:
                knowledge_context = self._run_async_rag_search(user_input, kb_id, chat_history)
        
        # 获取记忆上下文
        memory_context = self._get_memory_context(session_id)
        
        # 获取任务状态
        task_status = self._get_task_status(session_id)
        
        # 使用新的分层提示词构建器
        system_prompt = build_system_prompt(
            user_input=user_input,
            chat_history=chat_history,
            memory_context=memory_context,
            knowledge_context=knowledge_context,
            task_status=task_status,
            todo_reminder=todo_reminder if todo_reminder else None,
            planning_prompt=planning_prompt if planning_prompt else None,
            available_tools=available_tools
        )
        
        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))
        
        # 添加历史消息
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # 处理包含 tool_calls 的 assistant 消息
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # 转换 tool_calls 格式
                    messages.append(AIMessage(content=content, tool_calls=tool_calls))
                else:
                    messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
        
        # 添加当前用户消息
        messages.append(HumanMessage(content=user_input))
        
        return messages
    
    def _apply_micro_compact(self, messages: List) -> List:
        """
        应用微观压缩到消息列表
        
        将旧的工具调用结果压缩为简洁占位符，仅保留最近 N 次。
        这在每次 LLM 调用前执行，防止工具结果堆积占用上下文。
        
        Args:
            messages: LangChain 消息列表
            
        Returns:
            压缩后的消息列表
        """
        from services.context.context_compactor import micro_compact
        return micro_compact(messages)
    
    def _get_available_tool_names(self, session_id: str) -> List[str]:
        """
        获取当前会话可用的工具名称列表
        
        用于系统提示词中的工具感知
        """
        try:
            tools = tool_manager.get_tools_for_session(
                session_id,
                self.session_store,
                include_sub_agent=True
            )
            return [getattr(t, 'name', str(t)) for t in tools]
        except Exception as e:
            logger.warning(f"[AgentService] 获取工具列表失败: {e}")
            return []
    
    def _get_memory_context(self, session_id: str, query: str = None) -> Optional[str]:
        """
        获取用户的记忆上下文
        
        从长期记忆中检索与当前对话相关的信息
        
        Args:
            session_id: 会话ID
            query: 查询文本（可选，用于语义检索）
        """
        if not session_id:
            return None
        
        try:
            # 使用长期记忆服务检索相关记忆
            from services.context.long_term_memory import long_term_memory
            
            # 获取最近的用户信息（重要度高）
            user_memories = long_term_memory.get_recent_memories(
                limit=10,
                memory_types=['user_info', 'preference', 'project']
            )
            
            if user_memories:
                # 格式化记忆上下文
                lines = ["以下是已记录的用户信息："]
                for mem in user_memories:
                    mem_type = mem.get('memory_type', 'fact')
                    content = mem.get('content', '')
                    type_labels = {
                        'user_info': '个人信息',
                        'preference': '偏好',
                        'project': '项目',
                        'decision': '决策',
                        'fact': '事实'
                    }
                    type_label = type_labels.get(mem_type, mem_type)
                    lines.append(f"- [{type_label}] {content}")
                return "\n".join(lines)
            
            return None
        except Exception as e:
            logger.warning(f"[AgentService] 获取记忆上下文失败: {e}")
            return None
    
    def _get_task_status(self, session_id: str) -> Optional[str]:
        """
        获取当前任务状态摘要
        """
        if not session_id:
            return None
        
        try:
            from agent.tools.todo_manager import get_todo_manager
            manager = get_todo_manager(session_id)
            status = manager.get_status()
            
            if status and status.get("items"):
                return manager.render()
        except Exception as e:
            logger.debug(f"[AgentService] 获取任务状态失败: {e}")
        
        return None
    
    def _get_planning_prompt(
        self,
        user_input: str,
        chat_history: List[Dict],
        session_id: str
    ) -> str:
        """
        获取 Planning 提示词
        
        判断任务是否需要规划，如果需要则生成规划提示词
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            session_id: 会话ID
            
        Returns:
            规划提示词，如果不需要则返回空字符串
        """
        try:
            from agent.planning import PlanningService, get_session_plan, set_session_plan
            
            # 获取可用工具
            available_tools = self._get_available_tool_names(session_id)
            
            # 创建规划服务
            planning_service = PlanningService()
            
            # 分析任务复杂度
            should_plan = planning_service.should_plan(
                user_input, chat_history, available_tools
            )
            
            if not should_plan:
                return ""
            
            # 检查是否已有计划
            existing_plan = get_session_plan(session_id)
            if existing_plan and existing_plan.steps:
                # 检查计划是否仍在执行中
                pending_steps = [
                    s for s in existing_plan.steps
                    if s.status in ["pending", "in_progress"]
                ]
                if pending_steps:
                    # 计划仍在执行中，返回提醒
                    return planning_service.generate_plan_prompt(existing_plan)
            
            # 生成新计划
            plan = planning_service.generate_plan(
                user_input, chat_history, available_tools
            )
            
            # 保存计划
            set_session_plan(session_id, plan)
            
            # 返回规划提示词
            return planning_service.generate_plan_prompt(plan)
            
        except Exception as e:
            logger.warning(f"[AgentService] 获取规划提示词失败: {e}")
            return ""
    
    def _build_messages_for_cancel(
        self,
        chat_history: List[Dict],
        context_message: str,
        session_id: str = None
    ) -> List:
        """
        为取消/确认场景构建消息列表
        
        重要：必须包含任务状态和规划信息，否则Agent会丢失任务进度
        
        Args:
            chat_history: 对话历史
            context_message: 上下文消息
            session_id: 会话ID
            
        Returns:
            LangChain消息对象列表
        """
        messages = []
        
        # 获取可用工具（用于工具感知）
        available_tools = self._get_available_tool_names(session_id) if session_id else []
        
        # 获取任务状态
        task_status = self._get_task_status(session_id)
        
        # 获取记忆上下文
        memory_context = self._get_memory_context(session_id)
        
        # 构建完整的系统提示（包含任务状态）
        system_prompt = build_system_prompt(
            user_input=context_message,
            chat_history=chat_history,
            memory_context=memory_context,
            task_status=task_status,
            available_tools=available_tools
        )
        
        # 添加系统提示
        messages.append(SystemMessage(content=system_prompt))
        
        # 添加历史消息
        for msg in chat_history:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # 处理包含 tool_calls 的 assistant 消息
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    messages.append(AIMessage(content=content, tool_calls=tool_calls))
                else:
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
        # ========== 首次对话引导检测 ==========
        with db_manager.get_session() as db_session:
            if onboarding_service.need_onboarding(db_session):
                logger.info(f"[AgentService] 检测到首次对话，触发引导流程")
                greeting = onboarding_service.get_greeting()
                return {
                    "type": ChatResponseType.ONBOARDING_REQUIRED.value,
                    "message": greeting,
                    "session_id": session_id
                }
        
        # 检查上下文窗口是否超限
        overflow_info = check_context_overflow(session_id)
        if overflow_info["is_overflow"]:
            # 保存当前状态
            self._context_overflow_states[session_id] = {
                "user_input": user_input,
                "token_count": overflow_info["token_count"],
                "usage_ratio": overflow_info["usage_ratio"]
            }
            
            return {
                "type": ChatResponseType.CONTEXT_LIMIT_REACHED.value,
                "message": f"会话上下文已达到最大窗口限制（{overflow_info['token_count']}/{overflow_info['max_tokens']} tokens，{overflow_info['usage_ratio']*100:.1f}%）",
                "token_count": overflow_info["token_count"],
                "max_tokens": overflow_info["max_tokens"],
                "usage_ratio": overflow_info["usage_ratio"],
                "session_id": session_id
            }
        
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
            
            # 检查强制任务提醒
            forced_reminder = check_task_reminder(session_id)
            if forced_reminder:
                reminder = forced_reminder
            
            # 检查是否需要 Planning
            planning_prompt = self._get_planning_prompt(user_input, chat_history, session_id)
            
            # 构建消息
            messages = self._build_messages(chat_history, user_input, reminder, planning_prompt, session_id)
            
            # 应用微观压缩（压缩旧的工具调用结果）
            messages = self._apply_micro_compact(messages)
            
            # 获取Agent
            agent = self._get_agent_for_session(session_id)
            
            # 执行（设置很大的recursion_limit，实际上移除步数限制）
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 1000}
            )
            
            # 提取输出
            output = stream_handler.extract_ai_message(result)
            
            # 增加任务管理器轮次
            todo_mgr.increment_turn()
            
            # 再次检查是否需要强制提醒（用于下一轮）
            if todo_mgr.should_remind():
                logger.info(f"[AgentService] 会话 {session_id} 已 {todo_mgr._turns_since_last_update} 轮未更新任务状态")
            
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
            # 保留向后兼容，但这种情况不应该再发生
            self._recursion_pause_states[session_id] = {
                "chat_history": chat_history,
                "user_input": user_input,
                "last_output": None
            }
            
            self.session_store.add_message(session_id, "user", user_input)
            
            return {
                "type": ChatResponseType.RECURSION_LIMIT_REACHED.value,
                "message": "执行步数较多，建议考虑简化任务或使用子Agent。",
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": ChatResponseType.ERROR.value,
                "output": f"执行出错: {str(e)}",
                "session_id": session_id
            }
    
    def handle_onboarding_reply(self, user_reply: str, session_id: str) -> Dict[str, Any]:
        """
        处理首次对话引导的用户回复
        
        Args:
            user_reply: 用户的回复（包含名字和角色期望）
            session_id: 会话ID
            
        Returns:
            响应字典
        """
        logger.info(f"[AgentService] 处理首次对话引导回复: {user_reply[:50]}...")
        
        with db_manager.get_session() as db_session:
            # 使用 LLM 提取信息并完成引导
            result = onboarding_service.complete_onboarding_from_reply(
                db_session,
                user_reply,
                self.llm  # 传入 LLM 客户端
            )
            
            if result.get('success'):
                # 生成确认消息
                user_name = result.get('user_name', '朋友')
                agent_role = result.get('agent_role', '智能助手')
                
                confirmation = onboarding_service.get_confirmation_message(
                    user_name, agent_role
                )
                
                # 保存对话历史（引导问候 + 用户回复 + 确认）
                greeting = onboarding_service.get_greeting()
                self.session_store.add_message(session_id, "assistant", greeting)
                self.session_store.add_message(session_id, "user", user_reply)
                self.session_store.add_message(session_id, "assistant", confirmation)
                
                return {
                    "type": ChatResponseType.RESPONSE.value,
                    "output": confirmation,
                    "session_id": session_id,
                    "onboarding_completed": True
                }
            elif result.get('need_retry'):
                # 提取无效，需要用户重新回答
                # 保存用户的无效回复，然后返回重试消息
                self.session_store.add_message(session_id, "user", user_reply)
                
                retry_message = result.get('message', '抱歉，我没有理解。请告诉我您的称呼和希望我扮演的角色。')
                self.session_store.add_message(session_id, "assistant", retry_message)
                
                return {
                    "type": ChatResponseType.ONBOARDING_REQUIRED.value,
                    "message": retry_message,
                    "session_id": session_id,
                    "need_retry": True
                }
            else:
                # 其他错误
                return {
                    "type": ChatResponseType.ERROR.value,
                    "output": f"引导设置失败: {result.get('error', '未知错误')}",
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
        
        # ========== 首次对话引导检测 ==========
        with db_manager.get_session() as db_session:
            if onboarding_service.need_onboarding(db_session):
                logger.info(f"[AgentService] 检测到首次对话，触发引导流程")
                greeting = onboarding_service.get_greeting()
                yield {
                    "type": ChatResponseType.ONBOARDING_REQUIRED.value,
                    "message": greeting,
                    "session_id": session_id
                }
                return
        
        # 检查上下文窗口是否超限
        overflow_info = check_context_overflow(session_id)
        if overflow_info["is_overflow"]:
            # 保存当前状态
            self._context_overflow_states[session_id] = {
                "user_input": user_input,
                "token_count": overflow_info["token_count"],
                "usage_ratio": overflow_info["usage_ratio"]
            }
            
            yield {
                "type": ChatResponseType.CONTEXT_LIMIT_REACHED.value,
                "message": f"会话上下文已达到最大窗口限制（{overflow_info['token_count']}/{overflow_info['max_tokens']} tokens，{overflow_info['usage_ratio']*100:.1f}%）",
                "token_count": overflow_info["token_count"],
                "max_tokens": overflow_info["max_tokens"],
                "usage_ratio": overflow_info["usage_ratio"],
                "session_id": session_id
            }
            return
        
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
            
            # 检查强制任务提醒
            forced_reminder = check_task_reminder(session_id)
            if forced_reminder:
                reminder = forced_reminder
            
            # 检查是否需要 Planning
            planning_prompt = self._get_planning_prompt(user_input, chat_history, session_id)
            
            # 构建消息
            messages = self._build_messages(chat_history, user_input, reminder, planning_prompt, session_id)
            
            # 应用微观压缩（压缩旧的工具调用结果）
            messages = self._apply_micro_compact(messages)
            
            # 获取Agent
            agent = self._get_agent_for_session(session_id)
            
            # 收集完整响应
            full_response = ""
            
            # 流式执行（设置很大的recursion_limit，实际上移除步数限制）
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": 1000}
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
                result = agent.invoke(
                    {"messages": messages},
                    config={"recursion_limit": 1000}
                )
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
            
            # 再次检查是否需要强制提醒（用于下一轮）
            if todo_mgr.should_remind():
                logger.info(f"[AgentService] 会话 {session_id} 已 {todo_mgr._turns_since_last_update} 轮未更新任务状态")
            
            # 发送完成信号
            yield {
                "type": ChatResponseType.DONE.value,
                "content": full_response
            }
            
        except GraphRecursionError:
            # 保留向后兼容
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
                "message": "执行步数较多，建议考虑简化任务或使用子Agent。",
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
                # 获取会话历史
                chat_history = self.session_store.get_messages(session_id)
                
                # 构建执行上下文，包含用户原始请求和当前进度
                exec_context = f"""命令已执行成功。

**执行的命令:** {command}

**执行结果:**
{result}

---

请继续完成用户的原始请求。

**用户原始请求:** {user_message}

**重要提醒:**
- 向目标收束，禁止发散思维
- 已完成的任务不要重复执行
- 继续执行下一个待完成任务
"""
                
                messages = self._build_messages_for_cancel(chat_history, exec_context, session_id)
                
                # 应用微观压缩
                messages = self._apply_micro_compact(messages)
                
                agent = self._get_agent_for_session(session_id)
                agent_result = agent.invoke({"messages": messages})
                output = stream_handler.extract_ai_message(agent_result)
                
                # 检查下一个确认请求
                confirmation_info = stream_handler.extract_confirmation_info(output)
                if confirmation_info:
                    # 保存当前的助手消息
                    self.session_store.add_message(session_id, "assistant", output)
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
                # 获取会话历史
                chat_history = self.session_store.get_messages(session_id)
                
                # 构建执行上下文，包含用户原始请求和当前进度
                exec_context = f"""命令已执行成功。

**执行的命令:** {command}

**执行结果:**
{result}

---

请继续完成用户的原始请求。

**用户原始请求:** {user_message}

**重要提醒:**
- 向目标收束，禁止发散思维
- 已完成的任务不要重复执行
- 继续执行下一个待完成任务
"""
                
                full_response = ""
                messages = self._build_messages_for_cancel(chat_history, exec_context, session_id)
                
                # 应用微观压缩
                messages = self._apply_micro_compact(messages)
                
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
                                # 保存当前的助手消息再返回
                                if full_response:
                                    self.session_store.add_message(session_id, "assistant", full_response)
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
                
                messages = self._build_messages_for_cancel(chat_history, cancel_context, session_id)
                
                # 应用微观压缩
                messages = self._apply_micro_compact(messages)
                
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
                f"任务执行已继续。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            messages = self._build_messages_for_cancel(chat_history, continue_context, session_id)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
            
            # 应用微观压缩
            messages = self._apply_micro_compact(messages)
            
            agent = self._get_agent_for_session(session_id)
            
            result = agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 1000}
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
                "message": "执行步数较多，是否继续执行？",
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
                f"任务执行已继续。\n"
                f"请继续完成之前的任务。如果任务已经完成，请总结结果。"
            )
            
            todo_mgr = get_todo_manager(session_id)
            reminder = todo_mgr.get_reminder_message()
            
            messages = self._build_messages_for_cancel(chat_history, continue_context, session_id)
            if reminder:
                messages.insert(1, SystemMessage(content=reminder))
            
            # 应用微观压缩
            messages = self._apply_micro_compact(messages)
            
            agent = self._get_agent_for_session(session_id)
            
            full_response = ""
            
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": 1000}
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
                "message": "执行步数较多，是否继续执行？",
                "partial_output": full_response
            }
            
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"继续执行失败: {str(e)}"
            }
    
    def continue_with_emergency_compact(
        self,
        session_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        """
        紧急压缩后继续执行任务
        
        当上下文超限后，用户选择继续时调用此方法
        
        Args:
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        self.clear_cancel_flag(session_id)
        
        overflow_state = self._context_overflow_states.pop(session_id, None)
        
        if not overflow_state:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": "没有找到上下文超限状态"
            }
            return
        
        try:
            # 执行紧急压缩
            compact_result = emergency_compact(
                session_id=session_id,
                llm_client=self.llm
            )
            
            if not compact_result.get("success"):
                yield {
                    "type": ChatResponseType.ERROR.value,
                    "content": f"紧急压缩失败：{compact_result.get('message')}"
                }
                return
            
            # 更新session_store
            from services.context.context_compactor import context_compactor
            chat_history, _ = self.session_store.get_full_context(session_id, overflow_state.get("user_input", ""))
            
            # 设置会话工具
            self._setup_session_tools(session_id)
            
            # 构建继续执行的上下文
            continue_context = f"""上下文已紧急压缩（保留了最近 {Config.EMERGENCY_COMPACT_KEEP_MESSAGES} 条消息）。

请继续完成用户的原始请求：{overflow_state.get('user_input', '')}

重要提醒：
- 向目标收束，禁止发散思维
- 只执行必需的操作
- 完成后立即返回结果
"""
            
            messages = self._build_messages_for_cancel(chat_history, continue_context, session_id)
            messages = self._apply_micro_compact(messages)
            
            agent = self._get_agent_for_session(session_id)
            full_response = ""
            
            for chunk in agent.stream(
                {"messages": messages},
                stream_mode=["messages", "updates"],
                config={"recursion_limit": 1000}
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
            
        except Exception as e:
            yield {
                "type": ChatResponseType.ERROR.value,
                "content": f"紧急压缩后继续执行失败: {str(e)}"
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
    
    # ==================== 团队模式方法 ====================
    
    def _get_agents_team(self, session_id: str) -> AgentsTeam:
        """
        获取或创建会话的AgentsTeam
        
        Args:
            session_id: 会话ID
            
        Returns:
            AgentsTeam实例
        """
        tools = tool_manager.get_tools_for_session(
            session_id,
            self.session_store,
            include_sub_agent=True
        )
        
        return get_agents_team(
            session_id=session_id,
            tools=tools,
            session_store=self.session_store,
            max_followers=self.MAX_FOLLOWERS
        )
    
    def chat_with_routing(
        self,
        user_input: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        带路由的对话执行（非流式）
        
        自动判断是否需要团队模式：
        1. 首次对话引导检测（最高优先级）
        2. 意图识别与路由
        3. 简单任务 -> 单Agent执行
        4. 复杂任务 -> 团队模式执行
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Returns:
            响应字典
        """
        # ========== 首次对话引导检测（最高优先级） ==========
        with db_manager.get_session() as db_session:
            if onboarding_service.need_onboarding(db_session):
                logger.info(f"[AgentService] 检测到首次对话，触发引导流程")
                greeting = onboarding_service.get_greeting()
                return {
                    "type": ChatResponseType.ONBOARDING_REQUIRED.value,
                    "message": greeting,
                    "session_id": session_id
                }
        
        if not self.TEAM_MODE_ENABLED:
            # 团队模式未启用，走原有流程
            return self.chat(user_input, session_id)
        
        try:
            # 获取AgentsTeam
            team = self._get_agents_team(session_id)
            
            # 获取对话历史
            chat_history, _ = self.session_store.get_full_context(session_id, user_input)
            
            # 路由决策
            result = team.process(user_input, chat_history)
            
            if result.get("mode") == "single_agent":
                # 单Agent模式，走原有流程
                logger.info(f"[AgentService] 路由决策: 单Agent模式")
                return self.chat(user_input, session_id)
            
            else:
                # 团队模式已执行完成
                logger.info(f"[AgentService] 团队模式执行完成")
                
                # 保存执行结果
                self._team_results[session_id] = result
                
                # 保存对话历史
                self.session_store.add_message(session_id, "user", user_input)
                
                # 格式化输出
                if result.get("success"):
                    output = result.get("final_output", "团队执行完成")
                else:
                    output = f"团队执行遇到问题：{result.get('error', '未知错误')}\n\n已完成的任务：\n" + "\n".join([
                        f"- {task_id}: {task_info.get('status')}"
                        for task_id, task_info in result.get("subtask_results", {}).items()
                    ])
                
                self.session_store.add_message(session_id, "assistant", output)
                
                return {
                    "type": ChatResponseType.RESPONSE.value,
                    "output": output,
                    "session_id": session_id,
                    "execution_mode": "team_mode",
                    "stats": result.get("stats"),
                    "decision": result.get("decision")
                }
                
        except Exception as e:
            logger.error(f"[AgentService] 团队模式执行失败，回退到单Agent模式: {e}")
            return self.chat(user_input, session_id)
    
    def chat_stream_with_routing(
        self,
        user_input: str,
        session_id: str
    ) -> Generator[Dict[str, Any], None, None]:
        """
        带路由的流式对话执行
        
        自动判断是否需要团队模式：
        1. 首次对话引导检测（最高优先级）
        2. 意图识别与路由
        3. 简单任务 -> 单Agent流式执行
        4. 复杂任务 -> 团队模式执行（实时推送进度）
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Yields:
            流式数据字典
        """
        # ========== 首次对话引导检测（最高优先级） ==========
        with db_manager.get_session() as db_session:
            if onboarding_service.need_onboarding(db_session):
                logger.info(f"[AgentService] 检测到首次对话，触发引导流程")
                greeting = onboarding_service.get_greeting()
                yield {
                    "type": ChatResponseType.ONBOARDING_REQUIRED.value,
                    "message": greeting,
                    "session_id": session_id
                }
                return
        
        if not self.TEAM_MODE_ENABLED:
            # 团队模式未启用，走原有流程
            yield from self.chat_stream(user_input, session_id)
            return
        
        try:
            # 获取AgentsTeam
            team = self._get_agents_team(session_id)
            
            # 获取对话历史
            chat_history, _ = self.session_store.get_full_context(session_id, user_input)
            
            # 使用流式路由处理
            final_output = None
            execution_stats = {}
            
            for progress in team.process_stream(user_input, chat_history):
                progress_type = progress.get("type")
                
                if progress_type == "routing_decision":
                    # 路由决策
                    if progress.get("mode") == "single_agent":
                        logger.info(f"[AgentService] 路由决策: 单Agent模式")
                        yield from self.chat_stream(user_input, session_id)
                        return
                    else:
                        logger.info(f"[AgentService] 路由决策: 团队模式")
                        yield {
                            "type": "team_mode_start",
                            "decision": {
                                "mode": progress.get("mode"),
                                "complexity_score": progress.get("complexity_score"),
                                "reasoning": progress.get("reasoning")
                            }
                        }
                
                elif progress_type == "single_agent_mode":
                    # 单Agent模式，走原有流程
                    yield from self.chat_stream(user_input, session_id)
                    return
                
                elif progress_type == "task_decomposition":
                    # 任务拆解中
                    yield {
                        "type": "team_progress",
                        "stage": "decomposition",
                        "message": progress.get("message", "正在拆解任务...")
                    }
                
                elif progress_type == "team_start":
                    # 团队执行开始
                    yield {
                        "type": "team_progress",
                        "stage": "start",
                        "goal": progress.get("goal"),
                        "total_tasks": progress.get("total_tasks"),
                        "parallel_groups": progress.get("parallel_groups")
                    }
                
                elif progress_type == "group_start":
                    # 并行组开始
                    logger.info(f"[AgentService] 转发 group_start 事件: 组 {progress.get('group_index')}, 任务数: {len(progress.get('tasks', []))}")
                    yield {
                        "type": "team_progress",
                        "stage": "group_start",
                        "group_index": progress.get("group_index"),
                        "total_groups": progress.get("total_groups"),
                        "tasks": progress.get("tasks")
                    }
                
                elif progress_type == "task_start":
                    # 任务开始
                    yield {
                        "type": "team_progress",
                        "stage": "task_start",
                        "task_id": progress.get("task_id"),
                        "description": progress.get("description"),
                        "batch_id": progress.get("batch_id")
                    }
                
                elif progress_type == "task_complete":
                    # 任务完成
                    yield {
                        "type": "team_progress",
                        "stage": "task_complete",
                        "task_id": progress.get("task_id"),
                        "success": progress.get("success"),
                        "summary": progress.get("summary"),
                        "batch_id": progress.get("batch_id")
                    }
                
                elif progress_type == "group_complete":
                    # 并行组完成
                    yield {
                        "type": "team_progress",
                        "stage": "group_complete",
                        "group_index": progress.get("group_index")
                    }
                
                elif progress_type == "team_integrating":
                    # 整合结果
                    yield {
                        "type": "team_progress",
                        "stage": "integrating",
                        "message": progress.get("message", "正在整合结果...")
                    }
                
                elif progress_type == "team_integrating_content":
                    # 流式整合结果内容
                    yield {
                        "type": "team_integrating_content",
                        "content": progress.get("content"),
                        "accumulated": progress.get("accumulated")
                    }
                
                elif progress_type == "team_complete":
                    # 团队执行完成
                    final_output = progress.get("output", "团队执行完成")
                    execution_stats = progress.get("stats", {})
                    
                    # 保存对话历史
                    self.session_store.add_message(session_id, "user", user_input)
                    self.session_store.add_message(session_id, "assistant", final_output)
                    
                    # 发送完成信号（不再重复流式输出，因为已经在 team_integrating_content 中流式输出了）
                    yield {
                        "type": ChatResponseType.DONE.value,
                        "content": final_output,
                        "execution_mode": "team_mode",
                        "stats": execution_stats
                    }
                
                elif progress_type == "team_error":
                    # 团队执行错误
                    error_msg = progress.get("error", "团队执行失败")
                    self.session_store.add_message(session_id, "user", user_input)
                    self.session_store.add_message(session_id, "assistant", f"团队执行遇到问题：{error_msg}")
                    
                    yield {
                        "type": ChatResponseType.ERROR.value,
                        "output": f"团队执行失败: {error_msg}"
                    }
            
        except Exception as e:
            logger.error(f"[AgentService] 团队模式执行失败，回退到单Agent模式: {e}")
            yield from self.chat_stream(user_input, session_id)
    
    def get_team_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取团队执行状态
        
        返回详细的进度信息，供前端轮询使用
        
        Args:
            session_id: 会话ID
            
        Returns:
            团队状态信息
        """
        try:
            team = self._get_agents_team(session_id)
            leader = team.leader
            task_board = leader.task_board
            plan = task_board.get_plan()
            
            if not plan:
                return {
                    "status": "idle",
                    "message": "当前没有执行计划"
                }
            
            # 获取进度信息
            progress = task_board.get_progress()
            
            # 构建任务列表
            tasks = []
            for group_idx, group in enumerate(plan.parallel_groups):
                group_tasks = []
                for task_id in group:
                    task = plan.subtasks.get(task_id)
                    if task:
                        task_info = {
                            "id": task_id,
                            "description": task.description,
                            "status": task.status.value,
                            "priority": task.priority.value
                        }
                        if task.result:
                            task_info["result"] = task.result[:200] if len(task.result) > 200 else task.result
                        if task.error:
                            task_info["error"] = task.error
                        if task.assigned_to:
                            task_info["assigned_to"] = task.assigned_to
                        group_tasks.append(task_info)
                tasks.append({
                    "group_index": group_idx + 1,
                    "total_groups": len(plan.parallel_groups),
                    "tasks": group_tasks
                })
            
            return {
                "status": "active",
                "goal": plan.goal,
                "total_tasks": len(plan.subtasks),
                "completed": progress.get("completed", 0),
                "in_progress": progress.get("in_progress", 0),
                "pending": progress.get("pending", 0),
                "failed": progress.get("failed", 0),
                "parallel_groups": len(plan.parallel_groups),
                "tasks": tasks,
                "execution_log": leader._execution_log[-10:] if leader._execution_log else []
            }
            
        except Exception as e:
            logger.warning(f"[AgentService] 获取团队状态失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def get_task_board_view(self, session_id: str) -> str:
        """
        获取任务看板视图
        
        Args:
            session_id: 会话ID
            
        Returns:
            格式化的任务看板字符串
        """
        try:
            team = self._get_agents_team(session_id)
            return team.get_task_board_view()
        except Exception as e:
            return f"获取任务看板失败: {e}"
    
    def cleanup_session(self, session_id: str) -> None:
        """
        清理会话相关的所有资源
        
        Args:
            session_id: 会话ID
        """
        # 清理原有的会话资源
        remove_todo_manager(session_id)
        remove_task_manager(session_id)
        clear_session_tools(session_id)
        
        # 清理团队模式资源
        remove_agents_team(session_id)
        
        # 清理状态
        if session_id in self._cancel_flags:
            del self._cancel_flags[session_id]
        if session_id in self._recursion_pause_states:
            del self._recursion_pause_states[session_id]
        if session_id in self._context_overflow_states:
            del self._context_overflow_states[session_id]
        if session_id in self._team_results:
            del self._team_results[session_id]
        
        logger.info(f"[AgentService] 会话 {session_id} 资源已清理")


__all__ = ['AgentService']
