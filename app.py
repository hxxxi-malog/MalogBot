"""
Flask应用主入口

统一使用ChatService处理对话：
- 支持流式和非流式输出
- 支持工具调用
- 支持命令确认机制（所有执行类命令需要用户确认）
- 支持会话管理（创建、删除、切换）
"""
import uuid
import json
import os
import asyncio

from flask import Flask, render_template, request, jsonify, session, Response
from werkzeug.utils import secure_filename

from config import Config
from services.chat_service import chat_service
from services.knowledge_base_service import knowledge_base_service
from services.document_service import document_service

# 创建Flask应用
app = Flask(__name__)
app.config.from_object(Config)

# 设置Secret Key（用于session）
app.secret_key = Config.SECRET_KEY


def get_session_id():
    """获取或创建会话ID"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


# ==================== 会话管理 API ====================

@app.route('/sessions', methods=['GET'])
def get_sessions():
    """
    获取所有会话列表
    
    返回：
    - sessions: 会话列表
    - current_session_id: 当前会话ID（Flask session中存储的ID）
    """
    try:
        # 获取当前 Flask session 中的 session_id（不自动创建）
        current_session_id = session.get('session_id', None)
        
        sessions = chat_service.get_all_sessions()
        
        return jsonify({
            'sessions': sessions,
            'current_session_id': current_session_id
        })
    except Exception as e:
        return jsonify({
            'error': f'获取会话列表失败: {str(e)}'
        }), 500


@app.route('/sessions/new', methods=['POST'])
def new_session():
    """
    创建新会话
    
    返回：
    - session_id: 新会话的ID
    """
    try:
        # 创建新会话
        new_session_id = chat_service.create_session()
        
        # 切换到新会话
        session['session_id'] = new_session_id
        
        return jsonify({
            'status': 'ok',
            'session_id': new_session_id,
            'message': '新会话已创建'
        })
    except Exception as e:
        return jsonify({
            'error': f'创建会话失败: {str(e)}'
        }), 500


@app.route('/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """
    删除会话
    
    Args:
        session_id: 要删除的会话ID
        
    返回：
    - status: 操作状态
    """
    try:
        # 不允许删除当前会话，需要先切换
        current_session_id = get_session_id()
        if session_id == current_session_id:
            return jsonify({
                'error': '无法删除当前会话，请先切换到其他会话'
            }), 400
        
        # 删除会话
        success = chat_service.delete_session(session_id)
        
        if success:
            return jsonify({
                'status': 'ok',
                'message': '会话已删除'
            })
        else:
            return jsonify({
                'error': '会话不存在'
            }), 404
    except Exception as e:
        return jsonify({
            'error': f'删除会话失败: {str(e)}'
        }), 500


@app.route('/sessions/<session_id>/switch', methods=['POST'])
def switch_session(session_id: str):
    """
    切换到指定会话
    
    Args:
        session_id: 目标会话ID
        
    返回：
    - status: 操作状态
    - session_id: 当前会话ID
    """
    try:
        # 确保会话存在
        session_info = chat_service.get_session_info(session_id)
        
        if not session_info:
            # 如果会话不存在，创建一个新的
            chat_service.create_session()
            # 使用传入的 session_id
            session['session_id'] = session_id
        else:
            # 切换到已存在的会话
            session['session_id'] = session_id
        
        return jsonify({
            'status': 'ok',
            'session_id': session_id,
            'session_info': session_info
        })
    except Exception as e:
        return jsonify({
            'error': f'切换会话失败: {str(e)}'
        }), 500


@app.route('/sessions/<session_id>/info', methods=['GET'])
def get_session_detail(session_id: str):
    """
    获取会话详情
    
    Args:
        session_id: 会话ID
        
    返回：
    - session_info: 会话信息
    - messages: 消息历史
    """
    try:
        session_info = chat_service.get_session_info(session_id)
        
        if not session_info:
            return jsonify({
                'error': '会话不存在'
            }), 404
        
        messages = chat_service.get_history(session_id)
        
        return jsonify({
            'session_info': session_info,
            'messages': messages
        })
    except Exception as e:
        return jsonify({
            'error': f'获取会话详情失败: {str(e)}'
        }), 500


# ==================== 联网搜索设置 API ====================

@app.route('/web-search/status', methods=['GET'])
def get_web_search_status():
    """
    获取当前会话的联网搜索状态
    
    返回：
    - enabled: 是否启用联网搜索
    - session_id: 当前会话ID
    """
    try:
        session_id = get_session_id()
        enabled = chat_service.get_web_search_status(session_id)
        
        return jsonify({
            'enabled': enabled,
            'session_id': session_id
        })
    except Exception as e:
        return jsonify({
            'error': f'获取联网搜索状态失败: {str(e)}'
        }), 500


@app.route('/web-search/toggle', methods=['POST'])
def toggle_web_search():
    """
    切换联网搜索开关
    
    请求体：
    - enabled: 是否启用联网搜索（boolean）
    
    返回：
    - enabled: 新的状态
    - session_id: 当前会话ID
    """
    try:
        data = request.json
        enabled = data.get('enabled', False)
        
        session_id = get_session_id()
        
        # 设置联网搜索状态
        chat_service.set_web_search_enabled(session_id, enabled)
        
        return jsonify({
            'enabled': enabled,
            'session_id': session_id,
            'message': f'联网搜索已{"开启" if enabled else "关闭"}'
        })
    except Exception as e:
        return jsonify({
            'error': f'切换联网搜索失败: {str(e)}'
        }), 500


# ==================== 对话 API ====================

@app.route('/chat', methods=['POST'])
def chat():
    """
    处理聊天请求（非流式）
    
    返回：
    - type: "response" | "confirmation_required" | "error"
    - output: 助手回复（正常情况）
    - command: 需要确认的命令
    - operation: 操作类型
    - working_dir: 执行路径
    """
    try:
        data = request.json
        user_input = data.get('message', '')

        if not user_input:
            return jsonify({'error': '消息不能为空'}), 400

        session_id = get_session_id()

        # 调用ChatService处理对话
        result = chat_service.chat(user_input, session_id)

        # 根据返回类型处理
        if result['type'] == 'confirmation_required':
            return jsonify({
                'type': 'confirmation_required',
                'command': result['command'],
                'command_type': result.get('command_type', 'execute'),
                'operation': result.get('operation', '执行命令'),
                'working_dir': result.get('working_dir', ''),
                'is_dangerous': result.get('is_dangerous', False),
                'reason': result.get('reason', ''),
                'message': result.get('message', '需要用户确认'),
                'session_id': result['session_id']
            })

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'type': 'error',
            'output': f'服务器错误: {str(e)}'
        }), 500


@app.route('/chat/stream', methods=['POST'])
def chat_stream():
    """
    流式聊天接口
    使用Server-Sent Events (SSE) 返回流式数据
    """
    data = request.json
    user_input = data.get('message', '')
    session_id = get_session_id()

    def generate():
        try:
            if not user_input:
                yield f"data: {json.dumps({'type': 'error', 'content': '消息不能为空'}, ensure_ascii=False)}\n\n"
                return

            # 调用流式服务
            for chunk in chat_service.chat_stream(user_input, session_id):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'服务器错误: {str(e)}'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/confirm', methods=['POST'])
def confirm_command():
    """
    确认并执行命令（非流式）
    
    请求体：
    - command: 要执行的命令
    - user_message: 用户原始消息（可选，用于继续对话）
    """
    try:
        data = request.json
        command = data.get('command', '')
        user_message = data.get('user_message', '')

        if not command:
            return jsonify({'error': '命令不能为空'}), 400

        session_id = get_session_id()

        # 执行确认的命令
        result = chat_service.confirm_command(
            command,
            session_id,
            user_message
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({
            'type': 'error',
            'output': f'执行命令失败: {str(e)}'
        }), 500


@app.route('/confirm/stream', methods=['POST'])
def confirm_command_stream():
    """
    确认并执行命令（流式）
    
    请求体：
    - command: 要执行的命令
    - user_message: 用户原始消息（可选，用于继续对话）
    """
    data = request.json
    command = data.get('command', '')
    user_message = data.get('user_message', '')
    session_id = get_session_id()

    def generate():
        try:
            if not command:
                yield f"data: {json.dumps({'type': 'error', 'content': '命令不能为空'}, ensure_ascii=False)}\n\n"
                return

            # 流式执行确认的命令
            for chunk in chat_service.confirm_command_stream(
                    command,
                    session_id,
                    user_message
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'执行命令失败: {str(e)}'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/cancel', methods=['POST'])
def cancel_command():
    """
    取消命令执行，返回上下文给 LLM 继续处理
    
    请求体：
    - command: 用户取消的命令
    - user_message: 用户原始消息（可选，用于继续对话）
    """
    data = request.json
    command = data.get('command', '')
    user_message = data.get('user_message', '')
    session_id = get_session_id()

    def generate():
        try:
            if not command:
                yield f"data: {json.dumps({'type': 'done', 'content': '用户已取消'}, ensure_ascii=False)}\n\n"
                return

            # 流式处理取消的命令
            for chunk in chat_service.cancel_command_stream(
                    command,
                    session_id,
                    user_message
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'处理取消失败: {str(e)}'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route('/history', methods=['GET'])
def get_history():
    """获取对话历史"""
    session_id = get_session_id()
    history = chat_service.get_history(session_id)

    return jsonify({
        'messages': history,
        'session_id': session_id
    })


@app.route('/stop', methods=['POST'])
def stop_generation():
    """
    取消当前流式输出
    
    用户可以在模型输出期间调用此接口取消输出
    """
    session_id = get_session_id()
    chat_service.request_cancel(session_id)
    
    return jsonify({
        'status': 'ok',
        'message': '已发送取消请求'
    })


@app.route('/reset', methods=['POST'])
def reset():
    """
    重置当前会话（清空消息历史）
    
    注意：这不会删除会话，只是清空消息历史
    """
    session_id = get_session_id()
    chat_service.clear_history(session_id)

    return jsonify({
        'status': 'ok',
        'message': '会话历史已清空'
    })


# ==================== 递归限制继续执行 API ====================

@app.route('/continue', methods=['POST'])
def continue_task():
    """
    继续执行因递归限制暂停的任务（非流式）
    
    当任务执行达到步数限制时，用户可以选择继续执行。
    这将重置计数器并继续之前的任务。
    
    返回：
    - type: "response" | "recursion_limit_reached" | "error"
    - output: 助手回复
    """
    try:
        session_id = get_session_id()
        result = chat_service.continue_task(session_id)
        
        if result['type'] == 'confirmation_required':
            return jsonify({
                'type': 'confirmation_required',
                'command': result['command'],
                'command_type': result.get('command_type', 'execute'),
                'operation': result.get('operation', '执行命令'),
                'working_dir': result.get('working_dir', ''),
                'is_dangerous': result.get('is_dangerous', False),
                'reason': result.get('reason', ''),
                'message': result.get('message', '需要用户确认'),
                'session_id': result['session_id']
            })
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'type': 'error',
            'output': f'继续执行失败: {str(e)}'
        }), 500


@app.route('/continue/stream', methods=['POST'])
def continue_task_stream():
    """
    继续执行因递归限制暂停的任务（流式）
    
    使用 Server-Sent Events (SSE) 返回流式数据
    """
    session_id = get_session_id()

    def generate():
        try:
            for chunk in chat_service.continue_task_stream(session_id):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': f'继续执行失败: {str(e)}'}, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


# ==================== 知识库管理 API ====================

@app.route('/knowledge-bases', methods=['GET'])
def list_knowledge_bases():
    """
    获取所有知识库列表
    """
    try:
        kbs = knowledge_base_service.list_knowledge_bases()
        return jsonify({
            'knowledge_bases': kbs
        })
    except Exception as e:
        return jsonify({
            'error': f'获取知识库列表失败: {str(e)}'
        }), 500


@app.route('/knowledge-bases', methods=['POST'])
def create_knowledge_base():
    """
    创建知识库
    
    请求体：
    - name: 知识库名称
    - description: 描述（可选）
    """
    try:
        data = request.json
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        if not name:
            return jsonify({'error': '知识库名称不能为空'}), 400
        
        kb = knowledge_base_service.create_knowledge_base(name, description)
        return jsonify({
            'status': 'ok',
            'knowledge_base': kb
        })
    except Exception as e:
        return jsonify({
            'error': f'创建知识库失败: {str(e)}'
        }), 500


@app.route('/knowledge-bases/<kb_id>', methods=['GET'])
def get_knowledge_base(kb_id: str):
    """
    获取知识库详情
    """
    try:
        kb = knowledge_base_service.get_knowledge_base(kb_id)
        if not kb:
            return jsonify({'error': '知识库不存在'}), 404
        
        return jsonify({
            'knowledge_base': kb
        })
    except Exception as e:
        return jsonify({
            'error': f'获取知识库详情失败: {str(e)}'
        }), 500


@app.route('/knowledge-bases/<kb_id>', methods=['DELETE'])
def delete_knowledge_base(kb_id: str):
    """
    删除知识库
    """
    try:
        success = knowledge_base_service.delete_knowledge_base(kb_id)
        if not success:
            return jsonify({'error': '知识库不存在'}), 404
        
        return jsonify({
            'status': 'ok',
            'message': '知识库已删除'
        })
    except Exception as e:
        return jsonify({
            'error': f'删除知识库失败: {str(e)}'
        }), 500


@app.route('/knowledge-bases/<kb_id>/documents', methods=['GET'])
def list_documents(kb_id: str):
    """
    获取知识库下的文档列表
    """
    try:
        docs = knowledge_base_service.get_documents(kb_id)
        return jsonify({
            'documents': docs
        })
    except Exception as e:
        return jsonify({
            'error': f'获取文档列表失败: {str(e)}'
        }), 500


@app.route('/knowledge-bases/<kb_id>/documents', methods=['POST'])
def upload_document(kb_id: str):
    """
    上传文档到知识库
    
    支持的文件类型：.txt, .md, .json, .csv, .pdf, .doc, .docx
    """
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'error': '没有上传文件'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': '没有选择文件'}), 400
        
        # 检查文件类型
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()
        
        if file_ext not in document_service.get_supported_file_types():
            return jsonify({
                'error': f'不支持的文件类型: {file_ext}。支持的类型: {document_service.get_supported_file_types()}'
            }), 400
        
        # 检查文件大小
        file.seek(0, 2)  # 移动到文件末尾
        file_size = file.tell()
        file.seek(0)  # 重置到开头
        
        if file_size > Config.MAX_FILE_SIZE:
            return jsonify({
                'error': f'文件大小超过限制 ({Config.MAX_FILE_SIZE / 1024 / 1024}MB)'
            }), 400
        
        # 检查知识库是否存在
        kb = knowledge_base_service.get_knowledge_base(kb_id)
        if not kb:
            return jsonify({'error': '知识库不存在'}), 404
        
        # 保存文件
        upload_dir = os.path.join(Config.UPLOAD_FOLDER, str(kb_id))
        os.makedirs(upload_dir, exist_ok=True)
        
        # 使用UUID作为文件名，避免冲突
        file_id = str(uuid.uuid4())
        file_path = os.path.join(upload_dir, f"{file_id}{file_ext}")
        file.save(file_path)
        
        # 异步处理文档
        async def process_doc():
            return await document_service.process_document(file_path, filename, kb_id)
        
        # 运行异步处理
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(process_doc())
        except Exception as e:
            # 数据库操作异常
            return jsonify({
                'error': f'文档处理失败: {str(e)}'
            }), 500
        
        if result.get('status') == 'completed':
            return jsonify({
                'status': 'ok',
                'message': '文档上传成功',
                'document_id': result.get('document_id'),
                'chunk_count': result.get('chunk_count')
            })
        else:
            return jsonify({
                'error': result.get('error', '文档处理失败')
            }), 500
        
    except Exception as e:
        return jsonify({
            'error': f'上传文档失败: {str(e)}'
        }), 500


@app.route('/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id: str):
    """
    删除文档
    """
    try:
        success = knowledge_base_service.delete_document(doc_id)
        if not success:
            return jsonify({'error': '文档不存在'}), 404
        
        return jsonify({
            'status': 'ok',
            'message': '文档已删除'
        })
    except Exception as e:
        return jsonify({
            'error': f'删除文档失败: {str(e)}'
        }), 500


# ==================== 会话知识库设置 API ====================

@app.route('/sessions/<session_id>/knowledge-base', methods=['GET'])
def get_session_knowledge_base(session_id: str):
    """
    获取会话当前选中的知识库
    """
    try:
        kb_id = chat_service.get_knowledge_base_id(session_id)
        
        kb_info = None
        if kb_id:
            kb_info = knowledge_base_service.get_knowledge_base(kb_id)
        
        return jsonify({
            'knowledge_base_id': kb_id,
            'knowledge_base': kb_info
        })
    except Exception as e:
        return jsonify({
            'error': f'获取知识库设置失败: {str(e)}'
        }), 500


@app.route('/sessions/<session_id>/knowledge-base', methods=['PUT'])
def set_session_knowledge_base(session_id: str):
    """
    设置会话的知识库
    
    请求体：
    - knowledge_base_id: 知识库ID（null表示不使用知识库）
    """
    try:
        data = request.json
        kb_id = data.get('knowledge_base_id')  # 可以是 None
        
        # 验证知识库是否存在（如果不是 None）
        if kb_id:
            kb = knowledge_base_service.get_knowledge_base(kb_id)
            if not kb:
                return jsonify({'error': '知识库不存在'}), 404
        
        chat_service.set_knowledge_base_id(session_id, kb_id)
        
        return jsonify({
            'status': 'ok',
            'knowledge_base_id': kb_id,
            'message': '知识库设置已更新'
        })
    except Exception as e:
        return jsonify({
            'error': f'设置知识库失败: {str(e)}'
        }), 500


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
