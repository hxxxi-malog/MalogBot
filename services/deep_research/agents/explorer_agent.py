"""
探索型 Agent

职责：
- 搜索、发现信息
- 多源搜索和去重
- 内容清洗
- 返回清洗后的内容列表和来源信息
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


# 探索型 Agent 系统提示词
EXPLORER_SYSTEM_PROMPT = """你是一个专注于信息搜索和发现的探索型 Agent。

## 核心职责

1. **关键词优化**：根据研究主题生成高质量搜索关键词
   - 从用户问题中提炼核心关键词
   - 生成多维度关键词（同义词、相关词、专业术语）
   - 避免重复搜索已查询过的内容

2. **多源搜索**：使用多种搜索工具获取信息
   - 优先使用专业搜索工具
   - 对比不同来源的信息
   - 记录信息来源 URL 和标题

3. **去重过滤**：避免重复获取相同内容
   - 检查 URL 是否已访问
   - 检查关键词是否已搜索
   - 对相似内容进行去重

4. **内容清洗**：提取有价值的核心内容
   - 去除广告、导航等噪音
   - 提取正文内容
   - 保留关键结构信息

## 执行原则

- **向目标收束**：搜索结果必须与研究主题相关
- **避免重复**：已搜索的关键词和已访问的 URL 不要重复
- **质量优先**：优先获取权威、可靠的信息来源
- **广度覆盖**：多维度搜索，覆盖主题的不同方面

## 输出格式

搜索完成后，请按以下格式返回：

执行结果：[成功/失败]

搜索结果摘要：
- 搜索关键词：[关键词列表]
- 找到来源：[数量] 个
- 核心发现：[简要描述主要发现]

关键信息列表：
1. [信息1] - 来源：[URL]
2. [信息2] - 来源：[URL]
...

