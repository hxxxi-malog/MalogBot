# MalogBot

一个基于 Flask 和 LangChain 的智能 AI 助手，支持工具调用、知识库问答（RAG）和联网搜索。

## ✨ 功能特性

### 核心功能
- **🤖 智能对话** - 基于大语言模型的智能对话能力
- **📊 流式响应** - 支持 token-by-token 的流式输出，打字机效果
- **📂 会话管理** - 支持多会话创建、切换和对话历史管理

### 工具能力
- **💻 Bash 工具** - AI 可以执行 Bash 命令帮助用户完成任务
- **✅ 命令确认机制** - 执行类命令需要用户确认，保障安全
- **⚠️ 危险命令检测** - 自动检测 sudo、rm 等危险操作并警告
- **🌐 联网搜索** - 支持百度云 MCP 联网搜索，获取实时信息

### 知识库（RAG）
- **📚 知识库管理** - 创建、删除知识库，支持多知识库切换
- **📄 文档处理** - 支持 PDF、Word、Markdown、TXT 等多种格式
- **🔍 向量检索** - 基于 pgvector 的 HNSW 索引，快速相似度搜索
- **🎯 智能重排序** - 使用阿里云百炼 Rerank 模型优化检索结果

### 可扩展性
- **🔧 Skills 系统** - 支持自定义技能扩展
- **🔌 MCP 协议** - 支持 Model Context Protocol 工具集成

## 📁 项目结构

```
MalogBot/
├── app.py                  # Flask 应用主入口
├── config.py               # 配置管理模块
├── requirements.txt        # 项目依赖
├── .env                    # 环境变量配置（不提交到 git）
│
├── agent/                  # Agent 模块
│   ├── llm.py              # LLM 客户端封装
│   ├── prompts.py          # 提示词模板
│   └── tools/              # 工具模块
│       ├── bash.py         # Bash 命令执行工具
│       ├── skills.py       # 技能加载工具
│       ├── sub_agent.py    # 子代理工具
│       ├── task_manager.py # 任务管理工具
│       └── todo_manager.py # TODO 管理工具
│
├── services/               # 服务层
│   ├── chat_service.py     # 对话服务（流式/非流式）
│   ├── db_manager.py       # 数据库管理
│   ├── knowledge_base_service.py  # 知识库服务
│   ├── document_service.py # 文档处理服务
│   ├── rag_service.py      # RAG 检索服务
│   ├── embedding_service.py # 向量化服务（阿里云百炼）
│   └── session_store.py    # 会话存储
│
├── models/                 # 数据模型
│   ├── database.py         # 数据库基础模型
│   └── knowledge_base.py   # 知识库相关模型
│
├── mcp/                    # MCP 协议适配
│   └── adapters.py         # 百度云 Web Search 适配器
│
├── skills/                 # 技能模块
│   └── postgres-performance-diagnosis/  # PostgreSQL 性能诊断技能
│
├── templates/              # HTML 模板
│   └── index.html          # 对话界面
│
├── static/                 # 静态文件
├── uploads/                # 文件上传目录
└── postgres_data/          # PostgreSQL 数据目录（Docker）
```

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-username/MalogBot.git
cd MalogBot
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
```

### 3. 激活虚拟环境

```bash
# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 启动数据库

使用 Docker 启动 PostgreSQL（带 pgvector 扩展）：

```bash
# 创建并启动数据库容器
./start_db.sh create

# 或使用 Docker 命令
docker run -d \
    --name malogbot-db \
    -e POSTGRES_USER=malog \
    -e POSTGRES_PASSWORD=your_password \
    -e POSTGRES_DB=malogbot \
    -p 5433:5432 \
    -v $(pwd)/postgres_data:/var/lib/postgresql/data \
    ankane/pgvector:latest
```

### 6. 配置环境变量

创建 `.env` 文件并配置：

```bash
# ==================== LLM 配置 ====================
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat

# ==================== Flask 配置 ====================
SECRET_KEY=你的Flask密钥
FLASK_DEBUG=True

# ==================== 数据库配置 ====================
DATABASE_URL=postgresql://malog:your_password@127.0.0.1:5433/malogbot

# ==================== 工具配置 ====================
BASH_TIMEOUT=30
AGENT_RECURSION_LIMIT=25

# ==================== 联网搜索（百度云 MCP） ====================
BAIDU_MCP_API_KEY=你的百度云API密钥
WEB_SEARCH_ENABLED=false

# ==================== 向量化服务（阿里云百炼） ====================
DASHSCOPE_API_KEY=你的阿里云API密钥
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
RERANK_MODEL=qwen3-vl-rerank

# ==================== RAG 配置 ====================
RAG_TOP_N=10
RAG_TOP_K=3
CHUNK_SIZE=500
CHUNK_OVERLAP=50

# ==================== 文件上传 ====================
UPLOAD_FOLDER=./uploads
MAX_FILE_SIZE=10485760

# ==================== LangSmith 追踪（可选） ====================
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=你的LangSmith密钥
LANGCHAIN_PROJECT=MalogBot
```

