"""
MCP 服务 API 接口

提供前端调用的 REST API，支持：
- 服务 CRUD 操作
- 工具发现和刷新
- 配置导入导出
- 服务状态管理
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional

from flask import Blueprint, request, jsonify

from mcp.registry import mcp_registry
from mcp.tools import mcp_tools_manager, get_cached_mcp_tools

logger = logging.getLogger(__name__)

# 创建 Blueprint
mcp_bp = Blueprint('mcp', __name__, url_prefix='/mcp')


def run_async(coro):
    """在同步上下文中运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)


# ==================== 服务管理 API ====================

@mcp_bp.route('/servers', methods=['GET'])
def list_servers():
    """
    获取所有 MCP 服务列表
    
    Query Parameters:
        enabled_only: 是否只返回启用的服务（默认 false）
        category: 按分类过滤（可选）
    
    Returns:
        servers: 服务列表
        stats: 统计信息
    """
    try:
        # 确保初始化
        mcp_registry.initialize()
        
        enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'
        category = request.args.get('category', None)
        
        servers = mcp_registry.list_services(
            enabled_only=enabled_only,
            category=category
        )
        stats = mcp_registry.get_stats()
        
        return jsonify({
            'status': 'ok',
            'servers': servers,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取服务列表失败: {e}")
        return jsonify({
            'error': f'获取服务列表失败: {str(e)}'
        }), 500


@mcp_bp.route('/servers', methods=['POST'])
def register_server():
    """
    注册新的 MCP 服务
    
    Request Body:
        name: 服务名称（唯一标识，必填）
        transport_type: 传输类型（stdio/sse/http，默认 stdio）
        command: 启动命令（stdio 模式）
        args: 命令参数（数组）
        env: 环境变量（对象）
        url: 服务 URL（sse/http 模式）
        headers: HTTP 头（对象）
        display_name: 显示名称
        description: 描述
        category: 分类
        tags: 标签（数组）
        auto_start: 是否自动启动（默认 true）
        enabled: 是否启用（默认 true）
    
    Returns:
        status: 状态
        message: 消息
        server: 创建的服务信息
    """
    try:
        data = request.json
        
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': '服务名称不能为空'}), 400
        
        # 验证必填字段
        transport_type = data.get('transport_type', 'stdio')
        if transport_type == 'stdio':
            if not data.get('command'):
                return jsonify({'error': 'stdio 模式需要提供 command'}), 400
        elif transport_type in ('sse', 'http'):
            if not data.get('url'):
                return jsonify({'error': f'{transport_type} 模式需要提供 url'}), 400
        
        success, msg, server = mcp_registry.register_service(
            name=name,
            transport_type=transport_type,
            command=data.get('command'),
            args=data.get('args'),
            env=data.get('env'),
            url=data.get('url'),
            headers=data.get('headers'),
            display_name=data.get('display_name'),
            description=data.get('description'),
            category=data.get('category'),
            tags=data.get('tags'),
            auto_start=data.get('auto_start', True),
            enabled=data.get('enabled', True)
        )
        
        if success:
            logger.info(f"[MCP API] 注册服务成功: {name}")
            return jsonify({
                'status': 'ok',
                'message': msg,
                'server': server
            })
        else:
            return jsonify({'error': msg}), 400
            
    except Exception as e:
        logger.error(f"[MCP API] 注册服务失败: {e}")
        return jsonify({
            'error': f'注册服务失败: {str(e)}'
        }), 500


@mcp_bp.route('/servers/<name>', methods=['GET'])
def get_server(name: str):
    """
    获取单个服务详情
    
    Args:
        name: 服务名称
    
    Returns:
        server: 服务信息
    """
    try:
        server = mcp_registry.get_service(name)
        
        if not server:
            return jsonify({'error': f'服务 "{name}" 不存在'}), 404
        
        return jsonify({
            'status': 'ok',
            'server': server
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取服务详情失败: {e}")
        return jsonify({
            'error': f'获取服务详情失败: {str(e)}'
        }), 500


@mcp_bp.route('/servers/<name>', methods=['PUT'])
def update_server(name: str):
    """
    更新服务配置
    
    Args:
        name: 服务名称
    
    Request Body:
        要更新的字段（见 register_server）
    
    Returns:
        status: 状态
        message: 消息
        server: 更新后的服务信息
    """
    try:
        data = request.json
        
        success, msg, server = mcp_registry.update_service(name, **data)
        
        if success:
            logger.info(f"[MCP API] 更新服务成功: {name}")
            return jsonify({
                'status': 'ok',
                'message': msg,
                'server': server
            })
        else:
            return jsonify({'error': msg}), 400
            
    except Exception as e:
        logger.error(f"[MCP API] 更新服务失败: {e}")
        return jsonify({
            'error': f'更新服务失败: {str(e)}'
        }), 500


@mcp_bp.route('/servers/<name>', methods=['DELETE'])
def delete_server(name: str):
    """
    删除服务
    
    Args:
        name: 服务名称
    
    Returns:
        status: 状态
        message: 消息
    """
    try:
        success, msg = mcp_registry.delete_service(name)
        
        if success:
            logger.info(f"[MCP API] 删除服务成功: {name}")
            return jsonify({
                'status': 'ok',
                'message': msg
            })
        else:
            return jsonify({'error': msg}), 400
            
    except Exception as e:
        logger.error(f"[MCP API] 删除服务失败: {e}")
        return jsonify({
            'error': f'删除服务失败: {str(e)}'
        }), 500


# ==================== 服务状态 API ====================

@mcp_bp.route('/servers/<name>/enable', methods=['POST'])
def enable_server(name: str):
    """启用服务"""
    try:
        success, msg = mcp_registry.enable_service(name)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': f'服务 "{name}" 已启用'
            })
        else:
            return jsonify({'error': msg}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@mcp_bp.route('/servers/<name>/disable', methods=['POST'])
def disable_server(name: str):
    """禁用服务"""
    try:
        success, msg = mcp_registry.disable_service(name)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': f'服务 "{name}" 已禁用'
            })
        else:
            return jsonify({'error': msg}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@mcp_bp.route('/servers/<name>/refresh', methods=['POST'])
def refresh_server(name: str):
    """
    刷新单个服务（重新发现工具）
    
    Args:
        name: 服务名称
    
    Returns:
        status: 状态
        message: 消息
        tools: 发现的工具列表
    """
    try:
        async def do_refresh():
            return await mcp_registry.refresh_service(name)
        
        success, msg = run_async(do_refresh())
        
        # 获取更新后的服务信息
        server = mcp_registry.get_service(name)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': msg,
                'server': server
            })
        else:
            return jsonify({'error': msg}), 400
            
    except Exception as e:
        logger.error(f"[MCP API] 刷新服务失败: {e}")
        return jsonify({
            'error': f'刷新服务失败: {str(e)}'
        }), 500


