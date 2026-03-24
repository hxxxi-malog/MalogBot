"""
Flask应用主入口

重构版本：
- 使用ChatService处理对话
- 支持危险命令确认
- 添加会话管理接口
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
    处理聊天请求
    
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
            # 返回危险命令确认请求
            return jsonify({
                'type': 'dangerous_command',
                'command': result['command'],
                'reason': result['reason'],
                'message': result['message'],
                'session_id': result['session_id']
            })
        
        # 正常响应或错误
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            'type': 'error',
            'output': f'服务器错误: {str(e)}'
        }), 500


@app.route('/confirm', methods=['POST'])
def confirm_command():
    """
    确认并执行危险命令
    
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
