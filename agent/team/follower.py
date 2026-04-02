"""
Follower Agent模块

实现Follower Agent的核心能力：
1. 从任务看板领取任务
2. 执行任务并汇报结果
3. 工具调用和技能使用
"""
import json
import logging
import threading
import asyncio
from typing import Dict, Any, List, Optional, Generator
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import uuid

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.errors import GraphRecursionError

from config import Config
from agent.team.types import (
    SubTask,
    TaskStatus,
    FollowerInfo,
    TeamResult
)
from agent.team.task_board import TaskBoard

logger = logging.getLogger(__name__)


# ==================== Follower系统提示词 ====================

FOLLOWER_SYSTEM_PROMPT = """你是一个专注的任务执行者（Follower Agent）。你的职责是从任务看板领取任务并执行。

## 核心行为准则

1. **向目标收束**：每次执行任务都要向目标收束，禁止发散思维
   - 明确任务的核心目标
   - 只执行达成目标所必需的操作
   - 达成目标后立即停止

2. **严格任务边界**：只执行任务描述中明确要求的内容，不要做任何"顺便"或"额外"的操作

3. **完成即停止**：任务完成后立即返回结果摘要

4. **遇到障碍即报告**：如果无法完成，立即返回失败报告，说明原因

## 任务执行流程

1. 接收任务描述和上下文
2. 分析任务需要的工具和步骤
3. 执行必要的操作
4. 返回执行结果摘要

## 输出格式

执行完成后，请按以下格式返回：

执行结果：[成功/失败]

关键产出：
- [产出的关键信息/文件/结果]

执行摘要：
[简要描述执行过程和结果，供Leader整合]
"""


