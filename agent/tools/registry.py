"""
工具注册中心

实现声明即注册的工具管理机制：
1. 使用装饰器 @register_tool 声明工具时自动注册
2. 支持工具分类、优先级、子Agent可见性等元数据
3. 新增工具无需修改 ToolManager，只需导入模块即可

设计原则：
- 开闭原则：新增工具不修改现有代码
- 单一职责：Registry 只负责注册和查询
- 元数据驱动：工具的行为由元数据控制
"""
import logging
from typing import Dict, List, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """工具分类枚举"""
    BASE = "base"              # 基础工具（bash, todo等）
    MEMORY = "memory"          # 记忆存储
    SKILLS = "skills"          # 技能发现
    TASK = "task"              # 任务管理
    PLANNING = "planning"      # 规划工具
    KNOWLEDGE = "knowledge"    # 知识库
    SUB_AGENT = "sub_agent"    # 子Agent（仅主Agent可用）
    WEB = "web"                # 联网搜索
    CUSTOM = "custom"          # 自定义工具


@dataclass
class ToolMeta:
    """工具元数据"""
    tool: Any                              # 工具实例
    name: str                              # 工具名称
    category: ToolCategory = ToolCategory.BASE
    for_sub_agent: bool = True            # 子Agent是否可用
    priority: int = 100                   # 优先级（数字越小越先加载）
    description: str = ""                 # 描述
    tags: List[str] = field(default_factory=list)  # 标签
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他工具
    enabled: bool = True                  # 是否启用
    module: str = ""                      # 来源模块


