"""
Leader Agent模块

实现Leader Agent的核心能力：
1. 任务拆解与DAG构建
2. Agent池管理
3. 任务调度与监控
4. 结果整合与冲突检测
"""
import json
import logging
import time
from typing import Dict, Any, List, Optional, Generator
from datetime import datetime
from concurrent.futures import Future

from langchain_core.messages import HumanMessage, SystemMessage

from agent.team.types import (
    SubTask,
    TaskStatus,
    TaskPriority,
    DAGPlan,
    TeamResult,
    ExecutionMode
)
from agent.team.router import IntentRouter, RoutingDecision
from agent.team.task_board import TaskBoard
from agent.team.follower import FollowerPool

logger = logging.getLogger(__name__)


# ==================== 任务拆解系统提示词 ====================

DECOMPOSITION_SYSTEM_PROMPT = """你是一个任务规划专家，负责将复杂任务拆解为可执行的子任务。

## 你的任务

分析用户的目标，将其拆解为具体的子任务。每个子任务应该：
1. 明确、可执行
2. 有清晰的完成标准
3. 标注与其他任务的依赖关系

## 输出格式

请以JSON格式输出子任务列表：
```json
{
    "subtasks": [
        {
            "id": "task_1",
            "description": "任务描述",
            "dependencies": [],
            "priority": "high|medium|low",
            "tool_hints": ["建议使用的工具"],
            "skill_hint": "建议使用的技能（可选）",
            "context": {"额外上下文": "值"}
        },
        {
            "id": "task_2",
            "description": "任务描述",
            "dependencies": ["task_1"],
            "priority": "medium",
            "tool_hints": ["工具名"]
        }
    ],
    "execution_strategy": "parallel|sequential",
    "estimated_total_steps": 10,
    "notes": "规划说明"
}
```

## 规划原则

1. **依赖最小化**：尽量减少任务间的依赖，提高并行度
2. **粒度适中**：每个任务应该是可独立执行的最小单元
3. **优先级合理**：关键路径上的任务应该有更高优先级
4. **工具提示**：为每个任务建议可能需要的工具

## 任务依赖规则

- 只有当任务A的输出是任务B的输入时，才需要依赖关系
- 没有依赖关系的任务应该可以并行执行
- 避免循环依赖

只输出JSON，不要输出其他内容。
"""


# ==================== 结果整合系统提示词 ====================

INTEGRATION_SYSTEM_PROMPT = """你是一个结果整合专家，负责将多个子任务的执行结果整合为最终答案。

## 你的任务

分析所有子任务的执行结果，生成：
1. 任务整体完成情况
2. 关键发现和产出
3. 最终答案或建议

## 输出格式

请以JSON格式输出整合结果：
```json
{
    "overall_success": true,
    "summary": "任务整体完成情况描述",
    "key_findings": ["发现1", "发现2"],
    "deliverables": ["产出1", "产出2"],
    "recommendations": ["建议1", "建议2"],
    "final_answer": "给用户的最终答案"
}
```

## 整合原则

1. **保持一致性**：确保各子任务结果逻辑一致
2. **检测冲突**：发现并标注相互矛盾的结论
3. **提炼要点**：提取对用户最有价值的信息
4. **结构清晰**：组织成易于理解的形式

只输出JSON，不要输出其他内容。
"""

INTEGRATION_MARKDOWN_SYSTEM_PROMPT = """你是一个结果整合专家，负责将多个子任务的执行结果整合为最终答复（面向用户阅读）。

## 输出要求（Markdown）
- 仅输出 Markdown（不要输出 JSON）
- 结构清晰、信息密度高、避免冗长
- 如果有失败/不确定之处，要明确标注

## 建议结构
## Summary
- ...

## Key findings
- ...

## Deliverables
- ...

## Recommendations
- ...

## Final answer
（给用户的最终答复）
"""


