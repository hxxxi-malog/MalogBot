"""
Agent提示词模块

采用分层架构设计：
1. 核心规则层（常驻）：角色定义、行为准则、安全边界
2. 能力索引层（常驻）：工具分类目录，让LLM知道有哪些工具
3. 场景指南层（按需）：详细的使用示例和规范
4. 上下文层（动态）：记忆、知识库、任务状态等
"""

import logging
from typing import List, Dict, Optional, Set
from functools import lru_cache

logger = logging.getLogger(__name__)


# ============================================================
# 第一层：核心规则（常驻，约 25 行）
# ============================================================

CORE_RULES = """你是一个智能助手，帮助用户完成各种任务。

## 核心行为准则

1. **工具优先**：执行操作时优先调用工具，禁止用纯文本描述"应该做的事"
2. **主动记忆**：检测到用户信息（姓名、偏好、决策）时立即调用 store_memory，不要询问
3. **任务隔离**：复杂多步骤任务创建子Agent执行，简单任务直接执行
4. **安全确认**：危险操作（删除、格式化、rm -rf等）必须先向用户确认

## 任务执行原则

1. **理解意图**：执行前明确用户的核心目标
2. **最小化执行**：只做用户明确要求的事，不自行扩展
3. **完成即停止**：达成目标后立即结束，汇报结果并等待新指令
4. **避免重复**：已完成的操作不要再次执行

## 响应规范

- 完成操作后简要说明结果，不要过度解释
- 遇到错误时分析原因并提供解决建议
- 不确定时主动询问，不要猜测

## 上下文管理（重要）

**工具结果会自动清理**：旧的工具调用结果会被压缩为简洁占位符（如 [tool: bash]），仅保留最近几次。

**主动记笔记**：如果工具返回的信息对后续任务重要，请主动在回复中记录关键信息：
- 文件路径和关键内容摘要
- 重要的配置值和参数
- 发现的问题和解决方案
- 需要后续使用的中间结果

这样可以避免关键信息在压缩中丢失。
"""


# ============================================================
# 第二层：能力索引（常驻，让LLM感知所有可用工具）
# ============================================================

TOOL_CAPABILITY_INDEX = """
## 可用工具索引

### 记忆管理
- `store_memory`：存储用户信息到长期记忆（个人信息、偏好、决策、项目信息）
- `store_memories_batch`：批量存储多条信息

### 任务管理（简单线性）
- `todo_manager`：管理简单线性任务列表（无依赖关系）
- `get_todo_status`：获取当前任务状态

### 任务管理（复杂依赖）
- `task_create`：创建支持依赖关系的任务（DAG编排）
- `task_update`：更新任务状态（completed/in_progress/paused）
- `task_get_ready`：获取可执行的任务（无阻塞）
- `task_get_blocked`：获取被阻塞的任务
- `task_get_status`：获取整体进度
- `task_visualize`：可视化任务依赖图

### 执行能力
- `execute_bash`：执行shell命令（读取类直接执行，修改类需确认）
- `spawn_sub_agent`：创建子Agent执行复杂任务（搜索、多步骤操作、代码重构）
- `web_search`：联网搜索信息（需启用）

### 技能系统
- `list_skills`：列出可用技能
- `get_skill`：获取技能详细说明
- `get_skill_reference`：获取技能参考资料
- `get_skill_template`：获取技能输出模板

### 工具使用帮助
- `get_bash_tool_detailed_usage`：获取bash工具详细用法
- `get_tool_usage`：获取任意工具的详细用法说明

---
**提示**：不确定某个工具的具体用法时，调用 `get_tool_usage('工具名')` 获取详细说明。
"""


# ============================================================
# 第三层：场景指南（按需加载）
# ============================================================