class ToolRegistry:
    """
    工具注册中心（单例模式）
    
    核心功能：
    1. register(): 注册工具
    2. get_tools(): 按条件获取工具
    3. tool(): 装饰器方式注册
    
    使用示例：
        # 方式1：装饰器注册
        @registry.tool(category=ToolCategory.MEMORY, for_sub_agent=True)
        def my_tool(input: str) -> str:
            return input
        
        # 方式2：直接注册
        registry.register(my_tool, category=ToolCategory.MEMORY)
        
        # 方式3：使用 langchain @tool 装饰器后注册
        @tool
        def my_tool(input: str) -> str:
            return input
        registry.register(my_tool, category=ToolCategory.MEMORY)
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if ToolRegistry._initialized:
            return
        ToolRegistry._initialized = True
        
        # 工具存储：name -> ToolMeta
        self._tools: Dict[str, ToolMeta] = {}
        
        # 分类索引：category -> Set[str]
        self._category_index: Dict[ToolCategory, Set[str]] = {
            cat: set() for cat in ToolCategory
        }
        
        # 模块索引：module -> Set[str]
        self._module_index: Dict[str, Set[str]] = {}
        
        # 已加载的模块集合
        self._loaded_modules: Set[str] = set()
        
        logger.info("[ToolRegistry] 初始化完成")
    
    def register(
        self,
        tool: Any,
        name: str = None,
        category: ToolCategory = ToolCategory.BASE,
        for_sub_agent: bool = True,
        priority: int = 100,
        description: str = "",
        tags: List[str] = None,
        dependencies: List[str] = None,
        module: str = ""
    ) -> Any:
        """
        注册工具
        
        Args:
            tool: 工具实例（langchain BaseTool 或函数）
            name: 工具名称（默认从工具获取）
            category: 工具分类
            for_sub_agent: 子Agent是否可用
            priority: 优先级
            description: 描述
            tags: 标签
            dependencies: 依赖的其他工具
            module: 来源模块
            
        Returns:
            返回工具实例（支持链式调用）
        """
        # 获取工具名称
        tool_name = name or getattr(tool, 'name', None) or getattr(tool, '__name__', str(id(tool)))
        
        # 获取工具描述
        if not description:
            description = getattr(tool, 'description', '') or ''
        
        # 创建元数据
        meta = ToolMeta(
            tool=tool,
            name=tool_name,
            category=category,
            for_sub_agent=for_sub_agent,
            priority=priority,
            description=description,
            tags=tags or [],
            dependencies=dependencies or [],
            module=module
        )
        
        # 注册
        self._tools[tool_name] = meta
        
        # 更新索引
        self._category_index[category].add(tool_name)
        
        if module:
            if module not in self._module_index:
                self._module_index[module] = set()
            self._module_index[module].add(tool_name)
        
        logger.debug(f"[ToolRegistry] 注册工具: {tool_name} (category={category.value}, for_sub_agent={for_sub_agent})")
        
        return tool
    
    def unregister(self, name: str) -> bool:
        """
        取消注册工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功取消
        """
        if name not in self._tools:
            return False
        
        meta = self._tools[name]
        
        # 从索引中移除
        self._category_index[meta.category].discard(name)
        if meta.module:
            if meta.module in self._module_index:
                self._module_index[meta.module].discard(name)
        
        # 从工具存储中移除
        del self._tools[name]
        
        logger.debug(f"[ToolRegistry] 取消注册工具: {name}")
        return True
    
    def tool(
        self,
        category: ToolCategory = ToolCategory.BASE,
        for_sub_agent: bool = True,
        priority: int = 100,
        tags: List[str] = None,
        module: str = ""
    ) -> Callable:
        """
        装饰器方式注册工具
        
        用法:
            @registry.tool(category=ToolCategory.MEMORY)
            def my_tool(input: str) -> str:
                return input
        """
        def decorator(func: Callable) -> Callable:
            # 获取模块名
            nonlocal module
            if not module and hasattr(func, '__module__'):
                module = func.__module__
            
            self.register(
                func,
                category=category,
                for_sub_agent=for_sub_agent,
                priority=priority,
                tags=tags,
                module=module
            )
            return func
        
        return decorator
    
    def get_tools(
        self,
        categories: List[ToolCategory] = None,
        for_sub_agent: bool = None,
        include_disabled: bool = False,
        module: str = None
    ) -> List[Any]:
        """
        获取工具列表
        
        Args:
            categories: 过滤分类（None表示所有分类）
            for_sub_agent: 过滤子Agent可用性（None表示不过滤）
            include_disabled: 是否包含禁用的工具
            module: 过滤来源模块
            
        Returns:
            工具实例列表
        """
        result = []
        
        for name, meta in self._tools.items():
            # 过滤禁用的工具
            if not include_disabled and not meta.enabled:
                continue
            
            # 过滤分类
            if categories and meta.category not in categories:
                continue
            
            # 过滤子Agent可用性
            if for_sub_agent is not None and meta.for_sub_agent != for_sub_agent:
                continue
            
            # 过滤模块
            if module and meta.module != module:
                continue
            
            result.append(meta)
        
        # 按优先级排序
        result.sort(key=lambda m: m.priority)
        
        return [m.tool for m in result]
    
    def get_tool_names(
        self,
        categories: List[ToolCategory] = None,
        for_sub_agent: bool = None
    ) -> List[str]:
        """获取工具名称列表"""
        tools = self.get_tools(categories=categories, for_sub_agent=for_sub_agent)
        return [getattr(t, 'name', getattr(t, '__name__', str(id(t)))) for t in tools]
    
    def get_meta(self, name: str) -> Optional[ToolMeta]:
        """获取工具元数据"""
        return self._tools.get(name)
    
    def get_all_categories(self) -> List[ToolCategory]:
        """获取有工具的分类列表"""
        return [cat for cat, names in self._category_index.items() if names]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取注册统计信息"""
        return {
            "total_tools": len(self._tools),
            "by_category": {
                cat.value: len(names) 
                for cat, names in self._category_index.items() 
                if names
            },
            "by_module": {
                module: len(names)
                for module, names in self._module_index.items()
            },
            "loaded_modules": list(self._loaded_modules)
        }
    
    def mark_module_loaded(self, module: str):
        """标记模块已加载"""
        self._loaded_modules.add(module)
    
    def is_module_loaded(self, module: str) -> bool:
        """检查模块是否已加载"""
        return module in self._loaded_modules
    
    def enable_tool(self, name: str) -> bool:
        """启用工具"""
        if name in self._tools:
            self._tools[name].enabled = True
            return True
        return False
    
    def disable_tool(self, name: str) -> bool:
        """禁用工具"""
        if name in self._tools:
            self._tools[name].enabled = False
            return True
        return False
    
    def clear(self):
        """清空所有注册（主要用于测试）"""
        self._tools.clear()
        for cat in self._category_index:
            self._category_index[cat].clear()
        self._module_index.clear()
        self._loaded_modules.clear()
        logger.info("[ToolRegistry] 已清空所有注册")


# 全局注册中心实例
registry = ToolRegistry()


# ==================== 便捷函数 ====================

def register_tool(
    tool: Any,
    category: ToolCategory = ToolCategory.BASE,
    for_sub_agent: bool = True,
    priority: int = 100,
    **kwargs
) -> Any:
    """
    便捷注册函数
    
    用法:
        @tool
        def my_tool():
            pass
        
        register_tool(my_tool, category=ToolCategory.MEMORY)
    """
    return registry.register(
        tool,
        category=category,
        for_sub_agent=for_sub_agent,
        priority=priority,
        **kwargs
    )


def get_all_tools(for_sub_agent: bool = None) -> List[Any]:
    """获取所有工具"""
    return registry.get_tools(for_sub_agent=for_sub_agent)


def get_tools_by_category(category: ToolCategory, for_sub_agent: bool = None) -> List[Any]:
    """按分类获取工具"""
    return registry.get_tools(categories=[category], for_sub_agent=for_sub_agent)


# ==================== 导出 ====================

__all__ = [
    'ToolRegistry',
    'ToolCategory',
    'ToolMeta',
    'registry',
    'register_tool',
    'get_all_tools',
    'get_tools_by_category'
]
