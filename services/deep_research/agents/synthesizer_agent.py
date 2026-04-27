"""
总结型 Agent

职责：
- 阶段性总结：各研究方向的阶段性总结
- 全篇报告：整合所有研究方向生成最终报告
- 结构化输出：生成符合规范的报告格式
- 来源整理：整理所有参考信息来源
"""
from dataclasses import dataclass
import json
import logging
from typing import Any, Optional
from datetime import datetime

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


# 总结型 Agent 系统提示词
SYNTHESIZER_SYSTEM_PROMPT = """你是一个专注于信息整合和报告生成的总结型 Agent。

## 核心职责

1. **阶段性总结**：对单个研究方向进行总结
   - 整合该方向的所有学习成果
   - 提炼核心结论和关键发现
   - 评估信息的充分性

2. **全篇报告**：整合所有研究方向生成最终报告
   - 汇总各方向的研究结论
   - 识别跨方向的共性和差异
   - 形成针对用户问题的综合回答

3. **结构化输出**：生成符合规范的报告格式
   - Markdown 格式
   - 清晰的层级结构
   - 可追溯的引用链接

4. **来源整理**：整理所有参考信息来源
   - 去重和排序
   - 标注可信度
   - 提供完整引用

## 报告结构规范

### 阶段性总结

```markdown
## 研究方向：[方向名称]

### 核心发现
- [发现1]
- [发现2]
...

### 关键结论
[结论性陈述]

### 信息充分性评估
[评估是否有足够信息回答该方向的研究问题]

### 参考来源
- [来源1] - [标题]
- [来源2] - [标题]
```

### 全篇报告

```markdown
# [研究标题]

## 摘要
[研究内容概述，200-300 字]

## 各方向研究结论
### 1. [方向名称]
[研究内容]

### 2. [方向名称]
[研究内容]
...

## 汇总结果分析
[综合分析，识别共性、差异、趋势]

## 针对用户问题回答
[直接回答用户的问题，结构化呈现]

## 参考信息来源
- [来源1 URL] - [标题] - [可信度]
- [来源2 URL] - [标题] - [可信度]
...
```

## 执行原则

- **结构清晰**：使用标题、列表、段落组织内容
- **证据支撑**：每个结论都有来源支撑
- **用户导向**：最终回答必须针对用户原始问题
- **简洁明了**：避免冗余，突出重点

## 输出格式

总结完成后，直接输出 Markdown 格式的报告内容。
"""


@dataclass
class DirectionSummary:
    """研究方向总结"""
    direction_id: str
    direction_name: str
    key_findings: list[str]
    conclusion: str
    is_sufficient: bool  # 信息是否充分
    sources: list[str]   # 参考来源 URL
    
    def to_dict(self) -> dict:
        return {
            "direction_id": self.direction_id,
            "direction_name": self.direction_name,
            "key_findings": self.key_findings,
            "conclusion": self.conclusion,
            "is_sufficient": self.is_sufficient,
            "sources": self.sources,
        }