class FollowerAgent:
    """
    Follower Agent
    
    职责：
    1. 从任务看板领取任务
    2. 执行任务（调用工具）
    3. 汇报执行结果
    """
    
    def __init__(
        self,
        follower_id: str,
        task_board: TaskBoard,
        tools: List,
        session_id: str = "default"
    ):
        """
        初始化Follower Agent
        
        Args:
            follower_id: Follower唯一标识
            task_board: 任务看板引用
            tools: 可用工具列表
            session_id: 会话ID
        """
        self.follower_id = follower_id
        self.task_board = task_board
        self.tools = tools
        self.session_id = session_id
        
        # 状态
        self._status = "idle"
        self._current_task: Optional[SubTask] = None
        self._completed_tasks: List[str] = []
        
        # 创建LLM和Agent
        from agent.llm import get_llm
        self.llm = get_llm(streaming=False)
        self.agent = create_react_agent(self.llm, tools)
    
    def get_info(self) -> FollowerInfo:
        """获取Follower信息"""
        return FollowerInfo(
            id=self.follower_id,
            status=self._status,
            current_task=self._current_task.id if self._current_task else None,
            completed_tasks=self._completed_tasks.copy(),
            tools=[getattr(t, 'name', str(t)) for t in self.tools]
        )
    
    def is_available(self) -> bool:
        """检查是否可用"""
        return self._status == "idle"
    
    def claim_and_execute(self) -> Optional[Dict[str, Any]]:
        """
        领取并执行任务
        
        Returns:
            执行结果，如果没有任务返回None
        """
        # 检查是否可用
        if not self.is_available():
            return None
        
        # 尝试领取任务
        ready_tasks = self.task_board.get_ready_tasks()
        if not ready_tasks:
            return None
        
        # 领取优先级最高的任务
        task = ready_tasks[0]
        claimed_task = self.task_board.claim_task(task.id, self.follower_id)
        
        if not claimed_task:
            return None
        
        # 更新状态
        self._status = "busy"
        self._current_task = claimed_task
        
        try:
            # 执行任务
            result = self._execute_task(claimed_task)
            
            # 更新任务状态
            if result.get("success"):
                self.task_board.complete_task(
                    claimed_task.id,
                    result.get("summary", ""),
                    self.follower_id
                )
                self._completed_tasks.append(claimed_task.id)
            else:
                self.task_board.fail_task(
                    claimed_task.id,
                    result.get("error", "执行失败"),
                    self.follower_id
                )
            
            return result
            
        except Exception as e:
            logger.error(f"[Follower {self.follower_id}] 执行任务异常: {e}")
            self.task_board.fail_task(
                claimed_task.id,
                str(e),
                self.follower_id
            )
            return {
                "success": False,
                "task_id": claimed_task.id,
                "error": str(e)
            }
            
        finally:
            # 重置状态
            self._status = "idle"
            self._current_task = None

    def execute_claimed_task(self, claimed_task: SubTask) -> Dict[str, Any]:
        """
        执行一个已经由外部完成 claim 的任务。
        用于确保 task_start/task_complete 的 task_id 与真实执行一致。
        """
        if not self.is_available():
            return {
                "success": False,
                "task_id": claimed_task.id,
                "error": "Follower is not available"
            }

        self._status = "busy"
        self._current_task = claimed_task

        try:
            result = self._execute_task(claimed_task)

            if result.get("success"):
                self.task_board.complete_task(
                    claimed_task.id,
                    result.get("summary", ""),
                    self.follower_id
                )
                self._completed_tasks.append(claimed_task.id)
            else:
                self.task_board.fail_task(
                    claimed_task.id,
                    result.get("error", "执行失败"),
                    self.follower_id
                )

            return result

        except Exception as e:
            logger.error(f"[Follower {self.follower_id}] 执行任务异常: {e}")
            self.task_board.fail_task(
                claimed_task.id,
                str(e),
                self.follower_id
            )
            return {
                "success": False,
                "task_id": claimed_task.id,
                "error": str(e)
            }

        finally:
            self._status = "idle"
            self._current_task = None
    
    def _execute_task(self, task: SubTask) -> Dict[str, Any]:
        """
        执行单个任务
        
        Args:
            task: 任务对象
            
        Returns:
            执行结果
        """
        logger.info(f"[Follower {self.follower_id}] 开始执行任务: {task.id}")
        
        # 构建消息
        messages = self._build_messages(task)
        
        tool_calls = []
        execution_log = []
        
        try:
            # 执行（使用更大的 recursion_limit，避免步数限制）
            result = self.agent.invoke(
                {"messages": messages},
                config={"recursion_limit": 1000}
            )
            
            # 提取结果
            if result and "messages" in result:
                # 记录工具调用
                for msg in result["messages"]:
                    if isinstance(msg, AIMessage):
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tool_calls.append({
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {})
                                })
                
                # 提取最终消息
                final_message = self._extract_final_message(result)
                steps_used = sum(1 for msg in result["messages"] if isinstance(msg, AIMessage))
                
                return {
                    "success": True,
                    "task_id": task.id,
                    "summary": final_message,
                    "tool_calls": tool_calls,
                    "steps_used": steps_used
                }
            
            return {
                "success": False,
                "task_id": task.id,
                "error": "未能获取执行结果"
            }
            
        except GraphRecursionError:
            return {
                "success": False,
                "task_id": task.id,
                "error": "达到递归限制（1000），任务过于复杂"
            }
            
        except Exception as e:
            logger.error(f"[Follower {self.follower_id}] 执行出错: {e}")
            return {
                "success": False,
                "task_id": task.id,
                "error": str(e)
            }
    
    def _build_messages(self, task: SubTask) -> List:
        """构建消息列表"""
        messages = [SystemMessage(content=FOLLOWER_SYSTEM_PROMPT)]
        
        # 构建任务描述
        task_content = f"""任务ID: {task.id}
任务描述: {task.description}
优先级: P{task.priority.value}
"""
        
        # 添加工具提示
        if task.tool_hints:
            task_content += f"\n建议工具: {', '.join(task.tool_hints)}"
        
        # 添加技能提示
        if task.skill_hint:
            task_content += f"\n建议技能: {task.skill_hint}"
        
        # 添加上下文
        if task.context:
            task_content += f"\n\n任务上下文:\n{json.dumps(task.context, ensure_ascii=False, indent=2)}"
        
        # 添加依赖结果（如果有）
        if task.dependencies:
            task_content += "\n\n依赖任务的执行结果:"
            plan = self.task_board.get_plan()
            if plan:
                for dep_id in task.dependencies:
                    dep_task = plan.subtasks.get(dep_id)
                    if dep_task and dep_task.result:
                        task_content += f"\n[{dep_id}] {dep_task.result[:500]}"
        
        messages.append(HumanMessage(content=task_content))
        return messages
    
    def _extract_final_message(self, result: Dict) -> str:
        """提取最终消息"""
        if result and "messages" in result:
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage):
                    return msg.content
        return ""