### 7. 运行应用

```bash
python app.py
```

访问 http://127.0.0.1:5000 开始对话。

## 📖 API 接口文档

### 会话管理

| 接口 | 方法 | 描述 |
|------|------|------|
| `/sessions` | GET | 获取所有会话列表 |
| `/sessions/new` | POST | 创建新会话 |
| `/sessions/<session_id>` | DELETE | 删除指定会话 |
| `/sessions/<session_id>/switch` | POST | 切换到指定会话 |
| `/sessions/<session_id>/info` | GET | 获取会话详情 |
| `/sessions/<session_id>/knowledge-base` | GET/PUT | 获取/设置会话知识库 |

### 对话接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/chat` | POST | 非流式对话 |
| `/chat/stream` | POST | 流式对话（SSE） |
| `/history` | GET | 获取对话历史 |
| `/reset` | POST | 重置当前会话 |
| `/stop` | POST | 取消当前流式输出 |

### 命令确认接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/confirm` | POST | 确认执行命令（非流式） |
| `/confirm/stream` | POST | 确认执行命令（流式） |
| `/cancel` | POST | 取消命令执行 |

### 任务继续接口

| 接口 | 方法 | 描述 |
|------|------|------|
| `/continue` | POST | 继续执行因递归限制暂停的任务 |
| `/continue/stream` | POST | 继续执行（流式） |

### 联网搜索设置

| 接口 | 方法 | 描述 |
|------|------|------|
| `/web-search/status` | GET | 获取联网搜索状态 |
| `/web-search/toggle` | POST | 切换联网搜索开关 |

### 知识库管理

| 接口 | 方法 | 描述 |
|------|------|------|
| `/knowledge-bases` | GET | 获取知识库列表 |
| `/knowledge-bases` | POST | 创建知识库 |
| `/knowledge-bases/<kb_id>` | GET | 获取知识库详情 |
| `/knowledge-bases/<kb_id>` | DELETE | 删除知识库 |
| `/knowledge-bases/<kb_id>/documents` | GET | 获取文档列表 |
| `/knowledge-bases/<kb_id>/documents` | POST | 上传文档 |
| `/documents/<doc_id>` | DELETE | 删除文档 |

## 🔧 核心模块说明

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
- **rag_service.py** - RAG 检索服务
  - HNSW 向量索引检索
  - 智能重排序
- **embedding_service.py** - 阿里云百炼向量化服务
  - 文本向量化
  - 文档重排序
- **document_service.py** - 文档处理服务
  - 多格式文档解析（PDF、Word、Markdown、TXT）
  - 文本分块

### MCP 模块

- **adapters.py** - MCP 协议适配器
  - 百度云 Web Search 工具集成
  - JSON-RPC 2.0 协议支持

## 🔒 安全机制

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

## 🛠️ 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | Flask |
| LLM 框架 | LangChain, LangGraph |
| 大语言模型 | DeepSeek API |
| 向量数据库 | PostgreSQL + pgvector |
| 向量化服务 | 阿里云百炼 |
| 联网搜索 | 百度云 MCP |
| 流式响应 | Server-Sent Events (SSE) |
| 文档解析 | pdfplumber, python-docx |

## 📊 数据库管理

使用 `start_db.sh` 脚本管理数据库：

```bash
# 启动数据库
./start_db.sh start

# 停止数据库
./start_db.sh stop

# 重启数据库
./start_db.sh restart

# 查看状态
./start_db.sh status

# 查看日志
./start_db.sh logs

# 连接数据库
./start_db.sh connect

# 备份数据库
./start_db.sh backup
```

## 📝 开发说明

### 添加新工具

1. 在 `agent/tools/` 目录下创建新的工具文件
2. 继承 `langchain_core.tools.BaseTool` 类
3. 在 `chat_service.py` 中注册工具

### 添加新技能

1. 在 `skills/` 目录下创建新的技能目录
2. 编写 `SKILL.md` 文件定义技能
3. 系统会自动加载并识别技能

## 📄 License

MIT
