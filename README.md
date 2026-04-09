# MalogBot

基于 RAG（检索增强生成）和智能 Agent 的知识管理助手，集成了向量检索、混合检索、长期记忆、联网搜索、多Agent团队协作等功能，提供全方位的知识管理和智能问答服务。

## 项目简介

MalogBot 是一个企业级智能助手平台，通过 RAG 技术实现知识库问答，结合大语言模型的能力，实现智能对话、工具调用、任务管理、多Agent协作等功能。系统采用三层上下文架构，支持长期记忆和自动压缩，确保长对话场景下的稳定运行。

## 核心特性

### 智能对话
- 基于 LangGraph 的 Agent 架构
- 流式响应（SSE），支持 token-by-token 输出
- 多轮对话支持，会话历史管理
- 命令确认机制，危险操作检测

### 多Agent团队协作
- 智能路由：自动判断任务复杂度，选择单Agent或团队模式
- 任务拆解：LLM驱动的复杂任务分解，自动构建DAG依赖图
- 并行执行：基于依赖关系的并行任务调度，最大化执行效率
- 流式反馈：实时推送任务进度，前端可视化展示
- 弹性扩展：动态Follower池管理，按需创建和回收资源

### RAG 知识库
- 混合检索（向量 + BM25），支持权重配置
- HNSW 向量索引，快速相似度搜索
- 智能重排序（阿里云百炼 Rerank）
- MMR 多样性重排序，避免重复内容

### 三层上下文架构
- Journal（JSONL）：原始消息存储
- Memory（向量）：长期记忆，支持语义检索
- Summary：当前上下文摘要
- 自动压缩机制，控制 Token 消耗

### 工具系统
- Bash 工具：执行命令，支持安全检测
- Memory 工具：主动存储重要信息
- Task 工具：任务创建和管理
- Skills 工具：自定义技能扩展
- Sub Agent：子代理协作

### 联网搜索
- 百度云 MCP Web Search 集成
- 获取实时信息
- 支持会话级别开关

## 技术栈

### 后端

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| Web 框架 | Flask |
| LLM 框架 | LangChain, LangGraph |
| 大语言模型 | DeepSeek API |
| 数据库 | PostgreSQL 15+ (pgvector) |
| 向量化服务 | 阿里云百炼 |
| 联网搜索 | 百度云 MCP |
| 流式响应 | Server-Sent Events (SSE) |
| 文档解析 | pdfplumber, python-docx |

### 前端

| 类别 | 技术 |
|------|------|
| 模板引擎 | Jinja2 |
| 样式 | 原生 CSS |
| 交互 | 原生 JavaScript |

## 项目结构

```
malogbot/
├── app.py                    # Flask 应用主入口
├── config.py                 # 配置管理模块
├── requirements.txt          # 项目依赖
├── start_db.sh              # 数据库管理脚本
│
├── agent/                    # Agent 模块
│   ├── llm.py               # LLM 客户端封装
│   ├── prompts.py           # 提示词模板
│   ├── team/                # 多Agent团队协作系统
│   │   ├── __init__.py      # 模块导出
│   │   ├── types.py         # 类型定义
│   │   ├── router.py        # 意图路由器
│   │   ├── leader.py        # Leader Agent
│   │   ├── task_board.py    # 任务看板
│   │   ├── follower.py      # Follower Agent
│   │   └── orchestrator.py  # 团队编排器
│   ├── team_v2/             # 团队系统v2（Swarm模式）
│   │   ├── orchestrator.py  # StateGraph编排器
│   │   ├── decomposer.py    # 任务分解器
│   │   └── types.py         # 类型定义
│   └── tools/               # 工具模块
│       ├── bash.py          # Bash 命令执行
│       ├── memory.py        # 长期记忆存储
│       ├── skills.py        # 技能加载
│       ├── sub_agent.py     # 子代理
│       ├── task_manager.py  # 任务管理
│       └── todo_manager.py  # TODO 管理
│
├── services/                 # 服务层
│   ├── core/                # 核心模块
│   │   ├── interfaces.py    # 抽象接口定义
│   │   └── types.py         # 核心类型定义
│   ├── agent/               # Agent 服务
│   ├── context/             # 上下文管理
│   │   ├── session_store.py       # 会话存储
│   │   ├── conversation_journal.py # 对话日志
│   │   ├── context_compactor.py   # 上下文压缩
│   │   └── long_term_memory.py    # 长期记忆
│   ├── rag/                 # RAG 检索服务
│   │   ├── rag_service.py         # 检索服务
│   │   ├── embedding_service.py   # 向量化服务
│   │   ├── bm25_service.py        # BM25 检索
│   │   └── mmr_reranker.py        # MMR 重排序
│   ├── knowledge_base/      # 知识库服务
│   └── db_manager.py        # 数据库管理
│
├── models/                   # 数据模型
│   ├── database.py          # 基础模型
│   └── knowledge_base.py    # 知识库模型
│
├── mcp/                      # MCP 协议适配
│   └── adapters.py          # 百度云 Web Search
│
├── skills/                   # 技能模块
│   └── postgres-performance-diagnosis/
│
├── templates/                # HTML 模板
├── static/                   # 静态文件
├── uploads/                  # 文件上传目录
└── archives/                 # 归档目录
    ├── journals/            # 对话日志归档
    └── transcripts/         # 转录归档
```

