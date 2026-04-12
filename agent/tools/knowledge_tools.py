"""
Agent 知识库工具

实现 Agent 自主更新知识的能力：
1. remember_user_info - 记录用户个人信息
2. remember_preference - 记录用户偏好
3. record_mistake - 记录踩坑经验
4. update_environment - 更新环境信息

设计理念：
- Agent 在对话中识别重要信息，主动调用工具记录
- 工具后台异步执行，不阻塞对话流程
- 自动向量化存储，支持语义检索
"""
import json
import logging
import asyncio
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 后台处理线程池
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="knowledge_tool")

# 当前会话ID的上下文变量
_current_session: ContextVar[Optional[str]] = ContextVar('current_session', default=None)


def set_current_session(session_id: str):
    """设置当前会话ID"""
    _current_session.set(session_id)


def get_current_session() -> Optional[str]:
    """获取当前会话ID"""
    return _current_session.get()


# ==================== 输入模型定义 ====================

class RememberUserInfoInput(BaseModel):
    """记录用户信息的输入参数"""
    field: str = Field(
        description="字段名，如 name, timezone, occupation, company 等"
    )
    value: str = Field(
        description="字段值"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="置信度，用户明确说出时为1.0，推测时为0.5-0.8"
    )


class RememberPreferenceInput(BaseModel):
    """记录用户偏好的输入参数"""
    category: str = Field(
        description="偏好类别，如 communication(沟通风格), tech(技术偏好), workflow(工作流程)"
    )
    preference: str = Field(
        description="偏好内容，一句话描述"
    )
    strength: str = Field(
        default="moderate",
        description="强烈程度：strong(强烈), moderate(中等), slight(轻微)"
    )


class RecordMistakeInput(BaseModel):
    """记录踩坑的输入参数"""
    mistake_type: str = Field(
        description="错误类型，如 command_error, config_error, logic_error, api_error"
    )
    context: str = Field(
        description="错误上下文，发生了什么"
    )
    lesson: str = Field(
        description="学到的教训"
    )
    solution: Optional[str] = Field(
        default=None,
        description="解决方案（如果已解决）"
    )
    severity: str = Field(
        default="medium",
        description="严重程度：low, medium, high, critical"
    )


class UpdateEnvironmentInput(BaseModel):
    """更新环境信息的输入参数"""
    env_key: str = Field(
        description="环境信息键，如 database_host, api_endpoint, project_root"
    )
    env_value: str = Field(
        description="环境信息值"
    )
    description: Optional[str] = Field(
        default=None,
        description="补充说明（可选）"
    )


# ==================== 核心处理函数 ====================

def _get_llm_client():
    """获取 LLM 客户端"""
    try:
        from agent.llm import get_llm
        return get_llm(streaming=False)
    except Exception as e:
        logger.warning(f"[KnowledgeTool] 无法获取 LLM 客户端: {e}")
        return None


async def _get_embedding(text: str) -> Optional[List[float]]:
    """获取文本向量"""
    try:
        from services.rag.embedding_service import embedding_service
        return await embedding_service.get_single_embedding(text)
    except Exception as e:
        logger.error(f"[KnowledgeTool] 获取向量失败: {e}")
        return None


def _process_user_info(field: str, value: str, confidence: float, session_id: str):
    """处理用户信息存储"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import user_profile_repo, knowledge_item_repo
        
        logger.info(f"[KnowledgeTool] 记录用户信息: {field}={value}, confidence={confidence}")
        
        with db_manager.get_session() as session:
            # 1. 更新 user_profile_fields 表
            user_profile_repo.set_field(
                session,
                field_name=field,
                field_value=value,
                confidence=confidence,
                source='agent_tool'
            )
            
            # 2. 创建 knowledge_item 记录
            content = f"用户{field}是{value}"
            
            # 获取向量
            embedding = loop.run_until_complete(_get_embedding(content))
            
            if embedding:
                knowledge_item_repo.create_with_embedding(
                    session,
                    content=content,
                    item_type='user_info',
                    embedding=embedding,
                    source_file_type='user',
                    session_id=session_id,
                    importance=confidence,  # 使用置信度作为重要性
                    tags=['user_info', field]
                )
            
            logger.info(f"[KnowledgeTool] 用户信息记录完成: {field}")
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 记录用户信息失败: {e}")
    finally:
        loop.close()


def _process_preference(category: str, preference: str, strength: str, session_id: str):
    """处理用户偏好存储"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import knowledge_item_repo
        
        logger.info(f"[KnowledgeTool] 记录用户偏好: {category}/{preference}, strength={strength}")
        
        with db_manager.get_session() as session:
            # 构建内容
            strength_cn = {'strong': '强烈', 'moderate': '中等', 'slight': '轻微'}.get(strength, '中等')
            content = f"用户{strength_cn}偏好：在{category}方面，{preference}"
            
            # 获取向量
            embedding = loop.run_until_complete(_get_embedding(content))
            
            # 重要性基于偏好强度
            importance = {'strong': 0.9, 'moderate': 0.7, 'slight': 0.5}.get(strength, 0.7)
            
            if embedding:
                knowledge_item_repo.create_with_embedding(
                    session,
                    content=content,
                    item_type='preference',
                    embedding=embedding,
                    source_file_type='user',
                    session_id=session_id,
                    importance=importance,
                    tags=['preference', category]
                )
            
            logger.info(f"[KnowledgeTool] 用户偏好记录完成: {category}")
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 记录用户偏好失败: {e}")
    finally:
        loop.close()


