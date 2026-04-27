"""
分析型 Agent

职责：
- 阶段性分析单个研究方向
- 信息提取和观点归纳
- 质量评估和置信度打分
- 反思循环：检查信息冲突、验证准确性、判断是否需要补充检索
"""
from dataclasses import dataclass
import json
import logging
from typing import Any, Optional

from services.deep_research.agents.base import (
    BaseExpertAgent,
    AgentType,
    AgentResult,
    AgentContext,
    BASE_SYSTEM_PROMPT,
)
from services.deep_research.models import Learning, Source
from services.deep_research.track import ResearchTrack

logger = logging.getLogger(__name__)


# 分析型 Agent 系统提示词
ANALYZER_SYSTEM_PROMPT = """你是一个专注于信息分析和提炼的分析型 Agent。

## 核心职责

1. **信息提取**：从搜索结果中提取关键信息
   - 识别主要观点和结论
   - 提取关键数据和事实
   - 记录信息来源

2. **观点归纳**：整合多个来源的信息
   - 对比不同来源的观点
   - 识别共识和分歧
   - 归纳主流观点

3. **质量评估**：评估信息质量和可信度
   - 检查信息来源的权威性
   - 评估信息的新鲜度和准确性
   - 识别潜在的偏见或利益相关

4. **反思验证**：检查信息的完整性和准确性
   - 识别信息冲突或矛盾
   - 检查是否有遗漏的关键信息
   - 判断是否需要补充检索

## 分析框架

对于每个研究方向，请按以下框架进行分析：

### 1. 核心发现
[列出 3-5 个最重要的发现]

### 2. 关键观点
[列出主要观点及其支持来源]

### 3. 数据支撑
[列出关键数据和统计信息]

### 4. 信息质量评估
- 来源可信度：[高/中/低]
- 信息新鲜度：[最新/较新/陈旧]
- 信息完整性：[完整/部分/不足]

### 5. 信息冲突
[如果有冲突信息，说明冲突点和各来源观点]

### 6. 知识缺口
[当前信息不足以覆盖的内容]

### 7. 建议补充检索
[如果需要补充检索，列出建议的关键词]

## 执行原则

- **客观中立**：不带偏见地分析信息
- **证据导向**：结论必须基于证据
- **批判思维**：质疑和验证信息
- **完整性检查**：确保覆盖主题的关键方面

## 输出格式

分析完成后，请按以下格式返回：

执行结果：[成功/失败]

核心发现：
1. [发现1]
2. [发现2]
...

置信度评分：[0.0-1.0]

关键结论：
[总结性结论]

建议下一步：
[如果需要补充检索或进一步分析，说明建议]
"""


@dataclass
class AnalysisResult:
    """分析结果"""
    key_findings: list[str]           # 核心发现
    key_points: list[dict]            # 关键观点
    data_support: list[dict]          # 数据支撑
    quality_score: float              # 质量评分 0-1
    confidence: float                 # 置信度 0-1
    conflicts: list[dict]             # 信息冲突
    gaps: list[str]                   # 知识缺口
    suggested_queries: list[str]      # 建议补充查询
    
    def to_dict(self) -> dict:
        return {
            "key_findings": self.key_findings,
            "key_points": self.key_points,
            "data_support": self.data_support,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "conflicts": self.conflicts,
            "gaps": self.gaps,
            "suggested_queries": self.suggested_queries,
        }


