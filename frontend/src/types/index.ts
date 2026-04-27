// 会话相关类型
export interface Session {
  session_id: string
  message_count: number
  created_at: string
  updated_at: string
}

// 确认卡片数据
export interface ConfirmationData {
  command: string
  working_dir?: string
  is_dangerous?: boolean
  reason?: string
  command_type?: string
  operation?: string
}

// 递归限制卡片数据
export interface RecursionLimitData {
  message?: string
  partial_output?: string
}

// 任务信息
export interface TaskInfo {
  id: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  result?: string
}

// 任务组
export interface TaskGroup {
  group_index: number
  total_groups: number
  tasks: TaskInfo[]
}

// 团队状态
export interface TeamStatus {
  status: 'idle' | 'active' | 'running' | 'completed' | 'error'
  goal?: string
  total_tasks: number
  completed: number
  in_progress: number
  pending?: number
  failed?: number
  parallel_groups?: number
  tasks: TaskGroup[]
  execution_log?: string[]
  error?: string
  message?: string
  complexity_score?: number
}

// 消息附加组件类型
export interface MessageAttachments {
  // 确认卡片
  confirmation?: ConfirmationData
  // 递归限制卡片
  recursionLimit?: RecursionLimitData
  // 团队进度状态
  teamStatus?: TeamStatus
  // 团队模式阶段
  teamPhase?: 'init' | 'running' | 'integrating' | 'done'
  // 整合内容
  integratingContent?: string
}

// 消息相关类型
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  // 附加组件
  attachments?: MessageAttachments
}

// 知识库相关类型
export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  document_count: number
  chunk_count: number
}

export interface Document {
  id: string
  filename: string
  chunk_count: number
  status: string
}

// MCP 服务相关类型
export interface MCPServer {
  name: string
  display_name?: string
  transport_type: 'streamable-http' | 'http' | 'sse' | 'stdio'
  url?: string
  headers?: Record<string, string>
  command?: string
  args?: string[]
  env?: Record<string, string>
  description?: string
  category?: string
  enabled: boolean
  auto_start: boolean
  status: 'enabled' | 'connected' | 'error' | 'disabled'
  tools_count: number
  last_error?: string
}

export interface MCPStats {
  total_services: number
  enabled_services: number
  connected_services: number
  error_services: number
  total_tools: number
}

// SSE 事件类型
export interface StreamEvent {
  type: string
  content?: string
  accumulated?: string
  command?: string
  working_dir?: string
  is_dangerous?: boolean
  reason?: string
  message?: string
  partial_output?: string
  team_status?: TeamStatus
  need_retry?: boolean
  command_type?: string
  operation?: string
  [key: string]: unknown
}

// 应用状态类型
export interface AppState {
  session: {
    currentId: string | null
    list: Session[]
    isWelcomeMode: boolean
  }
  settings: {
    webSearchEnabled: boolean
    knowledgeBaseId: string | null
  }
  chat: {
    messages: Message[]
    isStreaming: boolean
    abortController: AbortController | null
    originalUserMessage: string
    onboardingMode: boolean
  }
  knowledge: {
    list: KnowledgeBase[]
  }
}

// API 响应类型
export interface ApiResponse {
  status?: string
  error?: string
  [key: string]: unknown
}

export interface SessionsResponse extends ApiResponse {
  sessions: Session[]
  current_session_id: string | null
}

export interface SessionInfoResponse extends ApiResponse {
  messages: Message[]
}

export interface KnowledgeBasesResponse extends ApiResponse {
  knowledge_bases: KnowledgeBase[]
}

export interface DocumentsResponse extends ApiResponse {
  documents: Document[]
}

export interface MCPServersResponse extends ApiResponse {
  servers: MCPServer[]
  stats: MCPStats
}

export interface TeamStatusResponse extends ApiResponse {
  status: string
  team_status: TeamStatus
}
