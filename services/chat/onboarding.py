"""
首次对话引导服务（Onboarding Service）

实现首次对话时的用户引导机制：
1. 检测是否需要引导（SOUL/USER为空）
2. 生成引导问候语
3. 解析用户回复提取结构化信息
4. 填充 SOUL 和 USER 知识块

使用方式：
    from services.onboarding_service import onboarding_service
    
    # 检查是否需要引导
    if onboarding_service.need_onboarding(session):
        # 获取引导问候语
        greeting = onboarding_service.get_greeting()
        # 解析用户回复并完成引导
        result = onboarding_service.complete_onboarding(session, user_reply)
"""
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from models.agent_knowledge import KnowledgeFile
from services.db_manager import db_manager
from services.agent_knowledge_repository import (
    knowledge_file_repo,
    user_profile_repo
)

logger = logging.getLogger(__name__)


# 引导问候语模板
ONBOARDING_GREETING = """你好啊新朋友！很高兴认识你！

在开始我们的对话之前，我想先了解一下：
1. 我该怎么称呼你？
2. 你希望我扮演什么角色呢？
   （比如：编程助手、学习伙伴、生活顾问、创意搭档等）

你可以一起告诉我，比如："我是小明，希望你做我的编程助手"""


# 用户回复解析 Prompt
ONBOARDING_EXTRACTION_PROMPT = """你是一个信息提取助手。请从用户的回复中提取以下信息：

用户回复：
{user_reply}

请提取：
1. user_name: 用户希望被称呼的名字（必填）
2. agent_role: 用户希望 Agent 扮演的角色（必填）
3. relationship: 用户与 Agent 的关系定位（可选，如"师徒"、"伙伴"、"助手与用户"）
4. additional_notes: 其他值得记录的信息（可选）

输出格式（JSON）：
{{
    "user_name": "提取的名字",
    "agent_role": "提取的角色",
    "relationship": "关系定位",
    "additional_notes": "其他信息",
    "is_valid": true或false
}}

重要规则：
1. user_name 和 agent_role 是必填字段，必须能从用户回复中明确提取或合理推断
2. 如果用户回复中没有提供名字或角色信息（比如只说"你好"、"嘿嘿"等），设置 is_valid 为 false
3. 如果能提取到有效信息，设置 is_valid 为 true
4. 当 is_valid 为 false 时，user_name 和 agent_role 设为 null
5. 只输出 JSON，不要有其他内容"""


