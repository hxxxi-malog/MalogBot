"""
Prompt 组装器

负责将各知识块格式化并组装成完整的 System Prompt
"""
import logging
from typing import Dict, Any, List, Optional

from models.agent_knowledge import KnowledgeItem, AgentRule, AgentMistake

logger = logging.getLogger(__name__)


# ==================== 模板定义 ====================

SYSTEM_PROMPT_TEMPLATE = '''# 我是谁

{soul_content}

# 用户是谁

{user_content}

# 行为规范

{agents_content}

# 长期记忆

{memory_content}

{dynamic_section}

---

## 记忆管理指南

- 当用户透露个人信息或表达偏好时，主动记录
- 当发现错误或问题时，及时总结教训
- 一条记忆只记录一个事实，保持简洁精准
'''

DYNAMIC_SECTION_TEMPLATE = '''# 相关记忆（基于查询动态检索）

{dynamic_content}

（以上记忆平均相关度：{avg_score:.2f}）
'''

EMPTY_DYNAMIC_SECTION = ""

USER_PROFILE_TEMPLATE = '''## 基本信息

{profile_fields}
'''

USER_MEMORY_TEMPLATE = '''
## 用户相关记忆

{memory_items}
'''

AGENTS_TEMPLATE = '''## 行为规则

{rules}

## 近期踩坑

{mistakes}
'''

EMPTY_RULES = "（暂无行为规则）"
EMPTY_MISTAKES = "（暂无踩坑记录）"
EMPTY_MEMORY = "（暂无长期记忆）"

# 格式化模板
MEMORY_ITEM_FORMAT = "- [{type}] {content}"
RULE_FORMAT = "- [{priority}] {content}"
MISTAKE_FORMAT = "- [{severity}] {lesson}"
DYNAMIC_ITEM_FORMAT = "- {content} (相关度: {score:.2f})"

# 类型标签映射
ITEM_TYPE_LABELS = {
    'user_info': '用户信息',
    'preference': '偏好',
    'fact': '事实',
    'lesson': '教训',
    'rule': '规则',
    'project': '项目',
    'decision': '决策',
    'summary': '摘要'
}

# 用户画像字段标签映射
USER_FIELD_LABELS = {
    'name': '称呼',
    'agent_role': '期望角色',
    'relationship': '关系定位',
    'timezone': '时区',
    'occupation': '职业',
    'interests': '兴趣爱好'
}

# 规则优先级标签
PRIORITY_LABELS = {
    'high': '高',
    'medium': '中',
    'low': '低'
}

# 踩坑严重程度标签
SEVERITY_LABELS = {
    'critical': '严重',
    'high': '高',
    'medium': '中',
    'low': '低'
}


