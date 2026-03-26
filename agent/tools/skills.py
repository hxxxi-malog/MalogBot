"""
Skills 工具模块

提供技能发现和加载功能，让 LLM 可以使用预定义的技能。
"""
import os
import json
import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path
from functools import lru_cache

from langchain_core.tools import tool


# Skills 根目录
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


def parse_skill_frontmatter(content: str) -> Dict[str, Any]:
    """
    解析 SKILL.md 文件的 YAML frontmatter
    
    Args:
        content: SKILL.md 文件内容
        
    Returns:
        包含 metadata 和 body 的字典
    """
    if not content.startswith('---'):
        return {"metadata": {}, "body": content}
    
    # 查找第二个 ---
    end_idx = content.find('---', 3)
    if end_idx == -1:
        return {"metadata": {}, "body": content}
    
    frontmatter = content[3:end_idx].strip()
    body = content[end_idx + 3:].strip()
    
    try:
        metadata = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        metadata = {}
    
    return {"metadata": metadata or {}, "body": body}


def get_skill_path(skill_name: str) -> Optional[Path]:
    """
    获取技能目录路径
    
    Args:
        skill_name: 技能名称
        
    Returns:
        技能目录路径，不存在则返回 None
    """
    skill_path = SKILLS_DIR / skill_name
    if skill_path.exists() and skill_path.is_dir():
        return skill_path
    return None


def list_available_skills() -> List[Dict[str, str]]:
    """
    列出所有可用的技能
    
    Returns:
        技能列表，每个技能包含 name, description, path
    """
    skills = []
    
    if not SKILLS_DIR.exists():
        return skills
    
    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                try:
                    content = skill_file.read_text(encoding='utf-8')
                    parsed = parse_skill_frontmatter(content)
                    metadata = parsed.get("metadata", {})
                    
                    skills.append({
                        "name": metadata.get("name", skill_dir.name),
                        "description": metadata.get("description", "无描述"),
                        "path": str(skill_dir)
                    })
                except Exception:
                    skills.append({
                        "name": skill_dir.name,
                        "description": "无法读取技能描述",
                        "path": str(skill_dir)
                    })
    
    return skills


# ==================== LangChain Tools ====================

@tool
def list_skills() -> str:
    """
    列出所有可用的技能。
    
    返回技能名称、描述和路径，让用户了解可以使用哪些技能。
    
    Returns:
        技能列表的 JSON 字符串
    """
    skills = list_available_skills()
    
    if not skills:
        return json.dumps({
            "success": False,
            "message": "没有找到可用的技能。请确保 skills 目录存在且包含 SKILL.md 文件。"
        }, ensure_ascii=False)
    
    result = {
        "success": True,
        "count": len(skills),
        "skills": skills
    }
    
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_skill(skill_name: str) -> str:
    """
    获取指定技能的完整内容。
    
    读取技能的 SKILL.md 文件，返回技能的详细说明和指导。
    在使用技能前，应先调用此函数了解技能的具体用法。
    
    Args:
        skill_name: 技能名称，例如 "postgres-performance-diagnosis"
        
    Returns:
        技能内容的字符串，包含完整的使用说明
    """
    skill_path = get_skill_path(skill_name)
    
    if not skill_path:
        available = [s["name"] for s in list_available_skills()]
        return json.dumps({
            "success": False,
            "message": f"技能 '{skill_name}' 不存在。",
            "available_skills": available
        }, ensure_ascii=False)
    
    skill_file = skill_path / "SKILL.md"
    
    if not skill_file.exists():
        return json.dumps({
            "success": False,
            "message": f"技能目录存在但缺少 SKILL.md 文件: {skill_path}"
        }, ensure_ascii=False)
    
    try:
        content = skill_file.read_text(encoding='utf-8')
        parsed = parse_skill_frontmatter(content)
        
        return json.dumps({
            "success": True,
            "skill_name": skill_name,
            "metadata": parsed["metadata"],
            "content": parsed["body"],
            "path": str(skill_path)
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"读取技能文件失败: {str(e)}"
        }, ensure_ascii=False)


@tool
def get_skill_reference(skill_name: str, reference_file: str = "reference.md") -> str:
    """
    获取技能的参考文档。
    
    某些技能包含详细的参考文档（如 SQL 查询、API 文档等），
    此函数用于获取这些额外的参考资料。
    
    Args:
        skill_name: 技能名称
        reference_file: 参考文件名，默认为 "reference.md"
        
    Returns:
        参考文档的内容
    """
    skill_path = get_skill_path(skill_name)
    
    if not skill_path:
        return json.dumps({
            "success": False,
            "message": f"技能 '{skill_name}' 不存在。"
        }, ensure_ascii=False)
    
    ref_file = skill_path / reference_file
    
    if not ref_file.exists():
        # 列出可用的参考文件
        available_files = []
        for f in skill_path.iterdir():
            if f.is_file() and f.suffix == '.md':
                available_files.append(f.name)
        
        return json.dumps({
            "success": False,
            "message": f"参考文件 '{reference_file}' 不存在。",
            "available_files": available_files
        }, ensure_ascii=False)
    
    try:
        content = ref_file.read_text(encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "skill_name": skill_name,
            "file_name": reference_file,
            "content": content
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"读取参考文件失败: {str(e)}"
        }, ensure_ascii=False)


@tool
def get_skill_template(skill_name: str, template_file: str = "report_template.md") -> str:
    """
    获取技能的输出模板。
    
    某些技能定义了输出格式模板，此函数用于获取模板内容，
    帮助按照标准格式生成输出。
    
    Args:
        skill_name: 技能名称
        template_file: 模板文件名，默认为 "report_template.md"
        
    Returns:
        模板内容
    """
    return get_skill_reference(skill_name, template_file)


# 导出工具列表
SKILLS_TOOLS = [
    list_skills,
    get_skill,
    get_skill_reference,
    get_skill_template
]

__all__ = [
    'list_skills',
    'get_skill',
    'get_skill_reference',
    'get_skill_template',
    'SKILLS_TOOLS',
    'list_available_skills',
    'get_skill_path',
    'parse_skill_frontmatter'
]