def _process_mistake(
    mistake_type: str,
    context: str,
    lesson: str,
    solution: Optional[str],
    severity: str,
    session_id: str
):
    """处理踩坑记录存储"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import agent_mistake_repo, knowledge_item_repo
        
        logger.info(f"[KnowledgeTool] 记录踩坑: type={mistake_type}, severity={severity}")
        
        with db_manager.get_session() as session:
            # 1. 检查是否存在相似踩坑（向量检索）
            embedding = loop.run_until_complete(_get_embedding(context))
            
            if embedding:
                # 查找相似踩坑
                similar_mistakes = agent_mistake_repo.get_by_type(session, mistake_type, limit=10)
                
                for m in similar_mistakes:
                    m_embedding = m.get_embedding(session)
                    if m_embedding:
                        # 计算相似度
                        import numpy as np
                        sim = np.dot(embedding, m_embedding) / (
                            np.linalg.norm(embedding) * np.linalg.norm(m_embedding)
                        )
                        if sim > 0.85:
                            # 相似踩坑，增加计数
                            agent_mistake_repo.increment_occurrence(session, m.id)
                            logger.info(f"[KnowledgeTool] 发现相似踩坑(id={m.id})，增加计数")
                            return
            
            # 2. 创建新的踩坑记录
            if embedding:
                mistake = agent_mistake_repo.create_with_embedding(
                    session,
                    mistake_type=mistake_type,
                    context=context,
                    embedding=embedding,
                    lesson=lesson,
                    solution=solution,
                    severity=severity,
                    session_id=session_id
                )
            else:
                mistake = agent_mistake_repo.create(
                    session,
                    mistake_type=mistake_type,
                    context=context,
                    lesson=lesson,
                    solution=solution,
                    severity=severity,
                    session_id=session_id
                )
            
            # 3. 同时创建 knowledge_item 记录（用于检索）
            if embedding:
                content = f"踩坑经验：{lesson}"
                knowledge_item_repo.create_with_embedding(
                    session,
                    content=content,
                    item_type='lesson',
                    embedding=embedding,
                    source_file_type='agents',
                    source_id=mistake.id,
                    session_id=session_id,
                    importance={'low': 0.3, 'medium': 0.5, 'high': 0.7, 'critical': 0.9}.get(severity, 0.5),
                    tags=['mistake', mistake_type, severity]
                )
            
            logger.info(f"[KnowledgeTool] 踩坑记录完成: id={mistake.id}")
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 记录踩坑失败: {e}")
    finally:
        loop.close()


def _process_environment(env_key: str, env_value: str, description: Optional[str], session_id: str):
    """处理环境信息存储"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import knowledge_item_repo, knowledge_file_repo
        
        logger.info(f"[KnowledgeTool] 更新环境信息: {env_key}={env_value}")
        
        with db_manager.get_session() as session:
            # 构建内容
            content = f"{env_key}: {env_value}"
            if description:
                content += f" ({description})"
            
            # 获取向量
            embedding = loop.run_until_complete(_get_embedding(content))
            
            if embedding:
                # 创建 knowledge_item
                knowledge_item_repo.create_with_embedding(
                    session,
                    content=content,
                    item_type='fact',
                    embedding=embedding,
                    source_file_type='tools',
                    session_id=session_id,
                    importance=0.6,
                    tags=['environment', env_key]
                )
            
            # 更新 TOOLS 知识块（可选）
            tools_file = knowledge_file_repo.get_by_type(session, 'tools')
            if tools_file:
                # 追加到 full_content
                if tools_file.full_content:
                    tools_file.full_content += f"\n- {content}"
                else:
                    tools_file.full_content = f"# 环境信息\n\n- {content}"
                tools_file.version += 1
            
            logger.info(f"[KnowledgeTool] 环境信息记录完成: {env_key}")
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 记录环境信息失败: {e}")
    finally:
        loop.close()


