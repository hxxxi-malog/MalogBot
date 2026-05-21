# Changelog

All notable changes to MalogBot will be documented in this file.

## [2.0.0] - 2026-05-21

### Added

- **团队协作 v2 (Swarm模式)**：基于 LangGraph StateGraph 的全新编排架构
  - TaskDecomposer：LLM驱动的任务自动分解
  - FollowerExecutor：独立子任务并行执行
  - ResultIntegrator：LLM智能整合子任务结果
  - 更简洁的架构，更可靠的执行流程

- **深度研究系统**：专家型Agent协作的深度研究系统
  - 标准研究模式：直接生成研究计划并执行
  - 深度研究模式：澄清问题 -> 研究计划 -> 用户确认 -> 执行
  - 三类专家型Agent：探索型、分析型、总结型
  - 状态机驱动流程，严格的状态转换DAG
  - 多方向并行研究，方向间完全并行
  - 分层去重机制：Track本地去重 + Session全局去重(Redis) + 向量相似度去重
  - 流式报告生成 + PDF异步导出
  - SSE实时进度推送
  - 用户干预：研究中可发送补充信息引导方向
  - 消息持久化：研究进度实时持久化，会话切换后状态可恢复

- **RAG 查询优化器**：复杂查询自动优化
  - 指代消解（Coreference Resolution）
  - Step-Back 抽象问题生成
  - 问题分解（Question Decomposition）
  - 多查询重写（Multi-Query Rewriting）
  - 成本控制：子问题数量 <= 5，每子问题查询变体 <= 3

- **首次对话引导 (Onboarding)**
  - 首次对话自动检测，引导用户建立身份
  - 智能解析用户回复，提取姓名、角色偏好
  - 自动填充 SOUL 和 USER 知识块

- **MCP Streamable HTTP 传输**
  - 实现 MCP v2025.03.26 协议的 Streamable HTTP 传输层
  - 统一消息入口：所有消息通过单一 /message 端点
  - 会话管理：服务器可返回 Mcp-Session-Id 头
  - 动态 SSE 升级：服务器可将请求升级为 SSE 连接

- **消息持久化与断线重连**
  - 研究进度实时持久化到数据库
  - 会话切换后研究状态可恢复
  - 会话详情API返回关联的研究任务及报告内容

- **上下文归档与恢复**
  - ContextArchive 模型：存储压缩前的完整对话历史
  - 支持上下文回溯和恢复

- **前端交互组件**
  - ClarificationCard：澄清问题交互卡片
  - PlanConfirmCard：研究计划确认卡片
  - ResearchProgressCard：研究进度展示
  - ResearchCompletedCard：研究完成结果展示
  - TeamProgressCard：团队协作进度可视化
  - RecursionLimitCard：递归限制提示卡片

- **子Agent双模式**
  - default模式：同进程，共享messages数组，低隔离
  - fork模式：独立进程，全新messages数组，中隔离

- **Redis 内存管理**
  - Redis 配置 maxmemory 256mb + allkeys-lru 淘汰策略
  - 防止 Redis 内存无限增长

- **Docker 多阶段构建优化**
  - 新增 frontend-builder 构建阶段
  - Docker 构建时自动编译前端

### Changed

- Python 版本要求从 3.10+ 提升至 3.11+
- 前端 Vue 3 升级至 3.5+
- 前端 Vite 升级至 8.0+
- 前端 TypeScript 升级至 6.0+
- 前端 Tailwind CSS 升级至 4.0+
- 前端新增依赖：@microsoft/fetch-event-source, @vueuse/core, highlight.js, marked
- 重排序模型升级为 qwen3-vl-rerank
- Dockerfile 改为多阶段构建（含前端构建阶段）
- Docker 健康检查 start-period 从 5s 调整为 15s
- deploy.sh 不再需要单独构建前端

### Fixed

- 修复研究任务查询中的 N+1 问题，使用 joinedload 预加载
- 修复会话切换后研究状态丢失的问题
- 修复深度研究 SSE 事件缓冲区溢出问题

---

## [1.0.0] - 2025-12-01

### Added

- 基于 RAG（检索增强生成）的智能对话系统
- LangGraph Agent 架构，支持流式响应（SSE）
- 多轮对话支持，会话历史管理
- 命令确认机制，危险操作检测
- Agent 自我进化知识库（SOUL/USER/AGENTS/MEMORY）
- Bootstrap 动态加载（Token预算分配）
- 多Agent团队协作 v1（Leader-Follower模式）
- RAG 知识库（向量+BM25混合检索）
- 三层上下文架构（Journal/Memory/Summary）
- 两级缓存系统（L1本地+L2 Redis）
- MCP 协议适配
- 联网搜索（百度云 MCP）
- Prometheus + Grafana 监控系统
- RAGAS 检索评估系统
- Vue 3 + TypeScript 前端界面
- Docker 一键部署
