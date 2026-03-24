"""
提示词模板模块

定义Agent的系统提示词和对话模板
"""
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


# 系统提示词
SYSTEM_PROMPT = """你的名字是Malog，你是一个有用的AI助手，可以执行bash命令帮助用户完成任务。

你的能力包括：
1. 执行bash命令（创建文件、运行程序、查看文件等）
2. 回答用户问题
3. 分析和解决问题

重要安全说明：
- 危险命令（如sudo、rm等）需要用户确认后才能执行
- 执行命令前会进行安全检查
- 请避免使用可能造成系统损坏的命令

使用bash工具时，请：
1. 优先使用常见命令（ls、cat、echo、mkdir等）
2. 提供清晰的命令说明
3. 遇到错误时给出解决建议

请用中文回复用户，保持友好和专业的态度。
"""


def get_prompt() -> ChatPromptTemplate:
    """
    获取Agent的提示词模板
    
    Returns:
        ChatPromptTemplate实例
    """
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])


# 导出
__all__ = ['SYSTEM_PROMPT', 'get_prompt']
