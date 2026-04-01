"""
RAG 查询优化器模块

实现复杂长句的 RAG 查询优化，包括：
1. 查询复杂度判断（简单/复杂/对话）
2. 指代消解（Coreference Resolution）
3. Step-Back 抽象问题生成
4. 问题分解
5. 多查询重写
6. 结果整合

优化流程（按优先级）：
指代消解 -> Step-Back -> 问题分解 -> 多查询重写

成本控制：
- 子问题数量 <= 5
- 每个子问题的查询变体 <= 3
"""
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import asyncio

from config import Config

logger = logging.getLogger(__name__)


class QueryComplexity(Enum):
    """查询复杂度枚举"""
    SIMPLE = "simple"      # 简单查询，如 "RAG 是什么"
    COMPLEX = "complex"    # 复杂查询，需要分解
    CONVERSATIONAL = "conversational"  # 对话查询，需要指代消解


@dataclass
class OptimizedQuery:
    """优化后的查询结构"""
    original_query: str                          # 原始查询
    resolved_query: Optional[str] = None         # 指代消解后的查询
    step_back_query: Optional[str] = None        # Step-Back 抽象问题
    sub_questions: List[str] = field(default_factory=list)  # 分解的子问题
    query_variants: Dict[str, List[str]] = field(default_factory=dict)  # 每个子问题的查询变体
    complexity: QueryComplexity = QueryComplexity.SIMPLE
    optimization_steps: List[str] = field(default_factory=list)  # 执行的优化步骤记录


@dataclass
class QueryOptimizationConfig:
    """查询优化配置"""
    # 成本控制
    max_sub_questions: int = 5          # 最大子问题数量
    max_variants_per_question: int = 3  # 每个子问题的最大查询变体数
    
    # 功能开关
    enable_coreference: bool = True     # 启用指代消解
    enable_step_back: bool = True       # 启用 Step-Back
    enable_decomposition: bool = True   # 启用问题分解
    enable_multi_query: bool = True     # 启用多查询重写
    
    # 复杂度判断阈值
    simple_query_max_words: int = 10    # 简单查询的最大词数
    complex_query_min_words: int = 15   # 复杂查询的最小词数
    
    @classmethod
    def from_config(cls) -> 'QueryOptimizationConfig':
        """从全局配置创建实例"""
        return cls(
            max_sub_questions=Config.QUERY_OPT_MAX_SUB_QUESTIONS,
            max_variants_per_question=Config.QUERY_OPT_MAX_VARIANTS,
            enable_coreference=Config.QUERY_OPT_ENABLE_COREFERENCE,
            enable_step_back=Config.QUERY_OPT_ENABLE_STEP_BACK,
            enable_decomposition=Config.QUERY_OPT_ENABLE_DECOMPOSITION,
            enable_multi_query=Config.QUERY_OPT_ENABLE_MULTI_QUERY,
            simple_query_max_words=Config.QUERY_OPT_SIMPLE_MAX_WORDS,
            complex_query_min_words=Config.QUERY_OPT_COMPLEX_MIN_WORDS
        )