class FollowerPool:
    """
    Follower池
    
    管理多个Follower Agent，支持并行任务执行
    """
    
    def __init__(
        self,
        task_board: TaskBoard,
        tools: List,
        session_id: str = "default",
        max_followers: int = 3
    ):
        """
        初始化Follower池
        
        Args:
            task_board: 任务看板
            tools: 可用工具列表
            session_id: 会话ID
            max_followers: 最大Follower数量
        """
        self.task_board = task_board
        self.tools = tools
        self.session_id = session_id
        self.max_followers = max_followers
        
        self._followers: Dict[str, FollowerAgent] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_followers)
    
    def get_or_create_follower(self) -> Optional[FollowerAgent]:
        """
        获取或创建可用的Follower
        
        Returns:
            可用的Follower，如果没有返回None
        """
        with self._lock:
            # 查找空闲的Follower
            for follower in self._followers.values():
                if follower.is_available():
                    return follower
            
            # 创建新的Follower
            if len(self._followers) < self.max_followers:
                follower_id = f"follower_{uuid.uuid4().hex[:8]}"
                follower = FollowerAgent(
                    follower_id=follower_id,
                    task_board=self.task_board,
                    tools=self.tools,
                    session_id=self.session_id
                )
                self._followers[follower_id] = follower
                logger.info(f"[FollowerPool] 创建新Follower: {follower_id}")
                return follower
            
            return None
    
    def execute_parallel(self) -> List[Dict[str, Any]]:
        """
        并行执行就绪的任务
        
        改进：正确处理超时，确保任务状态一致性
        
        Returns:
            执行结果列表
        """
        results = []
        future_follower_map = {}  # future -> follower 映射
        
        # 获取就绪任务数量
        ready_tasks = self.task_board.get_ready_tasks()
        if not ready_tasks:
            return results
        
        # 为每个就绪任务分配Follower
        for _ in range(min(len(ready_tasks), self.max_followers)):
            follower = self.get_or_create_follower()
            if follower:
                future = self._executor.submit(follower.claim_and_execute)
                future_follower_map[future] = follower
        
        # 收集结果（使用更长的超时，让任务有足够时间完成）
        for future, follower in future_follower_map.items():
            try:
                result = future.result(timeout=Config.SUB_AGENT_FORK_TIMEOUT)
                if result:
                    results.append(result)
            except FuturesTimeoutError:
                # 超时：任务执行时间过长
                logger.error(f"[FollowerPool] Follower {follower.follower_id} 执行超时")
                # 检查 follower 是否还在执行任务
                if follower._current_task:
                    task_id = follower._current_task.id
                    logger.error(f"[FollowerPool] 任务 {task_id} 执行超时，标记为失败")
                    # 标记任务失败
                    self.task_board.fail_task(
                        task_id,
                        f"任务执行超时（超过 {Config.SUB_AGENT_FORK_TIMEOUT} 秒）",
                        follower.follower_id
                    )
                    # 重置 follower 状态
                    follower._status = "idle"
                    follower._current_task = None
                    results.append({
                        "success": False,
                        "task_id": task_id,
                        "error": f"执行超时（{Config.SUB_AGENT_FORK_TIMEOUT}秒）"
                    })
                # 尝试取消 future（如果还在运行）
                future.cancel()
            except Exception as e:
                logger.error(f"[FollowerPool] 任务执行异常: {e}")
                # 确保 follower 状态被重置
                if follower._current_task:
                    self.task_board.fail_task(
                        follower._current_task.id,
                        str(e),
                        follower.follower_id
                    )
                    follower._status = "idle"
                    follower._current_task = None
        
        return results
    
    def execute_parallel_stream(self, batch_id: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        流式并行执行就绪的任务
        
        实时 yield 任务开始和完成事件，解决阻塞问题
        
        Yields:
            事件字典，包含 task_start 或 task_complete 类型
        """
        # 获取就绪任务
        ready_tasks = self.task_board.get_ready_tasks()
        if not ready_tasks:
            return

        future_map: Dict[Future, Dict[str, Any]] = {}

        # 先 claim 再 start，确保事件 task_id 与真实执行一致
        for task in ready_tasks[:self.max_followers]:
            follower = self.get_or_create_follower()
            if not follower:
                continue

            claimed_task = self.task_board.claim_task(task.id, follower.follower_id)
            if not claimed_task:
                continue

            start_event: Dict[str, Any] = {
                "type": "task_start",
                "task_id": claimed_task.id,
                "description": claimed_task.description
            }
            if batch_id is not None:
                start_event["batch_id"] = batch_id
            yield start_event

            future = self._executor.submit(follower.execute_claimed_task, claimed_task)
            future_map[future] = {
                "follower": follower,
                "task_id": claimed_task.id
            }

        # 收集结果
        for future, meta in future_map.items():
            follower: FollowerAgent = meta["follower"]
            task_id: str = meta["task_id"]
            try:
                result = future.result(timeout=Config.SUB_AGENT_FORK_TIMEOUT)
                if result:
                    complete_event: Dict[str, Any] = {
                        "type": "task_complete",
                        "task_id": result.get("task_id"),
                        "success": result.get("success"),
                        "summary": result.get("summary", "")[:200]
                    }
                    if batch_id is not None:
                        complete_event["batch_id"] = batch_id
                    yield complete_event
            except FuturesTimeoutError:
                logger.error(f"[FollowerPool] Follower {follower.follower_id} 执行超时")
                self.task_board.fail_task(
                    task_id,
                    f"任务执行超时（超过 {Config.SUB_AGENT_FORK_TIMEOUT} 秒）",
                    follower.follower_id
                )
                follower._status = "idle"
                follower._current_task = None
                timeout_event: Dict[str, Any] = {
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": False,
                    "summary": f"执行超时（{Config.SUB_AGENT_FORK_TIMEOUT}秒）"
                }
                if batch_id is not None:
                    timeout_event["batch_id"] = batch_id
                yield timeout_event
                future.cancel()
            except Exception as e:
                logger.error(f"[FollowerPool] 任务执行异常: {e}")
                self.task_board.fail_task(
                    task_id,
                    str(e),
                    follower.follower_id
                )
                follower._status = "idle"
                follower._current_task = None
                error_event: Dict[str, Any] = {
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": False,
                    "summary": str(e)
                }
                if batch_id is not None:
                    error_event["batch_id"] = batch_id
                yield error_event
    
    def execute_sequential(self) -> List[Dict[str, Any]]:
        """
        顺序执行所有就绪任务
        
        Returns:
            执行结果列表
        """
        results = []
        
        while True:
            # 获取就绪任务
            ready_tasks = self.task_board.get_ready_tasks()
            if not ready_tasks:
                break
            
            # 获取可用Follower
            follower = self.get_or_create_follower()
            if not follower:
                logger.warning("[FollowerPool] 没有可用的Follower")
                break
            
            # 执行任务
            result = follower.claim_and_execute()
            if result:
                results.append(result)
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """获取池状态"""
        with self._lock:
            followers_info = [
                follower.get_info().to_dict()
                for follower in self._followers.values()
            ]
            
            available = sum(1 for f in self._followers.values() if f.is_available())
            
            return {
                "total_followers": len(self._followers),
                "max_followers": self.max_followers,
                "available": available,
                "busy": len(self._followers) - available,
                "followers": followers_info
            }
    
    def shutdown(self):
        """关闭池"""
        self._executor.shutdown(wait=False)
        self._followers.clear()


# 导出
__all__ = [
    'FollowerAgent',
    'FollowerPool',
    'FOLLOWER_SYSTEM_PROMPT'
]
