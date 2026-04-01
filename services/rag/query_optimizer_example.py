"""
RAG 查询优化器使用示例

演示如何使用查询优化器进行复杂长句的 RAG 检索优化
"""
import asyncio
import logging
from typing import List, Dict, Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from services.rag.query_optimizer import (
    QueryOptimizer,
    QueryOptimizationConfig,
    QueryComplexity,
    QueryComplexityAnalyzer,
    CoreferenceResolver,
    StepBackGenerator,
    QuestionDecomposer,
    MultiQueryRewriter
)


def example_complexity_analysis():
    """示例：查询复杂度分析"""
    print("\n" + "="*60)
    print("示例 1: 查询复杂度分析")
    print("="*60)
    
    config = QueryOptimizationConfig()
    analyzer = QueryComplexityAnalyzer(config)
    
    # 测试用例
    test_cases = [
        ("RAG 是什么", None, "简单查询"),
        ("怎么解决 AI 产品的落地难点？", None, "复杂查询"),
        ("它的核心内容里，怎么解决 AI 产品的落地难点？", 
         [{"role": "user", "content": "推荐一本 AI 产品经理的书"},
          {"role": "assistant", "content": "《AI Product Management: A Practical Guide》"}],
         "对话查询（包含指代词）"),
        ("Python 如何实现一个简单的 Web 服务器？", None, "复杂查询"),
        ("这个方法怎么用？", 
         [{"role": "user", "content": "介绍一下 FastAPI"},
          {"role": "assistant", "content": "FastAPI 是一个现代 Python Web 框架..."}],
         "对话查询"),
    ]
    
    for query, history, description in test_cases:
        complexity = analyzer.analyze(query, history)
        print(f"\n查询: {query}")
        print(f"描述: {description}")
        print(f"判定结果: {complexity.value}")
        print("-" * 40)


def example_coreference_resolution():
    """示例：指代消解（需要 LLM）"""
    print("\n" + "="*60)
    print("示例 2: 指代消解")
    print("="*60)
    
    # 注意：这里需要实际的 LLM 客户端才能工作
    # 这里仅展示接口用法
    resolver = CoreferenceResolver(llm_client=None)
    
    query = "它的核心内容里，怎么解决 AI 产品的落地难点？"
    history = [
        {"role": "user", "content": "推荐一本 AI 产品经理的书"},
        {"role": "assistant", "content": "《AI Product Management: A Practical Guide》是一本很好的入门书籍..."}
    ]
    
    print(f"原始查询: {query}")
    print(f"对话历史:")
    for msg in history:
        print(f"  {msg['role']}: {msg['content'][:50]}...")
    
    # 无 LLM 时返回原查询
    resolved = resolver.resolve(query, history)
    print(f"\n消解结果: {resolved}")
    print("（注：需要 LLM 客户端才能实际执行指代消解）")


def example_step_back():
    """示例：Step-Back 抽象问题生成（需要 LLM）"""
    print("\n" + "="*60)
    print("示例 3: Step-Back 抽象问题")
    print("="*60)
    
    generator = StepBackGenerator(llm_client=None)
    
    queries = [
        "《AI Product Management》中，解决 AI 产品落地难点的方法是什么？",
        "Python 如何使用 FastAPI 实现 REST API 的分页功能？",
        "RAG 系统中怎么优化检索质量？"
    ]
    
    for query in queries:
        print(f"\n原始问题: {query}")
        print("（注：需要 LLM 客户端才能生成 Step-Back 问题）")


def example_question_decomposition():
    """示例：问题分解（需要 LLM）"""
    print("\n" + "="*60)
    print("示例 4: 问题分解")
    print("="*60)
    
    decomposer = QuestionDecomposer(llm_client=None, max_sub_questions=5)
    
    query = "《AI Product Management》中，解决 AI 产品落地难点的方法是什么？"
    print(f"原始问题: {query}")
    
    sub_questions = decomposer.decompose(query)
    print(f"\n分解后的子问题数量: {len(sub_questions)}")
    for i, sq in enumerate(sub_questions, 1):
        print(f"  {i}. {sq}")


def example_multi_query_rewriting():
    """示例：多查询重写（需要 LLM）"""
    print("\n" + "="*60)
    print("示例 5: 多查询重写")
    print("="*60)
    
    rewriter = MultiQueryRewriter(llm_client=None, max_variants=3)
    
    query = "AI 产品落地的常见难点有哪些？"
    print(f"原始查询: {query}")
    
    variants = rewriter.rewrite(query)
    print(f"\n生成的变体数量: {len(variants)}")
    for i, v in enumerate(variants, 1):
        print(f"  {i}. {v}")


