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

// ============ 深度研究相关类型 ============

// 研究模式
export type ResearchMode = 'standard' | 'deep'

// 研究状态
export type ResearchStatus =
  | 'pending'
  | 'analyzing'
  | 'pending_clarification'
  | 'resumed'
  | 'planning'
  | 'pending_confirmation'
  | 'confirmed'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'cancelled'

// 研究方向状态
export type ResearchDirectionStatus =
  | 'pending'
  | 'exploring'
  | 'analyzing'
  | 'synthesizing'
  | 'completed'
  | 'failed'

// 澄清问题
export interface ClarificationQuestion {
  question: string
  options: string[]
  answer?: string
}

// 澄清问题数据（包含 task_id）
export interface ClarificationData {
  task_id: string
  questions: ClarificationQuestion[]
}

// 研究方向规格
export interface DirectionSpec {
  id: string
  name: string
  description: string
  keywords: string[]
  priority: number
}

// 研究任务
export interface ResearchTask {
  id: string
  session_id: string
  query: string
  mode: ResearchMode
  status: ResearchStatus
  clarification_questions: ClarificationQuestion[]
  current_step: string
  error_message: string
  started_at?: string
  completed_at?: string
  created_at: string
  updated_at: string
}

// 研究计划
export interface ResearchPlan {
  id: string
  task_id: string
  directions: DirectionSpec[]
  is_confirmed: boolean
  confirmed_at?: string
}

// 研究方向进度
export interface ResearchDirectionProgress {
  direction_id: string
  direction_name: string
  status: ResearchDirectionStatus
  progress: number // 0-100
  current_action: string
  learnings_count: number
  sources_count: number
}

// 研究进度状态
export interface ResearchProgress {
  task_id: string
  status: ResearchStatus
  mode: ResearchMode
  progress_pct: number
  elapsed_seconds: number
  directions: ResearchDirectionProgress[]
  current_action: string
  estimated_remaining?: string
}

// 研究进度日志条目（瀑布流显示）
export interface ResearchProgressLogEntry {
  id: string
  timestamp: Date
  direction_id: string
  direction_name: string
  phase: 'started' | 'exploring' | 'analyzing' | 'synthesizing' | 'completed' | 'failed'
  message: string
  progress: number
  learnings_count?: number
  sources_count?: number
}

// SSE 事件数据类型
export interface ResearchProgressEvent {
  step_index: number
  step_total: number
  status: string
  current_action: string
  progress_pct: number
}

export interface ResearchDirectionProgressEvent {
  direction_id: string
  direction_name: string
  status: string
  progress: number
  current_action: string
  learnings_count: number
  sources_count: number
}

export interface ResearchClarificationEvent {
  questions: ClarificationQuestion[]
}

export interface ResearchPlanConfirmEvent {
  task_id: string
  directions: DirectionSpec[]
  estimated_time: string
  can_modify: boolean
}

export interface ResearchCompletedEvent {
  report_url: string
  source_count: number
  duration_seconds: number
  word_count: number
}

// 研究完成附件数据（前端显示用）
export interface ResearchCompletedData {
  task_id: string
  source_count: number
  duration_seconds: number
  report_id?: string
  word_count?: number
}

export interface ResearchErrorEvent {
  error_code: string
  error_message: string
  recoverable: boolean
  suggestion: string
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
  // 深度研究进度
  researchProgress?: ResearchProgress
  // 研究进度日志（瀑布流）
  researchProgressLogs?: ResearchProgressLogEntry[]
  // 研究计划确认
  researchPlan?: ResearchPlanConfirmEvent
  // 澄清问题（包含 task_id）
  clarification?: ClarificationData
  // 研究完成（下载报告）
  researchCompleted?: ResearchCompletedData
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
  seq_no?: string
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

export interface ResearchTaskHistory {
  task_id: string
  query: string
  mode: string
  status: string
  created_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  plan: { directions: DirectionSpec[]; is_confirmed: boolean } | null
  report_content: string | null
  report_word_count: number | null
  report_source_count: number | null
}

export interface SessionInfoResponse extends ApiResponse {
  messages: Message[]
  research_tasks?: ResearchTaskHistory[]
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
