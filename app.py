"""
Flask应用主入口

统一使用ChatService处理对话：
- 支持流式和非流式输出
- 支持工具调用
- 支持命令确认机制（所有执行类命令需要用户确认）
- 支持会话管理
"""
import uuid
import json

from flask import Flask, render_template, request, jsonify, session, Response

from config import Config
from services.chat_service import chat_service

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
    """重置对话"""
    session_id = get_session_id()
    chat_service.clear_history(session_id)
    session.clear()

    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
