"""
Bootstrap 加载机制模块

实现第四阶段：基于 Token 预算的动态知识加载
1. TokenCounter - Token 计数器（tiktoken）
2. BootstrapConfig/BootstrapResult - 数据结构定义
3. PromptAssembler - Prompt 组装器
4. BootstrapService - 核心加载服务
"""

from services.bootstrap.token_counter import TokenCounter, token_counter
from services.bootstrap.models import (
    SessionType,
    BootstrapConfig,
    BootstrapResult,
    BootstrapStats
)
from services.bootstrap.prompt_assembler import PromptAssembler, prompt_assembler
from services.bootstrap.bootstrap_service import BootstrapService, bootstrap_service

__all__ = [
    # Token 计数
    'TokenCounter',
    'token_counter',
    # 数据结构
    'SessionType',
    'BootstrapConfig',
    'BootstrapResult',
    'BootstrapStats',
    # Prompt 组装
    'PromptAssembler',
    'prompt_assembler',
    # 核心服务
    'BootstrapService',
    'bootstrap_service'
]