## 快速开始

### 环境要求

- Python 3.10+
- Docker（用于 PostgreSQL）
- DeepSeek API Key
- 阿里云百炼 API Key（可选，用于 RAG）
- 百度云 API Key（可选，用于联网搜索）

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/malogbot.git
cd malogbot
```

### 2. 创建虚拟环境

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 启动数据库

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

### 5. 配置环境变量

创建 `.env` 文件并配置：

```bash
# ==================== LLM 配置 ====================
DEEPSEEK_API_KEY=your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
MODEL_NAME=deepseek-chat

# ==================== Flask 配置 ====================
SECRET_KEY=your-secret-key
FLASK_DEBUG=True

# ==================== 数据库配置 ====================
DATABASE_URL=postgresql://malog:your_password@127.0.0.1:5433/malogbot

# ==================== Agent 配置 ====================
BASH_TIMEOUT=30
AGENT_RECURSION_LIMIT=25

# ==================== 向量化服务（阿里云百炼） ====================
DASHSCOPE_API_KEY=your-dashscope-api-key
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
RERANK_MODEL=qwen3-vl-rerank

# ==================== RAG 配置 ====================
RAG_TOP_N=10
RAG_TOP_K=3
CHUNK_SIZE=500
CHUNK_OVERLAP=50
ENABLE_HYBRID_SEARCH=true
BM25_WEIGHT=0.3
VECTOR_WEIGHT=0.7
ENABLE_MMR=true
MMR_ALPHA=0.7

# ==================== 联网搜索（百度云 MCP） ====================
BAIDU_MCP_API_KEY=your-baidu-api-key
WEB_SEARCH_ENABLED=false

# ==================== 长期记忆配置 ====================
ENABLE_LONG_TERM_MEMORY=true
MEMORY_TOKEN_BUDGET=2000
MEMORY_RELEVANCE_THRESHOLD=0.65

# ==================== 文件上传 ====================
UPLOAD_FOLDER=./uploads
MAX_FILE_SIZE=10485760

