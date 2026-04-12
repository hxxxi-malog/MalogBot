"""
Bootstrap 加载服务

实现第四阶段核心功能：
基于 Token 预算的动态知识加载，支持质量门槛过滤

加载流程：
1. 初始化预算追踪器
2. 固定加载 SOUL（从 knowledge_files 表）
3. 加载 USER（整合 user_profile_fields + knowledge_items）
4. 加载 AGENTS（规则优先 + 近期踩坑）
5. 加载 MEMORY（长期记忆，按重要性排序）
6. 动态检索（基于用户查询）
7. 组装 Prompt
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy.orm import Session as DBSession

from models.agent_knowledge import KnowledgeFile, KnowledgeItem, AgentRule, AgentMistake
from services.bootstrap.token_counter import TokenCounter, token_counter
from services.bootstrap.models import (
    SessionType,
    BootstrapConfig,
    BootstrapResult,
    BootstrapStats
)
from services.bootstrap.prompt_assembler import PromptAssembler, prompt_assembler
from services.agent_knowledge_repository import (
    knowledge_file_repo,
    knowledge_item_repo,
    agent_rule_repo,
    agent_mistake_repo,
    user_profile_repo
)
from services.memory_search_engine import memory_search_engine

logger = logging.getLogger(__name__)


class BootstrapService:
    """Bootstrap 加载服务
    
    负责根据 Token 预算动态加载知识块，组装 System Prompt
    
    使用示例：
        service = BootstrapService()
        
        # 使用默认配置
        result = await service.load(user_query="帮我看看数据库问题", session=db_session)
        
        # 使用自定义配置
        config = BootstrapConfig(knowledge_budget=10000)
        result = await service.load(config=config, user_query="...", session=db_session)
        
        print(result.system_prompt)
        print(f"Used tokens: {result.used_tokens}/{result.budget}")
    """
    
    def __init__(self):
        """初始化 Bootstrap 服务"""
        self.token_counter = token_counter
        self.assembler = prompt_assembler
        logger.info("[BootstrapService] 初始化完成")
    
    async def load(
        self,
        session: DBSession,
        user_query: str = "",
        config: BootstrapConfig = None
    ) -> BootstrapResult:
        """
        执行 Bootstrap 加载
        
        Args:
            session: 数据库会话
            user_query: 用户查询（用于动态检索）
            config: 加载配置（None 则使用默认配置）
        
        Returns:
            BootstrapResult 包含 system_prompt 和统计信息
        """
        cfg = config or BootstrapConfig()
        budget = cfg.get_total_budget()
        stats = BootstrapStats()
        
        logger.info(f"[BootstrapService] 开始加载，预算: {budget} tokens")
        logger.info(f"[BootstrapService] 用户查询: {user_query[:50]}..." if user_query else "[BootstrapService] 无用户查询")
        
        # 初始化内容变量
        soul_content = ""
        user_content = ""
        agents_content = ""
        memory_content = ""
        dynamic_content = ""
        avg_score = 0.0
        
        used_tokens = 0
        
        # ==================== Step 1: 加载 SOUL ====================
        soul_content, soul_tokens = self._load_soul(session, cfg)
        used_tokens += soul_tokens
        stats.soul_tokens = soul_tokens
        logger.info(f"[BootstrapService] SOUL 加载完成: {soul_tokens} tokens")
        
        # ==================== Step 2: 加载 USER ====================
        if cfg.enable_user:
            remaining = budget - used_tokens
            user_budget = min(cfg.user_budget, remaining)
            
            if user_budget > 100:  # 至少 100 tokens 才有意义
                user_content, user_tokens, user_count = self._load_user(
                    session, cfg, user_budget
                )
                used_tokens += user_tokens
                stats.user_tokens = user_tokens
                stats.user_items_count = user_count
                logger.info(f"[BootstrapService] USER 加载完成: {user_tokens} tokens, {user_count} items")
        
        # ==================== Step 3: 加载 AGENTS ====================
        if cfg.enable_agents:
            remaining = budget - used_tokens
            agents_budget = min(cfg.agents_budget, remaining)
            
            if agents_budget > 100:
                agents_content, agents_tokens, rules_count, mistakes_count = self._load_agents(
                    session, cfg, agents_budget
                )
                used_tokens += agents_tokens
                stats.agents_tokens = agents_tokens
                stats.agents_rules_count = rules_count
                stats.agents_mistakes_count = mistakes_count
                logger.info(f"[BootstrapService] AGENTS 加载完成: {agents_tokens} tokens, {rules_count} rules, {mistakes_count} mistakes")
        
        # ==================== Step 4: 加载 MEMORY ====================
        if cfg.enable_memory:
            remaining = budget - used_tokens
            memory_budget = min(cfg.memory_budget, remaining)
            
            if memory_budget > 100:
                memory_content, memory_tokens, memory_count = self._load_memory(
                    session, cfg, memory_budget
                )
                used_tokens += memory_tokens
                stats.memory_tokens = memory_tokens
                stats.memory_items_count = memory_count
                logger.info(f"[BootstrapService] MEMORY 加载完成: {memory_tokens} tokens, {memory_count} items")
        
        # ==================== Step 5: 动态检索 ====================
        if cfg.enable_dynamic and user_query:
            remaining = budget - used_tokens
            dynamic_budget = min(cfg.dynamic_budget, remaining)
            
            if dynamic_budget > 100:
                dynamic_content, dynamic_tokens, dynamic_count, avg_score, filtered = await self._load_dynamic(
                    session, user_query, cfg, dynamic_budget
                )
                used_tokens += dynamic_tokens
                stats.dynamic_tokens = dynamic_tokens
                stats.dynamic_items_count = dynamic_count
                stats.avg_score = avg_score
                stats.filtered_count = filtered
                logger.info(f"[BootstrapService] 动态检索完成: {dynamic_tokens} tokens, {dynamic_count} items, avg_score={avg_score:.2f}")
        
        # ==================== Step 6: 组装 Prompt ====================
        system_prompt = self.assembler.assemble(
            soul_content=soul_content,
            user_content=user_content,
            agents_content=agents_content,
            memory_content=memory_content,
            dynamic_content=dynamic_content,
            avg_score=avg_score
        )
        
        # 最终校验
        final_tokens = self.token_counter.count_tokens(system_prompt)
        
        if final_tokens > budget:
            warning = f"Prompt 超预算: {final_tokens} > {budget}"
            logger.warning(f"[BootstrapService] {warning}")
            stats.add_warning(warning)
        
        logger.info(f"[BootstrapService] 加载完成，总 tokens: {final_tokens}/{budget} ({final_tokens/budget:.1%})")
        logger.info(f"[BootstrapService] 加载条目: {stats.total_items_count}, 被过滤: {stats.filtered_count}")
        
        return BootstrapResult(
            system_prompt=system_prompt,
            used_tokens=final_tokens,
            budget=budget,
            stats=stats,
            soul_content=soul_content,
            user_content=user_content,
            agents_content=agents_content,
            memory_content=memory_content,
            dynamic_content=dynamic_content
        )
    
    def _load_soul(
        self,
        session: DBSession,
        config: BootstrapConfig
    ) -> Tuple[str, int]:
        """
        加载 SOUL 知识块
        
        SOUL 是 Agent 人格定义，必须加载，不可截断
        """
        soul_file = knowledge_file_repo.get_by_type(session, 'soul')
        soul_content = self.assembler.format_soul(soul_file)
        soul_tokens = self.token_counter.count_tokens(soul_content)
        
        # SOUL 超预算时仍需加载，但记录告警
        if soul_tokens > config.soul_budget:
            logger.warning(f"[BootstrapService] SOUL 超预算: {soul_tokens} > {config.soul_budget}")
        
        return soul_content, soul_tokens
    
    def _load_user(
        self,
        session: DBSession,
        config: BootstrapConfig,
        budget: int
    ) -> Tuple[str, int, int]:
        """
        加载 USER 知识块
        
        来源：
        1. user_profile_fields 表（name, agent_role 等）
        2. knowledge_items 中 source_file_type='user' 的条目
        """
        used_tokens = 0
        items_count = 0
        
        # 来源1: user_profile_fields
        profile = user_profile_repo.get_high_confidence(session, min_confidence=0.5)
        profile_content = self.assembler.format_user_profile(profile)
        profile_tokens = self.token_counter.count_tokens(profile_content)
        
        # 预留一些空间给知识条目
        max_profile_tokens = int(budget * 0.3)
        
        if profile_tokens > max_profile_tokens:
            # 截断 profile 内容
            profile_content = profile_content[:max_profile_tokens * 3]  # 粗略估算
            profile_tokens = self.token_counter.count_tokens(profile_content)
        
        used_tokens += profile_tokens
        
        # 来源2: knowledge_items
        remaining = budget - used_tokens
        user_items = knowledge_item_repo.get_by_source_file(session, 'user', limit=100)
        
        # 过滤低重要性
        user_items = [item for item in user_items if item.importance >= config.min_importance]
        
        # 按 Token 预算截断
        user_items_content = ""
        if user_items and remaining > 50:
            user_items_content, items_count = self._load_items_within_budget(
                user_items, remaining
            )
            user_items_tokens = self.token_counter.count_tokens(user_items_content)
            used_tokens += user_items_tokens
        
        # 组装
        user_content = self.assembler.format_user(profile, user_items[:items_count] if user_items else [])
        total_tokens = self.token_counter.count_tokens(user_content)
        
        return user_content, total_tokens, items_count
    
    def _load_agents(
        self,
        session: DBSession,
        config: BootstrapConfig,
        budget: int
    ) -> Tuple[str, int, int, int]:
        """
        加载 AGENTS 知识块
        
        来源：
        1. agent_rules 表中 is_active=True 的规则
        2. agent_mistakes 表中近 30 天的踩坑记录
        """
        # 规则优先
        rules = agent_rule_repo.get_active(session, limit=50)
        
        # 近期踩坑
        mistakes = self._get_recent_mistakes(session, days=30, limit=20)
        
        used_tokens = 0
        rules_count = 0
        mistakes_count = 0
        
        # 预算分配：规则 60%，踩坑 40%
        rules_budget = int(budget * 0.6)
        mistakes_budget = budget - rules_budget
        
        # 加载规则
        rules_content = ""
        if rules:
            rules_content, rules_count = self._load_rules_within_budget(rules, rules_budget)
            used_tokens += self.token_counter.count_tokens(rules_content)
        
        # 加载踩坑
        mistakes_content = ""
        if mistakes:
            mistakes_content, mistakes_count = self._load_mistakes_within_budget(mistakes, mistakes_budget)
            used_tokens += self.token_counter.count_tokens(mistakes_content)
        
        # 组装
        agents_content = self.assembler.format_agents(
            rules[:rules_count] if rules else [],
            mistakes[:mistakes_count] if mistakes else []
        )
        total_tokens = self.token_counter.count_tokens(agents_content)
        
        return agents_content, total_tokens, rules_count, mistakes_count
    
    def _load_memory(
        self,
        session: DBSession,
        config: BootstrapConfig,
        budget: int
    ) -> Tuple[str, int, int]:
        """
        加载 MEMORY 知识块（长期记忆）
        
        从 knowledge_items 中加载 source_file_type='memory' 的条目
        """
        memory_items = knowledge_item_repo.get_by_source_file(session, 'memory', limit=200)
        
        # 过滤低重要性和过期记忆
        memory_items = [
            item for item in memory_items 
            if item.importance >= config.min_importance and not item.is_expired
        ]
        
        if not memory_items:
            return "", 0, 0
        
        # 按 Token 预算加载
        memory_content, count = self._load_items_within_budget(memory_items, budget)
        tokens = self.token_counter.count_tokens(memory_content)
        
        return memory_content, tokens, count
    
    async def _load_dynamic(
        self,
        session: DBSession,
        user_query: str,
        config: BootstrapConfig,
        budget: int
    ) -> Tuple[str, int, int, float, int]:
        """
        执行动态检索
        
        基于用户查询检索相关记忆
        """
        # 计算召回量
        recall_k = config.calculate_recall_k(budget)
        
        logger.info(f"[BootstrapService] 动态检索召回量: {recall_k}")
        
        try:
            # 调用检索引擎
            results = await memory_search_engine.search(
                query=user_query,
                session=session,
                top_k=recall_k
            )
        except Exception as e:
            logger.error(f"[BootstrapService] 动态检索失败: {e}")
            return "", 0, 0, 0.0, 0
        
        if not results:
            return "", 0, 0, 0.0, 0
        
        # 质量过滤
        filtered_count = 0
        filtered_results = []
        for r in results:
            score = r.final_score if hasattr(r, 'final_score') else r.hybrid_score
            if score >= config.min_hybrid_score:
                filtered_results.append(r)
            else:
                filtered_count += 1
        
        if not filtered_results:
            return "", 0, 0, 0.0, filtered_count
        
        # 转换为字典列表
        results_dict = [
            {
                'content': r.content,
                'final_score': r.final_score if hasattr(r, 'final_score') else r.hybrid_score
            }
            for r in filtered_results
        ]
        
        # 按 Token 预算截断
        dynamic_content, count = self._load_dynamic_within_budget(results_dict, budget)
        tokens = self.token_counter.count_tokens(dynamic_content)
        
        # 计算平均分
        if count > 0:
            avg_score = sum(r['final_score'] for r in results_dict[:count]) / count
        else:
            avg_score = 0.0
        
        return dynamic_content, tokens, count, avg_score, filtered_count
    
    def _get_recent_mistakes(
        self,
        session: DBSession,
        days: int = 30,
        limit: int = 20
    ) -> List[AgentMistake]:
        """
        获取近期的踩坑记录
        
        Args:
            session: 数据库会话
            days: 最近多少天
            limit: 返回数量限制
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        try:
            return session.query(AgentMistake).filter(
                AgentMistake.created_at >= cutoff
            ).order_by(
                AgentMistake.severity.desc(),
                AgentMistake.created_at.desc()
            ).limit(limit).all()
        except Exception as e:
            logger.error(f"[BootstrapService] 获取踩坑记录失败: {e}")
            return []
    
    def _load_items_within_budget(
        self,
        items: List[KnowledgeItem],
        budget: int
    ) -> Tuple[str, int]:
        """
        在预算内加载知识条目
        
        Returns:
            (内容字符串, 加载条目数)
        """
        lines = []
        used_tokens = 0
        count = 0
        
        for item in items:
            # 格式化单条
            type_label = {
                'user_info': '用户信息',
                'preference': '偏好',
                'fact': '事实',
                'lesson': '教训',
                'rule': '规则',
                'project': '项目'
            }.get(item.item_type, item.item_type)
            
            line = f"- [{type_label}] {item.content}"
            line_tokens = self.token_counter.count_tokens(line)
            
            if used_tokens + line_tokens > budget:
                break
            
            lines.append(line)
            used_tokens += line_tokens
            count += 1
        
        return '\n'.join(lines), count
    
    def _load_rules_within_budget(
        self,
        rules: List[AgentRule],
        budget: int
    ) -> Tuple[str, int]:
        """
        在预算内加载规则
        """
        lines = []
        used_tokens = 0
        count = 0
        
        for rule in rules:
            # 优先级标签
            if rule.priority >= 80:
                priority_label = "高"
            elif rule.priority >= 50:
                priority_label = "中"
            else:
                priority_label = "低"
            
            line = f"- [{priority_label}优先级] {rule.content}"
            line_tokens = self.token_counter.count_tokens(line)
            
            if used_tokens + line_tokens > budget:
                break
            
            lines.append(line)
            used_tokens += line_tokens
            count += 1
        
        return '\n'.join(lines), count
    
    def _load_mistakes_within_budget(
        self,
        mistakes: List[AgentMistake],
        budget: int
    ) -> Tuple[str, int]:
        """
        在预算内加载踩坑记录
        """
        lines = []
        used_tokens = 0
        count = 0
        
        severity_labels = {
            'critical': '严重',
            'high': '高',
            'medium': '中',
            'low': '低'
        }
        
        for m in mistakes:
            severity_label = severity_labels.get(m.severity, m.severity)
            lesson = m.lesson or (m.context[:100] if len(m.context) > 100 else m.context)
            
            line = f"- [{severity_label}] {lesson}"
            line_tokens = self.token_counter.count_tokens(line)
            
            if used_tokens + line_tokens > budget:
                break
            
            lines.append(line)
            used_tokens += line_tokens
            count += 1
        
        return '\n'.join(lines), count
    
    def _load_dynamic_within_budget(
        self,
        results: List[Dict[str, Any]],
        budget: int
    ) -> Tuple[str, int]:
        """
        在预算内加载动态检索结果
        """
        lines = []
        used_tokens = 0
        count = 0
        
        for r in results:
            content = r.get('content', '')
            score = r.get('final_score', 0)
            
            line = f"- {content} (相关度: {score:.2f})"
            line_tokens = self.token_counter.count_tokens(line)
            
            if used_tokens + line_tokens > budget:
                break
            
            lines.append(line)
            used_tokens += line_tokens
            count += 1
        
        return '\n'.join(lines), count


# 创建全局实例
bootstrap_service = BootstrapService()


__all__ = ['BootstrapService', 'bootstrap_service']
