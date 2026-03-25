"""
配置管理模块

管理Flask、Database、LLM、Tools等所有配置项
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Config:
    """应用配置类"""

    # Flask配置
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    # 数据库配置（Docker PostgreSQL）
    # 注意：使用5433端口避免与本地PostgreSQL冲突
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'postgresql://malog:2153315236@127.0.0.1:5433/malogbot'
    )

    # LLM配置
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
    MODEL_NAME = os.getenv('MODEL_NAME', 'deepseek-chat')  # 使用deepseek-chat支持工具调用

    # 工具配置
    BASH_TIMEOUT = int(os.getenv('BASH_TIMEOUT', '30'))  # 命令超时时间（秒）
    
    # Agent 配置
    AGENT_RECURSION_LIMIT = int(os.getenv('AGENT_RECURSION_LIMIT', '25'))  # Agent 递归限制

    # LangSmith 可视化追踪配置
    LANGCHAIN_TRACING_V2 = os.getenv('LANGCHAIN_TRACING_V2', 'false').lower() == 'true'
    LANGCHAIN_API_KEY = os.getenv('LANGCHAIN_API_KEY')
    LANGCHAIN_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'MalogBot')

    # 危险命令配置
    DANGEROUS_COMMANDS = [
        'sudo',
        'rm',
        'rmdir',
        'chmod',
        'chown',
        'dd',
        'mkfs',
        'fdisk',
        'shutdown',
        'reboot',
        'init 0',
        'init 6',
        '>',
        '>>',
        '|',  # 重定向和管道需要谨慎
    ]

    # 允许的危险命令（白名单）
    ALLOWED_DANGEROUS_PATTERNS = [
        'rm *.pyc',  # 允许删除pyc文件
        'rm -rf node_modules',  # 允许删除node_modules
        'rm -rf .venv',  # 允许删除虚拟环境
        'rm -rf venv',
    ]

    # Web 搜索配置（百度云 MCP）
    # 百度云 Web Search MCP 服务
    BAIDU_MCP_API_KEY = os.getenv('BAIDU_MCP_API_KEY')  # 百度云 API Key
    BAIDU_MCP_URL = os.getenv('BAIDU_MCP_URL', 'https://qianfan.baidubce.com/v2/tools/web-search/mcp')
    WEB_SEARCH_ENABLED = os.getenv('WEB_SEARCH_ENABLED', 'false').lower() == 'true'  # 默认关闭

    # MCP 配置
    MCP_ENABLED = os.getenv('MCP_ENABLED', 'true').lower() == 'true'  # 是否启用 MCP，默认开启