class QueryComplexityAnalyzer:
    """查询复杂度分析器"""
    
    # 指代词模式
    PRONOUN_PATTERNS = [
        r'它[们]?',          # 它、它们
        r'他[们]?',          # 他、他们
        r'她[们]?',          # 她、她们
        r'这[个些本那]?',     # 这个、这些、这本、那
        r'其[中他她]?',       # 其中、其他
        r'该',               # 该（如"该方法"）
        r'上述',             # 上述
        r'前面提到的',        # 前面提到的
    ]
    
    # 复杂查询关键词
    COMPLEX_KEYWORDS = [
        '如何', '怎么', '怎样', '为什么', '哪些', '什么',
        '比较', '对比', '区别', '联系', '关系',
        '分析', '解释', '说明', '阐述', '总结',
        '步骤', '流程', '方法', '方案', '策略',
        '以及', '并且', '同时', '另外', '还有',
        '首先', '然后', '最后', '其次',
    ]
    
    # 简单查询模式
    SIMPLE_PATTERNS = [
        r'^(什么|是|谁|哪|何时|在哪).{0,20}[？?]?$',
        r'^(定义|介绍|解释|说明).{0,10}$',
        r'^.{1,8}是(什么|谁)$',
    ]
    
    def __init__(self, config: QueryOptimizationConfig):
        self.config = config
        self._pronoun_regex = re.compile('|'.join(self.PRONOUN_PATTERNS))
        self._complex_keyword_regex = re.compile('|'.join(self.COMPLEX_KEYWORDS))
        self._simple_patterns = [re.compile(p) for p in self.SIMPLE_PATTERNS]
    
    def analyze(
        self, 
        query: str, 
        chat_history: List[Dict[str, Any]] = None
    ) -> QueryComplexity:
        """
        分析查询复杂度
        
        Args:
            query: 用户查询
            chat_history: 对话历史
            
        Returns:
            查询复杂度级别
        """
        # 检查是否是对话查询（包含指代词且有对话历史）
        if chat_history and len(chat_history) > 0:
            if self._contains_pronouns(query):
                logger.info(f"[QueryOptimizer] 检测到指代词，判定为对话查询")
                return QueryComplexity.CONVERSATIONAL
        
        # 检查是否匹配简单查询模式
        for pattern in self._simple_patterns:
            if pattern.match(query.strip()):
                logger.info(f"[QueryOptimizer] 匹配简单查询模式")
                return QueryComplexity.SIMPLE
        
        # 基于词数和关键词判断
        word_count = len(query)
        has_complex_keywords = bool(self._complex_keyword_regex.search(query))
        
        if word_count <= self.config.simple_query_max_words and not has_complex_keywords:
            logger.info(f"[QueryOptimizer] 词数较少且无复杂关键词，判定为简单查询")
            return QueryComplexity.SIMPLE
        
        if word_count >= self.config.complex_query_min_words or has_complex_keywords:
            logger.info(f"[QueryOptimizer] 词数较多或包含复杂关键词，判定为复杂查询")
            return QueryComplexity.COMPLEX
        
        # 默认为简单查询
        return QueryComplexity.SIMPLE
    
    def _contains_pronouns(self, query: str) -> bool:
        """检查查询是否包含指代词"""
        return bool(self._pronoun_regex.search(query))


class CoreferenceResolver:
    """指代消解器"""
    
    def __init__(self, llm_client=None):
        """
        初始化指代消解器
        
        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client
    
    def resolve(
        self, 
        query: str, 
        chat_history: List[Dict[str, Any]]
    ) -> str:
        """
        执行指代消解
        
        Args:
            query: 当前查询
            chat_history: 对话历史
            
        Returns:
            消解后的查询
        """
        if not chat_history or not self.llm_client:
            logger.warning("[CoreferenceResolver] 无对话历史或 LLM 客户端，跳过指代消解")
            return query
        
        # 提取最近几轮对话作为上下文
        recent_context = self._build_context(chat_history)
        
        prompt = f"""请对用户的查询进行指代消解，将代词替换为具体的实体。

对话历史：
{recent_context}

当前查询：
{query}

要求：
1. 识别查询中的代词（如"它"、"这个"、"那本书"等）
2. 根据对话历史确定代词指代的实体
3. 将代词替换为具体实体，保持语句通顺
4. 如果无法确定指代对象，保持原样