# ==================== 工具定义 ====================

@tool(args_schema=RememberUserInfoInput)
def remember_user_info(
    field: str,
    value: str,
    confidence: float = 1.0
) -> str:
    """
    记录用户的个人信息。
    
    当用户透露个人信息时调用此工具。信息会存储到用户画像中，
    并在后续对话中被记住。
    
    **何时使用**：
    - 用户告诉了你他的名字、职业、公司等
    - 用户提到了自己的位置、时区等
    - 用户透露了其他个人信息
    
    **示例**：
    - remember_user_info(field="name", value="张三")
    - remember_user_info(field="timezone", value="Asia/Shanghai")
    - remember_user_info(field="occupation", value="软件工程师", confidence=0.8)
    
    Args:
        field: 字段名
        value: 字段值
        confidence: 置信度（用户明确说出时为1.0，推测时为0.5-0.8）
        
    Returns:
        操作结果
    """
    session_id = get_current_session()
    
    # 提交到后台线程处理
    _executor.submit(
        _process_user_info,
        field, value, confidence, session_id
    )
    
    logger.info(f"[KnowledgeTool] 已提交用户信息记录: {field}={value}")
    return f"已记录用户信息：{field} = {value}"


@tool(args_schema=RememberPreferenceInput)
def remember_preference(
    category: str,
    preference: str,
    strength: str = "moderate"
) -> str:
    """
    记录用户的偏好或习惯。
    
    当用户表达偏好或习惯时调用此工具。这些偏好会影响后续的交互方式。
    
    **何时使用**：
    - 用户表达了喜欢或不喜欢某事物
    - 用户提到了自己的工作习惯
    - 用户说明了沟通风格偏好
    
    **示例**：
    - remember_preference(category="communication", preference="喜欢简洁的回答", strength="strong")
    - remember_preference(category="tech", preference="使用Python开发", strength="moderate")
    - remember_preference(category="workflow", preference="先分析再动手", strength="strong")
    
    Args:
        category: 偏好类别（如 communication, tech, workflow）
        preference: 偏好内容
        strength: 强烈程度（strong/moderate/slight）
        
    Returns:
        操作结果
    """
    session_id = get_current_session()
    
    _executor.submit(
        _process_preference,
        category, preference, strength, session_id
    )
    
    logger.info(f"[KnowledgeTool] 已提交用户偏好记录: {category}/{preference}")
    return f"已记录用户偏好：在{category}方面，{preference}"


@tool(args_schema=RecordMistakeInput)
def record_mistake(
    mistake_type: str,
    context: str,
    lesson: str,
    solution: str = None,
    severity: str = "medium"
) -> str:
    """
    记录踩坑经验。
    
    当 Agent 犯错或发现问题后调用此工具。这些经验会被记住，
    帮助避免类似错误。重复的踩坑会自动转化为行为规则。
    
    **何时使用**：
    - Agent 执行了错误操作
    - 发现了配置问题或陷阱
    - 学到了重要的教训
    
    **示例**：
    - record_mistake(
        mistake_type="command_error",
        context="执行 rm -rf 前没有确认路径",
        lesson="删除命令必须先确认目标路径",
        severity="critical"
      )
    - record_mistake(
        mistake_type="config_error",
        context="数据库连接池配置过小导致超时",
        lesson="连接池大小应该根据并发量设置",
        solution="将连接池从10增加到50",
        severity="high"
      )
    
    Args:
        mistake_type: 错误类型
        context: 错误上下文
        lesson: 学到的教训
        solution: 解决方案（可选）
        severity: 严重程度（low/medium/high/critical）
        
    Returns:
        操作结果
    """
    session_id = get_current_session()
    
    _executor.submit(
        _process_mistake,
        mistake_type, context, lesson, solution, severity, session_id
    )
    
    logger.info(f"[KnowledgeTool] 已提交踩坑记录: {mistake_type}")
    return f"已记录踩坑经验：{lesson}"


