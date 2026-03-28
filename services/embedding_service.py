"""
阿里云百炼向量化服务

提供文本向量化和重排序功能
"""
import httpx
from typing import List, Optional
import logging

from config import Config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """阿里云百炼向量化和重排序服务"""

    def __init__(self):
        """初始化服务"""
        self.api_key = Config.DASHSCOPE_API_KEY
        self.embedding_model = Config.EMBEDDING_MODEL
        self.rerank_model = Config.RERANK_MODEL
        self.embedding_dimension = Config.EMBEDDING_DIMENSION

        # API 端点
        self.embedding_url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
        self.rerank_url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"

    async def get_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """
        获取文本的向量表示

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量是一个浮点数列表
        """
        if not texts:
            return []

        # 阿里云百炼 API 限制：每批最多 10 条文本
        BATCH_SIZE = 10
        all_embeddings = []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # 分批处理
                for i in range(0, len(texts), BATCH_SIZE):
                    batch_texts = texts[i:i + BATCH_SIZE]
                    
                    response = await client.post(
                        self.embedding_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.embedding_model,
                            "input": {
                                "texts": batch_texts
                            },
                            "parameters": {
                                "text_type": "document"  # 文档类型
                            }
                        }
                    )

                    if response.status_code != 200:
                        logger.error(f"Embedding API error: {response.status_code} - {response.text}")
                        return None

                    data = response.json()

                    if "output" not in data or "embeddings" not in data["output"]:
                        logger.error(f"Invalid embedding response: {data}")
                        return None

                    # 提取向量并保持顺序
                    batch_embeddings = [item["embedding"] for item in data["output"]["embeddings"]]
                    all_embeddings.extend(batch_embeddings)
                    
                    logger.info(f"[Embedding] 已处理 {min(i + BATCH_SIZE, len(texts))}/{len(texts)} 个文本块")

                return all_embeddings

        except Exception as e:
            logger.error(f"Error getting embeddings: {str(e)}")
            return None

    async def get_single_embedding(self, text: str) -> Optional[List[float]]:
        """
        获取单个文本的向量表示

        Args:
            text: 文本内容

        Returns:
            向量（浮点数列表）
        """
        embeddings = await self.get_embeddings([text])
        if embeddings and len(embeddings) > 0:
            return embeddings[0]
        return None

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = None
    ) -> List[dict]:
        """
        对文档进行重排序

        Args:
            query: 查询文本
            documents: 文档列表
            top_k: 返回最相关的 top_k 个文档

        Returns:
            重排序后的文档列表，每个包含 index, relevance_score, document
        """
        if not documents:
            return []

        top_k = top_k or Config.RAG_TOP_K

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.rerank_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.rerank_model,
                        "input": {
                            "query": query,
                            "documents": documents
                        },
                        "parameters": {
                            "top_n": min(top_k, len(documents))
                        }
                    }
                )

                if response.status_code != 200:
                    logger.error(f"Rerank API error: {response.status_code} - {response.text}")
                    # 如果重排序失败，返回原始顺序的文档
                    return [
                        {"index": i, "relevance_score": 0.5, "document": doc}
                        for i, doc in enumerate(documents[:top_k])
                    ]

                data = response.json()

                if "output" not in data or "results" not in data["output"]:
                    logger.error(f"Invalid rerank response: {data}")
                    return [
                        {"index": i, "relevance_score": 0.5, "document": doc}
                        for i, doc in enumerate(documents[:top_k])
                    ]

                # 提取重排序结果
                results = []
                for item in data["output"]["results"]:
                    index = item["index"]
                    score = item["relevance_score"]
                    results.append({
                        "index": index,
                        "relevance_score": score,
                        "document": documents[index] if index < len(documents) else ""
                    })

                return results

        except Exception as e:
            logger.error(f"Error in reranking: {str(e)}")
            # 如果重排序失败，返回原始顺序的文档
            return [
                {"index": i, "relevance_score": 0.5, "document": doc}
                for i, doc in enumerate(documents[:top_k])
            ]


# 创建全局实例
embedding_service = EmbeddingService()

__all__ = ['EmbeddingService', 'embedding_service']
