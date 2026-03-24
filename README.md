# MalogBot

一个基于 Flask 和 LangChain 的智能 AI 助手，支持 Bash 命令执行和工具调用。

## 功能特性

- **智能对话** - 基于大语言模型的智能对话能力
- **流式响应** - 支持 token-by-token 的流式输出，打字机效果
- **Bash 工具** - AI 可以执行 Bash 命令帮助用户完成任务
- **命令确认机制** - 执行类命令需要用户确认，保障安全
- **危险命令检测** - 自动检测 sudo、rm 等危险操作并警告
- **会话管理** - 支持多会话和对话历史管理

## 项目结构

```
MalogBot/
├── app.py                  # Flask 应用主入口
├── config.py               # 配置管理模块
├── requirements.txt        # 项目依赖
├── .env                    # 环境变量配置（不提交到 git）
├── agent/                  # Agent 模块
│   ├── __init__.py
│   ├── llm.py              # LLM 客户端封装
│   ├── prompts.py          # 提示词模板
│   └── tools/              # 工具模块
│       ├── __init__.py
│       └── bash.py         # Bash 命令执行工具
├── services/               # 服务层
│   ├── __init__.py
│   └── chat_service.py     # 对话服务（支持流式/非流式）
├── models/                 # 数据模型
│   └── __init__.py
├── static/                 # 静态文件
├── templates/              # HTML 模板
│   └── index.html          # 对话界面
└── .venv/                  # 虚拟环境
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

### 4. 配置环境变量

创建 `.env` 文件并配置：

```bash
# LLM 配置
DEEPSEEK_API_KEY=你的实际密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat

# Flask 配置
SECRET_KEY=你的密钥
FLASK_DEBUG=True

# 工具配置
BASH_TIMEOUT=30
```

支持的模型：
- `deepseek-chat` - 通用对话模型（支持工具调用）
- `deepseek-coder` - 代码专用模型

### 5. 运行应用

```bash
python app.py
```

访问 http://127.0.0.1:5000 开始对话。

## API 接口

### 对话接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/chat` | POST | 非流式对话 |
| `/chat/stream` | POST | 流式对话（SSE） |
| `/history` | GET | 获取对话历史 |
| `/reset` | POST | 重置对话 |

### 命令确认接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/confirm` | POST | 确认执行命令（非流式） |
| `/confirm/stream` | POST | 确认执行命令（流式） |
| `/cancel` | POST | 取消命令执行 |

### 控制接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/stop` | POST | 取消当前流式输出 |

## 核心模块说明

### Agent 模块

- **llm.py** - 封装 LangChain 的 ChatOpenAI，连接 DeepSeek API
- **prompts.py** - 定义 AI 助手的系统提示词和对话模板
- **tools/bash.py** - 提供 Bash 命令执行能力
  - 命令分类：读取类命令可直接执行，执行类命令需确认
  - 危险命令检测：自动识别 sudo、rm 等危险操作

### 服务层

- **chat_service.py** - 统一的对话服务
  - 流式和非流式输出支持
  - 工具调用和命令确认机制
  - 会话历史管理
  - 取消机制支持

## 安全机制

### 命令分类

- **读取类命令** - `ls`、`cat`、`grep`、`pwd` 等，可直接执行
- **执行类命令** - 创建文件、运行程序、删除等，需要用户确认

### 危险命令检测

系统会自动检测以下危险操作：
- `sudo` - 超级用户权限
- `rm` - 删除文件
- `chmod` / `chown` - 权限修改
- `dd`、`mkfs`、`fdisk` - 磁盘操作
- `shutdown`、`reboot` - 系统控制

## 技术栈

- **Flask** - Web 框架
- **LangChain** - LLM 应用框架
- **LangGraph** - Agent 构建
- **DeepSeek API** - 大语言模型服务
- **Server-Sent Events (SSE)** - 流式响应

## License

MIT
