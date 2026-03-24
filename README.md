# MalogBot

一个基于Flask的AI对话机器人。

## 项目结构

```
MalogBot/
├── app.py              # 主应用入口
├── requirements.txt    # 项目依赖
├── .env               # 密钥配置 (不提交到git)
├── .env.example       # 密钥配置示例
├── static/            # 静态文件
├── templates/         # HTML模板
│   └── index.html     # 对话界面
└── .venv/             # 虚拟环境
```

## 快速开始

### 1. 创建虚拟环境

```bash
python -m venv .venv
```

### 2. 激活虚拟环境

```bash
# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置密钥

复制 `.env.example` 为 `.env`，并填入你的DeepSeek API密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```
DEEPSEEK_API_KEY=你的实际密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat
```

支持的模型：
- `deepseek-chat` - 通用对话模型
- `deepseek-coder` - 代码专用模型

### 5. 运行应用

```bash
python app.py
```

访问 http://127.0.0.1:5000 开始对话。

## 功能

- 流式响应（打字机效果）
- 简洁的对话界面
- 支持自定义API端点和模型