请直接输出消解后的查询，不要解释。"""

        try:
            response = self.llm_client.invoke(prompt)
            resolved = response.content if hasattr(response, 'content') else str(response)
            resolved = resolved.strip()
            
            logger.info(f"[CoreferenceResolver] 指代消解完成:")
            logger.info(f"  原始查询: {query}")
            logger.info(f"  消解后: {resolved}")
            
            return resolved
        except Exception as e:
            logger.error(f"[CoreferenceResolver] 指代消解失败: {e}")
            return query
    
    def _build_context(self, chat_history: List[Dict[str, Any]], max_turns: int = 3) -> str:
        """构建对话上下文"""
        context_parts = []
        # 取最近几轮对话
        recent_messages = chat_history[-max_turns * 2:] if len(chat_history) > max_turns * 2 else chat_history
        
        for msg in recent_messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if role == 'user':
                context_parts.append(f"用户：{content}")
            elif role == 'assistant':
                # 截取部分内容避免过长
                content_preview = content[:200] + "..." if len(content) > 200 else content
                context_parts.append(f"助手：{content_preview}")
        
        return "\n".join(context_parts)


class StepBackGenerator:
    """Step-Back 抽象问题生成器"""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    def generate(self, query: str) -> Optional[str]:
        """
        生成 Step-Back 抽象问题
        
        将具体问题抽象为更高层次的问题，用于检索全局框架。
        
        Args:
            query: 原始查询
            
        Returns:
            抽象问题
        """
        if not self.llm_client:
            logger.warning("[StepBackGenerator] 无 LLM 客户端，跳过 Step-Back")
            return None
        
        prompt = f"""请将以下具体问题抽象为一个更高层次的问题。

原始问题：{query}

要求：
1. 识别问题的核心主题和领域
2. 将具体问题提升为更抽象、更宏观的问题
3. 抽象问题应能帮助理解问题的整体框架
4. 保持问题的相关性，不要过于抽象

示例：
- 原始："《AI Product Management》书中怎么解决 AI 产品的落地难点？"
- 抽象："《AI Product Management》中关于 AI 产品落地的核心章节是什么？"

- 原始："Python 如何实现一个简单的 Web 服务器？"
- 抽象："Python 中实现 Web 服务的主要方法有哪些？"

请直接输出抽象后的问题，不要解释。"""

        try:
            response = self.llm_client.invoke(prompt)
            step_back = response.content if hasattr(response, 'content') else str(response)
            step_back = step_back.strip()
            
            logger.info(f"[StepBackGenerator] Step-Back 问题生成完成:")
            logger.info(f"  原始问题: {query}")
            logger.info(f"  抽象问题: {step_back}")
            
            return step_back
        except Exception as e:
            logger.error(f"[StepBackGenerator] Step-Back 生成失败: {e}")
            return None


class QuestionDecomposer:
    """问题分解器"""
    
    def __init__(self, llm_client=None, max_sub_questions: int = 5):
        self.llm_client = llm_client
        self.max_sub_questions = max_sub_questions
    
    def decompose(self, query: str) -> List[str]:
        """
        将复杂问题分解为子问题
        
        Args:
            query: 原始查询
            
        Returns:
            子问题列表
        """
        if not self.llm_client:
            logger.warning("[QuestionDecomposer] 无 LLM 客户端，跳过问题分解")
            return [query]
        
        prompt = f"""请将以下复杂问题分解为多个简单的子问题。

原始问题：{query}

要求：
1. 将问题拆分为 2-{self.max_sub_questions} 个独立的子问题
2. 每个子问题应该具体、可独立回答
3. 子问题之间应该有逻辑顺序
4. 子问题的答案组合起来能够回答原始问题
5. 每个子问题一行，使用数字编号

示例：
原始问题："《AI Product Management》中，解决 AI 产品落地难点的方法是什么？"

分解结果：
1. AI 产品落地的常见难点有哪些？
2. 书中针对每个难点提出了哪些解决方法？
3. 这些解决方法如何实际应用？