@tool(args_schema=UpdateEnvironmentInput)
def update_environment(
    env_key: str,
    env_value: str,
    description: str = None
) -> str:
    """
    更新环境信息。
    
    记录项目或系统相关的环境配置信息。这些信息会被记住，
    方便后续查询和使用。
    
    **何时使用**：
    - 发现了重要的项目配置
    - 确认了服务地址或端口
    - 获得了 API 密钥或凭证信息（不含实际密钥）
    
    **示例**：
    - update_environment(env_key="database_host", env_value="localhost:5433")
    - update_environment(env_key="project_root", env_value="/home/user/project")
    - update_environment(env_key="api_endpoint", env_value="https://api.example.com", description="生产环境API")
    
    Args:
        env_key: 环境信息键
        env_value: 环境信息值
        description: 补充说明（可选）
        
    Returns:
        操作结果
    """
    session_id = get_current_session()
    
    _executor.submit(
        _process_environment,
        env_key, env_value, description, session_id
    )
    
    logger.info(f"[KnowledgeTool] 已提交环境信息更新: {env_key}")
    return f"已更新环境信息：{env_key} = {env_value}"


# ==================== 检索工具 ====================

class MemorySearchInput(BaseModel):
    """记忆检索的输入参数"""
    query: str = Field(
        description="检索查询，描述你想查找的记忆内容"
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="返回数量，默认10条"
    )
    item_type: Optional[str] = Field(
        default=None,
        description="过滤类型（可选）：user_info, preference, fact, lesson, rule, project"
    )
    tags: Optional[str] = Field(
        default=None,
        description="过滤标签（可选），多个标签用逗号分隔"
    )
    min_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="最低相关度分数，默认0.3"
    )


@tool(args_schema=MemorySearchInput)
def memory_search(
    query: str,
    top_k: int = 10,
    item_type: str = None,
    tags: str = None,
    min_score: float = 0.3
) -> str:
    """
    检索历史记忆。
    
    Agent 需要回忆历史信息时调用此工具。使用混合检索（向量+关键词），
    返回最相关的记忆条目。
    
    **何时使用**：
    - 需要回忆用户之前说过的话
    - 需要查找项目配置信息
    - 需要查找之前的踩坑经验
    - 需要查找用户偏好
    
    **示例**：
    - memory_search(query="数据库配置", top_k=5)
    - memory_search(query="用户偏好", item_type="preference")
    - memory_search(query="PostgreSQL", tags="database,config")
    
    Args:
        query: 检索查询
        top_k: 返回数量
        item_type: 过滤类型（可选）
        tags: 过滤标签（可选）
        min_score: 最低相关度分数
        
    Returns:
        检索结果
    """
    logger.info(f"[KnowledgeTool] 记忆检索: query={query[:50]}, top_k={top_k}")
    
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import knowledge_item_repo_enhanced
        
        # 解析标签
        tag_list = None
        if tags:
            tag_list = [t.strip() for t in tags.split(',') if t.strip()]
        
        # 获取查询向量
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            query_embedding = loop.run_until_complete(_get_embedding(query))
        finally:
            loop.close()
        
        if query_embedding is None:
            return "无法获取查询向量，请稍后重试"
        
        with db_manager.get_session() as session:
            # 构建过滤条件
            item_types = [item_type] if item_type else None
            
            # 使用增强版检索
            results = knowledge_item_repo_enhanced.search_with_filters(
                session,
                query_embedding=query_embedding,
                item_types=item_types,
                tags=tag_list,
                top_k=top_k
            )
            
            if not results:
                return f"未找到与 '{query}' 相关的记忆"
            
            # 过滤低分结果
            results = [r for r in results if r.get('similarity', 0) >= min_score]
            
            if not results:
                return f"找到相关记忆，但相关度都低于 {min_score}"
            
            # 批量更新访问记录（LRU刷新）
            result_ids = [r['id'] for r in results]
            knowledge_item_repo_enhanced.batch_update_access(session, result_ids)
            
            # 格式化输出
            lines = [f"## 记忆检索结果 ({len(results)} 条)\n"]
            
            type_labels = {
                'user_info': '用户信息',
                'preference': '偏好',
                'fact': '事实',
                'lesson': '教训',
                'rule': '规则',
                'project': '项目',
                'daily': '日记',
                'decision': '决策'
            }
            
            for i, r in enumerate(results, 1):
                type_label = type_labels.get(r.get('item_type', ''), r.get('item_type', '未知'))
                score = r.get('similarity', 0)
                content = r.get('content', '')
                item_tags = r.get('tags', [])
                
                lines.append(f"{i}. [{type_label}] (相关度: {score:.2f})")
                lines.append(f"   {content}")
                if item_tags:
                    lines.append(f"   标签: {', '.join(item_tags)}")
                lines.append("")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 检索失败: {e}")
        return f"检索失败: {str(e)}"


class GetRulesInput(BaseModel):
    """获取规则的输入参数"""
    rule_type: Optional[str] = Field(
        default=None,
        description="规则类型（可选）：safety, efficiency, style, domain"
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="返回数量，默认10条"
    )


