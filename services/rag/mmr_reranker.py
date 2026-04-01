"""
MMR（Maximal Marginal Relevance）重排序服务

用于解决检索结果多样性问题，避免重复内容占据高位。

MMR得分公式：
MMR(d) = α × Relevance(d) + (1-α) × (1 - MaxSimilarity(d, S))

其中：
- α: 相关性权重（默认0.7）
- Relevance(d): 文档d的相关性分数
- MaxSimilarity(d, S): 文档d与已选集合S的最大相似度
- (1 - MaxSimilarity): 多样性分数
"""
import logging
from typing import List, Dict, Any, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class MMRReranker:
    """MMR重排序器"""
    
    def __init__(self, alpha: float = 0.7):
        """
        初始化MMR重排序器
        
        Args:
            alpha: 相关性权重，范围[0, 1]
                   - alpha越大，越偏向相关性
                   - alpha越小，越偏向多样性
                   - 默认0.7，平衡相关性和多样性
        """
        self.alpha = alpha
    
    def rerank(
        self,
        candidates: List[Dict[str, Any]],
        relevance_key: str = 'score',
        content_key: str = 'content',
        embedding_key: str = 'embedding',
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        使用MMR算法重排序候选结果
        
        Args:
            candidates: 候选结果列表，每个结果需包含相关性分数和内容
            relevance_key: 相关性分数的键名
            content_key: 内容文本的键名
            embedding_key: 向量嵌入的键名（可选，用于精确相似度计算）
            top_k: 返回结果数量
            
        Returns:
            重排序后的结果列表
        """
        if not candidates:
            return []
        
        # 先进行基于内容的去重（解决数据库中重复数据的问题）
        candidates = self._deduplicate_by_content(candidates, content_key)
        
        if len(candidates) <= top_k:
            # 候选数量不足，直接返回（已去重）
            return candidates[:top_k]
        
        # 提取相关性分数
        relevance_scores = np.array([
            c.get(relevance_key, 0) for c in candidates
        ])
        
        # 归一化相关性分数
        if relevance_scores.max() > relevance_scores.min():
            relevance_scores = (relevance_scores - relevance_scores.min()) / \
                              (relevance_scores.max() - relevance_scores.min())
        
        # 计算文本相似度矩阵
        similarity_matrix = self._compute_similarity_matrix(
            candidates, content_key, embedding_key
        )
        
        # MMR贪心选择
        selected_indices = []
        selected_set = set()
        
        for _ in range(top_k):
            best_idx = -1
            best_mmr = -float('inf')
            
            for i in range(len(candidates)):
                if i in selected_set:
                    continue
                
                # 计算MMR分数
                relevance = relevance_scores[i]
                
                # 计算与已选集合的最大相似度
                if selected_indices:
                    max_sim = max(similarity_matrix[i, j] for j in selected_indices)
                else:
                    max_sim = 0.0
                
                # MMR = α × 相关性 + (1-α) × (1 - 最大相似度)
                mmr_score = self.alpha * relevance + (1 - self.alpha) * (1 - max_sim)
                
                if mmr_score > best_mmr:
                    best_mmr = mmr_score
                    best_idx = i
            
            if best_idx >= 0:
                selected_indices.append(best_idx)
                selected_set.add(best_idx)
        
        # 构建结果
        results = []
        for idx in selected_indices:
            result = candidates[idx].copy()
            result['mmr_rank'] = len(results) + 1
            results.append(result)
        
        logger.info(
            f"[MMR] 重排序完成: 输入 {len(candidates)} 个候选, "
            f"输出 {len(results)} 个结果 (α={self.alpha})"
        )
        
        return results
    
    def _deduplicate_by_content(
        self,
        candidates: List[Dict[str, Any]],
        content_key: str,
        id_key: str = 'id'
    ) -> List[Dict[str, Any]]:
        """
        基于内容去重
        
        当内容完全相同时，保留相关性分数最高的一条
        
        Args:
            candidates: 候选结果列表
            content_key: 内容文本的键名
            id_key: ID的键名
            
        Returns:
            去重后的候选列表
        """
        seen_content = {}
        unique_candidates = []
        duplicate_count = 0
        
        for candidate in candidates:
            content = candidate.get(content_key, '')
            cand_id = candidate.get(id_key, '')
            score = candidate.get('relevance_score', candidate.get('score', 0))
            
            # 使用内容作为去重键
            if content in seen_content:
                # 如果当前分数更高，替换
                existing_idx = seen_content[content]
                existing_score = unique_candidates[existing_idx].get(
                    'relevance_score', 
                    unique_candidates[existing_idx].get('score', 0)
                )
                if score > existing_score:
                    unique_candidates[existing_idx] = candidate
                duplicate_count += 1
            else:
                seen_content[content] = len(unique_candidates)
                unique_candidates.append(candidate)
        
        if duplicate_count > 0:
            logger.info(f"[MMR] 去重: 移除了 {duplicate_count} 条重复内容")
        
        return unique_candidates
    
    def _compute_similarity_matrix(
        self,
        candidates: List[Dict[str, Any]],
        content_key: str,
        embedding_key: str
    ) -> np.ndarray:
        """
        计算候选文档之间的相似度矩阵
        
        优先使用向量嵌入计算余弦相似度，否则使用文本重叠度
        
        Args:
            candidates: 候选结果列表
            content_key: 内容文本的键名
            embedding_key: 向量嵌入的键名
            
        Returns:
            相似度矩阵 (n x n)
        """
        n = len(candidates)
        matrix = np.zeros((n, n))
        
        # 检查是否有向量嵌入
        has_embeddings = all(embedding_key in c and c[embedding_key] is not None 
                           for c in candidates)
        
        if has_embeddings:
            # 使用向量余弦相似度
            embeddings = []
            for c in candidates:
                emb = c[embedding_key]
                if isinstance(emb, str):
                    import json
                    emb = json.loads(emb)
                embeddings.append(np.array(emb))
            
            embeddings = np.array(embeddings)
            
            # 归一化
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1
            embeddings_normalized = embeddings / norms
            
            # 计算余弦相似度矩阵
            matrix = np.dot(embeddings_normalized, embeddings_normalized.T)
            
        else:
            # 使用Jaccard文本相似度
            contents = [c.get(content_key, '') for c in candidates]
            token_sets = [self._tokenize(c) for c in contents]
            
            for i in range(n):
                for j in range(i + 1, n):
                    sim = self._jaccard_similarity(token_sets[i], token_sets[j])
                    matrix[i, j] = sim
                    matrix[j, i] = sim
        
        return matrix
    
    def _tokenize(self, text: str) -> set:
        """简单分词（用于文本相似度计算）"""
        # 中文按字符分割，英文按单词分割
        import re
        tokens = set()
        
        # 中文
        chinese = re.findall(r'[\u4e00-\u9fff]+', text)
        for word in chinese:
            tokens.update(word)
        
        # 英文
        english = re.findall(r'[a-zA-Z]+', text.lower())
        tokens.update(english)
        
        return tokens
    
    def _jaccard_similarity(self, set1: set, set2: set) -> float:
        """计算Jaccard相似度"""
        if not set1 or not set2:
            return 0.0
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def rerank_with_embeddings(
        self,
        candidates: List[Dict[str, Any]],
        embeddings: List[List[float]],
        relevance_scores: List[float],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        使用预计算的向量嵌入进行MMR重排序
        
        Args:
            candidates: 候选结果列表
            embeddings: 对应的向量嵌入列表
            relevance_scores: 对应的相关性分数列表
            top_k: 返回结果数量
            
        Returns:
            重排序后的结果列表
        """
        if not candidates:
            return []
        
        # 添加嵌入和分数到候选中
        for i, c in enumerate(candidates):
            c['embedding'] = embeddings[i]
            c['score'] = relevance_scores[i]
        
        return self.rerank(
            candidates,
            relevance_key='score',
            embedding_key='embedding',
            top_k=top_k
        )


# 创建默认实例
mmr_reranker = MMRReranker(alpha=0.7)

__all__ = ['MMRReranker', 'mmr_reranker']
