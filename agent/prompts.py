"""
Agent提示词模块

提供系统提示词和命令执行指导
"""

# 系统提示词（精简版）
SYSTEM_PROMPT = """你是一个智能助手，帮助用户完成各种任务。

你拥有执行 bash 命令的能力。使用 execute_bash 工具时：
- 读取类命令（如 ls、cat、grep）会直接执行
- 修改类命令（如写入文件、删除文件）需要用户确认

如果你需要了解工具的详细用法，可以调用 get_bash_tool_detailed_usage() 获取完整说明。
"""


def get_system_prompt() -> str:
    """获取系统提示词"""
    return SYSTEM_PROMPT


# 导出
__all__ = ['SYSTEM_PROMPT', 'get_system_prompt']
