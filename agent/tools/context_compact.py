"""
上下文压缩工具模块（重构版）

提供手动触发上下文压缩的工具，供 Agent 使用：
1. compact_context - 手动压缩当前会话的上下文
2. list_archives - 列出可恢复的归档
3. restore_archive - 恢复指定的归档
4. get_context_stats - 获取上下文统计信息
5. search_memories - 搜索长期记忆
"""
from typing import Optional, List, Dict, Any
from langchain_core.tools import tool

from services.context_compactor import context_compactor
from services.long_term_memory import long_term_memory
from agent.llm import get_llm


def _get_session_id(config: dict = None) -> str:
    """
    从 config 或 contextvars 获取 session_id
    
    Args:
        config: 工具调用时传入的配置
        
    Returns:
        session_id
    """
    # 从 config 中获取 session_id
    session_id = None
    if config:
        session_id = config.get("configurable", {}).get("session_id")
    
    # 如果 config 中没有，尝试从 contextvars 获取
    if not session_id:
        from agent.tools.todo_manager import get_current_session
        session_id = get_current_session()
    
    return session_id


@tool
def compact_context(reason: str = "", config: dict = None) -> str:
    """
    手动压缩当前会话的上下文，释放 token 空间。
    
    **适用场景：**
    - 对话历史过长，影响注意力机制
    - 需要清理旧的工具调用结果
    - 预计后续对话较长，提前释放空间
    
    **工作原理：**
    1. 保存完整对话到JSONL文件和数据库归档（可恢复）
    2. 后台提取关键信息存储到长期记忆（向量检索）
    3. 使用 LLM 生成对话摘要
    4. 用摘要替换旧消息，保留最近的几条
    
    **三层存储架构：**
    - Journal层：完整原始对话，可恢复
    - Memory层：关键信息向量存储，可检索
    - Summary层：当前上下文摘要，轻量级
    
    Args:
        reason: 压缩原因（可选，用于记录）
        
    Returns:
        压缩结果，包含归档ID和压缩统计
    """
    session_id = _get_session_id(config)
    
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

