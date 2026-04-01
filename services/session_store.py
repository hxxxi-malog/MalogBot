"""
兼容层 - 会话存储

保持向后兼容，从新模块导出。
"""
from services.context.session_store import SessionStore, session_store

__all__ = ['SessionStore', 'session_store']
