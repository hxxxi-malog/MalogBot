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

    # ==================== 阿里云百炼配置 ====================
    # 阿里云百炼 API Key
    DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY')

    # 向量模型配置
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-v4')
    EMBEDDING_DIMENSION = int(os.getenv('EMBEDDING_DIMENSION', '1024'))

    # 重排序模型配置
    RERANK_MODEL = os.getenv('RERANK_MODEL', 'qwen3-vl-rerank')

    # RAG 配置
    RAG_TOP_N = int(os.getenv('RAG_TOP_N', '10'))  # 初始检索数量
    RAG_TOP_K = int(os.getenv('RAG_TOP_K', '3'))   # 重排序后返回的最相关数量
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '500'))  # 文本分块大小
    CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', '50'))  # 文本分块重叠大小

    # 文件上传配置
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', './uploads')
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '10485760'))  # 10MB

    # ==================== 上下文压缩配置 ====================
    # 微观压缩：保留最近的 N 个 tool_result
    KEEP_RECENT_TOOL_RESULTS = int(os.getenv('KEEP_RECENT_TOOL_RESULTS', '5'))
    
    # 自动压缩：Token 阈值（字符数近似）
    AUTO_COMPACT_THRESHOLD = int(os.getenv('AUTO_COMPACT_THRESHOLD', '50000'))
    
    # 压缩后保留的最近消息数
    KEEP_RECENT_MESSAGES = int(os.getenv('KEEP_RECENT_MESSAGES', '10'))