请输出分解后的子问题："""

        try:
            response = self.llm_client.invoke(prompt)
            result = response.content if hasattr(response, 'content') else str(response)
            
            # 解析子问题
            sub_questions = []
            for line in result.strip().split('\n'):
                line = line.strip()
                # 移除编号
                cleaned = re.sub(r'^\d+[.、)\]]\s*', '', line)
                if cleaned and len(cleaned) > 2:
                    sub_questions.append(cleaned)
            
            # 限制子问题数量
            sub_questions = sub_questions[:self.max_sub_questions]
            
            if not sub_questions:
                logger.warning("[QuestionDecomposer] 未解析出有效子问题，返回原始查询")
                return [query]
            
            logger.info(f"[QuestionDecomposer] 问题分解完成:")
            logger.info(f"  原始问题: {query}")
            logger.info(f"  子问题数量: {len(sub_questions)}")
            for i, sq in enumerate(sub_questions, 1):
                logger.info(f"  子问题 {i}: {sq}")
            
            return sub_questions
        except Exception as e:
            logger.error(f"[QuestionDecomposer] 问题分解失败: {e}")
            return [query]


class MultiQueryRewriter:
    """多查询重写器"""
    
    def __init__(self, llm_client=None, max_variants: int = 3):
        self.llm_client = llm_client
        self.max_variants = max_variants
    
    def rewrite(self, query: str) -> List[str]:
        """
        为查询生成多个变体
        
        Args:
            query: 原始查询
            
        Returns:
            查询变体列表（包含原始查询）
        """
        if not self.llm_client:
            logger.warning("[MultiQueryRewriter] 无 LLM 客户端，返回原始查询")
            return [query]
        
        prompt = f"""请为以下查询生成 {self.max_variants} 个语义相同但表达不同的变体。

原始查询：{query}

要求：
1. 保持核心语义不变
2. 使用不同的词汇和表达方式
3. 可以调整语序、替换同义词、改变句式
4. 每个变体一行，不要编号

示例：
原始查询："AI 产品落地的常见难点有哪些？"

变体：
AI 产品上线面临的典型挑战
人工智能产品部署的主要困难
AI 产品推向市场的常见障碍

