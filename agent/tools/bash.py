"""
Bash工具模块

提供bash命令执行能力，包含：
1. 命令分类（读取类 vs 执行类）
2. 执行类命令需要用户确认
3. 读取类命令可以直接执行
"""
import os
import re
import subprocess
from typing import Tuple, Dict, Any

from langchain_core.tools import tool

from config import Config


def get_command_type(command: str) -> Tuple[str, str, str]:
    """
    分析命令类型，判断是否需要用户确认
    
    Args:
        command: 要分析的bash命令
        
    Returns:
        (command_type, operation, working_dir) 元组：
        - command_type: "read"（读取类，可直接执行）或 "execute"（执行类，需要确认）
        - operation: 命令操作描述
        - working_dir: 执行路径
    """
    command_lower = command.lower().strip()
    working_dir = os.getcwd()
    
    # 读取类命令列表（这些命令只读取信息，不修改系统状态）
    read_only_patterns = [
        (r'^\s*ls\b', '列出目录内容'),
        (r'^\s*cat\b', '查看文件内容'),
        (r'^\s*head\b', '查看文件开头'),
        (r'^\s*tail\b', '查看文件结尾'),
        (r'^\s*less\b', '分页查看文件'),
        (r'^\s*more\b', '分页查看文件'),
        (r'^\s*pwd\b', '显示当前目录'),
        (r'^\s*whoami\b', '显示当前用户'),
        (r'^\s*which\b', '查找命令位置'),
        (r'^\s*whereis\b', '查找命令位置'),
        (r'^\s*find\b.*-\s*name\b', '查找文件'),
        (r'^\s*grep\b', '搜索文本'),
        (r'^\s*egrep\b', '搜索文本'),
        (r'^\s*fgrep\b', '搜索文本'),
        (r'^\s*wc\b', '统计文件信息'),
        (r'^\s*stat\b', '查看文件状态'),
        (r'^\s*file\b', '查看文件类型'),
        (r'^\s*du\b', '查看磁盘使用'),
        (r'^\s*df\b', '查看磁盘空间'),
        (r'^\s*tree\b', '显示目录树'),
        (r'^\s*echo\b.*\$\(', '显示变量或命令结果'),  # echo $VAR 或 echo $(cmd) 形式
        (r'^\s*echo\b[^>]*$', '显示文本'),  # echo 纯文本（不包含重定向）
        (r'^\s*type\b', '查看命令类型'),
        (r'^\s*uname\b', '显示系统信息'),
        (r'^\s*date\b', '显示日期'),
        (r'^\s*history\b', '查看命令历史'),
        (r'^\s*env\b', '查看环境变量'),
        (r'^\s*printenv\b', '查看环境变量'),
        (r'^\s*git\s+status\b', '查看Git状态'),
        (r'^\s*git\s+log\b', '查看Git日志'),
        (r'^\s*git\s+branch\b', '查看Git分支'),
        (r'^\s*git\s+remote\b', '查看Git远程仓库'),
        (r'^\s*git\s+diff\b', '查看Git差异'),
        (r'^\s*git\s+show\b', '查看Git提交'),
    ]
    
    # 检查是否是读取类命令
    for pattern, operation in read_only_patterns:
        if re.search(pattern, command_lower):
            return "read", operation, working_dir
    
    # 检查是否包含输出重定向（> 或 >>），这会修改文件
    if '>' in command:
        return "execute", "写入/重定向到文件", working_dir
    
    # 检查是否是读取类命令但有管道（如 cat file | grep xxx）
    # 如果管道后面也是读取类命令，整体仍是读取
    if '|' in command:
        parts = command.split('|')
        all_read = True
        for part in parts:
            part = part.strip()
            is_read_cmd = any(
                re.search(pattern, part.lower()) 
                for pattern, _ in read_only_patterns
            )
            if not is_read_cmd:
                all_read = False
                break
        if all_read:
            return "read", "管道组合查询", working_dir
    
    # 默认为执行类命令
    return "execute", "执行命令", working_dir


