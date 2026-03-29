"""
Bash工具模块

提供bash命令执行能力，包含：
1. 命令分类（读取类 vs 执行类）
2. 执行类命令需要用户确认
3. 读取类命令可以直接执行
4. 安全增强：防止命令注入、shell注入
"""
import os
import re
import shlex
import subprocess
from typing import Tuple, List, Optional

from langchain_core.tools import tool

from config import Config


# ==================== 安全配置 ====================

# 危险命令黑名单（这些命令必须用户确认）
DANGEROUS_COMMANDS = {
    # 文件操作危险命令
    'rm', 'rmdir', 'shred',
    # 权限相关
    'sudo', 'su', 'doas', 'chmod', 'chown', 'chgrp',
    # 系统危险操作
    'dd', 'mkfs', 'fdisk', 'parted', 'shutdown', 'reboot', 'init',
    # 网络命令（可能泄露数据）
    'nc', 'netcat', 'telnet', 'ssh', 'scp', 'rsync', 'wget', 'curl',
    # 进程管理
    'kill', 'killall', 'pkill',
    # 其他危险命令
    'crontab', 'at', 'batch',
}

# 安全命令白名单（这些命令可以无需确认执行）
SAFE_COMMANDS = {
    # 文件查看
    'ls', 'dir', 'cat', 'head', 'tail', 'less', 'more', 'wc',
    'file', 'stat', 'tree', 'du', 'df',
    # 文本处理
    'grep', 'egrep', 'fgrep', 'sed', 'awk', 'cut', 'sort', 'uniq',
    'diff', 'cmp', 'find', 'locate',
    # 系统信息
    'pwd', 'whoami', 'hostname', 'uname', 'date', 'cal', 'uptime',
    'env', 'printenv', 'echo', 'type', 'which', 'whereis',
    'history', 'id', 'groups',
    # Git 读取类
    'git',
    # 开发工具（读取类）
    'python', 'python3', 'pip', 'pip3', 'node', 'npm', 'npx',
}

# 命令注入危险模式（检测 shell 注入攻击）
# 注意：管道操作(|)是安全的常用功能，不应该被误判为注入
# 我们在其他地方通过检查管道后的命令是否安全来控制
INJECTION_PATTERNS = [
    (r';\s*\w', '命令分隔符注入 (;)'),
    # 移除管道注入检测，因为管道是合法的命令组合方式
    # 管道的安全性通过 get_command_type 中的逻辑来保证
    (r'\$\s*\(', '命令替换注入 ($())'),
    (r'`[^`]+`', '命令替换注入 (``)'),
    (r'&&\s*\w', '命令链注入 (&&)'),
    (r'\|\|\s*\w', '命令链注入 (||)'),
    (r'\$\{[^}]+\}', '变量扩展注入 (${}})'),
]


# ==================== 命令解析与安全检测 ====================

def parse_command(command: str) -> Tuple[List[str], Optional[str]]:
    """
    安全解析命令字符串
    
    Args:
        command: 要解析的命令字符串
        
    Returns:
        (tokens, error) 元组：
        - tokens: 解析后的参数列表
        - error: 错误信息（如果解析失败）
    """
    try:
        tokens = shlex.split(command)
        return tokens, None
    except ValueError as e:
        return [], f"命令解析错误: {str(e)}"


def detect_injection(command: str) -> Tuple[bool, str]:
    """
    检测命令注入攻击
    
    Args:
        command: 要检测的命令字符串
        
    Returns:
        (is_injection, reason) 元组
    """
    for pattern, reason in INJECTION_PATTERNS:
        if re.search(pattern, command):
            return True, reason
    return False, ""


def get_base_command(tokens: List[str]) -> str:
    """
    获取基础命令名称
    
    处理带路径的命令，如 /bin/rm -> rm
    """
    if not tokens:
        return ""
    return os.path.basename(tokens[0])


def check_dangerous_command(command: str) -> Tuple[bool, str]:
    """
    检查命令是否包含危险操作（增强版）
    
    Args:
        command: 要检查的bash命令
        
    Returns:
        (is_dangerous, reason) 元组
    """
    command_lower = command.lower().strip()
    
    # 1. 检查命令注入
    is_injection, injection_reason = detect_injection(command)
    if is_injection:
        return True, f"检测到潜在的安全威胁: {injection_reason}"
    
    # 2. 解析命令
    tokens, parse_error = parse_command(command)
    if parse_error:
        # 解析失败，可能是恶意构造
        return True, parse_error
    
    if not tokens:
        return False, ""
    
    # 3. 获取基础命令
    base_cmd = get_base_command(tokens)
    
    # 4. 检查白名单（配置文件中允许的危险模式）
    for allowed_pattern in Config.ALLOWED_DANGEROUS_PATTERNS:
        if allowed_pattern.lower() in command_lower:
            return False, ""
    
    # 5. 检查危险命令黑名单
    if base_cmd in DANGEROUS_COMMANDS:
        return True, f"危险命令: {base_cmd}"
    
    # 6. 检查特定的危险模式
    dangerous_patterns = [
        (r'rm\s+-rf\s+/', '可能删除整个系统'),
        (r'rm\s+-rf\s+~', '可能删除用户主目录'),
        (r'rm\s+-rf\s+\*', '可能删除当前目录所有文件'),
        (r'chmod\s+777', '可能造成权限问题'),
        (r'>\s*/dev/sd', '可能写入磁盘设备'),
    ]
    
    for pattern, reason in dangerous_patterns:
        if re.search(pattern, command_lower):
            return True, f"检测到危险操作: {reason}"
    
    return False, ""