class OnboardingService:
    """首次对话引导服务"""
    
    def __init__(self):
        self.greeting = ONBOARDING_GREETING
        self.extraction_prompt = ONBOARDING_EXTRACTION_PROMPT
    
    def need_onboarding(self, session: DBSession) -> bool:
        """检查是否需要进行首次对话引导
        
        检查条件：
        1. SOUL 知识块为空或仅包含占位内容
        2. USER 知识块缺少用户称呼
        
        Returns:
            True 表示需要引导
        """
        # 检查 SOUL 知识块
        soul = knowledge_file_repo.get_by_type(session, 'soul')
        soul_empty = (
            soul is None or 
            soul.full_content is None or 
            soul.full_content.strip() == '' or
            '待填充' in (soul.full_content or '')
        )
        
        # 检查用户称呼
        user_name = user_profile_repo.get_field(session, 'name')
        user_name_missing = user_name is None or user_name.field_value is None
        
        need = soul_empty or user_name_missing
        
        if need:
            logger.info(f"需要首次对话引导: soul_empty={soul_empty}, user_name_missing={user_name_missing}")
        
        return need
    
    def get_greeting(self) -> str:
        """获取引导问候语
        
        Returns:
            引导问候语文本
        """
        return self.greeting
    
    def extract_info_with_llm(self, user_reply: str, llm_client) -> Dict:
        """使用 LLM 从用户回复中提取结构化信息
        
        Args:
            user_reply: 用户的回复文本
            llm_client: LLM 客户端（支持 LangChain LLM 或有 chat 方法的客户端）
        
        Returns:
            提取的结构化信息字典，包含 is_valid 字段表示是否提取成功
        """
        logger.info(f"使用 LLM 提取引导信息: {user_reply[:50]}...")
        
        prompt = self.extraction_prompt.format(user_reply=user_reply)
        
        try:
            # 兼容 LangChain LLM 和自定义客户端
            if hasattr(llm_client, 'invoke'):
                # LangChain LLM
                from langchain_core.messages import HumanMessage
                response = llm_client.invoke([HumanMessage(content=prompt)])
                content = response.content
            elif hasattr(llm_client, 'chat'):
                # 自定义客户端
                response = llm_client.chat([
                    {"role": "user", "content": prompt}
                ])
                content = response.choices[0].message.content
            else:
                logger.warning(f"LLM 客户端类型不支持: {type(llm_client)}")
                return {"is_valid": False, "error": "LLM 客户端不支持"}
            
            # 提取 JSON 部分
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
                logger.info(f"LLM 提取结果: {result}")
                
                # 确保有 is_valid 字段
                if 'is_valid' not in result:
                    # 如果 LLM 没有返回 is_valid，根据必填字段判断
                    result['is_valid'] = bool(result.get('user_name') and result.get('agent_role'))
                
                return result
            else:
                logger.warning(f"LLM 响应未找到 JSON: {content}")
                return {"is_valid": False, "error": "无法解析 LLM 响应"}
                
        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            return {"is_valid": False, "error": str(e)}
    
    def generate_soul_content(self, user_name: str, agent_role: str, 
                              relationship: str = None,
                              additional_notes: str = None) -> str:
        """生成 SOUL 知识块内容
        
        Args:
            user_name: 用户称呼
            agent_role: Agent 角色
            relationship: 关系定位
            additional_notes: 附加说明
        
        Returns:
            SOUL 内容文本
        """
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        content = f"""# 我的身份

我是{agent_role}，我的用户是{user_name}。

## 核心定位

{relationship or '我是用户的智能助手，致力于提供专业、友好的帮助。'}

## 交互风格

- 友好、耐心、专业
- 记住用户的偏好，提供个性化服务
- 根据用户需求调整回答详细程度

## 工作原则

- 以用户需求为导向
- 提供准确、有帮助的信息
- 主动学习，不断改进

## 初始化信息

- 创建时间：{current_date}
- 用户称呼：{user_name}
- 角色定位：{agent_role}
"""
        
        if additional_notes:
            content += f"\n## 附加说明\n\n{additional_notes}\n"
        
        return content
    
    def generate_user_content(self, user_name: str, agent_role: str,
                              additional_notes: str = None) -> str:
        """生成 USER 知识块内容
        
        Args:
            user_name: 用户称呼
            agent_role: Agent 角色
            additional_notes: 附加说明
        
        Returns:
            USER 内容文本
        """
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        content = f"""# 用户画像

## 基本信息

- 称呼：{user_name}
- 首次对话时间：{current_date}
- 期望 Agent 角色：{agent_role}

## 交互偏好

（待积累）

## 技术背景

（待积累）

## 兴趣爱好

（待积累）
"""
        
        if additional_notes:
            content += f"\n## 附加信息\n\n{additional_notes}\n"
        
        return content
    
    def complete_onboarding(self, session: DBSession, 
                            user_name: str,
                            agent_role: str,
                            relationship: str = None,
                            additional_notes: str = None) -> Dict:
        """完成首次对话引导，填充知识块
        
        Args:
            session: 数据库会话
            user_name: 用户称呼
            agent_role: Agent 角色
            relationship: 关系定位
            additional_notes: 附加说明
        
        Returns:
            操作结果字典
        """
        logger.info(f"完成首次对话引导: user_name={user_name}, agent_role={agent_role}")
        
        try:
            # 1. 更新 SOUL 知识块
            soul_content = self.generate_soul_content(
                user_name, agent_role, relationship, additional_notes
            )
            soul = knowledge_file_repo.get_by_type(session, 'soul')
            if soul:
                soul.full_content = soul_content
                soul.summary_content = f"# SOUL\n\n我是{agent_role}，用户是{user_name}。"
                soul.version += 1
                logger.info("SOUL 知识块已更新")
            else:
                # 创建 SOUL 知识块
                soul = knowledge_file_repo.create(
                    session,
                    kb_type='soul',
                    summary_content=f"# SOUL\n\n我是{agent_role}，用户是{user_name}。",
                    full_content=soul_content,
                    version=1
                )
                logger.info("SOUL 知识块已创建")
            
            # 2. 更新 USER 知识块
            user_content = self.generate_user_content(
                user_name, agent_role, additional_notes
            )
            user_kb = knowledge_file_repo.get_by_type(session, 'user')
            if user_kb:
                user_kb.full_content = user_content
                user_kb.summary_content = f"# USER\n\n用户：{user_name}"
                user_kb.version += 1
                logger.info("USER 知识块已更新")
            else:
                user_kb = knowledge_file_repo.create(
                    session,
                    kb_type='user',
                    summary_content=f"# USER\n\n用户：{user_name}",
                    full_content=user_content,
                    version=1
                )
                logger.info("USER 知识块已创建")
            
            # 3. 更新用户画像字段
            user_profile_repo.set_field(
                session, 'name', user_name,
                confidence=1.0, source='首次对话引导'
            )
            user_profile_repo.set_field(
                session, 'agent_role', agent_role,
                confidence=1.0, source='首次对话引导'
            )
            if relationship:
                user_profile_repo.set_field(
                    session, 'relationship', relationship,
                    confidence=0.9, source='首次对话引导'
                )
            
            session.flush()
            
            return {
                'success': True,
                'user_name': user_name,
                'agent_role': agent_role,
                'relationship': relationship,
                'message': f"好的{user_name}！我会作为你的{agent_role}，尽我所能帮助你。有什么想聊的吗？"
            }
            
        except Exception as e:
            logger.error(f"完成首次对话引导失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def complete_onboarding_from_reply(self, session: DBSession, 
                                       user_reply: str,
                                       llm_client) -> Dict:
        """从用户回复完成引导（一体化方法）
        
        Args:
            session: 数据库会话
            user_reply: 用户的回复文本
            llm_client: LLM 客户端（必需，用于提取信息）
        
        Returns:
            操作结果字典，如果提取无效则返回 need_retry=True
        """
        # 使用 LLM 提取结构化信息
        info = self.extract_info_with_llm(user_reply, llm_client)
        
        # 检查提取结果是否有效
        if not info.get('is_valid', False):
            logger.warning(f"引导信息提取无效: {info}")
            return {
                'success': False,
                'need_retry': True,
                'error': info.get('error', '无法从回复中提取有效信息'),
                'message': '抱歉，我没有理解您的意思。请告诉我：\n1. 我该怎么称呼您？\n2. 您希望我扮演什么角色？（比如：编程助手、学习伙伴等）'
            }
        
        # 完成引导
        return self.complete_onboarding(
            session,
            user_name=info.get('user_name'),
            agent_role=info.get('agent_role'),
            relationship=info.get('relationship'),
            additional_notes=info.get('additional_notes')
        )
    
    def get_confirmation_message(self, user_name: str, agent_role: str) -> str:
        """获取引导完成的确认消息
        
        Args:
            user_name: 用户称呼
            agent_role: Agent 角色
        
        Returns:
            确认消息文本
        """
        return f"好的{user_name}！我会作为你的{agent_role}，尽我所能帮助你。有什么想聊的吗？"


# 创建全局实例
onboarding_service = OnboardingService()


# 导出
__all__ = [
    'OnboardingService',
    'onboarding_service',
    'ONBOARDING_GREETING'
]
