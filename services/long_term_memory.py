"""
兼容层 - 长期记忆

保持向后兼容，从新模块导出。
"""
from services.context.long_term_memory import (
    LongTermMemory, 
    long_term_memory,
    MemoryType,
    DEFAULT_RELEVANCE_THRESHOLD
)

__all__ = ['LongTermMemory', 'long_term_memory', 'MemoryType', 'DEFAULT_RELEVANCE_THRESHOLD']
