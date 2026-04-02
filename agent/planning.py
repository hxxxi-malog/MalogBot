"""
Planning 模块 - 任务复杂度判断和自动规划

核心功能：
1. 判断任务是否需要 Planning（一次循环能否完成）
2. 为复杂任务生成执行计划
3. 与 TodoManager 和 TaskManager 集成
"""
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """任务复杂度枚举"""
    SIMPLE = "simple"          # 简单任务，一次循环可完成
    MODERATE = "moderate"      # 中等复杂度，需要 2-3 步
    COMPLEX = "complex"        # 复杂任务，需要多次循环和多工具协作


@dataclass
class PlanStep:
    """计划步骤"""
    id: str
    description: str
    tool: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    expected_output: Optional[str] = None
    status: str = "pending"  # pending, in_progress, completed, failed
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "tool": self.tool,
            "dependencies": self.dependencies,
            "expected_output": self.expected_output,
            "status": self.status
        }


@dataclass
class TaskPlan:
    """任务计划"""
    goal: str                           # 用户目标
    complexity: TaskComplexity          # 复杂度评估
    steps: List[PlanStep]               # 执行步骤
    current_step_index: int = 0         # 当前步骤索引
    created_from_query: str = ""        # 原始查询
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "complexity": self.complexity.value,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
            "created_from_query": self.created_from_query
        }
    
    def get_current_step(self) -> Optional[PlanStep]:
        """获取当前步骤"""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None
    
    def get_next_step(self) -> Optional[PlanStep]:
        """获取下一个待执行的步骤"""
        for i, step in enumerate(self.steps):
            if step.status == "pending":
                # 检查依赖是否都已完成
                deps_completed = all(
                    self._get_step_by_id(dep_id).status == "completed"
                    for dep_id in step.dependencies
                    if self._get_step_by_id(dep_id)
                )
                if deps_completed:
                    return step
        return None
    
    def _get_step_by_id(self, step_id: str) -> Optional[PlanStep]:
        """通过ID获取步骤"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None


class PlanningService:
    """
    规划服务 - 判断任务复杂度并生成计划
    
    设计思路：
    - 基于关键词和模式匹配判断复杂度
    - 简单任务直接执行，无需规划
    - 复杂任务自动生成执行计划
    """
    
    # 需要多步骤执行的指示词
    MULTI_STEP_INDICATORS = [
        # 工具链式调用
        "然后", "接着", "之后", "再", "最后",
        # 信息收集类
        "搜索", "查找", "查询", "获取", "检索", "搜索一下", "查一下",
        "今天", "明天", "昨天", "当前", "最近", "现在",
        # 多文件操作
        "批量", "所有", "多个", "每个", "遍历",
        # 复杂流程
        "步骤", "流程", "阶段", "计划", "规划",
        # 数据处理链
        "分析", "整理", "汇总", "对比", "比较", "统计",
        # 需要外部信息
        "天气", "新闻", "价格", "行情", "汇率", "股价",
        "最新", "实时", "当前时间", "现在几点",
    ]
    
    # 简单任务的指示词（一次调用可完成）
    SIMPLE_INDICATORS = [
        "你是谁", "你叫什么", "自我介绍",
        "你好", "嗨", "hi", "hello",
        "谢谢", "感谢", "再见",
        "什么是", "解释", "说明", "定义",  # 知识问答类
        "写一个", "生成一个", "创建一个",  # 单文件生成
        "翻译", "润色", "修改",  # 文本处理
    ]
    
    # 需要特定工具链的任务模式
    TOOL_CHAIN_PATTERNS = [
        {
            "pattern": ["时间", "天气"],
            "tools": ["get_current_time", "web_search"],
            "description": "查询天气需要先获取时间再搜索"
        },
        {
            "pattern": ["搜索", "整理", "写入"],
            "tools": ["web_search", "bash"],
            "description": "搜索后整理写入文件"
        },
        {
            "pattern": ["分析", "重构", "测试"],
            "tools": ["bash", "spawn_sub_agent"],
            "description": "代码分析重构测试流程"
        },
    ]
    
    def __init__(self, llm_client=None):
        """
        初始化规划服务
        
        Args:
            llm_client: LLM 客户端（可选，用于复杂规划）
        """
        self.llm_client = llm_client
    
    def analyze_complexity(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        available_tools: List[str] = None
    ) -> TaskComplexity:
        """
        分析任务复杂度
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            available_tools: 可用工具列表
            
        Returns:
            任务复杂度枚举值
        """
        user_input_lower = user_input.lower()
        
        # 检查简单任务指示词
        simple_score = sum(
            1 for indicator in self.SIMPLE_INDICATORS
            if indicator in user_input_lower
        )
        
        # 检查多步骤指示词
        multi_step_score = sum(
            1 for indicator in self.MULTI_STEP_INDICATORS
            if indicator in user_input_lower
        )
        
        # 检查工具链模式
        tool_chain_score = 0
        for pattern_config in self.TOOL_CHAIN_PATTERNS:
            pattern = pattern_config["pattern"]
            matches = sum(1 for p in pattern if p in user_input_lower)
            if matches >= len(pattern) * 0.5:  # 匹配一半以上的模式词
                tool_chain_score += 1
        
        # 综合判断
        if simple_score >= 2 or (simple_score >= 1 and multi_step_score == 0):
            return TaskComplexity.SIMPLE
        
        if tool_chain_score >= 1 or multi_step_score >= 3:
            return TaskComplexity.COMPLEX
        
        if multi_step_score >= 1:
            return TaskComplexity.MODERATE
        
        # 默认为简单任务
        return TaskComplexity.SIMPLE
    
    def should_plan(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        available_tools: List[str] = None
    ) -> bool:
        """
        判断是否需要规划
        
        一次循环无法完成的任务需要规划
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            available_tools: 可用工具列表
            
        Returns:
            是否需要规划
        """
        complexity = self.analyze_complexity(
            user_input, chat_history, available_tools
        )
        return complexity != TaskComplexity.SIMPLE
    
    def generate_plan(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        available_tools: List[str] = None
    ) -> TaskPlan:
        """
        生成任务执行计划
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            available_tools: 可用工具列表
            
        Returns:
            任务计划对象
        """
        complexity = self.analyze_complexity(
            user_input, chat_history, available_tools
        )
        
        # 根据复杂度和输入生成计划步骤
        steps = self._generate_steps(
            user_input, complexity, available_tools
        )
        
        return TaskPlan(
            goal=user_input,
            complexity=complexity,
            steps=steps,
            created_from_query=user_input
        )
    
    def _generate_steps(
        self,
        user_input: str,
        complexity: TaskComplexity,
        available_tools: List[str] = None
    ) -> List[PlanStep]:
        """
        生成执行步骤
        
        基于用户输入和工具链模式生成具体步骤
        """
        steps = []
        user_input_lower = user_input.lower()
        
        # 检查特定模式并生成步骤
        for pattern_config in self.TOOL_CHAIN_PATTERNS:
            pattern = pattern_config["pattern"]
            matches = sum(1 for p in pattern if p in user_input_lower)
            
            if matches >= len(pattern) * 0.5:
                # 匹配到模式，生成对应步骤
                for i, tool in enumerate(pattern_config["tools"]):
                    step = PlanStep(
                        id=f"step_{i+1}",
                        description=f"执行 {tool} 操作",
                        tool=tool,
                        dependencies=[f"step_{i}"] if i > 0 else [],
                        expected_output=f"{tool} 执行结果"
                    )
                    steps.append(step)
                
                if steps:
                    return steps
        
        # 没有匹配到特定模式，生成通用步骤
        if complexity == TaskComplexity.MODERATE:
            steps = [
                PlanStep(
                    id="step_1",
                    description="分析任务需求",
                    expected_output="任务分析结果"
                ),
                PlanStep(
                    id="step_2",
                    description="执行核心操作",
                    expected_output="操作执行结果"
                ),
                PlanStep(
                    id="step_3",
                    description="整合信息并回复用户",
                    expected_output="最终回复"
                )
            ]
        elif complexity == TaskComplexity.COMPLEX:
            # 对于复杂任务，标记需要 LLM 生成详细计划
            steps = [
                PlanStep(
                    id="step_1",
                    description="制定详细执行计划",
                    expected_output="详细计划"
                ),
                PlanStep(
                    id="step_2",
                    description="按计划逐步执行",
                    expected_output="执行结果"
                ),
                PlanStep(
                    id="step_3",
                    description="验证和总结结果",
                    expected_output="最终结果"
                )
            ]
        
        return steps
    
    def generate_plan_prompt(self, plan: TaskPlan) -> str:
        """
        生成规划提示词
        
        当需要规划时，注入此提示词引导模型创建任务列表
        
        Args:
            plan: 任务计划
            
        Returns:
            提示词字符串
        """
        if plan.complexity == TaskComplexity.SIMPLE:
            return ""
        
        prompt = f"""
