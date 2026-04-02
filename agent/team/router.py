"""
意图识别与路由模块

Leader Agent的核心能力：
1. 查询分类：知识问答 / 任务执行 / 复杂项目
2. 复杂度评估：工具数、技能类型、依赖关系
3. 路由决策：单Agent模式 / 团队模式
"""
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import asdict

from agent.team.types import (
    QueryCategory,
    ExecutionMode,
    ComplexityAssessment,
    RoutingDecision,
    TaskPriority
)
from agent.llm import get_llm

logger = logging.getLogger(__name__)


# ==================== 系统提示词 ====================

ROUTER_SYSTEM_PROMPT = """你是一个智能路由分析器，负责分析用户请求并决定执行策略。

## 你的任务

分析用户的请求，输出以下信息：

1. **查询分类**：
   - knowledge_qa: 纯知识问答，不需要执行操作
   - task_execution: 需要执行具体任务
   - complex_project: 复杂项目，涉及多个子任务

2. **复杂度评估**：
   - score: 0-10的综合复杂度评分
   - tool_count: 预估需要的工具调用次数
   - skill_required: 是否需要特定技能
   - dependencies: 任务间的依赖关系列表
   - parallelizable: 子任务是否可以并行执行
   - estimated_steps: 预估的总执行步骤数

3. **执行模式建议**：
   - single_agent: 简单任务，单Agent即可完成
   - team_mode: 复杂任务，需要多Agent协作

## 判断标准

**单Agent模式**适用于：
- 简单问答（定义解释、概念说明）
- 单步操作（读文件、执行命令）
- 2-3步的简单流程
- 工具调用少于3次

**团队模式**适用于：
- 多步骤复杂流程（超过5步）
- 需要并行执行的任务
- 有明确依赖关系的子任务
- 需要特定技能的任务
- 工具调用超过5次
- 涉及代码重构、系统迁移等复杂项目

## 输出格式

请以JSON格式输出：
```json
{
    "category": "knowledge_qa|task_execution|complex_project",
    "complexity": {
        "score": 0-10,
        "tool_count": 0,
        "skill_required": true/false,
        "dependencies": ["依赖1", "依赖2"],
        "parallelizable": true/false,
        "estimated_steps": 0
    },
    "mode": "single_agent|team_mode",
    "reasoning": "判断理由"
}
```

只输出JSON，不要输出其他内容。
"""