def check_dangerous_command(command: str) -> Tuple[bool, str]:
    """
    检查命令是否包含危险操作
    
    Args:
        command: 要检查的bash命令
        
    Returns:
        (is_dangerous, reason) 元组：
        - is_dangerous: 是否是危险命令
        - reason: 危险原因说明
    """
    command_lower = command.lower().strip()

    # 检查白名单（允许的危险模式）
    for allowed_pattern in Config.ALLOWED_DANGEROUS_PATTERNS:
        if allowed_pattern.lower() in command_lower:
            return False, ""

    # 检查危险命令
    dangerous_keywords = {
        'sudo': '需要超级用户权限',
        'rm -rf /': '可能删除整个系统',
        'rm -rf ~': '可能删除用户主目录',
        'rm -rf *': '可能删除当前目录所有文件',
        'chmod 777': '可能造成权限问题',
        'chown': '修改文件所有者',
        'dd': '低级别磁盘操作',
        'mkfs': '格式化文件系统',
        'fdisk': '磁盘分区操作',
        'shutdown': '关闭系统',
        'reboot': '重启系统',
        'init 0': '关闭系统',
        'init 6': '重启系统',
    }

    for keyword, reason in dangerous_keywords.items():
        if keyword in command_lower:
            return True, f"检测到危险操作: {reason}"

    # 检查单独的rm命令（不在白名单中）
    if re.search(r'\brm\b', command_lower):
        # 检查是否是rm但不在白名单中
        is_in_whitelist = any(
            pattern.lower() in command_lower
            for pattern in Config.ALLOWED_DANGEROUS_PATTERNS
        )
        if not is_in_whitelist:
            return True, "删除命令需要确认"

    # 检查sudo
    if 'sudo' in command_lower:
        return True, "需要超级用户权限"

    return False, ""


def execute_bash_direct(command: str) -> str:
    """
    直接执行bash命令（内部方法，不通过LangChain）
    
    Args:
        command: 要执行的bash命令
        
    Returns:
        命令执行结果
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=Config.BASH_TIMEOUT
        )

        if result.returncode == 0:
            return result.stdout if result.stdout.strip() else "命令执行成功（无输出）"
        else:
            return f"错误（退出码 {result.returncode}）:\n{result.stderr}"

    except subprocess.TimeoutExpired:
        return f"错误: 命令执行超时（{Config.BASH_TIMEOUT}秒）"
    except Exception as e:
        return f"错误: {str(e)}"


# 定义一个特殊的返回结构，用于标记需要确认的命令
CONFIRMATION_REQUIRED_MARKER = "__CONFIRMATION_REQUIRED__"


@tool
def execute_bash(command: str) -> str:
    """
    执行bash命令并返回结果。
    
    用于执行shell命令，如创建文件、运行程序、查看文件内容等。
    
    重要说明：
    - 读取类命令（ls、cat、grep等）可以直接执行
    - 执行类命令（写入、删除、运行程序等）需要用户确认后才能执行
    - 危险命令（如sudo、rm等）会特别提示风险
    
    Args:
        command: 要执行的bash命令
        
    Returns:
        命令的输出结果，或需要确认的命令请求
        
    Examples:
        execute_bash("ls -la")  # 列出当前目录文件（读取类，直接执行）
        execute_bash("echo 'hello' > test.txt")  # 创建文件（执行类，需要确认）
        execute_bash("python script.py")  # 运行Python脚本（执行类，需要确认）
    """
    import json
    
    # 分析命令类型
    cmd_type, operation, working_dir = get_command_type(command)
    
    # 检查是否是危险命令
    is_dangerous, danger_reason = check_dangerous_command(command)
    
    # 如果是读取类命令，直接执行
    if cmd_type == "read" and not is_dangerous:
        return execute_bash_direct(command)
    
    # 执行类命令或危险命令，需要用户确认
    # 构建需要确认的消息
    if is_dangerous:
        confirm_message = f"⚠️ 危险命令检测: {danger_reason}"
    else:
        confirm_message = f"📋 执行类命令需要确认"
    
    # 返回特殊格式的JSON，等待用户确认
    return json.dumps({
        "type": CONFIRMATION_REQUIRED_MARKER,
        "command": command,
        "command_type": cmd_type,
        "operation": operation,
        "working_dir": working_dir,
        "is_dangerous": is_dangerous,
        "reason": danger_reason if is_dangerous else "",
        "message": confirm_message
    }, ensure_ascii=False)


def execute_confirmed_bash(command: str) -> str:
    """
    执行已确认的命令
    
    Args:
        command: 用户已确认的bash命令
        
    Returns:
        命令执行结果
    """
    return execute_bash_direct(command)


def execute_cancelled_bash(command: str) -> str:
    """
    处理用户取消的命令，返回取消信息供LLM继续处理
    
    Args:
        command: 用户取消的bash命令
        
    Returns:
        取消信息
    """
    return f"用户取消了命令执行: {command}"


# 导出工具列表
__all__ = [
    'execute_bash', 
    'execute_confirmed_bash', 
    'execute_cancelled_bash',
    'check_dangerous_command', 
    'get_command_type',
    'CONFIRMATION_REQUIRED_MARKER'
]