@mcp_bp.route('/refresh-all', methods=['POST'])
def refresh_all_servers():
    """
    刷新所有启用的服务
    
    Returns:
        status: 状态
        results: 刷新结果
    """
    try:
        async def do_refresh():
            return await mcp_registry.refresh_all_services()
        
        results = run_async(do_refresh())
        
        # 转换结果格式
        refresh_results = {}
        for name, (success, msg) in results.items():
            refresh_results[name] = {
                'success': success,
                'message': msg
            }
        
        # 同步工具管理器
        mcp_tools_manager.sync_from_registry()
        
        return jsonify({
            'status': 'ok',
            'results': refresh_results,
            'stats': mcp_registry.get_stats()
        })
        
    except Exception as e:
        logger.error(f"[MCP API] 刷新所有服务失败: {e}")
        return jsonify({
            'error': f'刷新服务失败: {str(e)}'
        }), 500


# ==================== 工具管理 API ====================

@mcp_bp.route('/tools', methods=['GET'])
def list_tools():
    """
    获取所有工具列表
    
    Query Parameters:
        server: 按服务名过滤（可选）
        category: 按分类过滤（可选）
    
    Returns:
        tools: 工具列表
        count: 工具数量
    """
    try:
        mcp_registry.initialize()
        mcp_tools_manager.sync_from_registry()
        
        server_name = request.args.get('server', None)
        category = request.args.get('category', None)
        
        if server_name:
            tools = mcp_registry.get_tools_by_server(server_name)
        elif category:
            tools = mcp_registry.get_tools_by_category(category)
        else:
            tools = mcp_registry.get_all_tools()
        
        # 转换为字典格式
        tools_list = [
            {
                'name': t.name,
                'description': t.description,
                'input_schema': t.input_schema,
                'server_name': t.server_name
            }
            for t in tools
        ]
        
        return jsonify({
            'status': 'ok',
            'tools': tools_list,
            'count': len(tools_list)
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取工具列表失败: {e}")
        return jsonify({
            'error': f'获取工具列表失败: {str(e)}'
        }), 500


@mcp_bp.route('/tools/langchain', methods=['GET'])
def get_langchain_tools():
    """
    获取 LangChain 格式的工具列表
    
    用于 Agent 直接加载使用
    
    Returns:
        tools: 工具名称和描述列表
        count: 工具数量
    """
    try:
        tools = get_cached_mcp_tools()
        
        tools_info = [
            {
                'name': t.name,
                'description': t.description
            }
            for t in tools
        ]
        
        return jsonify({
            'status': 'ok',
            'tools': tools_info,
            'count': len(tools_info)
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取 LangChain 工具失败: {e}")
        return jsonify({
            'error': f'获取工具失败: {str(e)}'
        }), 500


# ==================== 配置管理 API ====================

@mcp_bp.route('/config/export', methods=['GET'])
def export_config():
    """
    导出服务配置
    
    导出为 mcp_servers_config.json 格式
    
    Returns:
        config: 配置对象
    """
    try:
        config = mcp_registry.export_config()
        
        return jsonify({
            'status': 'ok',
            'config': config
        })
    except Exception as e:
        logger.error(f"[MCP API] 导出配置失败: {e}")
        return jsonify({
            'error': f'导出配置失败: {str(e)}'
        }), 500


@mcp_bp.route('/config/import', methods=['POST'])
def import_config():
    """
    导入服务配置
    
    从 mcp_servers_config.json 格式导入
    
    Request Body:
        config: 配置对象
        overwrite: 是否覆盖已存在的服务（默认 false）
    
    Returns:
        success_count: 成功导入数量
        fail_count: 失败数量
    """
    try:
        data = request.json
        config = data.get('config', {})
        overwrite = data.get('overwrite', False)
        
        # 如果需要覆盖，先删除现有服务
        if overwrite:
            servers = mcp_registry.list_services()
            for server in servers:
                mcp_registry.delete_service(server['name'])
        
        success_count, fail_count = mcp_registry.import_config(config)
        
        return jsonify({
            'status': 'ok',
            'success_count': success_count,
            'fail_count': fail_count,
            'message': f'成功导入 {success_count} 个服务，失败 {fail_count} 个'
        })
    except Exception as e:
        logger.error(f"[MCP API] 导入配置失败: {e}")
        return jsonify({
            'error': f'导入配置失败: {str(e)}'
        }), 500


# ==================== 分类管理 API ====================

@mcp_bp.route('/categories', methods=['GET'])
def list_categories():
    """
    获取所有服务分类
    
    Returns:
        categories: 分类列表
    """
    try:
        servers = mcp_registry.list_services()
        
        # 提取所有分类
        categories = set()
        for server in servers:
            if server.get('category'):
                categories.add(server['category'])
        
        return jsonify({
            'status': 'ok',
            'categories': list(categories)
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取分类失败: {e}")
        return jsonify({
            'error': f'获取分类失败: {str(e)}'
        }), 500


# ==================== 统计信息 API ====================

@mcp_bp.route('/stats', methods=['GET'])
def get_stats():
    """
    获取统计信息
    
    Returns:
        stats: 统计数据
    """
    try:
        stats = mcp_registry.get_stats()
        
        return jsonify({
            'status': 'ok',
            'stats': stats
        })
    except Exception as e:
        logger.error(f"[MCP API] 获取统计信息失败: {e}")
        return jsonify({
            'error': f'获取统计信息失败: {str(e)}'
        }), 500


# ==================== 测试连接 API ====================

@mcp_bp.route('/servers/<name>/test', methods=['POST'])
def test_connection(name: str):
    """
    测试服务连接
    
    尝试连接服务并发现工具
    
    Args:
        name: 服务名称
    
    Returns:
        success: 是否成功
        message: 消息
        tools_count: 发现的工具数量
    """
    try:
        async def do_test():
            return await mcp_registry.discover_tools(name)
        
        success, msg, tools = run_async(do_test())
        
        return jsonify({
            'status': 'ok' if success else 'error',
            'success': success,
            'message': msg,
            'tools_count': len(tools) if success else 0
        })
    except Exception as e:
        logger.error(f"[MCP API] 测试连接失败: {e}")
        return jsonify({
            'status': 'error',
            'success': False,
            'message': str(e),
            'tools_count': 0
        }), 500


# 导出 Blueprint
__all__ = ['mcp_bp']