def example_full_optimization():
    """示例：完整优化流程"""
    print("\n" + "="*60)
    print("示例 6: 完整优化流程")
    print("="*60)
    
    # 创建优化器（无 LLM，部分功能会回退）
    config = QueryOptimizationConfig(
        max_sub_questions=5,
        max_variants_per_question=3,
        enable_coreference=True,
        enable_step_back=True,
        enable_decomposition=True,
        enable_multi_query=True
    )
    
    optimizer = QueryOptimizer(llm_client=None, config=config)
    
    # 测试场景
    print("\n场景 1: 简单查询")
    print("-" * 40)
    result = optimizer.optimize("RAG 是什么", None)
    print(f"复杂度: {result.complexity.value}")
    print(f"优化步骤: {result.optimization_steps}")
    
    print("\n场景 2: 对话查询（带指代词）")
    print("-" * 40)
    history = [
        {"role": "user", "content": "推荐一本 AI 产品经理的书"},
        {"role": "assistant", "content": "《AI Product Management: A Practical Guide》"}
    ]
    result = optimizer.optimize(
        "它的核心内容里，怎么解决 AI 产品的落地难点？",
        history
    )
    print(f"复杂度: {result.complexity.value}")
    print(f"优化步骤: {result.optimization_steps}")
    print(f"子问题数量: {len(result.sub_questions)}")
    
    print("\n场景 3: 复杂查询")
    print("-" * 40)
    result = optimizer.optimize(
        "请详细解释 RAG 系统的设计原理，包括向量检索、重排序和上下文注入的具体实现方法",
        None
    )
    print(f"复杂度: {result.complexity.value}")
    print(f"优化步骤: {result.optimization_steps}")
    
    # 获取所有检索查询
    all_queries = optimizer.get_all_search_queries(result)
    print(f"生成的检索查询数量: {len(all_queries)}")


async def example_enhanced_rag():
    """示例：使用增强版 RAG 服务"""
    print("\n" + "="*60)
    print("示例 7: 增强版 RAG 服务")
    print("="*60)
    
    from services.rag.enhanced_rag_service import EnhancedRAGService
    
    # 创建服务（无 LLM）
    service = EnhancedRAGService(llm_client=None)
    
    print("增强版 RAG 服务配置:")
    print(f"  最大子问题数: {service.config.max_sub_questions}")
    print(f"  每子问题最大变体数: {service.config.max_variants_per_question}")
    print(f"  指代消解: {'启用' if service.config.enable_coreference else '禁用'}")
    print(f"  Step-Back: {'启用' if service.config.enable_step_back else '禁用'}")
    print(f"  问题分解: {'启用' if service.config.enable_decomposition else '禁用'}")
    print(f"  多查询重写: {'启用' if service.config.enable_multi_query else '禁用'}")
    
    # 注意：实际检索需要有效的知识库 ID
    print("\n（注：实际检索需要配置知识库和有效的 kb_id）")


def print_configuration_guide():
    """打印配置指南"""
    print("\n" + "="*60)
    print("配置指南")
    print("="*60)
    
    print("""
可以通过环境变量配置查询优化器：

# 成本控制
QUERY_OPT_MAX_SUB_QUESTIONS=5      # 最大子问题数量
QUERY_OPT_MAX_VARIANTS=3           # 每个子问题的最大查询变体数

# 功能开关
QUERY_OPT_ENABLE_COREFERENCE=true   # 启用指代消解
QUERY_OPT_ENABLE_STEP_BACK=true     # 启用 Step-Back
QUERY_OPT_ENABLE_DECOMPOSITION=true # 启用问题分解
QUERY_OPT_ENABLE_MULTI_QUERY=true   # 启用多查询重写

# 复杂度判断阈值
QUERY_OPT_SIMPLE_MAX_WORDS=10      # 简单查询的最大词数
QUERY_OPT_COMPLEX_MIN_WORDS=15     # 复杂查询的最小词数

# 总开关
ENABLE_ENHANCED_RAG=true           # 启用增强版 RAG
""")


def main():
    """运行所有示例"""
    print("\n" + "="*60)
    print("RAG 查询优化器示例")
    print("="*60)
    
    # 运行示例
    example_complexity_analysis()
    example_coreference_resolution()
    example_step_back()
    example_question_decomposition()
    example_multi_query_rewriting()
    example_full_optimization()
    
    # 异步示例
    asyncio.run(example_enhanced_rag())
    
    # 打印配置指南
    print_configuration_guide()
    
    print("\n" + "="*60)
    print("示例运行完成")
    print("="*60)


if __name__ == "__main__":
    main()