# ==================== LangSmith 追踪（可选） ====================
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=MalogBot
```

### 6. 运行应用

```bash
python app.py
```

服务将在 http://127.0.0.1:5000 启动。

## 核心功能

### 1. 知识库管理

- 创建和管理知识库
- 上传文档（PDF、DOCX、TXT、MD、JSON、CSV）
- 自动分块和向量化
- 文档删除和管理

### 2. 智能对话

- 基于 RAG 的知识问答
- 流式响应（SSE）
- 会话历史管理
- 多轮对话支持
- 命令确认机制

### 3. 多Agent团队协作

系统支持两种执行模式：

**单Agent模式**
- 适用于简单问答、单步操作
- 直接调用LLM执行
- 快速响应，低延迟

**团队协作模式**
- 适用于复杂任务（代码重构、系统迁移、批量操作等）
- 自动拆解为多个子任务
- DAG依赖分析与并行执行
- 实时进度反馈
- 结果智能整合

### 4. RAG 检索

- 向量检索（HNSW 索引）
- BM25 关键词检索
- 混合检索（加权融合）
- 智能重排序
- MMR 多样性优化

### 5. 上下文管理

三层架构设计：

- Journal（JSONL）：原始消息存储，支持归档
- Memory（向量）：长期记忆，语义检索
- Summary：当前上下文，自动压缩

### 6. 工具系统

Agent 可用工具：

- bash：执行 Bash 命令
- memory：存储重要信息到长期记忆
- skills：加载和执行自定义技能
- sub_agent：创建子代理处理子任务
- task_manager：任务管理
- todo_manager：TODO 管理
- context_compact：手动触发上下文压缩

### 7. 安全机制

- 命令分类：读取类直接执行，执行类需确认
- 危险命令检测：sudo、rm、chmod 等
- 白名单机制：允许特定危险命令模式

## API 文档

### 会话管理

```
GET  /sessions                      # 获取会话列表
POST /sessions/new                  # 创建新会话
DELETE /sessions/<session_id>       # 删除会话
POST /sessions/<session_id>/switch  # 切换会话
GET  /sessions/<session_id>/info    # 获取会话详情
GET  /sessions/<session_id>/knowledge-base  # 获取知识库设置
PUT  /sessions/<session_id>/knowledge-base  # 设置知识库
```

### 对话接口

```
POST /chat              # 非流式对话
POST /chat/stream       # 流式对话（SSE）
GET  /history           # 获取对话历史
POST /reset             # 重置会话
POST /stop              # 取消流式输出
```

### 命令确认

```
POST /confirm           # 确认执行命令（非流式）
POST /confirm/stream    # 确认执行命令（流式）
POST /cancel            # 取消命令执行
```

### 团队协作

```
GET  /team/status       # 获取团队执行状态
GET  /team/board        # 获取任务看板视图
```

### 任务继续

```
POST /continue          # 继续执行（非流式）
POST /continue/stream   # 继续执行（流式）
```

### 联网搜索

```
GET  /web-search/status  # 获取状态
POST /web-search/toggle  # 切换开关
```

### 知识库管理

```
GET  /knowledge-bases                  # 获取知识库列表
POST /knowledge-bases                  # 创建知识库
GET  /knowledge-bases/<kb_id>          # 获取知识库详情
DELETE /knowledge-bases/<kb_id>        # 删除知识库
GET  /knowledge-bases/<kb_id>/documents  # 获取文档列表
POST /knowledge-bases/<kb_id>/documents  # 上传文档
DELETE /documents/<doc_id>             # 删除文档
```

## 配置说明

### 检索配置

可在 `.env` 中调整检索策略：

```bash
# 混合检索开关
ENABLE_HYBRID_SEARCH=true

# 权重配置
BM25_WEIGHT=0.3          # 关键词匹配权重
VECTOR_WEIGHT=0.7        # 语义相似度权重

# MMR 多样性
ENABLE_MMR=true
MMR_ALPHA=0.7            # 相关性权重（越大越偏向相关性）

# 检索数量
RAG_TOP_N=10             # 初始检索数量
RAG_TOP_K=3              # 最终返回数量
```

### 上下文配置

```bash
# 最大上下文窗口
MAX_CONTEXT_TOKENS=128000

# 压缩阈值比例
COMPACT_THRESHOLD_RATIO=0.8

# 长期记忆
ENABLE_LONG_TERM_MEMORY=true
MEMORY_TOKEN_BUDGET=2000
MEMORY_RELEVANCE_THRESHOLD=0.65
```

### 模型配置

支持多种模型提供商：

- DeepSeek（默认）
- 兼容 OpenAI API 的服务

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t malogbot .

# 运行容器
docker run -d \
    --name malogbot \
    -p 5000:5000 \
    --env-file .env \
    malogbot
```

### 生产环境配置

- 修改 `.env` 中的敏感配置
- 设置 `FLASK_DEBUG=False`
- 配置反向代理（Nginx）
- 启用 HTTPS
- 使用 Gunicorn 或 uWSGI