[任务规划提醒]

检测到这是一个{plan.complexity.value}任务，一次循环可能无法完成。

目标：{plan.goal}

建议的执行步骤：
"""
        for step in plan.steps:
            deps = f" (依赖: {', '.join(step.dependencies)})" if step.dependencies else ""
            prompt += f"\n  [{step.id}] {step.description}{deps}"
        
        prompt += """

请使用 todo_manager 或 task_create 工具创建任务列表来跟踪进度。
每完成一个步骤后，立即更新任务状态。

重要规则：
1. 同一时间只能有一个任务处于 in_progress 状态
2. 完成一个任务后立即将其标记为 completed
3. 然后开始下一个任务，标记为 in_progress
4. 使用 task_get_ready 查看可执行的任务
"""
        return prompt


# ==================== 会话级别的计划管理 ====================

# 全局会话计划存储
_session_plans: Dict[str, TaskPlan] = {}


def get_session_plan(session_id: str) -> Optional[TaskPlan]:
    """
    获取会话的计划
    
    Args:
        session_id: 会话ID
        
    Returns:
        任务计划，如果不存在返回 None
    """
    return _session_plans.get(session_id)


def set_session_plan(session_id: str, plan: TaskPlan) -> None:
    """
    设置会话的计划
    
    Args:
        session_id: 会话ID
        plan: 任务计划
    """
    _session_plans[session_id] = plan


def clear_session_plan(session_id: str) -> None:
    """
    清除会话的计划
    
    Args:
        session_id: 会话ID
    """
    if session_id in _session_plans:
        del _session_plans[session_id]


# ==================== 导出 ====================

__all__ = [
    'PlanningService',
    'TaskComplexity',
    'TaskPlan',
    'PlanStep',
    'get_session_plan',
    'set_session_plan',
    'clear_session_plan'
]