class IntentRouter:
    """
    意图识别与路由器
    
    分析用户请求，决定执行策略
    """
    
    def __init__(self, llm_client=None):
        """
        初始化路由器
        
        Args:
            llm_client: LLM客户端（可选，默认使用全局配置）
        """
        self.llm = llm_client or get_llm(streaming=False)
    
    def analyze(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        available_tools: List[str] = None
    ) -> RoutingDecision:
        """
        分析用户请求并做出路由决策
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            available_tools: 可用工具列表
            
        Returns:
            路由决策
        """
        # 首先尝试快速规则判断
        quick_decision = self._quick_assess(user_input, available_tools)
        if quick_decision:
            logger.info(f"[Router] 快速判断: {quick_decision.mode.value}")
            return quick_decision
        
        # 使用LLM进行详细分析
        llm_decision = self._llm_assess(user_input, chat_history, available_tools)
        return llm_decision
    
    def _quick_assess(
        self,
        user_input: str,
        available_tools: List[str] = None
    ) -> Optional[RoutingDecision]:
        """
        快速规则判断
        
        对于明显的简单/复杂请求，直接返回决策
        """
        input_lower = user_input.lower()
        
        # ========== 明显的简单请求 ==========
        
        # 知识问答类
        simple_qa_patterns = [
            "什么是", "解释", "定义", "说明",
            "你好", "你是谁", "自我介绍",
            "谢谢", "再见"
        ]
        if any(p in input_lower for p in simple_qa_patterns):
            complexity = ComplexityAssessment(
                score=1.0,
                tool_count=0,
                skill_required=False,
                dependencies=[],
                parallelizable=False,
                estimated_steps=1,
                reasoning="简单知识问答"
            )
            return RoutingDecision(
                mode=ExecutionMode.SINGLE_AGENT,
                category=QueryCategory.KNOWLEDGE_QA,
                complexity=complexity,
                reasoning="简单问答，无需工具调用",
                suggested_followers=0
            )
        
        # 单步操作
        simple_task_patterns = [
            "读取", "查看", "显示", "列出",
            "搜索", "查找"
        ]
        complex_patterns = [
            "然后", "接着", "之后", "再", "最后",
            "批量", "所有", "多个", "每个",
            "重构", "迁移", "部署", "测试",
            "步骤", "流程", "阶段", "计划"
        ]
        
        has_simple = any(p in input_lower for p in simple_task_patterns)
        has_complex = any(p in input_lower for p in complex_patterns)
        
        if has_simple and not has_complex and len(user_input) < 50:
            complexity = ComplexityAssessment(
                score=2.0,
                tool_count=1,
                skill_required=False,
                dependencies=[],
                parallelizable=False,
                estimated_steps=1,
                reasoning="简单单步操作"
            )
            return RoutingDecision(
                mode=ExecutionMode.SINGLE_AGENT,
                category=QueryCategory.TASK_EXECUTION,
                complexity=complexity,
                reasoning="简单任务，单Agent可完成",
                suggested_followers=0
            )
        
        # ========== 明显的复杂请求 ==========
        
        # 复杂项目关键词
        complex_project_patterns = [
            "重构整个", "迁移系统", "多模块",
            "并行执行", "同时处理", "批量处理",
            "CI/CD", "自动化流程", "工作流"
        ]
        
        if any(p in input_lower for p in complex_project_patterns):
            complexity = ComplexityAssessment(
                score=8.0,
                tool_count=6,
                skill_required=True,
                dependencies=["需要分析依赖关系"],
                parallelizable=True,
                estimated_steps=10,
                reasoning="复杂项目，需要多步骤协作"
            )
            return RoutingDecision(
                mode=ExecutionMode.TEAM_MODE,
                category=QueryCategory.COMPLEX_PROJECT,
                complexity=complexity,
                reasoning="复杂项目，需要团队协作",
                suggested_followers=3
            )
        
        # 多步骤任务
        if has_complex:
            # 计算复杂度指示词数量
            complex_count = sum(1 for p in complex_patterns if p in input_lower)
            if complex_count >= 2:
                complexity = ComplexityAssessment(
                    score=6.0,
                    tool_count=4,
                    skill_required=False,
                    dependencies=["步骤间有依赖"],
                    parallelizable=False,
                    estimated_steps=5,
                    reasoning="多步骤任务"
                )
                return RoutingDecision(
                    mode=ExecutionMode.TEAM_MODE,
                    category=QueryCategory.TASK_EXECUTION,
                    complexity=complexity,
                    reasoning="多步骤任务，建议团队模式",
                    suggested_followers=2
                )
        
        # 无法快速判断，返回None让LLM分析
        return None
    
    def _llm_assess(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        available_tools: List[str] = None
    ) -> RoutingDecision:
        """
        使用LLM进行详细分析
        """
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # 构建分析提示
        analysis_prompt = f"""请分析以下用户请求：

用户请求：
{user_input}
"""
        
        if available_tools:
            analysis_prompt += f"""
可用工具：
{', '.join(available_tools)}
"""
        
        if chat_history and len(chat_history) > 0:
            recent_history = chat_history[-3:]
            history_text = "\n".join([
                f"{msg.get('role')}: {msg.get('content', '')[:100]}"
                for msg in recent_history
            ])
            analysis_prompt += f"""
最近的对话历史：
{history_text}
"""
        
        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=analysis_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            result_text = response.content
            
            # 解析JSON
            # 尝试提取JSON块
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = result_text[json_start:json_end]
                result = json.loads(json_str)
                
                # 构建结果
                complexity_data = result.get("complexity", {})
                complexity = ComplexityAssessment(
                    score=float(complexity_data.get("score", 5.0)),
                    tool_count=int(complexity_data.get("tool_count", 3)),
                    skill_required=bool(complexity_data.get("skill_required", False)),
                    dependencies=complexity_data.get("dependencies", []),
                    parallelizable=bool(complexity_data.get("parallelizable", False)),
                    estimated_steps=int(complexity_data.get("estimated_steps", 3)),
                    reasoning=complexity_data.get("reasoning", "")
                )
                
                category_str = result.get("category", "task_execution")
                category = QueryCategory(category_str) if category_str in [e.value for e in QueryCategory] else QueryCategory.TASK_EXECUTION
                
                mode_str = result.get("mode", "single_agent")
                mode = ExecutionMode(mode_str) if mode_str in [e.value for e in ExecutionMode] else ExecutionMode.SINGLE_AGENT
                
                return RoutingDecision(
                    mode=mode,
                    category=category,
                    complexity=complexity,
                    reasoning=result.get("reasoning", ""),
                    suggested_followers=2 if mode == ExecutionMode.TEAM_MODE else 0
                )
                
        except json.JSONDecodeError as e:
            logger.warning(f"[Router] JSON解析失败: {e}")
        except Exception as e:
            logger.error(f"[Router] LLM分析失败: {e}")
        
        # 默认返回单Agent模式
        return RoutingDecision(
            mode=ExecutionMode.SINGLE_AGENT,
            category=QueryCategory.TASK_EXECUTION,
            complexity=ComplexityAssessment(
                score=3.0,
                tool_count=2,
                skill_required=False,
                dependencies=[],
                parallelizable=False,
                estimated_steps=2,
                reasoning="默认评估"
            ),
            reasoning="无法准确分析，使用单Agent模式",
            suggested_followers=0
        )


# ==================== 全局实例 ====================

_router_instance: Optional[IntentRouter] = None


def get_router(llm_client=None) -> IntentRouter:
    """获取路由器实例"""
    global _router_instance
    if _router_instance is None:
        _router_instance = IntentRouter(llm_client)
    return _router_instance


# 导出
__all__ = [
    'IntentRouter',
    'RoutingDecision',
    'get_router'
]