请生成查询变体："""

        try:
            response = self.llm_client.invoke(prompt)
            result = response.content if hasattr(response, 'content') else str(response)
            
            # 解析变体
            variants = []
            for line in result.strip().split('\n'):
                line = line.strip()
                if line and len(line) > 2:
                    variants.append(line)
            
            # 限制变体数量
            variants = variants[:self.max_variants]
            
            # 确保原始查询在列表中
            if query not in variants:
                variants.insert(0, query)
            
            logger.info(f"[MultiQueryRewriter] 查询重写完成:")
            logger.info(f"  原始查询: {query}")
            logger.info(f"  变体数量: {len(variants)}")
            for i, v in enumerate(variants, 1):
                logger.info(f"  变体 {i}: {v}")
            
            return variants
        except Exception as e:
            logger.error(f"[MultiQueryRewriter] 查询重写失败: {e}")
            return [query]
    
    def rewrite_batch(self, queries: List[str]) -> Dict[str, List[str]]:
        """
        批量为多个查询生成变体
        
        Args:
            queries: 查询列表
            
        Returns:
            查问到变体的映射
        """
        result = {}
        for query in queries:
            result[query] = self.rewrite(query)
        return result


class QueryOptimizer:
    """
    RAG 查询优化器
    
    整合所有优化步骤，根据查询复杂度动态选择优化策略。
    """
    
    def __init__(
        self,
        llm_client=None,
        config: QueryOptimizationConfig = None
    ):
        """
        初始化查询优化器
        
        Args:
            llm_client: LLM 客户端
            config: 优化配置
        """
        self.llm_client = llm_client
        self.config = config or QueryOptimizationConfig()
        
        # 初始化各组件
        self.complexity_analyzer = QueryComplexityAnalyzer(self.config)
        self.coreference_resolver = CoreferenceResolver(llm_client)
        self.step_back_generator = StepBackGenerator(llm_client)
        self.question_decomposer = QuestionDecomposer(
            llm_client, 
            self.config.max_sub_questions
        )
        self.multi_query_rewriter = MultiQueryRewriter(
            llm_client, 
            self.config.max_variants_per_question
        )
        
        logger.info("[QueryOptimizer] 查询优化器初始化完成")
        logger.info(f"  最大子问题数: {self.config.max_sub_questions}")
        logger.info(f"  每子问题最大变体数: {self.config.max_variants_per_question}")
    
    def optimize(
        self,
        query: str,
        chat_history: List[Dict[str, Any]] = None
    ) -> OptimizedQuery:
        """
        优化查询
        
        Args:
            query: 原始查询
            chat_history: 对话历史
            
        Returns:
            优化后的查询结构
        """
        logger.info(f"[QueryOptimizer] 开始优化查询: {query}")
        
        result = OptimizedQuery(original_query=query)
        
        # Step 1: 分析查询复杂度
        complexity = self.complexity_analyzer.analyze(query, chat_history)
        result.complexity = complexity
        logger.info(f"[QueryOptimizer] 查询复杂度: {complexity.value}")
        
        # 根据复杂度决定优化策略
        if complexity == QueryComplexity.SIMPLE:
            # 简单查询：仅启用多查询重写
            result.optimization_steps.append("简单查询模式")
            if self.config.enable_multi_query:
                result.query_variants[query] = self.multi_query_rewriter.rewrite(query)
                result.optimization_steps.append("多查询重写")
            else:
                result.query_variants[query] = [query]
        
        elif complexity == QueryComplexity.CONVERSATIONAL:
            # 对话查询：必启指代消解 + 完整流程
            result.optimization_steps.append("对话查询模式")
            
            current_query = query
            
            # Step 2: 指代消解（必选）
            if self.config.enable_coreference and chat_history:
                resolved = self.coreference_resolver.resolve(query, chat_history)
                result.resolved_query = resolved
                current_query = resolved
                result.optimization_steps.append("指代消解")
            
            # Step 3: Step-Back
            if self.config.enable_step_back:
                step_back = self.step_back_generator.generate(current_query)
                if step_back:
                    result.step_back_query = step_back
                    result.optimization_steps.append("Step-Back")
            
            # Step 4: 问题分解
            if self.config.enable_decomposition:
                sub_questions = self.question_decomposer.decompose(current_query)
                result.sub_questions = sub_questions
                result.optimization_steps.append("问题分解")
            else:
                result.sub_questions = [current_query]
            
            # Step 5: 多查询重写
            if self.config.enable_multi_query:
                result.query_variants = self.multi_query_rewriter.rewrite_batch(result.sub_questions)
                result.optimization_steps.append("多查询重写")
            else:
                for sq in result.sub_questions:
                    result.query_variants[sq] = [sq]
        
        elif complexity == QueryComplexity.COMPLEX:
            # 复杂查询：完整流程（跳过指代消解）
            result.optimization_steps.append("复杂查询模式")
            
            current_query = query
            
            # Step 2: Step-Back
            if self.config.enable_step_back:
                step_back = self.step_back_generator.generate(current_query)
                if step_back:
                    result.step_back_query = step_back
                    result.optimization_steps.append("Step-Back")
            
            # Step 3: 问题分解
            if self.config.enable_decomposition:
                sub_questions = self.question_decomposer.decompose(current_query)
                result.sub_questions = sub_questions
                result.optimization_steps.append("问题分解")
            else:
                result.sub_questions = [current_query]
            
            # Step 4: 多查询重写
            if self.config.enable_multi_query:
                result.query_variants = self.multi_query_rewriter.rewrite_batch(result.sub_questions)
                result.optimization_steps.append("多查询重写")
            else:
                for sq in result.sub_questions:
                    result.query_variants[sq] = [sq]
        
        logger.info(f"[QueryOptimizer] 优化完成，执行步骤: {' -> '.join(result.optimization_steps)}")
        
        return result
    
    def get_all_search_queries(self, optimized: OptimizedQuery) -> List[str]:
        """
        获取所有需要检索的查询
        
        Args:
            optimized: 优化后的查询结构
            
        Returns:
            所有需要检索的查询列表
        """
        queries = []
        
        # 添加 Step-Back 查询
        if optimized.step_back_query:
            queries.append(optimized.step_back_query)
        
        # 添加所有子问题的变体
        for sub_q, variants in optimized.query_variants.items():
            queries.extend(variants)
        
        # 去重保持顺序
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        
        logger.info(f"[QueryOptimizer] 总共生成 {len(unique_queries)} 个检索查询")
        return unique_queries


class ResultIntegrator:
    """检索结果整合器"""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    def integrate(
        self,
        original_query: str,
        optimized_query: OptimizedQuery,
        search_results: Dict[str, List[Dict[str, Any]]]
    ) -> str:
        """
        整合所有检索结果生成最终答案
        
        Args:
            original_query: 原始用户查询
            optimized_query: 优化后的查询结构
            search_results: 各查询的检索结果 {query: [results]}
            
        Returns:
            整合后的上下文
        """
        logger.info(f"[ResultIntegrator] 开始整合检索结果")
        logger.info(f"  原始查询: {original_query}")
        logger.info(f"  检索查询数: {len(search_results)}")
        
        # 收集所有唯一结果
        all_chunks = []
        seen_ids = set()
        
        for query, results in search_results.items():
            for result in results:
                chunk_id = result.get('id', '')
                if chunk_id and chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    all_chunks.append(result)
        
        logger.info(f"[ResultIntegrator] 收集到 {len(all_chunks)} 个唯一结果块")
        
        if not all_chunks:
            return ""
        
        # 按相关性分数排序
        all_chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # 构建上下文
        context_parts = []
        total_length = 0
        max_context = 4000  # 最大上下文长度
        
        # 优先添加 Step-Back 结果（全局框架）
        if optimized_query.step_back_query:
            step_back_results = search_results.get(optimized_query.step_back_query, [])
            if step_back_results:
                context_parts.append("## 全局框架信息\n")
                for result in step_back_results[:2]:
                    content = result.get('content', '')
                    context_parts.append(f"- {content}\n")
                    total_length += len(content)
                context_parts.append("\n")
        
        # 添加子问题相关结果
        context_parts.append("## 相关信息\n")
        for i, result in enumerate(all_chunks[:15]):  # 限制数量
            content = result.get('content', '')
            if total_length + len(content) > max_context:
                break
            context_parts.append(f"[{i+1}] {content}\n")
            total_length += len(content)
        
        context = ''.join(context_parts)
        logger.info(f"[ResultIntegrator] 生成上下文长度: {len(context)}")
        
        return context
    
    def generate_answer(
        self,
        original_query: str,
        context: str
    ) -> str:
        """
        基于整合的上下文生成最终答案
        
        Args:
            original_query: 原始查询
            context: 整合的上下文
            
        Returns:
            最终答案
        """
        if not self.llm_client:
            logger.warning("[ResultIntegrator] 无 LLM 客户端，返回上下文")
            return context
        
        prompt = f"""请基于以下检索到的信息回答用户问题。

用户问题：{original_query}

检索到的相关信息：
{context}

要求：
1. 综合所有相关信息进行回答
2. 回答要有逻辑、有条理
3. 适当引用信息来源（如"根据资料..."）
4. 如果信息不足，诚实说明
5. 不要编造未提及的内容

请回答："""

        try:
            response = self.llm_client.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"[ResultIntegrator] 生成答案完成，长度: {len(answer)}")
            return answer
        except Exception as e:
            logger.error(f"[ResultIntegrator] 答案生成失败: {e}")
            return context


# 创建默认配置实例（从全局配置读取）
default_config = QueryOptimizationConfig.from_config()


__all__ = [
    'QueryComplexity',
    'OptimizedQuery',
    'QueryOptimizationConfig',
    'QueryComplexityAnalyzer',
    'CoreferenceResolver',
    'StepBackGenerator',
    'QuestionDecomposer',
    'MultiQueryRewriter',
    'QueryOptimizer',
    'ResultIntegrator',
    'default_config'
]