class LeaderAgent:
    """
    Leader Agent
    
    核心职责：
    1. 意图识别与路由
    2. 任务拆解与DAG构建
    3. Follower调度与监控
    4. 结果整合与冲突检测
    """
    
    def __init__(
        self,
        session_id: str,
        tools: List,
        session_store=None,
        max_followers: int = 3
    ):
        """
        初始化Leader Agent
        
        Args:
            session_id: 会话ID
            tools: 可用工具列表
            session_store: 会话存储
            max_followers: 最大Follower数量
        """
        self.session_id = session_id
        self.tools = tools
        self.session_store = session_store
        self.max_followers = max_followers
        
        # 核心组件
        from agent.llm import get_llm
        self.llm = get_llm(streaming=False)
        self.router = IntentRouter(self.llm)
        self.task_board = TaskBoard()
        self.follower_pool: Optional[FollowerPool] = None
        
        # 执行状态
        self._current_plan: Optional[DAGPlan] = None
        self._execution_log: List[str] = []
        self._start_time: Optional[float] = None
        self._runtime_batch_seq: int = 0
    
    def route(
        self,
        user_input: str,
        chat_history: List[Dict] = None
    ) -> RoutingDecision:
        """
        路由决策
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            
        Returns:
            路由决策
        """
        available_tools = [getattr(t, 'name', str(t)) for t in self.tools]
        return self.router.analyze(user_input, chat_history, available_tools)
    
    def decompose_task(
        self,
        goal: str,
        context: str = ""
    ) -> DAGPlan:
        """
        任务拆解
        
        将复杂目标拆解为子任务，构建DAG依赖图
        
        Args:
            goal: 用户目标
            context: 额外上下文
            
        Returns:
            DAG执行计划
        """
        logger.info(f"[Leader] 开始拆解任务: {goal}")
        
        # 使用LLM进行任务拆解
        decomposition = self._llm_decompose(goal, context)
        
        # 创建DAG计划
        plan = self.task_board.create_plan(goal, decomposition)
        self._current_plan = plan
        
        self._log(f"任务拆解完成: {len(plan.subtasks)}个子任务")
        self._log(f"可并行组数: {len(plan.parallel_groups)}")
        
        return plan
    
    def _llm_decompose(
        self,
        goal: str,
        context: str = ""
    ) -> List[Dict[str, Any]]:
        """
        使用LLM进行任务拆解
        """
        prompt = f"""请分析以下目标，将其拆解为具体的子任务。

目标：
{goal}
"""
        
        if context:
            prompt += f"""
上下文：
{context}
"""
        
        # 添加可用工具信息
        available_tools = [getattr(t, 'name', str(t)) for t in self.tools]
        prompt += f"""
可用工具：
{', '.join(available_tools)}
"""
        
        messages = [
            SystemMessage(content=DECOMPOSITION_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result_text = response.content
            
            # 解析JSON
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = result_text[json_start:json_end]
                result = json.loads(json_str)
                
                subtasks = result.get("subtasks", [])
                self._log(f"执行策略: {result.get('execution_strategy', 'sequential')}")
                
                return subtasks
                
        except json.JSONDecodeError as e:
            logger.warning(f"[Leader] JSON解析失败: {e}")
        except Exception as e:
            logger.error(f"[Leader] 任务拆解失败: {e}")
        
        # 默认拆解：单个任务
        return [{
            "id": "task_1",
            "description": goal,
            "dependencies": [],
            "priority": "high"
        }]
    
    def execute_team(
        self,
        parallel: bool = True
    ) -> TeamResult:
        """
        执行团队任务
        
        Args:
            parallel: 是否并行执行
            
        Returns:
            团队执行结果
        """
        self._start_time = time.time()
        
        # 初始化Follower池
        self.follower_pool = FollowerPool(
            task_board=self.task_board,
            tools=self.tools,
            session_id=self.session_id,
            max_followers=self.max_followers
        )
        
        self._log("开始团队执行")
        
        try:
            if parallel:
                results = self._execute_parallel()
            else:
                results = self._execute_sequential()
            
            # 整合结果
            final_result = self._integrate_results()
            
            return final_result
            
        finally:
            # 清理
            if self.follower_pool:
                self.follower_pool.shutdown()
    
    def _execute_parallel(self) -> List[Dict[str, Any]]:
        """
        并行执行
        
        改进：确保正确等待所有任务完成
        
        按并行组执行任务
        """
        all_results = []
        
        if not self._current_plan:
            return all_results
        
        for group_idx, group in enumerate(self._current_plan.parallel_groups):
            self._log(f"执行并行组 {group_idx + 1}/{len(self._current_plan.parallel_groups)}: {group}")
            
            # 执行当前组，确保所有任务完成
            max_iterations = 100  # 防止无限循环
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                
                # 获取就绪任务
                ready_tasks = self.task_board.get_ready_tasks()
                
                if not ready_tasks:
                    # 没有就绪任务，检查是否所有任务都已完成
                    progress = self.task_board.get_progress()
                    in_progress = progress.get("in_progress", 0)
                    
                    if in_progress == 0:
                        # 当前组所有任务已完成
                        break
                    
                    # 还有任务在执行中，等待
                    time.sleep(0.5)
                    continue
                
                # 执行就绪任务
                results = self.follower_pool.execute_parallel()
                all_results.extend(results)
            
            self._log(f"并行组 {group_idx + 1} 完成")
        
        return all_results
    
    def _execute_sequential(self) -> List[Dict[str, Any]]:
        """
        顺序执行
        """
        return self.follower_pool.execute_sequential()
    
    def _integrate_results(self) -> TeamResult:
        """
        整合结果
        
        汇总所有子任务结果，生成最终答案
        """
        if not self._current_plan:
            return TeamResult(
                success=False,
                goal="",
                final_output="没有执行计划",
                subtask_results={},
                execution_log=self._execution_log,
                total_time=0,
                followers_used=0,
                parallelism_achieved=0
            )
        
        # 收集子任务结果
        subtask_results = {}
        for task_id, task in self._current_plan.subtasks.items():
            subtask_results[task_id] = {
                "description": task.description,
                "status": task.status.value,
                "result": task.result,
                "error": task.error
            }
        
        # 检查整体成功
        all_completed = all(
            task.status == TaskStatus.COMPLETED
            for task in self._current_plan.subtasks.values()
        )
        
        # 使用LLM整合结果
        final_output = self._llm_integrate(
            self._current_plan.goal,
            subtask_results
        )
        
        # 计算统计信息
        total_time = time.time() - self._start_time if self._start_time else 0
        followers_used = self.max_followers if self.follower_pool else 0
        parallelism_achieved = max(
            len(group) for group in self._current_plan.parallel_groups
        ) if self._current_plan.parallel_groups else 1
        
        return TeamResult(
            success=all_completed,
            goal=self._current_plan.goal,
            final_output=final_output,
            subtask_results=subtask_results,
            execution_log=self._execution_log,
            total_time=total_time,
            followers_used=followers_used,
            parallelism_achieved=parallelism_achieved
        )
    
    def _integrate_results_stream(self) -> Generator[str, None, None]:
        """
        流式整合结果
        
        使用流式LLM调用，逐步返回整合结果
        """
        if not self._current_plan:
            yield "没有执行计划"
            return
        
        # 收集子任务结果
        subtask_results = {}
        for task_id, task in self._current_plan.subtasks.items():
            subtask_results[task_id] = {
                "description": task.description,
                "status": task.status.value,
                "result": task.result,
                "error": task.error
            }
        
        
        # 格式化子任务结果
        results_text = ""
        for task_id, result in subtask_results.items():
            results_text += f"""
任务 {task_id}: {result['description']}
状态: {result['status']}
结果: {result.get('result', '无')[:500]}
"""
            if result.get('error'):
                results_text += f"错误: {result['error']}\n"
        
        prompt = f"""请整合以下子任务的执行结果。

原始目标：
{self._current_plan.goal}

子任务执行结果：
{results_text}
"""
        
        messages = [
            SystemMessage(content=INTEGRATION_MARKDOWN_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        try:
            # 使用流式LLM
            from agent.llm import get_llm
            streaming_llm = get_llm(streaming=True)
            
            accumulated = ""
            for chunk in streaming_llm.stream(messages):
                if chunk.content:
                    accumulated += chunk.content
                    yield chunk.content
                    
        except Exception as e:
            logger.error(f"[Leader] 流式结果整合失败: {e}")
            yield f"任务执行完成。\n\n" + "\n".join([
                f"- {r['description']}: {r['status']}"
                for r in subtask_results.values()
            ])

    def _llm_integrate_json(self, goal: str, subtask_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用 LLM 产出结构化整合结果（JSON）。
        该结果用于统计/后续自动化，不直接面向用户渲染。
        """
        # 格式化子任务结果
        results_text = ""
        for task_id, result in subtask_results.items():
            results_text += f"""
任务 {task_id}: {result['description']}
状态: {result['status']}
结果: {str(result.get('result', '无'))[:500]}
"""
            if result.get('error'):
                results_text += f"错误: {result['error']}\n"

        prompt = f"""请整合以下子任务的执行结果。

原始目标：
{goal}

子任务执行结果：
{results_text}
"""

        messages = [
            SystemMessage(content=INTEGRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]

        try:
            response = self.llm.invoke(messages)
            result_text = response.content or ""

            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                json_str = result_text[json_start:json_end]
                return json.loads(json_str)
        except Exception as e:
            logger.warning(f"[Leader] JSON整合失败，返回降级结构: {e}")

        return {
            "overall_success": False,
            "summary": "integration_json 生成失败（已降级）",
            "key_findings": [],
            "deliverables": [],
            "recommendations": [],
            "final_answer": ""
        }
    
    def _llm_integrate(
        self,
        goal: str,
        subtask_results: Dict[str, Any]
    ) -> str:
        """
        使用LLM整合结果
        """
        # 格式化子任务结果
        results_text = ""
        for task_id, result in subtask_results.items():
            results_text += f"""
任务 {task_id}: {result['description']}
状态: {result['status']}
结果: {result.get('result', '无')[:500]}
"""
            if result.get('error'):
                results_text += f"错误: {result['error']}\n"
        
        prompt = f"""请整合以下子任务的执行结果。

原始目标：
{goal}

子任务执行结果：
{results_text}
"""
        
        messages = [
            SystemMessage(content=INTEGRATION_SYSTEM_PROMPT),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result_text = response.content
            
            # 解析JSON
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = result_text[json_start:json_end]
                result = json.loads(json_str)
                
                # 构建最终输出
                output_parts = []
                
                if result.get("summary"):
                    output_parts.append(f"整体情况: {result['summary']}")
                
                if result.get("key_findings"):
                    output_parts.append("\n关键发现:")
                    for finding in result["key_findings"]:
                        output_parts.append(f"  - {finding}")
                
                if result.get("deliverables"):
                    output_parts.append("\n产出物:")
                    for item in result["deliverables"]:
                        output_parts.append(f"  - {item}")
                
                if result.get("final_answer"):
                    output_parts.append(f"\n{result['final_answer']}")
                
                return "\n".join(output_parts)
                
        except Exception as e:
            logger.error(f"[Leader] 结果整合失败: {e}")
        
        # 返回原始结果摘要
        return f"任务执行完成。\n\n" + "\n".join([
            f"- {r['description']}: {r['status']}"
            for r in subtask_results.values()
        ])
    
    def monitor(self) -> Dict[str, Any]:
        """
        监控执行状态
        
        Returns:
            当前执行状态
        """
        progress = self.task_board.get_progress()
        
        status = {
            "session_id": self.session_id,
            "plan": self._current_plan.to_dict() if self._current_plan else None,
            "progress": progress,
            "execution_log": self._execution_log[-10:],  # 最近10条日志
            "follower_pool": self.follower_pool.get_status() if self.follower_pool else None
        }
        
        return status
    
    def _log(self, message: str):
        """记录执行日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self._execution_log.append(log_entry)
        logger.info(f"[Leader] {message}")
    
    def execute_team_stream(
        self,
        parallel: bool = True
    ) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行团队任务，实时推送进度
        
        Args:
            parallel: 是否并行执行
            
        Yields:
            进度更新字典
        """
        self._start_time = time.time()
        
        # 初始化Follower池
        self.follower_pool = FollowerPool(
            task_board=self.task_board,
            tools=self.tools,
            session_id=self.session_id,
            max_followers=self.max_followers
        )
        
        # 发送开始信号
        yield {
            "type": "team_start",
            "goal": self._current_plan.goal if self._current_plan else "",
            "total_tasks": len(self._current_plan.subtasks) if self._current_plan else 0,
            "parallel_groups": len(self._current_plan.parallel_groups) if self._current_plan else 0
        }
        
        try:
            if parallel:
                yield from self._execute_parallel_stream()
            else:
                yield from self._execute_sequential_stream()
            
            # 整合结果（流式）
            yield {"type": "team_integrating", "message": "正在整合结果..."}
            
            # 流式输出整合结果
            integrated_output = ""
            for chunk in self._integrate_results_stream():
                integrated_output += chunk
                yield {
                    "type": "team_integrating_content",
                    "content": chunk,
                    "accumulated": integrated_output
                }
            
            # 计算统计信息
            total_time = time.time() - self._start_time if self._start_time else 0
            all_completed = all(
                task.status == TaskStatus.COMPLETED
                for task in self._current_plan.subtasks.values()
            ) if self._current_plan else False

            # 额外生成结构化 JSON 结果（不影响 Markdown 流式展示）
            integration_json = {}
            try:
                subtask_results_json = {}
                for task_id, task in self._current_plan.subtasks.items():
                    subtask_results_json[task_id] = {
                        "description": task.description,
                        "status": task.status.value,
                        "result": task.result,
                        "error": task.error
                    }
                integration_json = self._llm_integrate_json(self._current_plan.goal, subtask_results_json)
            except Exception as e:
                logger.warning(f"[Leader] 生成 integration_json 失败: {e}")
                integration_json = {"error": str(e)}
            
            # 发送完成信号
            yield {
                "type": "team_complete",
                "success": all_completed,
                "output": integrated_output,
                "stats": {
                    "total_time": total_time,
                    "followers_used": self.max_followers if self.follower_pool else 0,
                    "tasks_completed": sum(
                        1 for t in self._current_plan.subtasks.values()
                        if t.status == TaskStatus.COMPLETED
                    ) if self._current_plan else 0
                    ,
                    "integration_json": integration_json
                }
            }
            
        except Exception as e:
            logger.error(f"[Leader] 流式执行失败: {e}")
            yield {
                "type": "team_error",
                "error": str(e)
            }
            
        finally:
            # 清理
            if self.follower_pool:
                self.follower_pool.shutdown()
    
    def _execute_parallel_stream(self) -> Generator[Dict[str, Any], None, None]:
        """
        并行执行（流式版本）
        
        改进：使用 FollowerPool.execute_parallel_stream 实时发送事件
        增加更详细的日志和错误处理
        """
        if not self._current_plan:
            logger.warning("[Leader] _execute_parallel_stream: 没有执行计划")
            return
        
        logger.info(f"[Leader] 开始流式并行执行，共 {len(self._current_plan.parallel_groups)} 个并行组")
        
        for group_idx, group in enumerate(self._current_plan.parallel_groups):
            # 获取该组任务的描述信息
            group_tasks_info = []
            for task_id in group:
                task = self._current_plan.subtasks.get(task_id)
                if task:
                    group_tasks_info.append({
                        "id": task_id,
                        "description": task.description
                    })
            
            # 发送并行组开始信号
            logger.info(f"[Leader] 发送 group_start 事件: 组 {group_idx + 1}, 任务数: {len(group_tasks_info)}")
            yield {
                "type": "group_start",
                "group_index": group_idx + 1,
                "total_groups": len(self._current_plan.parallel_groups),
                "tasks": group_tasks_info
            }
            
            # 执行当前组，确保所有任务完成
            max_iterations = 100  # 防止无限循环
            iteration = 0
            tasks_in_group = set(group)  # 该组的所有任务ID
            completed_in_group = set()  # 该组已完成的任务ID
            
            while iteration < max_iterations:
                iteration += 1
                
                # 获取就绪任务
                ready_tasks = self.task_board.get_ready_tasks()
                
                if not ready_tasks:
                    # 没有就绪任务，检查是否所有任务都已完成
                    progress = self.task_board.get_progress()
                    in_progress = progress.get("in_progress", 0)
                    
                    if in_progress == 0:
                        # 当前组所有任务已完成
                        logger.info(f"[Leader] 并行组 {group_idx + 1} 所有任务已完成")
                        break
                    
                    # 还有任务在执行中，等待
                    logger.debug(f"[Leader] 等待任务完成... (iteration {iteration})")
                    time.sleep(0.5)
                    continue
                
                # 使用流式执行方法，实时发送事件
                self._runtime_batch_seq += 1
                batch_id = str(self._runtime_batch_seq)
                logger.info(f"[Leader] 执行批次 {batch_id}, 就绪任务数: {len(ready_tasks)}")
                
                for event in self.follower_pool.execute_parallel_stream(batch_id=batch_id):
                    # 记录任务完成
                    if event.get("type") == "task_complete":
                        task_id = event.get("task_id")
                        if task_id in tasks_in_group:
                            completed_in_group.add(task_id)
                            logger.info(f"[Leader] 任务 {task_id} 完成，组内进度: {len(completed_in_group)}/{len(tasks_in_group)}")
                    
                    yield event
            
            # 发送并行组完成信号
            logger.info(f"[Leader] 发送 group_complete 事件: 组 {group_idx + 1}")
            yield {
                "type": "group_complete",
                "group_index": group_idx + 1
            }
    
    def _execute_sequential_stream(self) -> Generator[Dict[str, Any], None, None]:
        """顺序执行（流式版本）"""
        while True:
            ready_tasks = self.task_board.get_ready_tasks()
            if not ready_tasks:
                break
            
            task = ready_tasks[0]
            
            # 发送任务开始信号
            yield {
                "type": "task_start",
                "task_id": task.id,
                "description": task.description
            }
            
            # 执行任务
            results = self.follower_pool.execute_sequential()
            
            # 发送任务完成信号
            for result in results:
                yield {
                    "type": "task_complete",
                    "task_id": result.get("task_id"),
                    "success": result.get("success"),
                    "summary": result.get("summary", "")[:200]
                }


# 导出
__all__ = [
    'LeaderAgent',
    'DECOMPOSITION_SYSTEM_PROMPT',
    'INTEGRATION_SYSTEM_PROMPT'
]
