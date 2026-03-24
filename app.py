from flask import Flask, render_template, request, Response, jsonify
from openai import OpenAI
from dotenv import load_dotenv
import os
import json

# 加载环境变量
load_dotenv()

app = Flask(__name__)

# 初始化DeepSeek客户端 (使用OpenAI兼容接口)
client = OpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
)

MODEL_NAME = os.getenv('MODEL_NAME', 'gpt-3.5-turbo')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天请求，返回流式响应"""
    try:
        data = request.json
        messages = data.get('messages', [])
        
        if not messages:
            return jsonify({'error': 'No messages provided'}), 400
        
        def generate():
            try:
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    stream=True
                )
                
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        yield f"data: {json.dumps({'content': content})}\n\n"
                
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
