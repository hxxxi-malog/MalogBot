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
    
    # Agent 配置 - 上下文窗口限制
    # 取消最大步数限制，改为最大上下文窗口限制
    MAX_CONTEXT_TOKENS = int(os.getenv('MAX_CONTEXT_TOKENS', '128000'))  # 模型最大上下文窗口
    CONTEXT_WARNING_THRESHOLD = float(os.getenv('CONTEXT_WARNING_THRESHOLD', '0.9'))  # 90%时警告
    EMERGENCY_COMPACT_KEEP_MESSAGES = int(os.getenv('EMERGENCY_COMPACT_KEEP_MESSAGES', '3'))  # 紧急压缩保留消息数
    
    # 子Agent模式配置
    # default: 同进程，共享messages数组，低隔离，简单任务委派
    # fork: 独立进程，全新messages数组，共享文件缓存，中隔离，研究性任务
    SUB_AGENT_DEFAULT_MODE = os.getenv('SUB_AGENT_DEFAULT_MODE', 'default')
    SUB_AGENT_FORK_TIMEOUT = int(os.getenv('SUB_AGENT_FORK_TIMEOUT', '300'))  # fork模式超时（秒）
    
    # 子Agent递归限制（保留用于防止单个子Agent无限执行）
    SUB_AGENT_RECURSION_LIMIT = int(os.getenv('SUB_AGENT_RECURSION_LIMIT', '50'))

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

    # 混合检索配置
    ENABLE_HYBRID_SEARCH = os.getenv('ENABLE_HYBRID_SEARCH', 'true').lower() == 'true'  # 是否启用混合检索
    BM25_WEIGHT = float(os.getenv('BM25_WEIGHT', '0.3'))  # BM25检索权重
    VECTOR_WEIGHT = float(os.getenv('VECTOR_WEIGHT', '0.7'))  # 向量检索权重

    # MMR多样性重排序配置
    ENABLE_MMR = os.getenv('ENABLE_MMR', 'true').lower() == 'true'  # 是否启用MMR多样性重排序
    MMR_ALPHA = float(os.getenv('MMR_ALPHA', '0.7'))  # MMR相关性权重（越大越偏向相关性，越小越偏向多样性）

    # 文件上传配置
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', './uploads')
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '10485760'))  # 10MB

    # ==================== 上下文压缩配置（三层架构） ====================
    # 第一层：Journal（JSONL）- 原始消息存储
    
    # 模型最大上下文窗口（默认128k）
    MAX_CONTEXT_TOKENS = int(os.getenv('MAX_CONTEXT_TOKENS', '128000'))
    
    # 压缩触发阈值比例（达到80%时触发）
    COMPACT_THRESHOLD_RATIO = float(os.getenv('COMPACT_THRESHOLD_RATIO', '0.8'))
    
    # 第二层：Memory（向量）- 长期记忆
    
    # 是否启用长期记忆功能
    ENABLE_LONG_TERM_MEMORY = os.getenv('ENABLE_LONG_TERM_MEMORY', 'true').lower() == 'true'
    
    # 长期记忆注入的token预算
    MEMORY_TOKEN_BUDGET = int(os.getenv('MEMORY_TOKEN_BUDGET', '2000'))
    
    # 记忆相关性阈值（Rerank分数，只注入高于此阈值的记忆）
    MEMORY_RELEVANCE_THRESHOLD = float(os.getenv('MEMORY_RELEVANCE_THRESHOLD', '0.65'))
    
    # 第三层：Summary - 当前上下文
    
    # 微观压缩：保留最近的 N 个 tool_result（默认3个，更节省上下文）
    KEEP_RECENT_TOOL_RESULTS = int(os.getenv('KEEP_RECENT_TOOL_RESULTS', '3'))
    
    # 压缩后保留的最近消息数
    KEEP_RECENT_MESSAGES = int(os.getenv('KEEP_RECENT_MESSAGES', '10'))

    # ==================== RAG 查询优化配置 ====================
    # 复杂长句查询优化：指代消解、Step-Back、问题分解、多查询重写
    
    # 成本控制
    QUERY_OPT_MAX_SUB_QUESTIONS = int(os.getenv('QUERY_OPT_MAX_SUB_QUESTIONS', '5'))  # 最大子问题数量
    QUERY_OPT_MAX_VARIANTS = int(os.getenv('QUERY_OPT_MAX_VARIANTS', '3'))  # 每个子问题的最大查询变体数
    
    # 功能开关
    QUERY_OPT_ENABLE_COREFERENCE = os.getenv('QUERY_OPT_ENABLE_COREFERENCE', 'true').lower() == 'true'  # 启用指代消解
    QUERY_OPT_ENABLE_STEP_BACK = os.getenv('QUERY_OPT_ENABLE_STEP_BACK', 'true').lower() == 'true'  # 启用 Step-Back
    QUERY_OPT_ENABLE_DECOMPOSITION = os.getenv('QUERY_OPT_ENABLE_DECOMPOSITION', 'true').lower() == 'true'  # 启用问题分解
    QUERY_OPT_ENABLE_MULTI_QUERY = os.getenv('QUERY_OPT_ENABLE_MULTI_QUERY', 'true').lower() == 'true'  # 启用多查询重写
    
    # 复杂度判断阈值
    QUERY_OPT_SIMPLE_MAX_WORDS = int(os.getenv('QUERY_OPT_SIMPLE_MAX_WORDS', '10'))  # 简单查询的最大词数
    QUERY_OPT_COMPLEX_MIN_WORDS = int(os.getenv('QUERY_OPT_COMPLEX_MIN_WORDS', '15'))  # 复杂查询的最小词数
    
    # 是否启用增强版 RAG（查询优化）
    ENABLE_ENHANCED_RAG = os.getenv('ENABLE_ENHANCED_RAG', 'true').lower() == 'true'