class PromptAssembler:
    """Prompt 组装器
    
    负责将各知识块格式化并组装成完整的 System Prompt
    
    使用示例：
        assembler = PromptAssembler()
        
        # 格式化各部分
        soul_content = assembler.format_soul(soul_file)
        user_content = assembler.format_user(profile, user_items)
        
        # 组装最终 Prompt
        system_prompt = assembler.assemble(
            soul_content=soul_content,
            user_content=user_content,
            agents_content=agents_content,
            memory_content=memory_content,
            dynamic_content=dynamic_content,
            avg_score=0.75
        )
    """
    
    def __init__(self):
        """初始化组装器"""
        self.template = SYSTEM_PROMPT_TEMPLATE
        self.dynamic_template = DYNAMIC_SECTION_TEMPLATE
        logger.info("[PromptAssembler] 初始化完成")
    
    def assemble(
        self,
        soul_content: str,
        user_content: str,
        agents_content: str,
        memory_content: str,
        dynamic_content: str = "",
        avg_score: float = 0.0
    ) -> str:
        """
        组装完整的 System Prompt
        
        Args:
            soul_content: SOUL 知识块内容
            user_content: USER 知识块内容
            agents_content: AGENTS 知识块内容
            memory_content: MEMORY 知识块内容
            dynamic_content: 动态检索内容
            avg_score: 动态检索平均分数
        
        Returns:
            完整的 System Prompt
        """
        # 处理动态检索部分
        if dynamic_content:
            dynamic_section = self.dynamic_template.format(
                dynamic_content=dynamic_content,
                avg_score=avg_score
            )
        else:
            dynamic_section = EMPTY_DYNAMIC_SECTION
        
        # 组装完整 Prompt
        system_prompt = self.template.format(
            soul_content=soul_content or "（待初始化）",
            user_content=user_content or "（待积累）",
            agents_content=agents_content or "（暂无规则）",
            memory_content=memory_content or EMPTY_MEMORY,
            dynamic_section=dynamic_section
        )
        
        logger.debug(f"[PromptAssembler] 组装完成，Prompt 长度: {len(system_prompt)}")
        return system_prompt
    
    def format_soul(self, soul_file) -> str:
        """
        格式化 SOUL 知识块
        
        Args:
            soul_file: KnowledgeFile 对象
        
        Returns:
            格式化后的内容
        """
        if soul_file is None:
            return "（待初始化 Agent 人格）"
        
        content = soul_file.summary_content or soul_file.full_content
        if not content:
            return "（待初始化 Agent 人格）"
        
        return content
    
    def format_user(
        self,
        profile: Dict[str, Any],
        user_items: List[KnowledgeItem] = None
    ) -> str:
        """
        格式化 USER 知识块
        
        Args:
            profile: 用户画像字典
            user_items: 用户相关的知识条目列表
        
        Returns:
            格式化后的内容
        """
        parts = []
        
        # 基本信息
        if profile:
            profile_fields = self.format_user_profile(profile)
            parts.append(USER_PROFILE_TEMPLATE.format(profile_fields=profile_fields))
        
        # 用户相关记忆
        if user_items:
            memory_items = self.format_knowledge_items(user_items)
            parts.append(USER_MEMORY_TEMPLATE.format(memory_items=memory_items))
        
        if not parts:
            return "（待积累用户信息）"
        
        return '\n'.join(parts)
    
    def format_user_profile(self, profile: Dict[str, Any]) -> str:
        """
        格式化用户画像字段
        
        Args:
            profile: 用户画像字典 {field_name: field_value}
        
        Returns:
            格式化后的字符串
        """
        if not profile:
            return "（暂无基本信息）"
        
        lines = []
        for key, value in profile.items():
            if value is None:
                continue
            
            label = USER_FIELD_LABELS.get(key, key)
            
            # 处理列表类型
            if isinstance(value, list):
                value = ', '.join(str(v) for v in value)
            else:
                value = str(value)
            
            lines.append(f"- {label}：{value}")
        
        return '\n'.join(lines) if lines else "（暂无基本信息）"
    
    def format_agents(
        self,
        rules: List[AgentRule] = None,
        mistakes: List[AgentMistake] = None
    ) -> str:
        """
        格式化 AGENTS 知识块
        
        Args:
            rules: 行为规则列表
            mistakes: 踩坑记录列表
        
        Returns:
            格式化后的内容
        """
        rules_content = self.format_rules(rules) if rules else EMPTY_RULES
        mistakes_content = self.format_mistakes(mistakes) if mistakes else EMPTY_MISTAKES
        
        return AGENTS_TEMPLATE.format(
            rules=rules_content,
            mistakes=mistakes_content
        )
    
    def format_rules(self, rules: List[AgentRule]) -> str:
        """
        格式化行为规则
        
        Args:
            rules: AgentRule 列表
        
        Returns:
            格式化后的字符串
        """
        if not rules:
            return EMPTY_RULES
        
        lines = []
        for rule in rules:
            # 优先级标签
            if rule.priority >= 80:
                priority_label = "高"
            elif rule.priority >= 50:
                priority_label = "中"
            else:
                priority_label = "低"
            
            lines.append(RULE_FORMAT.format(
                priority=priority_label,
                content=rule.content
            ))
        
        return '\n'.join(lines)
    
    def format_mistakes(self, mistakes: List[AgentMistake]) -> str:
        """
        格式化踩坑记录
        
        Args:
            mistakes: AgentMistake 列表
        
        Returns:
            格式化后的字符串
        """
        if not mistakes:
            return EMPTY_MISTAKES
        
        lines = []
        for m in mistakes:
            severity_label = SEVERITY_LABELS.get(m.severity, m.severity)
            lesson = m.lesson or (m.context[:100] + '...' if len(m.context) > 100 else m.context)
            
            lines.append(MISTAKE_FORMAT.format(
                severity=severity_label,
                lesson=lesson
            ))
        
        return '\n'.join(lines)
    
    def format_knowledge_items(self, items: List[KnowledgeItem]) -> str:
        """
        格式化知识条目列表
        
        Args:
            items: KnowledgeItem 列表
        
        Returns:
            格式化后的字符串
        """
        if not items:
            return EMPTY_MEMORY
        
        lines = []
        for item in items:
            type_label = ITEM_TYPE_LABELS.get(item.item_type, item.item_type)
            lines.append(MEMORY_ITEM_FORMAT.format(
                type=type_label,
                content=item.content
            ))
        
        return '\n'.join(lines)
    
    def format_memory(self, items: List[KnowledgeItem]) -> str:
        """
        格式化长期记忆（MEMORY 知识块）
        
        Args:
            items: KnowledgeItem 列表
        
        Returns:
            格式化后的内容
        """
        return self.format_knowledge_items(items)
    
    def format_dynamic_results(
        self,
        results: List[Dict[str, Any]]
    ) -> str:
        """
        格式化动态检索结果
        
        Args:
            results: 检索结果列表，每项包含 content 和 score
        
        Returns:
            格式化后的字符串
        """
        if not results:
            return ""
        
        lines = []
        for r in results:
            content = r.get('content', '')
            score = r.get('final_score', r.get('hybrid_score', 0))
            
            lines.append(DYNAMIC_ITEM_FORMAT.format(
                content=content,
                score=score
            ))
        
        return '\n'.join(lines)


# 创建全局实例
prompt_assembler = PromptAssembler()


__all__ = ['PromptAssembler', 'prompt_assembler']
