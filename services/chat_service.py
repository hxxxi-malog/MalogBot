"""
对话服务模块

实现Agent Loop核心逻辑：
1. 用户消息 -> LLM -> 工具调用
2. 捕获中间步骤（思考、工具调用、执行结果）
3. 检测工具返回中的危险命令标记
4. 返回给前端等待用户确认
5. 用户确认后执行命令
"""
import json
from typing import List, Dict, Any, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from agent.llm import get_llm
from agent.tools.bash import execute_bash, execute_confirmed_bash, DANGEROUS_COMMAND_MARKER


class AgentStepCallback(BaseCallbackHandler):
    """
    自定义回调处理器，用于捕获Agent执行过程中的中间步骤
    """
    
    def __init__(self):
        self.steps = []
        self.current_step = None
    
    def on_llm_start(self, serialized, prompts, **kwargs):
        """LLM开始生成"""
        self.steps.append({
            "type": "thinking",
            "content": "正在思考..."
        })
    
    def on_llm_end(self, response, **kwargs):
        """LLM生成完成"""
        pass
    
    def on_tool_start(self, serialized, input_str, **kwargs):
        """工具开始执行"""
        tool_name = serialized.get("name", "unknown_tool")
        self.current_step = {
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_input": input_str,
            "content": f"🔧 调用工具: {tool_name}"
        }
        self.steps.append(self.current_step)
    
    def on_tool_end(self, output, **kwargs):
        """工具执行完成"""
        if self.current_step:
            self.current_step["tool_output"] = output
            self.current_step["content"] += f"\n✅ 执行完成"
    
    def on_tool_error(self, error, **kwargs):
        """工具执行错误"""
        if self.current_step:
            self.current_step["error"] = str(error)
            self.current_step["content"] += f"\n❌ 执行失败: {error}"
    
    def get_steps(self):
        """获取所有步骤"""
        return self.steps
    
    def clear_steps(self):
        """清空步骤"""
        self.steps = []
        self.current_step = None