class SynthesizerAgent(BaseExpertAgent):
    """
    总结型 Agent
    
    职责：阶段性总结 + 全篇报告
    
    使用方式：
        # 阶段性总结
        agent = SynthesizerAgent()
        result = agent.execute(context)
        
        # 全篇报告
        result = agent.synthesize(all_directions_contexts)
    
    输出：
        - Markdown 格式的报告内容
        - 整理好的参考来源
    """
    
    def __init__(
        self,
        tools: list = None,
        report_max_length: int = 10000,
    ):
        """
        初始化总结型 Agent
        
        Args:
            tools: 可用工具列表（通常为空）
            report_max_length: 报告最大长度（字符）
        """
        super().__init__(AgentType.SYNTHESIZER, tools=tools or [])
        self.report_max_length = report_max_length
    
    @property
    def system_prompt(self) -> str:
        return SYNTHESIZER_SYSTEM_PROMPT
    
    def execute(
        self,
        context: AgentContext,
        track: Optional[ResearchTrack] = None,
    ) -> AgentResult:
        """
        执行总结任务（阶段性总结）
        
        Args:
            context: 执行上下文，包含单个研究方向的信息
            track: 研究轨道（可选）
            
        Returns:
            AgentResult，包含阶段性总结
        """
        self._total_executions += 1
        logger.info(f"[SynthesizerAgent] Starting synthesis for topic: {context.topic}")
        
        # 构建任务描述
        task_message = self._build_synthesis_task(context)
        
        # 构建消息
        messages = self._build_messages(context, task_message)
        
        # 执行 Agent
        success, result = self._invoke_agent(messages)
        
        if not success:
            logger.error(f"[SynthesizerAgent] Synthesis failed: {result.get('error', 'Unknown error')}")
            return AgentResult(
                success=False,
                error=result.get("error", "总结执行失败"),
            )
        
        # 解析总结结果
        final_message = result.get("final_message", "")
        summary = self._parse_direction_summary(final_message, context)
        
        # 创建学习成果
        learnings = self._create_summary_learnings(summary, context)
        
        # 更新统计
        if success:
            self._successful_executions += 1
        
        logger.info(
            f"[SynthesizerAgent] Synthesis completed: {len(learnings)} learnings, "
            f"{len(context.existing_sources)} sources"
        )
        
        return AgentResult(
            success=True,
            data={
                "final_message": final_message,
                "summary": summary.to_dict() if summary else {},
                "markdown": final_message,
            },
            learnings=learnings,
            sources=context.existing_sources,
            metadata={
                "direction_name": context.topic,
                "is_sufficient": summary.is_sufficient if summary else False,
                "sources_count": len(context.existing_sources),
            },
        )
    
    def synthesize(
        self,
        contexts: list[AgentContext],
        user_query: str,
        title: str = "研究报告",
    ) -> AgentResult:
        """
        生成全篇报告
        
        Args:
            contexts: 所有研究方向的上下文列表
            user_query: 用户原始问题
            title: 报告标题
            
        Returns:
            AgentResult，包含完整的 Markdown 报告
        """
        self._total_executions += 1
        logger.info(f"[SynthesizerAgent] Starting full report synthesis for {len(contexts)} directions")
        
        # 构建全篇报告任务
        task_message = self._build_full_report_task(contexts, user_query, title)
        
        # 创建临时上下文
        temp_context = AgentContext(
            query=user_query,
            topic=title,
        )
        
        # 构建消息
        messages = self._build_messages(temp_context, task_message)
        
        # 执行 Agent
        success, result = self._invoke_agent(messages)
        
        if not success:
            logger.error(f"[SynthesizerAgent] Full report synthesis failed: {result.get('error', 'Unknown error')}")
            return AgentResult(
                success=False,
                error=result.get("error", "报告生成失败"),
            )
        
        # 获取最终报告
        final_message = result.get("final_message", "")
        
        # 收集所有来源
        all_sources = []
        for ctx in contexts:
            all_sources.extend(ctx.existing_sources)
        
        # 去重来源
        unique_sources = self._deduplicate_sources(all_sources)
        
        # 更新统计
        if success:
            self._successful_executions += 1
        
        logger.info(
            f"[SynthesizerAgent] Full report completed: {len(final_message)} chars, "
            f"{len(unique_sources)} sources"
        )
        
        return AgentResult(
            success=True,
            data={
                "final_message": final_message,
                "markdown": final_message,
                "word_count": len(final_message),
            },
            sources=unique_sources,
            metadata={
                "title": title,
                "directions_count": len(contexts),
                "sources_count": len(unique_sources),
                "generated_at": datetime.now().isoformat(),
            },
        )
    
    def _build_synthesis_task(self, context: AgentContext) -> str:
        """
        构建阶段性总结任务描述
        
        Args:
            context: 执行上下文
            
        Returns:
            任务描述
        """
        parts = [
            f"请对「{context.topic}」研究方向进行阶段性总结。",
        ]
        
        # 研究主题
        parts.append(f"研究方向：{context.topic}")
        
        # 用户原始问题
        if context.query:
            parts.append(f"用户原始问题：{context.query}")
        
        # 已有的学习成果
        if context.existing_learnings:
            parts.append("\n该方向的学习成果：")
            for i, learning in enumerate(context.existing_learnings, 1):
                parts.append(f"{i}. {learning.content}")
                if learning.keywords:
                    parts.append(f"   关键词：{', '.join(learning.keywords[:3])}")
        
        # 已有的信息来源
        if context.existing_sources:
            parts.append("\n信息来源：")
            for source in context.existing_sources[:10]:
                title = source.title or source.url
                parts.append(f"- {title}")
                if source.snippet:
                    parts.append(f"  {source.snippet[:80]}...")
        
        # 总结要求
        parts.append("\n请生成阶段性总结，包含：")
        parts.append("1. 核心发现（3-5 点）")
        parts.append("2. 关键结论")
        parts.append("3. 信息充分性评估")
        parts.append("4. 参考来源列表")
        
        return "\n".join(parts)
    
    def _build_full_report_task(
        self,
        contexts: list[AgentContext],
        user_query: str,
        title: str,
    ) -> str:
        """
        构建全篇报告任务描述
        
        Args:
            contexts: 所有研究方向的上下文
            user_query: 用户原始问题
            title: 报告标题
            
        Returns:
            任务描述
        """
        parts = [
            f"请生成关于「{title}」的完整研究报告。",
        ]
        
        # 报告标题
        parts.append(f"报告标题：{title}")
        
        # 用户原始问题
        parts.append(f"用户问题：{user_query}")
        
        # 各研究方向的内容
        parts.append("\n各研究方向的研究成果：")
        
        for i, ctx in enumerate(contexts, 1):
            parts.append(f"\n### 研究方向 {i}：{ctx.topic}")
            
            # 学习成果
            if ctx.existing_learnings:
                parts.append("核心发现：")
                for j, learning in enumerate(ctx.existing_learnings[:5], 1):
                    parts.append(f"{j}. {learning.content[:200]}")
            
            # 来源数量
            parts.append(f"参考来源：{len(ctx.existing_sources)} 个")
        
        # 报告要求
        parts.append("\n请生成完整的研究报告，包含：")
        parts.append("1. 摘要（200-300 字）")
        parts.append("2. 各方向研究结论")
        parts.append("3. 汇总结果分析")
        parts.append("4. 针对用户问题的回答")
        parts.append("5. 参考信息来源")
        
        return "\n".join(parts)
    
    def _parse_direction_summary(
        self,
        message: str,
        context: AgentContext,
    ) -> Optional[DirectionSummary]:
        """
        解析阶段性总结
        
        Args:
            message: Agent 返回的消息
            context: 执行上下文
            
        Returns:
            DirectionSummary 或 None
        """
        import re
        
        # 提取核心发现（支持多种格式）
        key_findings = []
        
        # 方法1：正则匹配列表格式
        findings_match = re.search(r'核心发现[：:]\s*\n((?:[-\*].*\n?)+)', message, re.MULTILINE)
        if findings_match:
            findings_text = findings_match.group(1)
            key_findings = [
                line.strip().lstrip('-* ').strip()
                for line in findings_text.split('\n')
                if line.strip()
            ]
        
        # 方法2：按行解析
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
                    if any(marker in stripped for marker in ['关键结论', '信息充分性', '参考来源', '###', '##']):
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
        
        # 提取关键结论
        conclusion = ""
        conclusion_match = re.search(r'关键结论[：:]\s*\n(.+?)(?=\n###|\n##|\Z)', message, re.DOTALL)
        if conclusion_match:
            conclusion = conclusion_match.group(1).strip()
        
        # 提取信息充分性
        is_sufficient = True
        sufficient_match = re.search(r'信息充分性[：:]\s*(.+)', message)
        if sufficient_match:
            sufficient_text = sufficient_match.group(1).lower()
            is_sufficient = "充分" in sufficient_text or "足够" in sufficient_text
        
        # 提取来源
        sources = []
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        sources = re.findall(url_pattern, message)
        
        return DirectionSummary(
            direction_id=context.track_id,
            direction_name=context.topic,
            key_findings=key_findings,
            conclusion=conclusion,
            is_sufficient=is_sufficient,
            sources=sources,
        )
    
    def _create_summary_learnings(
        self,
        summary: Optional[DirectionSummary],
        context: AgentContext,
    ) -> list[Learning]:
        """
        从总结创建学习成果
        
        Args:
            summary: 阶段性总结
            context: 执行上下文
            
        Returns:
            Learning 列表
        """
        if not summary:
            return []
        
        learnings = []
        
        # 从核心发现创建学习成果
        for finding in summary.key_findings:
            if len(finding) > 20:
                learnings.append(Learning(
                    content=finding,
                    confidence=0.8,  # 总结的置信度较高
                    keywords=context.direction_keywords[:5],
                    sources=summary.sources[:3],
                ))
        
        # 添加关键结论
        if summary.conclusion and len(summary.conclusion) > 30:
            learnings.append(Learning(
                content=f"结论：{summary.conclusion}",
                confidence=0.85,
                keywords=context.direction_keywords[:5],
                sources=summary.sources[:3],
            ))
        
        return learnings
    
    def _deduplicate_sources(self, sources: list[Source]) -> list[Source]:
        """
        去重来源列表
        
        Args:
            sources: 来源列表
            
        Returns:
            去重后的来源列表
        """
        seen_urls = set()
        unique_sources = []
        
        for source in sources:
            if source.url not in seen_urls:
                seen_urls.add(source.url)
                unique_sources.append(source)
        
        return unique_sources
    
    def generate_report(
        self,
        contexts: list[AgentContext],
        user_query: str,
        title: str = "研究报告",
    ) -> str:
        """
        生成报告（简化接口）
        
        Args:
            contexts: 所有研究方向的上下文
            user_query: 用户原始问题
            title: 报告标题
            
        Returns:
            Markdown 格式的报告内容
        """
        result = self.synthesize(contexts, user_query, title)
        
        if result.success:
            return result.data.get("markdown", "")
        else:
            return f"# 报告生成失败\n\n错误：{result.error}"
    
    def synthesize_direction(
        self,
        context: AgentContext,
    ) -> str:
        """
        阶段性总结（简化接口）
        
        Args:
            context: 执行上下文
            
        Returns:
            Markdown 格式的总结内容
        """
        result = self.execute(context)
        
        if result.success:
            return result.data.get("markdown", "")
        else:
            return f"## 总结失败\n\n错误：{result.error}"
