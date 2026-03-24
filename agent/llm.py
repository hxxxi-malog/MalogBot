"""
LLM客户端模块

封装LangChain的ChatOpenAI，连接DeepSeek API
支持deepseek-reasoner模型的思考过程输出
"""
from langchain_openai import ChatOpenAI
from config import Config


def get_llm(streaming: bool = False) -> ChatOpenAI:
    """
    获取LLM客户端实例
    
    Args:
        streaming: 是否启用流式输出
    
    Returns:
        ChatOpenAI实例，已配置DeepSeek API
    """
    return ChatOpenAI(
        model=Config.MODEL_NAME,
        openai_api_base=Config.DEEPSEEK_BASE_URL,
        openai_api_key=Config.DEEPSEEK_API_KEY,
        temperature=0.7,
        streaming=streaming
        # 注意: deepseek-reasoner不支持temperature等参数
        # 如果使用deepseek-reasoner,这些参数会被忽略
    )


# 导出
__all__ = ['get_llm']
