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
    
    # 数据库配置
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/malogbot'
    )
    
    # LLM配置
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')
    MODEL_NAME = os.getenv('MODEL_NAME', 'deepseek-chat')  # 使用deepseek-chat支持工具调用
    
    # 工具配置
    BASH_TIMEOUT = int(os.getenv('BASH_TIMEOUT', '30'))  # 命令超时时间（秒）
    
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