class ChatService:
    """对话服务类"""
    
    def __init__(self):
        """初始化对话服务"""
        self.llm = get_llm()
        self.tools = [execute_bash]
        
        # 创建回调处理器
        self.callback = AgentStepCallback()
        
        # 使用langgraph创建agent (新版langchain推荐)
        self.agent = create_react_agent(self.llm, self.tools)
        
        # MVP阶段：使用内存存储对话历史
        # key: session_id, value: 消息列表
        self._sessions: Dict[str, List[Dict]] = {}
    
    def chat(self, user_input: str, session_id: str = "default") -> Dict[str, Any]:
        """
        执行对话
        
        Args:
            user_input: 用户输入
            session_id: 会话ID
            
        Returns:
            包含输出和状态的字典：
            - type: "response" | "dangerous_command"
            - output: 助手回复（正常情况）
            - steps: 执行过程（思考、工具调用等）
            - command: 危险命令（需要确认时）
            - reason: 危险原因
        """
        # 清空调用历史
        self.callback.clear_steps()
        
        # 获取或创建会话历史
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        
        chat_history = self._sessions[session_id]
        
        try:
            # 使用langgraph调用agent
            from langchain_core.messages import HumanMessage
            
            messages = self._convert_to_langchain_messages(chat_history)
            messages.append(HumanMessage(content=user_input))
            
            result = self.agent.invoke({"messages": messages})
            
            # 提取最终输出
            output = ""
            if result and "messages" in result:
                # 获取最后一条AI消息
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        output = msg.content
                        break
            
            # 构建执行过程信息
            steps = self.callback.get_steps()
            
            # 检查输出中是否包含危险命令标记
            dangerous_info = self._extract_dangerous_command(output)
            
            if dangerous_info:
                # 返回危险命令确认请求
                return {
                    "type": "dangerous_command",
                    "command": dangerous_info["command"],
                    "reason": dangerous_info["reason"],
                    "message": dangerous_info["message"],
                    "steps": steps,
                    "session_id": session_id
                }
            
            # 更新对话历史
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": output})
            
            return {
                "type": "response",
                "output": output,
                "steps": steps,
                "session_id": session_id
            }
            
        except Exception as e:
            error_msg = f"执行出错: {str(e)}"
            return {
                "type": "error",
                "output": error_msg,
                "steps": self.callback.get_steps(),
                "session_id": session_id
            }
    
    def confirm_dangerous_command(
        self, 
        command: str, 
        session_id: str = "default",
        user_message: str = ""
    ) -> Dict[str, Any]:
        """
        执行用户确认的危险命令
        
        Args:
            command: 用户确认的命令
            session_id: 会话ID
            user_message: 用户原始消息（用于继续对话）
            
        Returns:
            执行结果
        """
        # 清空调用历史
        self.callback.clear_steps()
        
        try:
            # 记录步骤：用户确认
            self.callback.steps.append({
                "type": "user_confirm",
                "content": f"⚠️ 用户确认执行危险命令",
                "command": command
            })
            
            # 直接执行命令
            result = execute_confirmed_bash(command)
            
            # 记录步骤：执行结果
            self.callback.steps.append({
                "type": "tool_output",
                "content": f"📋 命令执行结果",
                "output": result
            })
            
            # 如果有用户消息，继续对话
            if user_message:
                # 将工具执行结果添加到历史
                chat_history = self._sessions.get(session_id, [])
                chat_history.append({
                    "role": "tool",
                    "content": f"命令已执行: {command}\n结果: {result}"
                })
                
                # 继续Agent循环
                agent_result = self.executor.invoke({
                    "input": user_message,
                    "chat_history": self._convert_to_langchain_messages(chat_history)
                })
                
                output = agent_result.get("output", "")
                intermediate_steps = agent_result.get("intermediate_steps", [])
                steps = self._build_steps_info(intermediate_steps)
                
                # 更新历史
                chat_history.append({"role": "assistant", "content": output})
                
                return {
                    "type": "response",
                    "output": output,
                    "steps": steps,
                    "session_id": session_id
                }
            
            return {
                "type": "response",
                "output": f"命令已执行:\n```\n{command}\n```\n\n结果:\n{result}",
                "steps": self.callback.get_steps(),
                "session_id": session_id
            }
            
        except Exception as e:
            return {
                "type": "error",
                "output": f"执行命令失败: {str(e)}",
                "steps": self.callback.get_steps(),
                "session_id": session_id
            }
    
    def get_history(self, session_id: str = "default") -> List[Dict]:
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
    
    def _convert_to_langchain_messages(self, messages: List[Dict]) -> List:
        """
        转换消息格式为LangChain消息对象
        
        Args:
            messages: 消息列表（字典格式）
            
        Returns:
            LangChain消息对象列表
        """
        result = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            elif role == "system":
                result.append(SystemMessage(content=content))
            elif role == "tool":
                # 工具消息需要特殊处理
                result.append(ToolMessage(content=content, tool_call_id=""))
        
        return result
    
    def _extract_dangerous_command(self, output: str) -> Optional[Dict]:
        """
        从输出中提取危险命令信息
        
        Args:
            output: Agent输出
            
        Returns:
            如果包含危险命令标记，返回命令信息；否则返回None
        """
        try:
            # 尝试解析JSON格式的危险命令标记
            if DANGEROUS_COMMAND_MARKER in output:
                # 提取JSON部分
                start_idx = output.find('{')
                end_idx = output.rfind('}') + 1
                
                if start_idx != -1 and end_idx > start_idx:
                    json_str = output[start_idx:end_idx]
                    data = json.loads(json_str)
                    
                    if data.get("type") == DANGEROUS_COMMAND_MARKER:
                        return {
                            "command": data.get("command"),
                            "reason": data.get("reason"),
                            "message": data.get("message")
                        }
        except (json.JSONDecodeError, KeyError) as e:
            # 解析失败，忽略
            pass
        
        return None
    
    def _build_steps_info(self, intermediate_steps: List) -> List[Dict]:
        """
        构建执行步骤信息
        
        Args:
            intermediate_steps: LangChain返回的中间步骤
            
        Returns:
            格式化的步骤信息列表
        """
        steps = []
        
        # 添加回调捕获的步骤
        steps.extend(self.callback.get_steps())
        
        # 添加中间步骤的详细信息
        for step in intermediate_steps:
            action, observation = step
            
            # 解析action
            if hasattr(action, 'tool'):
                tool_name = action.tool
                tool_input = action.tool_input
            else:
                tool_name = "unknown"
                tool_input = str(action)
            
            # 创建步骤信息
            step_info = {
                "type": "intermediate_step",
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": str(observation),
                "content": f"🔧 执行工具: {tool_name}"
            }
            
            steps.append(step_info)
        
        return steps


# 创建全局实例
chat_service = ChatService()


# 导出
__all__ = ['ChatService', 'chat_service', 'AgentStepCallback']
