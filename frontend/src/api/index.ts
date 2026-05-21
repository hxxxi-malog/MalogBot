/**
 * API 封装层
 * 统一处理后端 API 请求
 */

import type {
  SessionsResponse,
  SessionInfoResponse,
  KnowledgeBasesResponse,
  DocumentsResponse,
  MCPServersResponse,
  MCPServer,
  TeamStatusResponse,
  ResearchTask,
  ResearchProgress,
  DirectionSpec,
} from '@/types'

const BASE_URL = ''

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * 基础请求函数
 */
async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(BASE_URL + url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new ApiError(data.error || 'Request failed', response.status)
  }

  return response.json()
}

/**
 * Chat API
 */
export const chatApi = {
  /**
   * 发送消息并获取流式响应
   */
  stream: (message: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal,
    }),

  /**
   * 停止生成
   */
  stop: () => fetch(`${BASE_URL}/stop`, { method: 'POST' }),

  /**
   * 确认执行命令
   */
  confirm: (command: string, userMessage: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/confirm/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, user_message: userMessage }),
      signal,
    }),

  /**
   * 取消执行命令
   */
  cancel: (command: string, userMessage: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, user_message: userMessage }),
      signal,
    }),

  /**
   * 继续执行（递归限制后）
   */
  continue: (signal: AbortSignal) =>
    fetch(`${BASE_URL}/continue/stream`, {
      method: 'POST',
      signal,
    }),

  /**
   * 首次对话引导回复
   */
  onboardingReply: (message: string) =>
    request<{ type: string; message?: string; output?: string; need_retry?: boolean }>(
      '/onboarding/reply',
      {
        method: 'POST',
        body: JSON.stringify({ message }),
      }
    ),
}

/**
 * Session API
 */
export const sessionApi = {
  /**
   * 获取会话列表
   */
  list: () => request<SessionsResponse>('/sessions'),

  /**
   * 创建新会话
   */
  create: () => request<{ session_id: string }>('/sessions/new', { method: 'POST' }),

  /**
   * 删除会话
   */
  delete: (id: string) => request<{ status: string; error?: string }>(`/sessions/${id}`, { method: 'DELETE' }),

  /**
   * 切换会话
   */
  switch: (id: string) => request<{ status: string }>(`/sessions/${id}/switch`, { method: 'POST' }),

  /**
   * 获取会话详情（历史消息）
   */
  info: (id: string) => request<SessionInfoResponse>(`/sessions/${id}/info`),

  /**
   * 设置会话的知识库
   */
  setKnowledgeBase: (id: string, kbId: string | null) =>
    request(`/sessions/${id}/knowledge-base`, {
      method: 'PUT',
      body: JSON.stringify({ knowledge_base_id: kbId }),
    }),
}

/**
 * Web Search API
 */