## 数据库管理

使用 `start_db.sh` 脚本管理数据库：

```bash
./start_db.sh create   # 创建并启动
./start_db.sh start    # 启动
./start_db.sh stop     # 停止
./start_db.sh restart  # 重启
./start_db.sh status   # 查看状态
./start_db.sh logs     # 查看日志
./start_db.sh connect  # 连接数据库
./start_db.sh backup   # 备份数据库
```

## 开发指南

### 代码规范

- Python：遵循 PEP 8 规范
- 使用 dataclass 定义数据结构
- 抽象接口与具体实现分离

### 添加新工具

1. 在 `agent/tools/` 目录下创建新的工具文件
2. 继承 `langchain_core.tools.BaseTool` 类
3. 在 `agent/tools/__init__.py` 中注册工具

### 添加新技能

1. 在 `skills/` 目录下创建新的技能目录
2. 编写 `SKILL.md` 文件定义技能
3. 系统会自动加载并识别技能

### 测试

```bash
# 运行测试
python -m pytest tests/
```

## 架构设计

### 核心接口

系统采用依赖反转设计，高层模块依赖抽象接口：

- `ISessionStore`：会话存储接口
- `IContextCompactor`：上下文压缩接口
- `IAgentService`：Agent 服务接口
- `IRAGService`：RAG 检索接口
- `IEmbeddingService`：向量化服务接口
- `IKnowledgeBaseService`：知识库服务接口
- `ILongTermMemory`：长期记忆接口

### 三层上下文架构

```
┌─────────────────────────────────────────────┐
│                   LLM                       │
└─────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│              注入的上下文                     │
│  ┌─────────────┐  ┌─────────────────────┐   │
│  │ Long-term   │  │    Journal          │   │
│  │   Memory    │  │  (Recent Messages)  │   │
│  │  (Rerank)   │  │                     │   │
│  └─────────────┘  └─────────────────────┘   │
└─────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Vector  │  │  JSONL   │  │ Summary  │
   │   DB    │  │  Archive │  │ (Compact)│
   └─────────┘  └──────────┘  └──────────┘
```

### 多Agent团队协作架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户请求                              │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentsTeam 编排器                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              IntentRouter 意图路由                   │    │
│  └─────────────────────┬───────────────────────────────┘    │
└────────────────────────┼────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                              ▼
┌─────────────────────┐      ┌─────────────────────────────────┐
│    单Agent模式       │      │         团队模式                 │
│  (直接执行)          │      │  ┌───────────────────────────┐  │
└─────────────────────┘      │  │   LeaderAgent            │  │
                             │  │   - 任务拆解、DAG构建      │  │
                             │  │   - 监控调度、结果整合      │  │
                             │  └───────────┬───────────────┘  │
                             │              │                   │
                             │  ┌───────────┴───────────────┐  │
                             │  │      TaskBoard            │  │
                             │  │  - 任务状态管理            │  │
                             │  │  - 依赖关系维护            │  │
                             │  └───────────┬───────────────┘  │
                             │              │                   │
                             │  ┌───────────┴───────────────┐  │
                             │  │     FollowerPool          │  │
                             │  │  ┌─────┐ ┌─────┐ ┌─────┐ │  │
                             │  │  │ F1  │ │ F2  │ │ F3  │ │  │
                             │  │  └─────┘ └─────┘ └─────┘ │  │
                             │  │  (并行执行任务)            │  │
                             │  └───────────────────────────┘  │
                             └─────────────────────────────────┘
```

**团队协作流程**：

1. 意图路由：分析请求复杂度，决定执行模式
2. 任务拆解：Leader Agent将复杂任务拆解为子任务
3. DAG构建：分析依赖关系，构建执行计划
4. 并行执行：Follower Pool并行执行就绪任务
5. 结果整合：LLM智能整合各子任务结果

## 许可证

MIT License

## 联系方式

项目主页：[GitHub](https://github.com/hxxxi-malog/MalogBot/)

问题反馈：[Issues](https://github.com/hxxxi-malog/MalogBot/issues)
