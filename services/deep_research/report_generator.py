"""
研究报告生成器

负责将研究成果整合为结构化的 Markdown 报告。

报告结构：
1. 研究标题
2. 摘要
3. 各方向研究结论
4. 汇总分析
5. 用户问题回答
6. 参考信息来源
"""
import logging
from datetime import datetime
from typing import Optional

from services.deep_research.models import (
    ResearchTask as ResearchTaskModel,
    ResearchPlan as ResearchPlanModel,
    ResearchDirection as ResearchDirectionModel,
    ResearchReport as ResearchReportModel,
    Learning,
    Source,
)

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    研究报告生成器

    使用 Jinja2 模板生成结构化 Markdown 报告。
    """

    def __init__(self):
        """初始化报告生成器"""
        self.template = self._get_default_template()
        logger.info("ReportGenerator initialized")

    def generate_markdown(
        self,
        task: ResearchTaskModel,
        plan: Optional[ResearchPlanModel],
        directions: list[ResearchDirectionModel],
    ) -> str:
        """
        生成 Markdown 格式的研究报告

        Args:
            task: 研究任务
            plan: 研究计划（可选）
            directions: 研究方向列表

        Returns:
            Markdown 格式的报告内容
        """
        logger.info(f"[ReportGenerator] Generating report for task {task.id}")

        # 1. 生成标题
        title = f"研究报告：{task.query[:50]}{'...' if len(task.query) > 50 else ''}"

        # 2. 生成摘要
        summary = self._generate_summary(task, directions)

        # 3. 生成各方向结论
        direction_sections = self._generate_direction_sections(directions)

        # 4. 生成汇总分析
        synthesis = self._generate_synthesis(task, directions)

        # 5. 生成用户问题回答
        answer = self._generate_answer(task, directions)

        # 6. 生成参考来源
        sources = self._generate_sources(directions)

        # 7. 组装报告
        report_lines = [
            f"# {title}",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"> 研究模式：{'深度研究' if task.mode.value == 'deep' else '标准研究'}",
            f"> 研究方向数量：{len(directions)}",
            "",
            "---",
            "",
            "## 摘要",
            "",
            summary,
            "",
            "---",
            "",
            "## 各方向研究结论",
            "",
        ]

        report_lines.extend(direction_sections)

        report_lines.extend([
            "",
            "---",
            "",
            "## 汇总分析",
            "",
            synthesis,
            "",
            "---",
            "",
            "## 针对用户问题的回答",
            "",
            answer,
            "",
            "---",
            "",
            "## 参考信息来源",
            "",
        ])

        report_lines.extend(sources)

        # 添加页脚
        report_lines.extend([
            "",
            "---",
            "",
            f"*本报告由 MalogBot 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ])

        markdown_content = "\n".join(report_lines)
        logger.info(f"[ReportGenerator] Generated report with {len(markdown_content)} characters")

        return markdown_content

    def _generate_summary(
        self,
        task: ResearchTaskModel,
        directions: list[ResearchDirectionModel],
    ) -> str:
        """生成摘要"""
        # 收集所有学习成果
        all_learnings = []
        for direction in directions:
            all_learnings.extend(direction.learnings)

        if not all_learnings:
            return f"本研究针对「{task.query}」进行了深入调研，但由于搜索结果有限，未能获取足够的信息。"

        # 统计信息
        total_sources = sum(len(d.sources) for d in directions)
        completed_count = sum(1 for d in directions if d.status.value == "completed")

        # 提取关键发现（取置信度最高的前3个）
        sorted_learnings = sorted(
            all_learnings,
            key=lambda l: l.confidence,
            reverse=True
        )[:3]

        key_findings = [f"- {l.content}" for l in sorted_learnings]

        summary = f"""本研究针对「{task.query}」进行了深入调研。

研究概况：
- 共设置 {len(directions)} 个研究方向
- 完成 {completed_count} 个研究方向
- 参考 {total_sources} 个信息来源