def get_command_type(command: str) -> Tuple[str, str, str]:
    """
    分析命令类型，判断是否需要用户确认（增强版）
    
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
    
    # 解析命令
    tokens, _ = parse_command(command)
    if not tokens:
        return "execute", "未知命令", working_dir
    
    base_cmd = get_base_command(tokens)
    
    # 1. 检查是否是安全命令
    if base_cmd in SAFE_COMMANDS:
        # 特殊处理 git 命令，只允许读取类操作
        if base_cmd == 'git':
            git_read_only = ['status', 'log', 'branch', 'remote', 'diff', 'show', 
                            'ls-files', 'ls-tree', 'rev-parse', 'describe']
            if len(tokens) > 1 and tokens[1] in git_read_only:
                return "read", f"Git {tokens[1]}", working_dir
            # 其他 git 命令需要确认
            return "execute", "Git 操作", working_dir
        
        # 检查是否有输出重定向（写入文件）
        if '>' in command:
            return "execute", "写入/重定向到文件", working_dir
        
        return "read", f"执行 {base_cmd}", working_dir
    
    # 2. 检查是否是危险命令
    if base_cmd in DANGEROUS_COMMANDS:
        return "execute", f"危险命令: {base_cmd}", working_dir
    
    # 3. 检查管道和重定向（增强版）
    if '|' in command:
        # 检查管道后的所有命令是否安全
        parts = command.split('|')
        all_safe = True
        unsafe_commands = []
        
        for part in parts:
            part_tokens, _ = parse_command(part.strip())
            if part_tokens:
                part_base_cmd = get_base_command(part_tokens)
                # 检查是否在安全白名单中
                if part_base_cmd not in SAFE_COMMANDS:
                    all_safe = False
                    unsafe_commands.append(part_base_cmd)
                # 检查是否在危险黑名单中
                elif part_base_cmd in DANGEROUS_COMMANDS:
                    all_safe = False
                    unsafe_commands.append(part_base_cmd)
        
        if all_safe:
            return "read", "管道组合查询", working_dir
        else:
            # 管道中包含不安全的命令，需要确认
            return "execute", f"管道包含非安全命令: {', '.join(unsafe_commands)}", working_dir
    
    # 4. 默认为执行类命令
    return "execute", f"执行 {base_cmd}", working_dir


# ==================== 命令执行 ====================

def expand_tilde_in_tokens(tokens: List[str]) -> List[str]:
    """
    展开命令参数中的 ~ 符号为用户主目录
    
    Args:
        tokens: 解析后的命令参数列表
        
    Returns:
        展开后的参数列表
    """
    home_dir = os.path.expanduser("~")
    expanded_tokens = []
    
    for token in tokens:
        if token.startswith("~/"):
            # 展开 ~/path 格式
            expanded_tokens.append(token.replace("~", home_dir, 1))
        elif token == "~":
            # 单独的 ~ 展开
            expanded_tokens.append(home_dir)
        else:
            expanded_tokens.append(token)
    
    return expanded_tokens


def execute_bash_direct(command: str) -> str:
    """
    安全执行bash命令（增强版）
    
    改进：
    1. 使用 shlex 正确解析命令
    2. 使用 shell=False 防止 shell 注入
    3. 更完善的错误处理
    4. 自动展开 ~ 符号为用户主目录
    
    Args:
        command: 要执行的bash命令
        
    Returns:
        命令执行结果
    """
    try:
        # 1. 解析命令
        tokens, parse_error = parse_command(command)
        if parse_error:
            return f"{parse_error}"
        
        if not tokens:
            return "空命令"
        
        # 2. 获取基础命令并检查安全性
        base_cmd = get_base_command(tokens)
        
        # 最后一次安全检查（双重保险）
        is_dangerous, danger_reason = check_dangerous_command(command)
        if is_dangerous:
            return f"安全拦截：{danger_reason}"
        
        # 3. 构建执行命令
        # 对于简单命令，直接执行
        # 对于包含管道、重定向的复杂命令，需要通过 shell 执行
        needs_shell = any(c in command for c in ['|', '>', '<', '&&', '||', '`', '$('])
        
        if needs_shell:
            # 复杂命令需要 shell，但已经过安全检测
            # 在 shell 执行时，~ 会被 shell 自动展开
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=Config.BASH_TIMEOUT,
                cwd=os.getcwd()
            )
        else:
            # 简单命令直接执行，不经过 shell（更安全）
            # 需要手动展开 ~ 符号
            tokens = expand_tilde_in_tokens(tokens)
            result = subprocess.run(
                tokens,
                shell=False,
                capture_output=True,
                text=True,
                timeout=Config.BASH_TIMEOUT,
                cwd=os.getcwd()
            )

        if result.returncode == 0:
            return result.stdout.strip() if result.stdout.strip() else "命令执行成功（无输出）"
        else:
            error_msg = result.stderr.strip() if result.stderr.strip() else f"退出码 {result.returncode}"
            return f"错误：{error_msg}"

    except subprocess.TimeoutExpired:
        return f"命令执行超时（{Config.BASH_TIMEOUT}秒）"
    except FileNotFoundError:
        return f"命令不存在：{base_cmd}"
    except PermissionError:
        return f"权限不足：{base_cmd}"
    except Exception as e:
        return f"执行错误：{str(e)}"


# ==================== LangChain 工具定义 ====================

# 定义一个特殊的返回结构，用于标记需要确认的命令
CONFIRMATION_REQUIRED_MARKER = "__CONFIRMATION_REQUIRED__"


@tool
def execute_bash(command: str) -> str:
    """
    执行 bash 命令。读取类命令直接执行，修改类命令需要用户确认。
    
    安全命令（直接执行）：ls, cat, grep, find, pwd 等
    危险命令（需确认）：rm, sudo, chmod, 重定向(>) 等
    
    Args:
        command: 要执行的 bash 命令
        
    Returns:
        命令执行结果或确认请求
    """
    import json
    
    # 1. 安全检测
    is_dangerous, danger_reason = check_dangerous_command(command)
    
    # 2. 分析命令类型
    cmd_type, operation, working_dir = get_command_type(command)
    
    # 3. 如果检测到命令注入，直接拒绝
    if is_dangerous and "注入" in danger_reason:
        return f"安全拦截：{danger_reason}。请使用安全的命令格式。"
    
    # 4. 如果是安全的读取类命令，直接执行
    if cmd_type == "read" and not is_dangerous:
        return execute_bash_direct(command)
    
    # 5. 执行类命令或危险命令，需要用户确认
    if is_dangerous:
        confirm_message = f"[危险命令检测] {danger_reason}"
    else:
        confirm_message = "执行类命令需要确认"
    
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


# ==================== 详细说明（供动态加载） ====================

@tool
def get_bash_tool_detailed_usage() -> str:
    """
    获取 bash 工具的详细使用说明，包括安全策略和最佳实践。
    
    Returns:
        详细的使用说明文本
    """
    return """