执行摘要：
[描述搜索过程和主要发现]
"""


@dataclass
class SearchResult:
    """搜索结果"""
    url: str
    title: str
    snippet: str
    content: str = ""  # 清洗后的内容
    credibility_score: float = 0.5
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "content": self.content,
            "credibility_score": self.credibility_score,
        }


class ExplorerAgent(BaseExpertAgent):
    """
    探索型 Agent
    
    职责：搜索、发现信息、去重
    
    使用方式：
        agent = ExplorerAgent(tools=[search_tool, web_fetch_tool])
        result = agent.execute(context)
    
    输出：
        - 搜索结果列表
        - 清洗后的内容
        - 来源信息
    """
    
    def __init__(self, tools: list = None, max_results_per_query: int = 5):
        """
        初始化探索型 Agent
        
        Args:
            tools: 可用工具列表（应包含搜索工具）
            max_results_per_query: 每个查询的最大结果数
        """
        super().__init__(AgentType.EXPLORER, tools=tools)
        self.max_results_per_query = max_results_per_query
    
    @property
    def system_prompt(self) -> str:
        return EXPLORER_SYSTEM_PROMPT
    
    def execute(
        self,
        context: AgentContext,
        track: Optional[ResearchTrack] = None,
    ) -> AgentResult:
        """
        执行搜索任务
        
        Args:
            context: 执行上下文，包含研究主题、已访问 URL 等
            track: 研究轨道（可选，用于 SSE 推送和去重）
            
        Returns:
            AgentResult，包含搜索结果、来源信息
        """
        self._total_executions += 1
        logger.info(f"[ExplorerAgent] Starting search for topic: {context.topic}")
        
        # 构建任务描述
        task_message = self._build_task_message(context)
        
        # 构建消息
        messages = self._build_messages(context, task_message)
        
        # 执行 Agent
        success, result = self._invoke_agent(messages)
        
        if not success:
            logger.error(f"[ExplorerAgent] Search failed: {result.get('error', 'Unknown error')}")
            return AgentResult(
                success=False,
                error=result.get("error", "搜索执行失败"),
            )
        
        # 解析结果
        sources = self._parse_sources(result, context)
        learnings = self._extract_learnings(result, context)
        
        # 更新统计
        if success:
            self._successful_executions += 1
        
        logger.info(
            f"[ExplorerAgent] Search completed: {len(sources)} sources, "
            f"{len(learnings)} learnings"
        )
        
        return AgentResult(
            success=True,
            data={
                "final_message": result.get("final_message", ""),
                "tool_calls": result.get("tool_calls", []),
                "steps_used": result.get("steps_used", 0),
            },
            learnings=learnings,
            sources=sources,
            metadata={
                "query_count": len(context.direction_keywords),
                "visited_urls_count": len(context.visited_urls),
            },
        )
    
    def _build_task_message(self, context: AgentContext) -> str:
        """
        构建任务消息
        
        Args:
            context: 执行上下文
            
        Returns:
            任务描述
        """
        parts = [
            f"请搜索关于「{context.topic}」的相关信息。",
        ]
        
        # 添加关键词提示
        if context.direction_keywords:
            parts.append(f"建议使用以下关键词：{', '.join(context.direction_keywords)}")
        
        # 研究主题
        parts.append(f"请搜索关于 \"{context.topic}\" 的相关信息。")
        
        # 关键词提示
        if context.direction_keywords:
            parts.append(f"\n建议使用以下关键词进行搜索：{', '.join(context.direction_keywords)}")
        
        # 去重提示
        if context.visited_urls:
            parts.append(f"\n已访问的 URL（请勿重复访问）：")
            for url in list(context.visited_urls)[:10]:  # 只显示前 10 个
                parts.append(f"  - {url}")
        
        if context.searched_queries:
            parts.append(f"\n已搜索的关键词（请勿重复搜索）：")
            for query in list(context.searched_queries)[:10]:
                parts.append(f"  - {query}")
        
        # 已有信息
        if context.existing_learnings:
            parts.append(f"\n已发现的信息：")
            for learning in context.existing_learnings[:5]:
                parts.append(f"  - {learning.content[:100]}...")
        
        # 搜索目标
        parts.append(f"\n搜索目标：")
        parts.append(f"1. 找到 {self.max_results_per_query} 个高质量的信息来源")
        parts.append(f"2. 获取与研究主题相关的核心内容")
        parts.append(f"3. 记录信息来源的 URL 和标题")
        
        return "\n".join(parts)
    
    def _parse_sources(
        self,
        result: dict[str, Any],
        context: AgentContext,
    ) -> list[Source]:
        """
        从执行结果中解析信息来源
        
        Args:
            result: Agent 执行结果
            context: 执行上下文
            
        Returns:
            Source 列表
        """
        sources = []
        final_message = result.get("final_message", "")
        tool_calls = result.get("tool_calls", [])
        
        # 从工具调用中提取来源
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            args = tc.get("args", {})
            
            # 搜索工具通常返回结果
            if "search" in tool_name.lower() or "query" in args:
                # 尝试从参数中提取 URL
                if "url" in args:
                    sources.append(Source(
                        url=args["url"],
                        title=args.get("title", ""),
                        snippet=args.get("snippet", ""),
                        source_type="web",
                    ))
        
        # 从最终消息中提取 URL（简单正则匹配）
        import re
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, final_message)
        
        for url in urls[:self.max_results_per_query]:
            if url not in context.visited_urls:
                sources.append(Source(
                    url=url,
                    title="",  # 标题需要后续填充
                    snippet="",
                    source_type="web",
                ))
        
        logger.debug(f"Parsed {len(sources)} sources from result")
        return sources
    
    def _extract_learnings(
        self,
        result: dict[str, Any],
        context: AgentContext,
    ) -> list[Learning]:
        """
        从执行结果中提取学习成果
        
        Args:
            result: Agent 执行结果
            context: 执行上下文
            
        Returns:
            Learning 列表
        """
        learnings = []
        final_message = result.get("final_message", "")
        
        # 如果最终消息包含有价值的信息，创建 Learning
        if final_message and len(final_message) > 50:
            # 简单提取：将消息按段落分割
            paragraphs = final_message.split("\n\n")
            
            for para in paragraphs:
                para = para.strip()
                # 过滤太短或格式化的内容
                if len(para) > 30 and not para.startswith(("-", "*", "#", "执行")):
                    learnings.append(Learning(
                        content=para[:500],  # 限制长度
                        confidence=0.6,
                        keywords=context.direction_keywords[:5],
                    ))
        
        logger.debug(f"Extracted {len(learnings)} learnings from result")
        return learnings
    
    def search(self, keywords: list[str], context: AgentContext) -> AgentResult:
        """
        执行搜索（简化接口）
        
        Args:
            keywords: 搜索关键词列表
            context: 执行上下文
            
        Returns:
            AgentResult
        """
        context.direction_keywords = keywords
        return self.execute(context)
    
    def deduplicate(self, urls: list[str], context: AgentContext) -> list[str]:
        """
        去重 URL 列表
        
        Args:
            urls: URL 列表
            context: 执行上下文
            
        Returns:
            去重后的 URL 列表
        """
        unique_urls = []
        for url in urls:
            if url not in context.visited_urls and url not in unique_urls:
                unique_urls.append(url)
        
        logger.debug(f"Deduplicated {len(urls)} URLs to {len(unique_urls)}")
        return unique_urls
