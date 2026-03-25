"""
MCP 集成模块

提供 Model Context Protocol (MCP) 工具的集成支持
"""

from mcp.adapters import get_mcp_tools, get_web_search_tool

__all__ = ['get_mcp_tools', 'get_web_search_tool']
