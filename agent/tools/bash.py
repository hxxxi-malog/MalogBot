"""
Bash工具模块

提供bash命令执行能力，包含危险命令检测和用户确认机制
"""
import re
import subprocess
from typing import Tuple

from langchain_core.tools import tool

from config import Config


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


# 定义一个特殊的返回结构，用于标记危险命令
DANGEROUS_COMMAND_MARKER = "__DANGEROUS_COMMAND__"


@tool
def execute_bash(command: str) -> str:
    """
    执行bash命令并返回结果。
    
    用于执行shell命令，如创建文件、运行程序、查看文件内容等。
    
    重要说明：
    - 危险命令（如sudo、rm等）需要用户确认后才能执行
    - 如果命令被标记为危险，会返回特殊格式等待用户确认
    
    Args:
        command: 要执行的bash命令
        
    Returns:
        命令的输出结果，或危险命令确认请求
        
    Examples:
        execute_bash("ls -la")  # 列出当前目录文件
        execute_bash("echo 'hello' > test.txt")  # 创建文件
        execute_bash("python script.py")  # 运行Python脚本
    """
    # 检查命令是否危险
    is_dangerous, reason = check_dangerous_command(command)

    if is_dangerous:
        # 返回特殊格式的JSON，标记为危险命令
        import json
        return json.dumps({
            "type": DANGEROUS_COMMAND_MARKER,
            "command": command,
            "reason": reason,
            "message": f"⚠️ 危险命令检测: {reason}\n命令: {command}\n\n需要用户确认是否执行。"
        }, ensure_ascii=False)

    # 安全命令，直接执行
    return execute_bash_direct(command)


def execute_confirmed_bash(command: str) -> str:
    """
    执行已确认的危险命令
    
    Args:
        command: 用户已确认的bash命令
        
    Returns:
        命令执行结果
    """
    return execute_bash_direct(command)


# 导出工具列表
__all__ = ['execute_bash', 'execute_confirmed_bash', 'check_dangerous_command', 'DANGEROUS_COMMAND_MARKER']