SCENARIO_GUIDES = {
    "memory": """
## 记忆存储指南

### 触发时机
用户透露以下信息时，必须在回复前调用 store_memory：

| 信息类型 | memory_type | 示例 |
|---------|-------------|------|
| 个人信息 | user_info | "我叫Malog" → store_memory(content="用户姓名是Malog", memory_type="user_info") |
| 偏好 | preference | "我喜欢Python" → store_memory(content="用户偏好使用Python编程", memory_type="preference") |
| 决策 | decision | "我决定用PostgreSQL" → store_memory(content="用户决定使用PostgreSQL数据库", memory_type="decision") |
| 项目 | project | "我的项目叫MalogBot" → store_memory(content="用户项目名称是MalogBot", memory_type="project") |

### 存储原则
- 不询问是否存储，直接存储
- 内容要清晰完整，便于后续检索
- 重要性：个人信息 0.9+，偏好 0.85，决策 0.8，事实 0.75
""",

    "task_selection": """
## 任务管理工具选择

### TodoManager（简单线性）
适用场景：
- 任务无依赖关系，按顺序执行
- 临时性任务跟踪
- 快速记录待办事项

示例：写脚本、重构单个模块、执行简单流程

### TaskManager（复杂依赖）
适用场景：
- 任务有依赖关系（必须先完成A才能做B）
- 需要并行执行独立任务
- 任务需要持久化保存
- CI/CD流程、复杂项目迁移

示例：
```
# 创建依赖任务
task_create(subject="安装依赖", ...) → 返回 id=1
task_create(subject="运行测试", blocked_by=[1], ...) → 返回 id=2
task_update(task_id=1, status="completed") → id=2 自动解锁
```

### 选择决策
- 无依赖 → todo_manager
- 有依赖 → task_create + blocked_by
- 不确定 → 先用 todo_manager，复杂时迁移
""",

    "subagent": """
## 子Agent使用规范

### 适用场景
- 联网搜索/信息收集
- 多步骤文件操作
- 代码重构/调试
- 需要隔离执行的复杂任务

### 任务描述规范
任务描述必须精确具体，包含：
1. 具体操作：读取/写入/执行/搜索
2. 目标对象：明确的路径/命令/范围
3. 完成条件：什么情况算完成

**示例**：
- "读取 /path/to/file.py 的前50行，返回内容摘要"
- "搜索X相关内容，整理后写入指定文件，返回文件路径"

### 执行结果处理
- 成功：向用户汇报结果
- 部分完成：判断是否需要继续
- 失败：分析原因，考虑重试或报告
""",

    "bash": """
## Bash命令执行规范

### 权限分级
- 读取类（ls, cat, head, grep等）：直接执行
- 修改类（mkdir, touch, echo等）：需要确认
- 危险类（rm, chmod, chown等）：强制确认并说明风险

### 工作目录
- 默认在项目根目录执行
- 如需切换目录，使用 cd /path && command 形式
- 长路径操作建议使用绝对路径

### 常用快捷方式
- `get_bash_tool_detailed_usage()`：获取详细用法
- 查看大文件：`head -n 100 file.txt`
- 搜索内容：`grep -r "pattern" /path --include="*.py"`
- 查找文件：`find /path -name "*.py"`
""",

    "skills": """
## 技能系统使用

### 可用技能
调用 `list_skills()` 查看所有可用技能

### 使用流程
1. `list_skills()`：浏览可用技能
2. `get_skill('skill_name')`：获取技能详细说明
3. `get_skill_reference('skill_name', 'reference_file')`：获取参考资料
4. `get_skill_template('skill_name', 'template_file')`：获取输出模板

### 技能激活
某些技能需要在会话设置中激活，激活后相关工具自动可用
"""
}


# ============================================================
# 第四层模板：动态上下文注入模板
# ============================================================

CONTEXT_TEMPLATES = {
    "memory_context": """
## 用户记忆

以下是检索到的用户相关信息，请在回答时参考：

{content}

---
请在适当时引用这些记忆信息，让用户感受到个性化服务。
""",

    "knowledge_context": """
## 知识库上下文

以下是知识库中检索到的相关信息，请优先参考：

{content}

---
请在回答时适当引用知识库中的相关信息。
""",

    "task_status": """
## 当前任务状态

{content}

---
请在执行相关操作时考虑当前任务状态。
""",

    "todo_reminder": """
## 任务提醒

{content}
""",

    "tool_context": """
## 当前可用工具

{content}
"""
}


# ============================================================
# 场景触发规则（基于关键词）
# ============================================================

SCENARIO_TRIGGERS: Dict[str, Set[str]] = {
    "memory": {
        "我叫", "我的名字", "我喜欢", "我偏好", "记住", "别忘了",
        "我的邮箱", "我的电话", "我决定", "我选择", "项目叫"
    },
    "task_selection": {
        "任务", "步骤", "计划", "依赖", "并行", "先后顺序",
        "待办", "进度", "工作流", "流程"
    },
    "subagent": {
        "搜索", "查找资料", "联网", "重构", "多步骤", "批量处理",
        "分析代码", "整理", "收集信息"
    },
    "bash": {
        "执行命令", "运行", "shell", "终端", "bash", "脚本",
        "删除", "移动", "复制", "权限"
    },
    "skills": {
        "技能", "模板", "参考", "文档", "指南"
    }
}


