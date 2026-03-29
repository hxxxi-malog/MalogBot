"""
上下文压缩工具模块

提供手动触发上下文压缩的工具，供 Agent 使用：
1. compact_context - 手动压缩当前会话的上下文
2. list_archives - 列出可恢复的归档
3. restore_archive - 恢复指定的归档
"""
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool

from services.context_compactor import context_compactor
from agent.llm import get_llm


@tool
def compact_context(reason: str = "") -> str:
    """
    手动压缩当前会话的上下文，释放 token 空间。
    
    **适用场景：**
    - 对话历史过长，影响注意力机制
    - 需要清理旧的工具调用结果
    - 预计后续对话较长，提前释放空间
    
    **工作原理：**
    1. 保存完整对话到磁盘和数据库（可恢复）
    2. 使用 LLM 生成对话摘要
    3. 用摘要替换旧消息，保留最近的几条
    
    **注意事项：**
    - 压缩后，旧的详细内容会被摘要替代
    - 归档ID会返回，可用于恢复
    - 不影响任务列表和会话设置
    
    Args:
        reason: 压缩原因（可选，用于记录）
        
    Returns:
        压缩结果，包含归档ID和压缩统计
    """
    from agent.tools.todo_manager import get_current_session
    
    session_id = get_current_session()
    
    # 获取 LLM 客户端用于生成摘要
    llm = get_llm(streaming=False)
    
    result = context_compactor.manual_compact(session_id, llm)
    
    if result['success']:
        return f"""## 上下文压缩完成

- 归档ID: {result.get('archive_id', 'N/A')}
- 原始消息数: {result.get('original_count', 0)}
- 压缩后消息数: {result.get('compressed_count', 0)}
- 压缩原因: {reason or '手动触发'}

{result.get('message', '')}

注：完整对话已归档，可使用 restore_archive 工具恢复。
"""
    else:
        return f"压缩失败: {result.get('message', '未知错误')}"


@tool
def list_context_archives(limit: int = 5) -> str:
    """
    列出当前会话的可恢复归档列表。
    
    当上下文被压缩后，原始对话会被归档保存。
    使用此工具可以查看可恢复的归档记录。
    
    Args:
        limit: 最多返回的归档数量，默认5个
        
    Returns:
        归档列表，包含归档ID、消息数量、创建时间等
    """
    from agent.tools.todo_manager import get_current_session
    
    session_id = get_current_session()
    archives = context_compactor.list_archives(session_id, limit)
    
    if not archives:
        return "当前会话没有可恢复的归档记录。"
    
    lines = ["## 可恢复的上下文归档\n"]
    for a in archives:
        lines.append(f"- **归档ID**: `{a['archive_id']}`")
        lines.append(f"  - 消息数量: {a['message_count']}")
        lines.append(f"  - 创建时间: {a['created_at']}")
        lines.append("")
    
    lines.append("使用 `restore_archive` 工具可以恢复指定的归档。")
    
    return "\n".join(lines)


@tool
def restore_context_archive(archive_id: str) -> str:
    """
    从归档恢复完整的对话历史。
    
    **警告：**
    - 恢复会增加上下文长度
    - 当前对话内容会被归档内容替换
    - 建议仅在需要查看详细历史时使用
    
    **流程：**
    1. 从数据库读取归档的完整消息
    2. 替换当前会话的消息历史
    3. 恢复后可以继续基于完整历史对话
    
    Args:
        archive_id: 归档ID（从 list_context_archives 获取）
        
    Returns:
        恢复结果
    """
    from agent.tools.todo_manager import get_current_session
    from services.session_store import session_store
    
    session_id = get_current_session()
    
    # 从归档恢复
    messages = context_compactor.restore_from_archive(archive_id)
    
    if not messages:
        return f"恢复失败：找不到归档 {archive_id}"
    
    # 更新会话的消息历史
    session_store.replace_messages(session_id, messages)
    
    return f"""## 归档恢复成功

- 归档ID: {archive_id}
- 恢复的消息数: {len(messages)}

对话历史已恢复，现在可以查看完整的对话细节了。
注意：上下文长度已增加，如果影响性能可再次压缩。
"""


@tool
def get_context_stats() -> str:
    """
    获取当前会话的上下文统计信息。
    
    包括：
    - 消息数量
    - 估算的 token 数量
    - 压缩建议
    
    Returns:
        上下文统计信息
    """
    from agent.tools.todo_manager import get_current_session
    from services.session_store import session_store
    from services.context_compactor import AUTO_COMPACT_THRESHOLD
    
    session_id = get_current_session()
    messages = session_store.get_messages(session_id)
    
    # 估算 token 数量（字符数近似）
    total_chars = sum(len(m.get('content', '')) for m in messages)
    estimated_tokens = total_chars // 4  # 粗略估计
    
    # 判断是否需要压缩
    need_compress = total_chars > AUTO_COMPACT_THRESHOLD * 0.8  # 80% 阈值
    
    lines = [
        "## 上下文统计\n",
        f"- 消息数量: {len(messages)}",
        f"- 估算字符数: {total_chars:,}",
        f"- 估算 Token 数: ~{estimated_tokens:,}",
        f"- 自动压缩阈值: {AUTO_COMPACT_THRESHOLD:,} 字符",
        f"- 压缩建议: {'**建议压缩**' if need_compress else '暂不需要'}"
    ]
    
    if need_compress:
        lines.append("\n上下文较长，建议使用 `compact_context` 工具压缩以释放空间。")
    
    return "\n".join(lines)


# ==================== 导出 ====================

CONTEXT_COMPACT_TOOLS = [
    compact_context,
    list_context_archives,
    restore_context_archive,
    get_context_stats
]

__all__ = [
    'compact_context',
    'list_context_archives',
    'restore_context_archive',
    'get_context_stats',
    'CONTEXT_COMPACT_TOOLS'
]
