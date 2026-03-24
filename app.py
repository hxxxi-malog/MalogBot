"""
Flask应用主入口

统一使用ChatService处理对话：
- 支持流式和非流式输出
- 支持工具调用
- 支持危险命令确认
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
    - type: "response" | "dangerous_command" | "error"
    - output: 助手回复（正常情况）
    - command: 危险命令（需要确认时）
    - reason: 危险原因
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
        if result['type'] == 'dangerous_command':
            return jsonify({
                'type': 'dangerous_command',
                'command': result['command'],
                'reason': result['reason'],
                'message': result['message'],
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
    确认并执行危险命令（非流式）
    
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
        result = chat_service.confirm_dangerous_command(
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
    确认并执行危险命令（流式）
    
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
            for chunk in chat_service.confirm_dangerous_command_stream(
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


@app.route('/history', methods=['GET'])
def get_history():
    """获取对话历史"""
    session_id = get_session_id()
    history = chat_service.get_history(session_id)

    return jsonify({
        'messages': history,
        'session_id': session_id
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