def detect_scenario_hints(user_input: str, chat_history: List[Dict] = None) -> List[str]:
    """
    基于关键词检测需要加载的场景指南
    
    Args:
        user_input: 当前用户输入
        chat_history: 对话历史（可选，用于更精准判断）
        
    Returns:
        需要加载的场景指南列表
    """
    hints = []
    combined_text = user_input.lower()
    
    # 简单合并最近几轮对话内容
    if chat_history:
        recent = chat_history[-3:] if len(chat_history) > 3 else chat_history
        for msg in recent:
            if msg.get("role") == "user":
                combined_text += " " + msg.get("content", "").lower()
    
    # 匹配关键词
    for scenario, keywords in SCENARIO_TRIGGERS.items():
        if any(kw in combined_text for kw in keywords):
            hints.append(scenario)
    
    return hints


def count_tokens(text: str) -> int:
    """
    估算文本的 token 数量
    
    简单估算：中文约 1.5 字符/token，英文约 4 字符/token
    """
    if not text:
        return 0
    
    # 统计中文字符
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    
    return int(chinese_chars / 1.5 + other_chars / 4)


# ============================================================
# 提示词构建器
# ============================================================

class PromptBuilder:
    """
    动态系统提示词构建器
    
    分层构建，确保 LLM 对工具和能力有充分感知
    """
    
    # Token 预算配置
    MAX_SYSTEM_PROMPT_TOKENS = 2500  # 系统提示词总预算
    CORE_RULES_TOKENS = 200  # 核心规则约 200 tokens
    TOOL_INDEX_TOKENS = 400  # 工具索引约 400 tokens
    MAX_SCENARIO_GUIDES_TOKENS = 800  # 场景指南最大 800 tokens
    MAX_CONTEXT_TOKENS = 1000  # 动态上下文最大 1000 tokens
    
    def __init__(self):
        self._cached_tool_list = None
    
    def build(
        self,
        user_input: str,
        chat_history: List[Dict] = None,
        memory_context: str = None,
        knowledge_context: str = None,
        task_status: str = None,
        todo_reminder: str = None,
        available_tools: List[str] = None,
        max_tokens: int = None
    ) -> str:
        """
        构建系统提示词
        
        Args:
            user_input: 用户输入
            chat_history: 对话历史
            memory_context: 记忆上下文
            knowledge_context: 知识库上下文
            task_status: 任务状态
            todo_reminder: 任务提醒
            available_tools: 当前可用工具列表
            max_tokens: 最大 token 数
            
        Returns:
            完整的系统提示词
        """
        max_tokens = max_tokens or self.MAX_SYSTEM_PROMPT_TOKENS
        
        # 1. 核心规则（必须包含）
        prompt = CORE_RULES
        remaining = max_tokens - self.CORE_RULES_TOKENS
        
        # 2. 工具索引（必须包含，让 LLM 感知可用工具）
        if remaining > self.TOOL_INDEX_TOKENS:
            prompt += TOOL_CAPABILITY_INDEX
            remaining -= self.TOOL_INDEX_TOKENS
            
            # 如果有实际的工具列表，附加可用性说明
            if available_tools:
                tool_notice = self._build_tool_availability_notice(available_tools)
                if tool_notice:
                    prompt += tool_notice
                    remaining -= 50  # 预留
        
        # 3. 场景指南（按需加载）
        hints = detect_scenario_hints(user_input, chat_history)
        scenario_budget = min(remaining - 200, self.MAX_SCENARIO_GUIDES_TOKENS)  # 预留动态上下文
        
        for hint in hints:
            if hint in SCENARIO_GUIDES:
                guide_tokens = count_tokens(SCENARIO_GUIDES[hint])
                if guide_tokens <= scenario_budget:
                    prompt += SCENARIO_GUIDES[hint]
                    scenario_budget -= guide_tokens
                    remaining -= guide_tokens
        
        # 4. 动态上下文
        context_budget = min(remaining, self.MAX_CONTEXT_TOKENS)
        
        if memory_context and context_budget > 100:
            content = self._truncate_context(memory_context, 300)
            prompt += CONTEXT_TEMPLATES["memory_context"].format(content=content)
            context_budget -= count_tokens(prompt[-500:])
        
        if knowledge_context and context_budget > 150:
            content = self._truncate_context(knowledge_context, 400)
            prompt += CONTEXT_TEMPLATES["knowledge_context"].format(content=content)
            context_budget -= count_tokens(prompt[-600:])
        
        if task_status and context_budget > 100:
            content = self._truncate_context(task_status, 200)
            prompt += CONTEXT_TEMPLATES["task_status"].format(content=content)
        
        if todo_reminder:
            prompt += CONTEXT_TEMPLATES["todo_reminder"].format(content=todo_reminder)
        
        return prompt
    
    def _build_tool_availability_notice(self, tools: List[str]) -> str:
        """
        构建工具可用性说明
        
        让 LLM 知道当前会话实际可用的工具
        """
        if not tools:
            return ""
        
        # 检查特殊工具的可用性
        has_web_search = any('web_search' in str(t).lower() or 'search' in str(t).lower() for t in tools)
        has_sub_agent = any('sub_agent' in str(t).lower() or 'spawn' in str(t).lower() for t in tools)
        
        notices = []
        if has_web_search:
            notices.append("- 联网搜索：已启用")
        else:
            notices.append("- 联网搜索：未启用（可在会话设置中开启）")
        
        if has_sub_agent:
            notices.append("- 子Agent：可用")
        
        if notices:
            return f"\n### 当前会话工具状态\n" + "\n".join(notices) + "\n"
        
        return ""
    
    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """截断上下文以符合 token 限制"""
        if count_tokens(context) <= max_tokens:
            return context
        
        # 估算截断位置
        chars = int(max_tokens * 2)  # 保守估算
        return context[:chars] + "\n...[内容已截断]"
    
    def build_for_sub_agent(self, task_description: str, max_steps: int = 30) -> str:
        """
        构建子Agent专用系统提示词
        
        子Agent需要更简洁的提示词，专注于执行
        """
        return f"""你是一个专注的任务执行者。

## 最高优先级规则

1. **严格任务边界**：只执行任务描述中明确要求的内容
2. **完成即停止**：任务完成后立即返回结果
3. **遇到障碍即停止**：无法完成时立即返回失败报告

## 步数预算

最多 {max_steps} 步执行预算，每次工具调用消耗 1 步。

## 可用工具

- execute_bash：执行命令（读取类直接执行，修改类需确认）
- todo_manager：管理子任务（如需拆分）

## 输出格式

执行结果：[成功/失败]

执行过程：
1. [操作] -> [结果]

关键信息：
[提取任务相关的关键信息]
"""


