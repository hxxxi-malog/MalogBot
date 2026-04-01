"""
兼容层 - 上下文压缩

保持向后兼容，从新模块导出。
"""
from services.context.context_compactor import (
    ContextCompactor, 
    context_compactor,
    micro_compact,
    should_auto_compact,
    auto_compact,
    manual_compact
)

__all__ = [
    'ContextCompactor',
    'context_compactor',
    'micro_compact',
    'should_auto_compact',
    'auto_compact',
    'manual_compact'
]
