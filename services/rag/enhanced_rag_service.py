"""
增强版 RAG 服务

集成查询优化器，实现复杂长句的智能检索：
1. 查询复杂度分析
2. 指代消解
3. Step-Back 检索
4. 问题分解
5. 多查询重写
6. 结果整合
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from config import Config
from services.rag.rag_service import RAGService
from services.rag.query_optimizer import (
    QueryOptimizer,
    QueryOptimizationConfig,
    QueryComplexity,
    OptimizedQuery,
    ResultIntegrator
)

logger = logging.getLogger(__name__)


@dataclass
class EnhancedSearchResult:
    """增强版检索结果"""
    optimized_query: OptimizedQuery           # 优化后的查询结构
    raw_results: Dict[str, List[Dict]]        # 各查询的原始检索结果
    integrated_context: str                   # 整合后的上下文
    final_answer: Optional[str] = None        # 最终答案（可选）


class EnhancedRAGService:
    """
    增强版 RAG 服务
    
    在原有 RAG 服务基础上增加：
    - 智能查询优化
    - 多策略检索
    - 结果整合
    """
    
    def __init__(
        self,
        base_rag_service: RAGService = None,
        llm_client=None,
        config: QueryOptimizationConfig = None
    ):
        """
        初始化增强版 RAG 服务
        
        Args:
            base_rag_service: 基础 RAG 服务
            llm_client: LLM 客户端
            config: 查询优化配置
        """
        self.base_rag = base_rag_service or RAGService()
        self.llm_client = llm_client
        self.config = config or QueryOptimizationConfig.from_config()
        
        # 初始化查询优化器
        self.query_optimizer = QueryOptimizer(llm_client, self.config)
        self.result_integrator = ResultIntegrator(llm_client)
        
        logger.info("[EnhancedRAGService] 增强版 RAG 服务初始化完成")
        logger.info(f"  子问题上限: {self.config.max_sub_questions}")
        logger.info(f"  变体上限: {self.config.max_variants_per_question}")
        logger.info(f"  指代消解: {'启用' if self.config.enable_coreference else '禁用'}")
        logger.info(f"  Step-Back: {'启用' if self.config.enable_step_back else '禁用'}")
        logger.info(f"  问题分解: {'启用' if self.config.enable_decomposition else '禁用'}")
        logger.info(f"  多查询重写: {'启用' if self.config.enable_multi_query else '禁用'}")
    
    async def search_with_optimization(
        self,
        query: str,
        knowledge_base_id: str,
        chat_history: List[Dict[str, Any]] = None,
        top_n: int = None,
        top_k: int = None,
        use_mmr: bool = None,
        generate_answer: bool = False
    ) -> EnhancedSearchResult:
        """
        使用查询优化进行检索
        
        Args:
            query: 用户查询
            knowledge_base_id: 知识库ID
            chat_history: 对话历史（用于指代消解）
            top_n: 初始检索数量
            top_k: 重排序后返回数量
            use_mmr: 是否使用 MMR 重排序
            generate_answer: 是否生成最终答案
            
        Returns:
            增强版检索结果
        """
        logger.info(f"[EnhancedRAGService] 开始智能检索")
        logger.info(f"  查询: {query}")
        logger.info(f"  知识库: {knowledge_base_id}")
        
        # Step 1: 查询优化
        optimized = self.query_optimizer.optimize(query, chat_history)
        
        # Step 2: 获取所有需要检索的查询
        all_queries = self.query_optimizer.get_all_search_queries(optimized)
        
        logger.info(f"[EnhancedRAGService] 准备执行 {len(all_queries)} 个查询的检索")
        
        # Step 3: 并行执行所有检索
        search_tasks = []
        for search_query in all_queries:
            task = self.base_rag.search(
                query=search_query,
                knowledge_base_id=knowledge_base_id,
                top_n=top_n,
                top_k=top_k,
                use_mmr=use_mmr
            )
            search_tasks.append((search_query, task))
        
        # 等待所有检索完成
        raw_results = {}
        for search_query, task in search_tasks:
            try:
                results = await task
                raw_results[search_query] = results
                logger.info(f"[EnhancedRAGService] 查询 '{search_query[:30]}...' 检索到 {len(results)} 个结果")
            except Exception as e:
                logger.error(f"[EnhancedRAGService] 查询 '{search_query[:30]}...' 检索失败: {e}")
                raw_results[search_query] = []
        
        # Step 4: 整合结果
        integrated_context = self.result_integrator.integrate(
            original_query=query,
            optimized_query=optimized,
            search_results=raw_results
        )
        
        # Step 5: 可选生成最终答案
        final_answer = None
        if generate_answer and integrated_context:
            final_answer = self.result_integrator.generate_answer(
                original_query=query,
                context=integrated_context
            )
        
        result = EnhancedSearchResult(
            optimized_query=optimized,
            raw_results=raw_results,
            integrated_context=integrated_context,
            final_answer=final_answer
        )
        
        logger.info(f"[EnhancedRAGService] 智能检索完成")
        logger.info(f"  优化步骤: {' -> '.join(optimized.optimization_steps)}")
        logger.info(f"  上下文长度: {len(integrated_context)}")
        
        return result
    
    async def search_simple(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int = None,
        top_k: int = None,
        use_mmr: bool = None
    ) -> List[Dict[str, Any]]:
        """
        简单检索（不使用优化，直接调用基础服务）
        
        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 初始检索数量
            top_k: 重排序后返回数量
            use_mmr: 是否使用 MMR 重排序
            
        Returns:
            检索结果列表
        """
        return await self.base_rag.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_n=top_n,
            top_k=top_k,
            use_mmr=use_mmr
        )
    
    def get_optimization_stats(self, result: EnhancedSearchResult) -> Dict[str, Any]:
        """
        获取优化统计信息
        
        Args:
            result: 增强版检索结果
            
        Returns:
            统计信息字典
        """
        return {
            "complexity": result.optimized_query.complexity.value,
            "optimization_steps": result.optimized_query.optimization_steps,
            "original_query": result.optimized_query.original_query,
            "resolved_query": result.optimized_query.resolved_query,
            "step_back_query": result.optimized_query.step_back_query,
            "sub_questions_count": len(result.optimized_query.sub_questions),
            "total_search_queries": sum(
                len(variants) for variants in result.optimized_query.query_variants.values()
            ),
            "total_results": sum(
                len(results) for results in result.raw_results.values()
            ),
            "context_length": len(result.integrated_context)
        }


# 创建全局实例（延迟初始化）
_enhanced_rag_service: Optional[EnhancedRAGService] = None


def get_enhanced_rag_service(
    llm_client=None,
    config: QueryOptimizationConfig = None
) -> EnhancedRAGService:
    """
    获取增强版 RAG 服务实例（单例）
    
    Args:
        llm_client: LLM 客户端
        config: 优化配置
        
    Returns:
        EnhancedRAGService 实例
    """
    global _enhanced_rag_service
    
    if _enhanced_rag_service is None:
        _enhanced_rag_service = EnhancedRAGService(
            llm_client=llm_client,
            config=config
        )
    
    return _enhanced_rag_service


__all__ = [
    'EnhancedRAGService',
    'EnhancedSearchResult',
    'get_enhanced_rag_service'
]
