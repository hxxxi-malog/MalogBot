"""
Token 计数器

使用 tiktoken 进行精确的 Token 计数，支持：
1. GPT-4、GPT-3.5-turbo、DeepSeek 等模型（cl100k_base）
2. GPT-4o 等新模型（o200k_base）
3. 回退机制：tiktoken 不可用时使用字符估算
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# tiktoken 可用性检测
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    logger.warning("[TokenCounter] tiktoken 未安装，将使用字符估算方法")


class TokenCounter:
    """Token 计数器
    
    使用 tiktoken 进行精确计数，支持回退到字符估算。
    
    支持的编码：
    - cl100k_base: GPT-4, GPT-3.5-turbo, DeepSeek, Claude 等
    - o200k_base: GPT-4o, GPT-4o-mini 等
    
    使用方式：
        counter = TokenCounter()
        tokens = counter.count_tokens("你好，世界！")
    """
    
    def __init__(self, encoding_name: str = "cl100k_base"):
        """
        初始化 Token 计数器
        
        Args:
            encoding_name: 编码名称
                - cl100k_base: 适用于 GPT-4, GPT-3.5-turbo, DeepSeek 等
                - o200k_base: 适用于 GPT-4o 等
        """
        self._encoding = None
        self._encoding_name = encoding_name
        self._available = HAS_TIKTOKEN
        
        if self._available:
            logger.info(f"[TokenCounter] 初始化成功，编码: {encoding_name}")
        else:
            logger.info("[TokenCounter] 使用字符估算模式")
    
    @property
    def encoding(self):
        """延迟加载编码器"""
        if not self._available:
            return None
            
        if self._encoding is None:
            try:
                self._encoding = tiktoken.get_encoding(self._encoding_name)
                logger.debug(f"[TokenCounter] 编码器加载成功: {self._encoding_name}")
            except Exception as e:
                logger.error(f"[TokenCounter] 编码器加载失败: {e}")
                self._available = False
                return None
        
        return self._encoding
    
    def count_tokens(self, text: str) -> int:
        """
        计算 Token 数量
        
        Args:
            text: 文本内容
        
        Returns:
            Token 数量
        """
        if not text:
            return 0
        
        # 尝试使用 tiktoken
        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception as e:
                logger.warning(f"[TokenCounter] tiktoken 编码失败: {e}，回退到字符估算")
        
        # 回退：字符估算（中文约1.5字符/token，英文约4字符/token）
        # 简化为 len(text) // 3，对于中英文混合内容误差约 10-20%
        return self._estimate_by_chars(text)
    
    def _estimate_by_chars(self, text: str) -> int:
        """
        字符估算方法
        
        对于中英文混合内容：
        - 中文字符：约 1.5 字符/token
        - 英文字符：约 4 字符/token
        - 综合估算：len(text) // 3
        """
        if not text:
            return 0
        
        # 统计中英文字符
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total_chars = len(text)
        
        # 中文按 1.5 字符/token，其他按 4 字符/token
        # 加权估算
        if chinese_chars > 0:
            english_chars = total_chars - chinese_chars
            estimated = int(chinese_chars / 1.5 + english_chars / 4)
            return max(estimated, 1)
        else:
            # 纯英文/其他
            return max(total_chars // 4, 1)
    
    def estimate_tokens(self, text: str) -> int:
        """估算 Token（用于存储时预计算）
        
        与 count_tokens 相同，提供语义化命名
        """
        return self.count_tokens(text)
    
    def count_messages_tokens(self, messages: list) -> int:
        """
        计算消息列表的 Token 数量
        
        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
        
        Returns:
            总 Token 数量
        """
        total = 0
        for msg in messages:
            # 消息格式开销（role, content 键等）
            total += 4  # 每条消息约 4 tokens 格式开销
            content = msg.get('content', '')
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                # 多模态内容
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        total += self.count_tokens(item.get('text', ''))
        
        # 消息列表额外开销
        total += 3  # 消息列表的开始和结束标记
        
        return total
    
    @property
    def is_tiktoken_available(self) -> bool:
        """tiktoken 是否可用"""
        return self._available and self.encoding is not None


# 创建全局实例
token_counter = TokenCounter()


__all__ = ['TokenCounter', 'token_counter']