@tool(args_schema=GetRulesInput)
def get_active_rules(
    rule_type: str = None,
    limit: int = 10
) -> str:
    """
    获取当前生效的行为规则。
    
    查看已定义的行为规则，包括从踩坑中提炼的规则和用户要求的规则。
    
    **何时使用**：
    - 需要了解应该遵守的规则
    - 需要检查某类规则是否存在
    - 需要查看规则优先级
    
    Args:
        rule_type: 规则类型（可选）
        limit: 返回数量
        
    Returns:
        规则列表
    """
    logger.info(f"[KnowledgeTool] 获取规则: type={rule_type}, limit={limit}")
    
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import agent_rule_repo
        
        with db_manager.get_session() as session:
            if rule_type:
                rules = agent_rule_repo.get_by_type(session, rule_type, limit)
            else:
                rules = agent_rule_repo.get_active(session, limit)
            
            if not rules:
                return "当前没有生效的行为规则"
            
            lines = [f"## 行为规则 ({len(rules)} 条)\n"]
            
            type_labels = {
                'safety': '安全',
                'efficiency': '效率',
                'style': '风格',
                'domain': '领域'
            }
            
            for i, rule in enumerate(rules, 1):
                type_label = type_labels.get(rule.rule_type, rule.rule_type)
                lines.append(f"{i}. [{type_label}] (优先级: {rule.priority})")
                lines.append(f"   {rule.content}")
                if rule.source_type == 'mistake':
                    lines.append(f"   来源: 踩坑提炼")
                lines.append("")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 获取规则失败: {e}")
        return f"获取规则失败: {str(e)}"


class GetMistakesInput(BaseModel):
    """获取踩坑的输入参数"""
    days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="最近多少天的踩坑，默认30天"
    )
    severity: Optional[str] = Field(
        default=None,
        description="严重程度过滤（可选）：low, medium, high, critical"
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="返回数量，默认10条"
    )


@tool(args_schema=GetMistakesInput)
def get_recent_mistakes(
    days: int = 30,
    severity: str = None,
    limit: int = 10
) -> str:
    """
    获取近期的踩坑记录。
    
    查看最近犯过的错误和学到的教训，帮助避免重复犯错。
    
    **何时使用**：
    - 需要回顾最近的错误
    - 需要了解哪些坑已经踩过
    - 需要检查某类错误是否发生过
    
    Args:
        days: 最近多少天的踩坑
        severity: 严重程度过滤（可选）
        limit: 返回数量
        
    Returns:
        踩坑列表
    """
    logger.info(f"[KnowledgeTool] 获取踩坑: days={days}, severity={severity}")
    
    try:
        from services.db_manager import db_manager
        from services.agent_knowledge_repository import agent_mistake_repo
        
        with db_manager.get_session() as session:
            mistakes = agent_mistake_repo.get_recent(session, days=days, limit=limit)
            
            if severity:
                mistakes = [m for m in mistakes if m.severity == severity]
            
            if not mistakes:
                return f"最近 {days} 天没有踩坑记录"
            
            lines = [f"## 近期踩坑记录 ({len(mistakes)} 条)\n"]
            
            severity_labels = {
                'low': '低',
                'medium': '中',
                'high': '高',
                'critical': '严重'
            }
            
            for i, m in enumerate(mistakes, 1):
                sev_label = severity_labels.get(m.severity, m.severity)
                lines.append(f"{i}. [{sev_label}] {m.mistake_type}")
                lines.append(f"   上下文: {m.context[:100]}...")
                if m.lesson:
                    lines.append(f"   教训: {m.lesson}")
                if m.occurrence_count > 1:
                    lines.append(f"   发生次数: {m.occurrence_count}")
                lines.append("")
            
            return "\n".join(lines)
            
    except Exception as e:
        logger.error(f"[KnowledgeTool] 获取踩坑失败: {e}")
        return f"获取踩坑失败: {str(e)}"


# ==================== 导出 ====================

KNOWLEDGE_TOOLS = [
    # 记忆存储工具
    remember_user_info,
    remember_preference,
    record_mistake,
    update_environment,
    # 检索工具
    memory_search,
    get_active_rules,
    get_recent_mistakes
]

__all__ = [
    # 存储工具
    'remember_user_info',
    'remember_preference',
    'record_mistake',
    'update_environment',
    # 检索工具
    'memory_search',
    'get_active_rules',
    'get_recent_mistakes',
    # 工具列表
    'KNOWLEDGE_TOOLS',
    # 上下文管理
    'set_current_session',
    'get_current_session'
]