export const webSearchApi = {
  /**
   * 获取联网搜索状态
   */
  status: () => request<{ enabled: boolean }>('/web-search/status'),

  /**
   * 切换联网搜索
   */
  toggle: (enabled: boolean) =>
    request('/web-search/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),
}

/**
 * Knowledge Base API
 */
export const knowledgeApi = {
  /**
   * 获取知识库列表
   */
  list: () => request<KnowledgeBasesResponse>('/knowledge-bases'),

  /**
   * 创建知识库
   */
  create: (name: string, description?: string) =>
    request<{ id: string }>('/knowledge-bases', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),

  /**
   * 删除知识库
   */
  delete: (id: string) => fetch(`/knowledge-bases/${id}`, { method: 'DELETE' }),

  /**
   * 获取知识库文档列表
   */
  documents: (kbId: string) => request<DocumentsResponse>(`/knowledge-bases/${kbId}/documents`),

  /**
   * 上传文档
   */
  uploadDocument: (kbId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return fetch(`/knowledge-bases/${kbId}/documents`, {
      method: 'POST',
      body: formData,
    })
  },

  /**
   * 删除文档
   */
  deleteDocument: (docId: string) => fetch(`/documents/${docId}`, { method: 'DELETE' }),
}

/**
 * MCP API
 */
export const mcpApi = {
  /**
   * 获取 MCP 服务列表
   */
  list: () => request<MCPServersResponse>('/mcp/servers'),

  /**
   * 获取单个 MCP 服务详情
   */
  get: (name: string) => request<{ server: MCPServer }>(`/mcp/servers/${name}`),

  /**
   * 创建 MCP 服务
   */
  create: (data: Partial<MCPServer>) =>
    request('/mcp/servers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * 更新 MCP 服务
   */
  update: (name: string, data: Partial<MCPServer>) =>
    request(`/mcp/servers/${name}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /**
   * 删除 MCP 服务
   */
  delete: (name: string) => fetch(`/mcp/servers/${name}`, { method: 'DELETE' }),

  /**
   * 启用 MCP 服务
   */
  enable: (name: string) => fetch(`/mcp/servers/${name}/enable`, { method: 'POST' }),

  /**
   * 禁用 MCP 服务
   */
  disable: (name: string) => fetch(`/mcp/servers/${name}/disable`, { method: 'POST' }),

  /**
   * 测试 MCP 服务连接
   */
  test: (name: string) =>
    fetch(`/mcp/servers/${name}/test`, { method: 'POST' }).then(r => r.json()),

  /**
   * 刷新单个 MCP 服务
   */
  refresh: (name: string) =>
    fetch(`/mcp/servers/${name}/refresh`, { method: 'POST' }).then(r => r.json()),

  /**
   * 刷新所有 MCP 服务
   */
  refreshAll: () => fetch('/mcp/refresh-all', { method: 'POST' }).then(r => r.json()),

  /**
   * 导入 MCP 配置
   */
  importConfig: (config: unknown) =>
    request<{ success_count: number; fail_count: number }>('/mcp/config/import', {
      method: 'POST',
      body: JSON.stringify({ config, overwrite: true }),
    }),

  /**
   * 导出 MCP 配置
   */
  exportConfig: () => request<{ config: unknown }>('/mcp/config/export'),
}

/**
 * Team API
 */
export const teamApi = {
  /**
   * 获取团队模式状态
   */
  status: () => request<TeamStatusResponse>('/team/status'),
}

/**
 * Research API - 深度研究接口
 */
export const researchApi = {
  /**
   * 发起研究（单阶段启动）
   * 创建任务并立即提交异步执行，Redis STREAM 保证事件不丢失
   */
  start: (query: string, mode: 'standard' | 'deep', signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/research/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, mode }),
      signal,
    }),

  /**
   * 恢复研究（回答澄清问题后）
   */
  resume: (taskId: string, answer: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/research/${taskId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
      signal,
    }),

  /**
   * 取消研究
   */
  cancel: (taskId: string) =>
    request<{ status: string }>(`/api/research/${taskId}/cancel`, { method: 'POST' }),

  /**
   * 获取研究状态
   */
  status: (taskId: string) =>
    request<{ task: ResearchTask; progress: ResearchProgress }>(`/api/research/${taskId}/status`),

  /**
   * 获取研究计划
   */
  getPlan: (taskId: string) =>
    request<{ plan: { id: string; directions: DirectionSpec[] } }>(`/api/research/${taskId}/plan`),

  /**
   * 修改研究计划
   */
  updatePlan: (taskId: string, directions: DirectionSpec[]) =>
    request<{ plan: { id: string; directions: DirectionSpec[] } }>(`/api/research/${taskId}/plan`, {
      method: 'PUT',
      body: JSON.stringify({ directions }),
    }),

  /**
   * 确认研究计划
   */
  confirmPlan: (taskId: string) =>
    request<{ task: ResearchTask }>(`/api/research/${taskId}/confirm`, { method: 'POST' }),

  /**
   * SSE 事件流 URL（供 fetchEventSource 使用）
   * 支持 Last-Event-Seq-No 请求头实现增量回放
   */
  eventsUrl: (taskId: string) => `${BASE_URL}/api/research/${taskId}/events`,

  /**
   * 获取历史研究列表
   */
  history: () =>
    request<{ tasks: ResearchTask[] }>('/api/research/history'),

  /**
   * 发送干预消息（研究过程中）
   */
  intervene: (taskId: string, message: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/research/${taskId}/intervene`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal,
    }),
}