注：
- 完整对话已归档到JSONL文件，可使用 restore_context_archive 工具恢复
- 关键信息已提取并存储到长期记忆，可使用 search_memories 工具检索
"""
    else:
        return f"压缩失败: {result.get('message', '未知错误')}"


@tool
def list_context_archives(limit: int = 5, config: dict = None) -> str:
    """
    列出当前会话的可恢复归档列表。
    
    当上下文被压缩后，原始对话会被归档保存到JSONL文件。
    使用此工具可以查看可恢复的归档记录。
    
    Args:
        limit: 最多返回的归档数量，默认5个
        
    Returns:
        归档列表，包含归档ID、消息数量、创建时间等
    """
    session_id = _get_session_id(config)
    archives = context_compactor.list_archives(session_id, limit)
    
    if not archives:
        return "当前会话没有可恢复的归档记录。"
    
    lines = ["## 可恢复的上下文归档\n"]
    for a in archives:
        lines.append(f"- **归档ID**: `{a.get('id', 'N/A')}`")
        lines.append(f"  - 消息数量: {a.get('message_count', 0)}")
        lines.append(f"  - Token数量: {a.get('token_count', 0)}")
        lines.append(f"  - 创建时间: {a.get('created_at', 'N/A')}")
        lines.append("")
    
    lines.append("使用 `restore_context_archive` 工具可以恢复指定的归档。")
    
    return "\n".join(lines)


@tool
def restore_context_archive(archive_id: str, config: dict = None) -> str:
    """
    从归档恢复完整的对话历史。
    
    **警告：**
    - 恢复会增加上下文长度
    - 当前对话内容会被归档内容替换
    - 建议仅在需要查看详细历史时使用
    
    **流程：**
    1. 从JSONL文件读取归档的完整消息
    2. 替换当前会话的消息历史
    3. 恢复后可以继续基于完整历史对话
    
    Args:
        archive_id: 归档ID（从 list_context_archives 获取）
        
    Returns:
        恢复结果
    """
    from services.session_store import session_store
    
    session_id = _get_session_id(config)
    
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
def get_context_stats(config: dict = None) -> str:
    """
    获取当前会话的上下文统计信息。
    
    包括：
    - 消息数量和Token统计
    - 压缩阈值和使用比例
    - 长期记忆状态
    - 压缩建议
    
    Returns:
        上下文统计信息
    """
    import logging
    from services.session_store import session_store
    from services.context_compactor import context_compactor
    
    logger = logging.getLogger(__name__)
    
    session_id = _get_session_id(config)
    logger.info(f"[get_context_stats] session_id={session_id}")
    
    # 获取上下文统计
    stats = session_store.get_context_stats(session_id)
    
    # 获取消息数量
    message_count = session_store.get_message_count(session_id)
    
    # 判断是否需要压缩
    need_compress = stats.get('should_compact', False)
    usage_ratio = stats.get('usage_ratio', 0)
    
    lines = [
        "## 上下文统计\n",
        f"- 当前会话: `{session_id}`",
        f"- 消息数量: {message_count}",
        f"- Token估算: {stats.get('token_count', 0):,}",
        f"- 最大上下文: {stats.get('max_context_tokens', 0):,}",
        f"- 压缩阈值: {stats.get('compact_threshold', 0):,} (80%)",
        f"- 使用比例: {usage_ratio:.1%}",
        f"- 压缩建议: {'**建议压缩**' if need_compress else '暂不需要'}"
    ]
    
    if need_compress:
        lines.append("\n上下文较长，建议使用 `compact_context` 工具压缩以释放空间。")
        lines.append(f"距离阈值还需 {stats.get('tokens_until_compact', 0):,} tokens。")
    
    return "\n".join(lines)


@tool
def search_long_term_memories(
    query: str,
    limit: int = 5,
    memory_type: str = "",
    config: dict = None
) -> str:
    """
    搜索长期记忆中存储的关键信息。
    
    **长期记忆包含：**
    - 事实信息（fact）：用户告诉Agent的具体信息
    - 决策（decision）：Agent做出的重要决策
    - 偏好（preference）：用户的偏好设置
    - 行动（action）：执行的重要操作
    - 摘要（summary）：对话的总结
    - 上下文（context）：文件路径、项目结构等
    
    **使用场景：**
    - 回忆之前的对话内容
    - 查找用户偏好
    - 检索项目相关信息
    
    Args:
        query: 搜索查询
        limit: 返回结果数量，默认5
        memory_type: 记忆类型过滤（可选）：fact, decision, preference, action, summary, context
        
    Returns:
        搜索结果
    """
    session_id = _get_session_id(config)
    
    # 处理记忆类型过滤
    memory_types = [memory_type] if memory_type else None
    
    # 搜索记忆
    memories = long_term_memory.search_memories(
        query=query,
        limit=limit,
        memory_types=memory_types,
        session_id=session_id,
        min_importance=0.3
    )
    
    if not memories:
        return f"未找到与 '{query}' 相关的长期记忆。"
    
    lines = [f"## 长期记忆搜索结果\n"]
    lines.append(f"查询: {query}\n")
    
    for i, memory in enumerate(memories, 1):
        mem_type = memory.get('memory_type', 'unknown')
        content = memory.get('content', '')
        importance = memory.get('importance', 0)
        
        type_labels = {
            'fact': '事实',
            'decision': '决策',
            'preference': '偏好',
            'action': '行动',
            'summary': '摘要',
            'context': '上下文'
        }
        type_label = type_labels.get(mem_type, mem_type)
        
        lines.append(f"{i}. [{type_label}] (重要性: {importance:.1f})")
        lines.append(f"   {content}")
        lines.append("")
    
    return "\n".join(lines)


@tool
def get_recent_memories(
    limit: int = 10,
    memory_type: str = "",
    config: dict = None
) -> str:
    """
    获取最近的长期记忆。
    
    按时间倒序返回最近的记忆记录。
    
    Args:
        limit: 返回数量，默认10
        memory_type: 记忆类型过滤（可选）
        
    Returns:
        最近的记忆列表
    """
    session_id = _get_session_id(config)
    
    memory_types = [memory_type] if memory_type else None
    
    memories = long_term_memory.get_recent_memories(
        session_id=session_id,
        limit=limit,
        memory_types=memory_types
    )
    
    if not memories:
        return "当前没有长期记忆记录。"
    
    lines = ["## 最近的长期记忆\n"]
    
    type_labels = {
        'fact': '事实',
        'decision': '决策',
        'preference': '偏好',
        'action': '行动',
        'summary': '摘要',
        'context': '上下文'
    }
    
    for memory in memories:
        mem_type = memory.get('memory_type', 'unknown')
        content = memory.get('content', '')
        created_at = memory.get('created_at', '')
        type_label = type_labels.get(mem_type, mem_type)
        
        lines.append(f"- [{type_label}] {content[:100]}{'...' if len(content) > 100 else ''}")
        if created_at:
            lines.append(f"  时间: {created_at}")
    
    return "\n".join(lines)


# ==================== 导出 ====================

CONTEXT_COMPACT_TOOLS = [
    compact_context,
    list_context_archives,
    restore_context_archive,
    get_context_stats,
    search_long_term_memories,
    get_recent_memories
]

__all__ = [
    'compact_context',
    'list_context_archives',
    'restore_context_archive',
    'get_context_stats',
    'search_long_term_memories',
    'get_recent_memories',
    'CONTEXT_COMPACT_TOOLS'
]
