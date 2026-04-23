"""
RAGAS RAG 检索质量评估服务

使用 RAGAS 框架评估 RAG 系统的质量指标：
- Faithfulness (忠实度): 答案是否基于检索到的上下文生成
- Answer Relevancy (答案相关性): 答案与问题的相关程度
- Context Precision (上下文精确度): 检索到的上下文是否相关
- Context Recall (上下文召回率): 相关上下文是否被检索到
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset

from config import Config
from services.rag_service import rag_service
from services.knowledge_base_service import knowledge_base_service
from services.db_manager import db_manager
from models.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


class RAGASEvaluationService:
    """RAGAS 评估服务"""

    def __init__(self):
        """初始化评估服务"""
        # 配置 OpenAI 兼容的 LLM 用于评估
        # RAGAS 需要一个 LLM 来评估，这里使用 DeepSeek 或其他模型
        self.llm_config = {
            "model": Config.MODEL_NAME,
            "api_key": Config.DEEPSEEK_API_KEY,
            "base_url": Config.DEEPSEEK_BASE_URL,
        }

    async def evaluate_single_query(
        self,
        question: str,
        knowledge_base_id: str,
        ground_truth: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        评估单个查询的 RAG 质量

        Args:
            question: 用户问题
            knowledge_base_id: 知识库ID
            ground_truth: 真实答案（可选，用于计算 recall）

        Returns:
            评估结果字典
        """
        try:
            # 1. 执行 RAG 检索
            logger.info(f"[RAGAS] 开始评估: question={question[:50]}...")
            
            retrieved_contexts = await rag_service.search(question, knowledge_base_id)
            contexts = [ctx['content'] for ctx in retrieved_contexts]
            
            logger.info(f"[RAGAS] 检索到 {len(contexts)} 个上下文")

            if not contexts:
                return {
                    "error": "未检索到相关上下文",
                    "question": question,
                    "contexts": [],
                    "metrics": None
                }

            # 2. 构建评估数据集
            eval_data = {
                "question": [question],
                "contexts": [contexts],
                "answer": [""],  # 需要提供答案才能评估
            }
            
            if ground_truth:
                eval_data["ground_truth"] = [ground_truth]

            dataset = Dataset.from_dict(eval_data)

            # 3. 选择评估指标
            metrics = [faithfulness, answer_relevancy, context_precision]
            if ground_truth:
                metrics.append(context_recall)

            # 4. 执行评估
            # 注意: RAGAS 需要配置 LLM
            try:
                from langchain_openai import ChatOpenAI
                
                evaluator_llm = ChatOpenAI(
                    model=self.llm_config["model"],
                    api_key=self.llm_config["api_key"],
                    base_url=self.llm_config["base_url"],
                )
                
                # 设置 RAGAS 的 LLM
                import ragas
                ragas.llm = evaluator_llm
                
                result = evaluate(
                    dataset,
                    metrics=metrics,
                    llm=evaluator_llm
                )
                
                # 提取指标
                scores = {}
                for metric in metrics:
                    metric_name = metric.name
                    if metric_name in result:
                        scores[metric_name] = float(result[metric_name])
                
                return {
                    "question": question,
                    "contexts": contexts,
                    "metrics": scores,
                    "retrieved_count": len(contexts),
                    "evaluation_time": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"[RAGAS] 评估执行失败: {str(e)}")
                # 返回简化结果
                return {
                    "question": question,
                    "contexts": contexts,
                    "metrics": None,
                    "error": f"评估执行失败: {str(e)}",
                    "retrieved_count": len(contexts)
                }

        except Exception as e:
            logger.error(f"[RAGAS] 评估过程出错: {str(e)}")
            return {
                "error": str(e),
                "question": question,
                "contexts": [],
                "metrics": None
            }

    async def evaluate_batch(
        self,
        test_cases: List[Dict[str, str]],
        knowledge_base_id: str
    ) -> Dict[str, Any]:
        """
        批量评估多个测试用例

        Args:
            test_cases: 测试用例列表，每个包含 question 和可选的 ground_truth
            knowledge_base_id: 知识库ID

        Returns:
            批量评估结果
        """
        results = []
        total_metrics = {
            "faithfulness": [],
            "answer_relevancy": [],
            "context_precision": [],
            "context_recall": []
        }

        for case in test_cases:
            result = await self.evaluate_single_query(
                question=case["question"],
                knowledge_base_id=knowledge_base_id,
                ground_truth=case.get("ground_truth")
            )
            results.append(result)
            
            # 收集指标
            if result.get("metrics"):
                for metric, score in result["metrics"].items():
                    if metric in total_metrics:
                        total_metrics[metric].append(score)

        # 计算平均指标
        avg_metrics = {}
        for metric, scores in total_metrics.items():
            if scores:
                avg_metrics[f"avg_{metric}"] = sum(scores) / len(scores)

        return {
            "total_cases": len(test_cases),
            "results": results,
            "average_metrics": avg_metrics,
            "evaluation_time": datetime.now().isoformat()
        }

    def quick_evaluate_retrieval(
        self,
        question: str,
        knowledge_base_id: str
    ) -> Dict[str, Any]:
        """
        快速评估检索质量（不需要 LLM）

        只评估检索相关的基础指标：
        - 检索数量
        - 相似度分数分布

        Args:
            question: 用户问题
            knowledge_base_id: 知识库ID

        Returns:
            快速评估结果
        """
        import asyncio
        
        async def _evaluate():
            results = await rag_service.search(question, knowledge_base_id)
            
            if not results:
                return {
                    "question": question,
                    "retrieved_count": 0,
                    "avg_score": 0,
                    "max_score": 0,
                    "min_score": 0,
                    "scores": []
                }
            
            scores = [r['score'] for r in results]
            
            return {
                "question": question,
                "retrieved_count": len(results),
                "avg_score": sum(scores) / len(scores) if scores else 0,
                "max_score": max(scores) if scores else 0,
                "min_score": min(scores) if scores else 0,
                "scores": scores,
                "contexts_preview": [
                    {
                        "score": r['score'],
                        "preview": r['content'][:100] + "..."
                    }
                    for r in results[:3]
                ]
            }
        
        # 运行异步函数
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(_evaluate())


# 创建全局实例
ragas_evaluation_service = RAGASEvaluationService()

__all__ = ['RAGASEvaluationService', 'ragas_evaluation_service']
