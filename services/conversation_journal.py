"""
兼容层 - 对话日志

保持向后兼容，从新模块导出。
"""
from services.context.conversation_journal import (
    ConversationJournalService, 
    conversation_journal,
    JOURNAL_ROOT_DIR
)

__all__ = ['ConversationJournalService', 'conversation_journal', 'JOURNAL_ROOT_DIR']
