"""
Planning工具模块

提供任务规划和执行能力，供主Agent和子Agent使用。
"""
import json
import logging
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool

from agent.planning import (
    PlanningService,
    TaskComplexity,
    TaskPlan,
    PlanStep,
    get_session_plan,
    set_session_plan,
    clear_session_plan
)

logger = logging.getLogger(__name__)


# 会话规划状态存储
_session_planning_state: Dict[str, Dict[str, Any]] = {}


@tool
def planning_analyze(
    task_description: str,
    available_tools: List[str] = None
) -> str:
    """
    分析任务复杂度并生成执行计划。
    
    用于复杂任务的规划，帮助Agent理清执行步骤。
    子Agent也可以使用此工具进行任务分解。
    
    Args:
        task_description: 任务描述
        available_tools: 可用工具列表（可选）
        
    Returns:
        任务分析结果和计划
    """
    planning_service = PlanningService()
    
    # 分析复杂度
    complexity = planning_service.analyze_complexity(
        task_description,
        available_tools=available_tools
    )
    
    # 生成计划
    plan = planning_service.generate_plan(
        task_description,
        available_tools=available_tools
    )
    
    # 格式化输出
    output_lines = ["[任务分析结果]", ""]
    
    # 复杂度
    complexity_labels = {
        TaskComplexity.SIMPLE: "简单",
        TaskComplexity.MODERATE: "中等",
        TaskComplexity.COMPLEX: "复杂"
    }
    output_lines.append(f"复杂度评估：{complexity_labels.get(complexity, complexity.value)}")
    
    # 计划步骤
    if plan.steps:
        output_lines.append("")
        output_lines.append("建议执行步骤：")
        for i, step in enumerate(plan.steps, 1):
            status_icon = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
                "failed": "[!]"
            }.get(step.status, "[ ]")
            
            output_lines.append(f"  {status_icon} {step.id}: {step.description}")
            if step.tool:
                output_lines.append(f"      工具: {step.tool}")
            if step.dependencies:
                output_lines.append(f"      依赖: {', '.join(step.dependencies)}")
    
    # 执行建议
    output_lines.append("")
    output_lines.append("---")
    if complexity == TaskComplexity.SIMPLE:
        output_lines.append("建议：这是一个简单任务，可以直接执行。")
    elif complexity == TaskComplexity.MODERATE:
        output_lines.append("建议：这是一个中等复杂度任务，建议按步骤执行。")
        output_lines.append("使用 planning_execute 跟踪进度。")
    else:
        output_lines.append("建议：这是一个复杂任务，强烈建议：")
        output_lines.append("1. 使用 todo_manager 创建任务列表")
        output_lines.append("2. 使用 spawn_sub_agent 委派子任务")
        output_lines.append("3. 使用 planning_execute 跟踪进度")
    
    return "\n".join(output_lines)


@tool
def planning_execute(
    action: str,
    step_id: str = None,
    result: str = None
) -> str:
    """
    执行计划中的下一步或更新计划状态。
    
    Args:
        action: 操作类型，可选值：
            - "next": 获取下一个待执行的步骤
            - "start": 开始执行某个步骤
            - "complete": 标记步骤完成
            - "fail": 标记步骤失败
            - "status": 查看当前计划状态
        step_id: 步骤ID（start/complete/fail时需要）
        result: 执行结果（complete/fail时可选）
        
    Returns:
        操作结果
    """
    # 这里简化实现，实际可以与PlanningService集成
    output_lines = ["[计划执行]", ""]
    
    if action == "status":
        output_lines.append("当前计划状态：")
        output_lines.append("使用 planning_analyze 查看详细计划")
        
    elif action == "next":
        output_lines.append("下一个待执行步骤：")
        output_lines.append("建议使用 todo_manager 查看和更新任务状态")
        
    elif action == "start" and step_id:
        output_lines.append(f"开始执行步骤：{step_id}")
        output_lines.append("请执行相应操作，完成后使用 planning_execute action='complete' 标记")
        
    elif action == "complete" and step_id:
        output_lines.append(f"步骤 {step_id} 已标记为完成")
        if result:
            output_lines.append(f"执行结果：{result[:200]}...")
            
    elif action == "fail" and step_id:
        output_lines.append(f"步骤 {step_id} 已标记为失败")
        if result:
            output_lines.append(f"失败原因：{result}")
        output_lines.append("建议：分析失败原因，考虑替代方案或向用户报告")
        
    else:
        output_lines.append(f"未知操作：{action}")
        output_lines.append("可用操作：next, start, complete, fail, status")
    
    return "\n".join(output_lines)


# 导出
__all__ = [
    'planning_analyze',
    'planning_execute',
    'PLANNING_TOOLS'
]

PLANNING_TOOLS = [planning_analyze, planning_execute]
