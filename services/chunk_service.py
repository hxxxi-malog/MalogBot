"""
通用文本分块服务

提供文本分块功能，用于：
1. 记忆内容的分块处理
2. 文档内容的分块处理
3. 其他需要向量化的长文本分块
"""
import logging
from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import Config

logger = logging.getLogger(__name__)


class ChunkService:
    """通用文本分块服务"""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        min_chunk_size: int = 50  # 最小分块大小，小于此值不分块
    ):
        """
        初始化分块服务

        Args:
            chunk_size: 分块大小，默认使用配置值
            chunk_overlap: 分块重叠大小，默认使用配置值
            min_chunk_size: 最小分块大小阈值
        """
        self.chunk_size = chunk_size or Config.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or Config.CHUNK_OVERLAP
        self.min_chunk_size = min_chunk_size

        # 初始化递归分词器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
            separators=[
                "\n\n",  # 首先尝试按段落分割
                "\n",    # 然后按行分割
                "。",    # 中文句号
                "！",    # 中文感叹号
                "？",    # 中文问号
                "；",    # 中文分号
                ".",     # 英文句号
                "!",     # 英文感叹号
                "?",     # 英文问号
                ";",     # 英文分号
                " ",     # 空格
                ""       # 最后按字符分割
            ]
        )

    def should_chunk(self, text: str) -> bool:
        """
        判断文本是否需要分块

        Args:
            text: 待判断的文本

        Returns:
            是否需要分块
        """
        return len(text) > self.min_chunk_size

    def chunk_text(self, text: str) -> List[str]:
        """
        对文本进行分块

        如果文本长度小于最小分块大小，则返回原文本的单元素列表

        Args:
            text: 待分块的文本

        Returns:
            分块列表
        """
        if not text or not text.strip():
            return []

        # 如果文本较短，不需要分块
        if len(text) <= self.min_chunk_size:
            return [text.strip()]

        # 进行分块
        chunks = self.text_splitter.split_text(text)

        logger.info(f"[ChunkService] 文本分块完成: 原长度 {len(text)}, 分块数 {len(chunks)}")

        return chunks

    def chunk_for_memory(self, content: str) -> List[str]:
        """
        为记忆存储进行分块

        记忆内容通常较短，使用更小的最小分块阈值

        Args:
            content: 记忆内容

        Returns:
            分块列表
        """
        # 记忆内容使用较小的阈值
        memory_min_size = 200  # 200字符以下不分块

        if not content or not content.strip():
            return []

        # 如果内容较短，不需要分块
        if len(content) <= memory_min_size:
            return [content.strip()]

        # 进行分块，但限制分块数量，避免记忆碎片化
        chunks = self.text_splitter.split_text(content)

        # 如果分块太多，合并小的分块
        if len(chunks) > 5:
            # 合并相邻的小分块
            merged_chunks = []
            current_chunk = ""

            for chunk in chunks:
                if len(current_chunk) + len(chunk) < self.chunk_size:
                    current_chunk += "\n" + chunk if current_chunk else chunk
                else:
                    if current_chunk:
                        merged_chunks.append(current_chunk.strip())
                    current_chunk = chunk

            if current_chunk:
                merged_chunks.append(current_chunk.strip())

            chunks = merged_chunks

        logger.info(f"[ChunkService] 记忆分块完成: 原长度 {len(content)}, 分块数 {len(chunks)}")

        return chunks


# 创建全局实例
chunk_service = ChunkService()

__all__ = ['ChunkService', 'chunk_service']