# ============================================================
# 便捷函数
# ============================================================

# 全局构建器实例
_prompt_builder = PromptBuilder()


def build_system_prompt(
    user_input: str,
    chat_history: List[Dict] = None,
    memory_context: str = None,
    knowledge_context: str = None,
    task_status: str = None,
    todo_reminder: str = None,
    available_tools: List[str] = None
) -> str:
    """
    构建系统提示词的便捷函数
    """
    return _prompt_builder.build(
        user_input=user_input,
        chat_history=chat_history,
        memory_context=memory_context,
        knowledge_context=knowledge_context,
        task_status=task_status,
        todo_reminder=todo_reminder,
        available_tools=available_tools
    )


def build_sub_agent_prompt(task_description: str, max_steps: int = 30) -> str:
    """构建子Agent提示词的便捷函数"""
    return _prompt_builder.build_for_sub_agent(task_description, max_steps)


# 保持向后兼容
SYSTEM_PROMPT = CORE_RULES + TOOL_CAPABILITY_INDEX


def get_system_prompt() -> str:
    """获取系统提示词（向后兼容）"""
    return SYSTEM_PROMPT


# 导出
__all__ = [
    'CORE_RULES',
    'TOOL_CAPABILITY_INDEX', 
    'SCENARIO_GUIDES',
    'PromptBuilder',
    'build_system_prompt',
    'build_sub_agent_prompt',
    'detect_scenario_hints',
    'count_tokens',
    'SYSTEM_PROMPT',
    'get_system_prompt'
]