## Bash 工具详细使用说明

### 命令分类

**安全命令（可直接执行）**：
- 文件查看：ls, cat, head, tail, less, more, tree, du, df, wc, file, stat
- 文本处理：grep, sed, awk, cut, sort, uniq, diff, find, locate
- 系统信息：pwd, whoami, hostname, uname, date, env, echo, which

**需要确认的命令**：
- 文件写入：echo >, cat >, tee
- 文件操作：mv, cp, rm, mkdir, rmdir
- 系统命令：sudo, chmod, chown
- 危险命令：dd, mkfs, shutdown 等

### 安全策略

1. **管道命令是安全的**：可以自由使用管道操作符(|)组合多个安全的读取命令
   - 示例：`ls /Users/malog/Desktop | grep malog`
   - 示例：`cat file.txt | grep pattern`

2. **路径处理**：
   - 优先使用绝对路径：`/Users/malog/Desktop`
   - `~` 符号可能不会被正确展开，建议使用完整路径或 `$HOME` 变量

3. **安全检测**：
   - 自动检测命令注入攻击（如 `;`, `&&`, `||`, `$()` 等）
   - 危险命令会特别提示风险
   - 执行类命令需要用户确认后才能执行

### 最佳实践

1. 先确认文件存在：使用 `ls` 或 `test -f` 命令
2. 避免重复执行相同命令，记住之前的查询结果
3. 如果某个步骤失败，分析错误原因并提供替代方案
"""


# 导出工具列表
__all__ = [
    'execute_bash', 
    'execute_confirmed_bash', 
    'execute_cancelled_bash',
    'check_dangerous_command', 
    'get_command_type',
    'get_bash_tool_detailed_usage',
    'CONFIRMATION_REQUIRED_MARKER'
]