class AnalyzerAgent(BaseExpertAgent):
    """
    分析型 Agent
    
    职责：阶段性分析单个研究方向
    
    使用方式：
        agent = AnalyzerAgent(tools=[])
        result = agent.execute(context)
    
    输出：
        - 结构化 learnings
        - 置信度评分
        - 建议补充检索关键词
    """
    
    def __init__(
        self,
        tools: list = None,
        max_reflection_rounds: int = 2,
    ):
        """
        初始化分析型 Agent
        
        Args:
            tools: 可用工具列表（通常为空，分析不需要工具）
            max_reflection_rounds: 最大反思轮次
        """
        super().__init__(AgentType.ANALYZER, tools=tools or [])
        self.max_reflection_rounds = max_reflection_rounds
    
    @property
    def system_prompt(self) -> str:
        return ANALYZER_SYSTEM_PROMPT
    
    def execute(
        self,
        context: AgentContext,
        track: Optional[ResearchTrack] = None,
    ) -> AgentResult:
        """
        执行分析任务
        
        Args:
            context: 执行上下文，包含待分析的内容
            track: 研究轨道（可选）
            
        Returns:
            AgentResult，包含分析结果、学习成果
        """
        self._total_executions += 1
        logger.info(f"[AnalyzerAgent] Starting analysis for topic: {context.topic}")
        
        # 第一轮分析
        analysis_result = self._analyze(context)
        
        if not analysis_result.success:
            return analysis_result
        
        # 反思循环
        for round_num in range(self.max_reflection_rounds):
            logger.debug(f"[AnalyzerAgent] Reflection round {round_num + 1}")
            
            # 检查是否需要反思
            needs_reflection = self._check_needs_reflection(analysis_result)
            
            if not needs_reflection:
                logger.info(f"[AnalyzerAgent] No need for reflection after round {round_num}")
                break
            
            # 执行反思
            reflection_result = self._reflect(context, analysis_result)
            
            # 合并反思结果
            analysis_result = self._merge_reflection(analysis_result, reflection_result)
        
        # 更新统计
        if analysis_result.success:
            self._successful_executions += 1
        
        logger.info(
            f"[AnalyzerAgent] Analysis completed: confidence={analysis_result.metadata.get('confidence', 0):.2f}"
        )
        
        return analysis_result
    
    def _analyze(self, context: AgentContext) -> AgentResult:
        """
        执行分析
        
        Args:
            context: 执行上下文
            
        Returns:
            AgentResult
        """
        # 构建任务描述
        task_message = self._build_analysis_task(context)
        
        # 构建消息
        messages = self._build_messages(context, task_message)
        
        # 执行 Agent
        success, result = self._invoke_agent(messages)
        
        if not success:
            logger.error(f"[AnalyzerAgent] Analysis failed: {result.get('error', 'Unknown error')}")
            return AgentResult(
                success=False,
                error=result.get("error", "分析执行失败"),
            )
        
        # 解析分析结果
        final_message = result.get("final_message", "")
        analysis_data = self._parse_analysis_result(final_message)
        
        # 创建学习成果
        learnings = self._create_learnings(analysis_data, context)
        
        return AgentResult(
            success=True,
            data={
                "final_message": final_message,
                "analysis": analysis_data.to_dict() if analysis_data else {},
            },
            learnings=learnings,
            sources=context.existing_sources,
            metadata={
                "confidence": analysis_data.confidence if analysis_data else 0.5,
                "quality_score": analysis_data.quality_score if analysis_data else 0.5,
                "key_findings_count": len(analysis_data.key_findings) if analysis_data else 0,
            },
        )
    
    def _build_analysis_task(self, context: AgentContext) -> str:
        """
        构建分析任务描述
        
        Args:
            context: 执行上下文
            
        Returns:
            任务描述
        """
        parts = [
            f"请分析关于「{context.topic}」的研究内容。",
        ]
        
        # 研究主题
        parts.append(f"研究主题：{context.topic}")
        
        # 已有的学习成果
        if context.existing_learnings:
            parts.append("\n已有的研究发现：")
            for i, learning in enumerate(context.existing_learnings, 1):
                parts.append(f"{i}. {learning.content}")
                if learning.sources:
                    parts.append(f"   来源：{', '.join(learning.sources[:3])}")
        
        # 已有的信息来源
        if context.existing_sources:
            parts.append("\n信息来源：")
            for source in context.existing_sources[:10]:
                parts.append(f"- {source.title or source.url}")
                if source.snippet:
                    parts.append(f"  摘要：{source.snippet[:100]}...")
        
        # 分析要求
        parts.append("\n请按分析框架进行分析，重点关注：")
        parts.append("1. 核心发现和关键观点")
        parts.append("2. 信息质量和可信度评估")
        parts.append("3. 是否存在信息冲突或矛盾")
        parts.append("4. 是否需要补充检索")
        
        return "\n".join(parts)
    
    def _parse_analysis_result(self, message: str) -> Optional[AnalysisResult]:
        """
        解析分析结果
        
        Args:
            message: Agent 返回的消息
            
        Returns:
            AnalysisResult 或 None
        """
        import re
        
        # 提取核心发现（支持多种格式）
        key_findings = []
        # 格式1：带数字或破折号的列表
        findings_match = re.search(r'核心发现[：:]\s*\n((?:[-\*\d]+\..*\n?)+)', message, re.MULTILINE)
        if findings_match:
            findings_text = findings_match.group(1)
            key_findings = [
                line.strip().lstrip('0123456789-*. ').strip()
                for line in findings_text.split('\n')
                if line.strip() and not line.strip().startswith('#')
            ]
        
        # 如果没找到，尝试按行解析
        if not key_findings:
            lines = message.split('\n')
            in_findings = False
            for line in lines:
                stripped = line.strip()
                if '核心发现' in stripped:
                    in_findings = True
                    continue
                if in_findings and stripped:
                    # 检测是否进入下一节
                    if any(marker in stripped for marker in ['置信度', '关键结论', '知识缺口', '###', '##']):
                        in_findings = False
                        continue
                    # 提取列表项
                    if stripped.startswith('-') or stripped.startswith('*'):
                        finding = stripped.lstrip('-* ').strip()
                        if finding:
                            key_findings.append(finding)
                    elif stripped[0].isdigit() and '.' in stripped[:3]:
                        finding = stripped.split('.', 1)[-1].strip()
                        if finding:
                            key_findings.append(finding)
        
        # 提取置信度
        confidence = 0.5
        confidence_match = re.search(r'置信度[（(]评分[）)]?[：:]\s*([\d.]+)', message)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                confidence = max(0.0, min(1.0, confidence))
            except ValueError:
                pass
        
        # 提取质量评分
        quality_score = 0.5
        quality_match = re.search(r'质量评分[：:]\s*([\d.]+)', message)
        if quality_match:
            try:
                quality_score = float(quality_match.group(1))
                quality_score = max(0.0, min(1.0, quality_score))
            except ValueError:
                pass
        
        # 提取知识缺口
        gaps = []
        gaps_match = re.search(r'知识缺口[：:]\s*\n((?:[-\*].*\n?)+)', message, re.MULTILINE)
        if gaps_match:
            gaps_text = gaps_match.group(1)
            gaps = [
                line.strip().lstrip('-* ').strip()
                for line in gaps_text.split('\n')
                if line.strip()
            ]
        
        # 提取建议补充查询
        suggested_queries = []
        queries_match = re.search(r'建议补充检索[：:]\s*\n((?:[-\*].*\n?)+)', message, re.MULTILINE)
        if queries_match:
            queries_text = queries_match.group(1)
            suggested_queries = [
                line.strip().lstrip('-* ').strip()
                for line in queries_text.split('\n')
                if line.strip()
            ]
        
        return AnalysisResult(
            key_findings=key_findings,
            key_points=[],
            data_support=[],
            quality_score=quality_score,
            confidence=confidence,
            conflicts=[],
            gaps=gaps,
            suggested_queries=suggested_queries,
        )
    
    def _create_learnings(
        self,
        analysis: Optional[AnalysisResult],
        context: AgentContext,
    ) -> list[Learning]:
        """
        从分析结果创建学习成果
        
        Args:
            analysis: 分析结果
            context: 执行上下文
            
        Returns:
            Learning 列表
        """
        if not analysis:
            return []
        
        learnings = []
        
        # 从核心发现创建学习成果
        for finding in analysis.key_findings:
            if len(finding) > 20:  # 过滤太短的内容
                learnings.append(Learning(
                    content=finding,
                    confidence=analysis.confidence,
                    keywords=context.direction_keywords[:5],
                ))
        
        return learnings
    
    def _check_needs_reflection(self, result: AgentResult) -> bool:
        """
        检查是否需要反思
        
        Args:
            result: 分析结果
            
        Returns:
            是否需要反思
        """
        # 低置信度需要反思
        confidence = result.metadata.get("confidence", 1.0)
        if confidence < 0.7:
            logger.debug(f"Low confidence {confidence}, needs reflection")
            return True
        
        # 有知识缺口需要反思
        analysis_data = result.data.get("analysis", {})
        gaps = analysis_data.get("gaps", [])
        if gaps:
            logger.debug(f"Found {len(gaps)} knowledge gaps, needs reflection")
            return True
        
        return False
    
    def _reflect(
        self,
        context: AgentContext,
        previous_result: AgentResult,
    ) -> AgentResult:
        """
        执行反思
        
        Args:
            context: 执行上下文
            previous_result: 上一次分析结果
            
        Returns:
            反思结果
        """
        # 构建反思提示
        reflection_prompt = self._build_reflection_prompt(context, previous_result)
        
        # 构建消息
        messages = self._build_messages(context, reflection_prompt)
        
        # 执行
        success, result = self._invoke_agent(messages)
        
        if not success:
            return AgentResult(
                success=False,
                error=result.get("error", "反思执行失败"),
            )
        
        return AgentResult(
            success=True,
            data=result,
        )
    
    def _build_reflection_prompt(
        self,
        context: AgentContext,
        previous_result: AgentResult,
    ) -> str:
        """
        构建反思提示
        
        Args:
            context: 执行上下文
            previous_result: 上一次分析结果
            
        Returns:
            反思提示
        """
        parts = [
            "请对之前的分析进行反思和补充：",
        ]
        
        # 上一次分析的关键发现
        findings = previous_result.metadata.get("key_findings_count", 0)
        parts.append(f"\n之前发现了 {findings} 个关键点。")
        
        # 置信度
        confidence = previous_result.metadata.get("confidence", 0)
        parts.append(f"置信度为 {confidence:.2f}。")
        
        # 知识缺口
        analysis_data = previous_result.data.get("analysis", {})
        gaps = analysis_data.get("gaps", [])
        if gaps:
            parts.append("\n发现的知识缺口：")
            for gap in gaps:
                parts.append(f"- {gap}")
        
        # 反思问题
        parts.append("\n请思考：")
        parts.append("1. 是否遗漏了重要信息？")
        parts.append("2. 结论是否有足够的证据支撑？")
        parts.append("3. 是否存在未被发现的矛盾？")
        parts.append("4. 是否需要补充检索？如果需要，请提供具体的关键词。")
        
        return "\n".join(parts)
    
    def _merge_reflection(
        self,
        previous: AgentResult,
        reflection: AgentResult,
    ) -> AgentResult:
        """
        合并反思结果
        
        Args:
            previous: 上一次结果
            reflection: 反思结果
            
        Returns:
            合并后的结果
        """
        if not reflection.success:
            return previous
        
        # 解析反思消息
        reflection_message = reflection.data.get("final_message", "")
        
        # 合并学习成果
        new_learnings = []
        previous_contents = {l.content for l in previous.learnings}
        
        for learning in reflection.learnings:
            if learning.content not in previous_contents:
                new_learnings.append(learning)
        
        all_learnings = previous.learnings + new_learnings
        
        # 提取新的补充查询建议
        import re
        new_queries = []
        query_matches = re.findall(r'建议关键词[：:]\s*([^\n]+)', reflection_message)
        for match in query_matches:
            keywords = [k.strip() for k in match.split(',')]
            new_queries.extend(keywords)
        
        # 更新元数据
        metadata = previous.metadata.copy()
        metadata["reflection_queries"] = new_queries
        
        return AgentResult(
            success=True,
            data=previous.data,
            learnings=all_learnings,
            sources=previous.sources,
            metadata=metadata,
        )
    
    def analyze(self, content: str, context: AgentContext) -> AgentResult:
        """
        分析内容（简化接口）
        
        Args:
            content: 待分析内容
            context: 执行上下文
            
        Returns:
            AgentResult
        """
        # 将内容作为学习成果添加到上下文
        context.existing_learnings.append(Learning(
            content=content,
            confidence=0.5,
        ))
        return self.execute(context)
    
    def verify(self, learnings: list[Learning], context: AgentContext) -> AgentResult:
        """
        验证学习成果（简化接口）
        
        Args:
            learnings: 待验证的学习成果
            context: 执行上下文
            
        Returns:
            AgentResult
        """
        context.existing_learnings = learnings
        return self.execute(context)
