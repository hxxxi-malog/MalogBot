"""
BM25检索服务

提供基于BM25算法的关键词匹配检索
"""
import json
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import text

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

from services.db_manager import db_manager
from services.tokenizer_service import tokenizer_service

logger = logging.getLogger(__name__)


class BM25Service:
    """BM25检索服务"""
    
    def __init__(self):
        """初始化服务"""
        if not HAS_BM25:
            logger.warning("rank_bm25未安装，BM25检索功能将不可用")
        
        # 缓存：knowledge_base_id -> (corpus_tokens, chunk_ids, bm25_index)
        self._cache: Dict[str, dict] = {}
    
    def _load_corpus_from_db(self, knowledge_base_id: str) -> Optional[dict]:
        """
        从数据库加载知识库的语料库
        
        Args:
            knowledge_base_id: 知识库ID
            
        Returns:
            包含语料库数据的字典，或None
        """
        try:
            with db_manager.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, document_id, content, tokens, chunk_metadata
                    FROM document_chunks
                    WHERE knowledge_base_id = :kb_id
                    AND tokens IS NOT NULL
                """), {'kb_id': knowledge_base_id})
                
                rows = result.fetchall()
                
                if not rows:
                    logger.warning(f"[BM25] 知识库 {knowledge_base_id} 没有分词数据")
                    return None
                
                corpus_tokens = []
                chunk_ids = []
                chunk_data = []
                
                for row in rows:
                    chunk_id = str(row[0])
                    document_id = str(row[1])
                    content = row[2]
                    tokens_json = row[3]
                    metadata = row[4]
                    
                    # 解析tokens
                    try:
                        tokens = json.loads(tokens_json) if tokens_json else []
                    except json.JSONDecodeError:
                        tokens = []
                    
                    if tokens:
                        corpus_tokens.append(tokens)
                        chunk_ids.append(chunk_id)
                        chunk_data.append({
                            'id': chunk_id,
                            'document_id': document_id,
                            'content': content,
                            'metadata': metadata
                        })
                
                if not corpus_tokens:
                    return None
                
                # 构建BM25索引
                bm25_index = BM25Okapi(corpus_tokens)
                
                return {
                    'corpus_tokens': corpus_tokens,
                    'chunk_ids': chunk_ids,
                    'chunk_data': chunk_data,
                    'bm25_index': bm25_index
                }
                
        except Exception as e:
            logger.error(f"[BM25] 加载语料库失败: {str(e)}")
            return None
    
    def _get_index(self, knowledge_base_id: str) -> Optional[dict]:
        """
        获取知识库的BM25索引（带缓存）
        
        Args:
            knowledge_base_id: 知识库ID
            
        Returns:
            BM25索引数据
        """
        # 暂时禁用缓存，每次重新加载以确保数据最新
        # TODO: 可以在文档更新时清除缓存
        return self._load_corpus_from_db(knowledge_base_id)
    
    def search(
        self,
        query: str,
        knowledge_base_id: str,
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        BM25检索
        
        Args:
            query: 查询文本
            knowledge_base_id: 知识库ID
            top_n: 返回数量
            
        Returns:
            检索结果列表
        """
        if not HAS_BM25:
            logger.error("[BM25] rank_bm25未安装")
            return []
        
        # 获取索引
        index_data = self._get_index(knowledge_base_id)
        if not index_data:
            return []
        
        bm25_index = index_data['bm25_index']
        chunk_ids = index_data['chunk_ids']
        chunk_data = index_data['chunk_data']
        
        # 对查询进行分词
        query_tokens = tokenizer_service.tokenize(query)
        if not query_tokens:
            return []
        
        logger.info(f"[BM25] 查询分词: {query_tokens}")
        
        # BM25打分
        scores = bm25_index.get_scores(query_tokens)
        
        # 获取top_n结果
        # 结合分数和索引
        scored_results = list(zip(range(len(scores)), scores))
        scored_results.sort(key=lambda x: x[1], reverse=True)
        
        results = []
        for idx, score in scored_results[:top_n]:
            if score > 0:  # 只返回有分数的结果
                result = chunk_data[idx].copy()
                result['score'] = float(score)
                results.append(result)
        
        logger.info(f"[BM25] 检索找到 {len(results)} 个结果")
        return results
    
    def clear_cache(self, knowledge_base_id: str = None):
        """
        清除缓存
        
        Args:
            knowledge_base_id: 知识库ID，为None时清除所有缓存
        """
        if knowledge_base_id:
            self._cache.pop(knowledge_base_id, None)
        else:
            self._cache.clear()


# 创建全局实例
bm25_service = BM25Service()

__all__ = ['BM25Service', 'bm25_service']