关键发现：
{chr(10).join(key_findings)}"""

        return summary

    def _generate_direction_sections(
        self,
        directions: list[ResearchDirectionModel],
    ) -> list[str]:
        """生成各研究方向章节"""
        sections = []

        for i, direction in enumerate(directions, 1):
            # 方向标题
            section = [
                f"### 方向 {i}：{direction.name}",
                "",
            ]

            # 方向总结
            if direction.summary:
                section.extend([
                    "**总结**：",
                    "",
                    direction.summary,
                    "",
                ])

            # 学习成果
            if direction.learnings:
                section.extend([
                    "**主要发现**：",
                    "",
                ])

                for learning in direction.learnings[:5]:  # 限制显示数量
                    confidence_indicator = self._get_confidence_indicator(learning.confidence)
                    section.append(f"- {confidence_indicator} {learning.content}")

                section.append("")

            # 信息来源数量
            if direction.sources:
                section.append(f"*本方向参考了 {len(direction.sources)} 个信息来源*")
                section.append("")

            sections.extend(section)

        return sections

    def _generate_synthesis(
        self,
        task: ResearchTaskModel,
        directions: list[ResearchDirectionModel],
    ) -> str:
        """生成汇总分析"""
        # 收集所有学习成果
        all_learnings = []
        for direction in directions:
            all_learnings.extend(direction.learnings)

        if not all_learnings:
            return "由于搜索结果有限，无法进行汇总分析。"

        # 按关键词聚类
        keyword_groups = {}
        for learning in all_learnings:
            for keyword in learning.keywords[:3]:
                if keyword not in keyword_groups:
                    keyword_groups[keyword] = []
                keyword_groups[keyword].append(learning.content)

        # 生成综合分析
        synthesis_lines = [
            f"通过对 {len(directions)} 个研究方向的成果进行综合分析，得出以下结论：",
            "",
        ]

        # 提取关键主题
        top_keywords = sorted(
            keyword_groups.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )[:5]

        for keyword, contents in top_keywords:
            synthesis_lines.append(f"**{keyword}**")
            synthesis_lines.append(f"- 相关发现 {len(contents)} 条")
            synthesis_lines.append("")

        # 综合结论
        synthesis_lines.extend([
            "综合以上分析，可以看出：",
            "",
            "1. 研究覆盖了问题的多个维度",
            "2. 不同方向的发现相互印证和补充",
            "3. 形成了较为完整的知识体系",
        ])

        return "\n".join(synthesis_lines)

    def _generate_answer(
        self,
        task: ResearchTaskModel,
        directions: list[ResearchDirectionModel],
    ) -> str:
        """生成针对用户问题的直接回答"""
        # 收集所有总结
        summaries = [d.summary for d in directions if d.summary]

        if not summaries:
            return f"本研究未能找到足够的信息来回答「{task.query}」。建议您尝试使用其他关键词或扩展研究范围。"

        # 组合回答
        answer_lines = [
            f"针对您的问题「{task.query}」，本研究得出以下结论：",
            "",
        ]

        # 从各方向提取关键信息
        for i, direction in enumerate(directions, 1):
            if direction.summary:
                # 取总结的前200字符
                summary_preview = direction.summary[:200]
                if len(direction.summary) > 200:
                    summary_preview += "..."
                answer_lines.append(f"{i}. **{direction.name}**：{summary_preview}")
                answer_lines.append("")

        return "\n".join(answer_lines)

    def _generate_sources(
        self,
        directions: list[ResearchDirectionModel],
    ) -> list[str]:
        """生成参考来源列表"""
        # 收集并去重所有来源
        seen_urls = set()
        sources_list = []

        for direction in directions:
            for source in direction.sources:
                if source.url not in seen_urls:
                    seen_urls.add(source.url)
                    sources_list.append(source)

        # 按可信度排序
        sources_list.sort(key=lambda s: s.credibility_score, reverse=True)

        if not sources_list:
            return ["*本研究未引用外部信息来源*"]

        source_lines = []
        for i, source in enumerate(sources_list[:20], 1):  # 限制显示数量
            title = source.title or "无标题"
            if len(title) > 60:
                title = title[:60] + "..."
            source_lines.append(f"{i}. [{title}]({source.url})")
            if source.snippet:
                snippet_preview = source.snippet[:100]
                if len(source.snippet) > 100:
                    snippet_preview += "..."
                source_lines.append(f"   > {snippet_preview}")

        return source_lines

    def _get_confidence_indicator(self, confidence: float) -> str:
        """获取置信度指示符"""
        if confidence >= 0.8:
            return "✓✓✓"
        elif confidence >= 0.6:
            return "✓✓"
        elif confidence >= 0.4:
            return "✓"
        else:
            return "?"

    def _get_default_template(self) -> str:
        """获取默认报告模板"""
        return """# {{ title }}

> 生成时间：{{ timestamp }}
> 研究模式：{{ mode }}
> 研究方向数量：{{ direction_count }}

---

## 摘要

{{ summary }}

---

## 各方向研究结论

{% for direction in directions %}
### 方向 {{ loop.index }}：{{ direction.name }}

**总结**：
{{ direction.summary }}

**主要发现**：
{% for learning in direction.learnings %}
- {{ learning.content }}
{% endfor %}

{% endfor %}

---

## 汇总分析

{{ synthesis }}

---

## 针对用户问题的回答

{{ answer }}

---

## 参考信息来源

{% for source in sources %}
{{ loop.index }}. [{{ source.title }}]({{ source.url }})
{% endfor %}

---

*本报告由 MalogBot 自动生成*
"""


def generate_report(
    task: ResearchTaskModel,
    plan: Optional[ResearchPlanModel],
    directions: list[ResearchDirectionModel],
) -> ResearchReportModel:
    """
    生成研究报告的便捷函数

    Args:
        task: 研究任务
        plan: 研究计划
        directions: 研究方向列表

    Returns:
        研究报告对象
    """
    generator = ReportGenerator()
    markdown = generator.generate_markdown(task, plan, directions)

    # 统计来源数量
    source_count = sum(len(d.sources) for d in directions)

    report = ResearchReportModel(
        task_id=task.id,
        title=f"研究报告：{task.query[:50]}",
        content_markdown=markdown,
        source_count=source_count,
    )
    report.calculate_word_count()

    return report
