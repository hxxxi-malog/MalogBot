/**
 * 全局状态管理
 * 使用 Vue 3 reactive 实现轻量级状态管理
 */

import { reactive, computed } from 'vue'
import type { Session, Message, KnowledgeBase, MessageAttachments, TeamStatus, ResearchProgress, ResearchPlanConfirmEvent, ClarificationQuestion, ResearchProgressLogEntry } from '@/types'

/**
 * 应用状态接口
 */
interface AppState {
  // 会话状态
  session: {
    currentId: string | null
    list: Session[]
    isWelcomeMode: boolean
  }
  // 设置状态
  settings: {
    webSearchEnabled: boolean
    knowledgeBaseId: string | null
    researchMode: 'chat' | 'standard' | 'deep'  // 普通对话 | 标准研究 | 深度研究
  }
  // 聊天状态
  chat: {
    messages: Message[]
    isStreaming: boolean
    abortController: AbortController | null
    originalUserMessage: string
    onboardingMode: boolean
  }
  // 知识库缓存
  knowledge: {
    list: KnowledgeBase[]
  }
  // 深度研究状态
  research: {
    taskId: string | null
    isResearching: boolean
    confirmTime: number | null  // 确认计划的时间戳(ms)，用于从确认后开始计时
  }
}

/**
 * 创建全局状态
 */
const store = reactive<AppState>({
  session: {
    currentId: null,
    list: [],
    isWelcomeMode: true,
  },
  settings: {
    webSearchEnabled: false,
    knowledgeBaseId: null,
    researchMode: 'chat',  // 默认普通对话
  },
  chat: {
    messages: [],
    isStreaming: false,
    abortController: null,
    originalUserMessage: '',
    onboardingMode: false,
  },
  knowledge: {
    list: [],
  },
  research: {
    taskId: null,
    isResearching: false,
    confirmTime: null,
  },
})

// ==================== Getters ====================

/**
 * 当前会话
 */
export const currentSession = computed(() =>
  store.session.list.find(s => s.session_id === store.session.currentId)
)

/**
 * 是否处于欢迎页模式
 */
export const isWelcomeMode = computed(() => store.session.isWelcomeMode)

/**
 * 是否正在流式输出
 */
export const isStreaming = computed(() => store.chat.isStreaming)

/**
 * 当前知识库 ID
 */
export const currentKnowledgeBaseId = computed(() => store.settings.knowledgeBaseId)

/**
 * 联网搜索是否启用
 */
export const webSearchEnabled = computed(() => store.settings.webSearchEnabled)

/**
 * 知识库列表
 */
export const knowledgeBases = computed(() => store.knowledge.list)

/**
 * 当前会话的消息列表
 */
export const messages = computed(() => store.chat.messages)

/**
 * 是否处于引导模式
 */
export const onboardingMode = computed(() => store.chat.onboardingMode)

/**
 * 研究模式
 */
export const researchMode = computed(() => store.settings.researchMode)

/**
 * 是否正在研究
 */
export const isResearching = computed(() => store.research.isResearching)

/**
 * 当前研究任务 ID
 */
export const researchTaskId = computed(() => store.research.taskId)

/**
 * 确认计划的时间戳
 */
export const researchConfirmTime = computed(() => store.research.confirmTime)

// ==================== Session Actions ====================

/**
 * 设置当前会话 ID
 */
export function setSessionId(id: string | null) {
  store.session.currentId = id
  store.session.isWelcomeMode = id === null
}

/**
 * 设置会话列表
 */
export function setSessions(sessions: Session[]) {
  store.session.list = sessions
}

/**
 * 切换到欢迎页
 */
export function showWelcomeMode() {
  store.session.isWelcomeMode = true
  store.session.currentId = null
}

/**
 * 切换到聊天模式
 */
export function showChatMode() {
  store.session.isWelcomeMode = false
}

// ==================== Chat Actions ====================

/**
 * 添加消息
 */
export function addMessage(message: Message) {
  store.chat.messages.push(message)
}

/**
 * 更新最后一条消息内容
 */
export function updateLastMessage(content: string) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    lastMessage.content = content
  }
}

/**
 * 更新最后一条消息的附加组件
 */
export function updateLastMessageAttachments(attachments: Partial<MessageAttachments>) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    Object.assign(lastMessage.attachments, attachments)
  }
}

/**
 * 清除最后一条消息的确认卡片
 */
export function clearLastMessageConfirmation() {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.attachments) {
    lastMessage.attachments.confirmation = undefined
  }
}

/**
 * 更新团队状态
 */
export function updateTeamStatus(status: TeamStatus | undefined) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    // 使用 Object.assign 确保响应式更新
    lastMessage.attachments = {
      ...lastMessage.attachments,
      teamStatus: status
    }
    console.log('[Store] Team status updated:', status)
  }
}

/**
 * 设置团队阶段
 */
export function setTeamPhase(phase: 'init' | 'running' | 'integrating' | 'done' | undefined) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    // 使用 Object.assign 确保响应式更新
    lastMessage.attachments = {
      ...lastMessage.attachments,
      teamPhase: phase
    }
    console.log('[Store] Team phase set:', phase)
  }
}

/**
 * 设置整合内容
 */
export function setIntegratingContent(content: string | undefined) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    // 使用 Object.assign 确保响应式更新
    lastMessage.attachments = {
      ...lastMessage.attachments,
      integratingContent: content
    }
    console.log('[Store] Integrating content set, length:', content?.length || 0)
  }
}

/**
 * 清空消息列表
 */
export function clearMessages() {
  store.chat.messages = []
}

/**
 * 设置流式输出状态
 */
export function setStreaming(value: boolean) {
  store.chat.isStreaming = value
}

/**
 * 设置 AbortController
 */
export function setAbortController(controller: AbortController | null) {
  store.chat.abortController = controller
}

/**
 * 获取 AbortController
 */
export function getAbortController() {
  return store.chat.abortController
}

/**
 * 设置原始用户消息（用于命令确认）
 */
export function setOriginalUserMessage(message: string) {
  store.chat.originalUserMessage = message
}

/**
 * 获取原始用户消息
 */
export function getOriginalUserMessage() {
  return store.chat.originalUserMessage
}

/**
 * 设置引导模式
 */
export function setOnboardingMode(value: boolean) {
  store.chat.onboardingMode = value
}

// ==================== Settings Actions ====================

/**
 * 设置联网搜索启用状态
 */
export function setWebSearchEnabled(value: boolean) {
  store.settings.webSearchEnabled = value
}

/**
 * 设置当前知识库
 */
export function setKnowledgeBaseId(id: string | null) {
  store.settings.knowledgeBaseId = id
}

// ==================== Knowledge Actions ====================

/**
 * 设置知识库列表
 */
export function setKnowledgeBases(list: KnowledgeBase[]) {
  store.knowledge.list = list
}

// ==================== Research Actions ====================

/**
 * 设置研究模式
 */
export function setResearchMode(mode: 'chat' | 'standard' | 'deep') {
  store.settings.researchMode = mode
}

/**
 * 设置研究任务 ID
 */
export function setResearchTaskId(taskId: string | null) {
  store.research.taskId = taskId
}

/**
 * 设置是否正在研究
 */
export function setResearching(value: boolean) {
  store.research.isResearching = value
}

/**
 * 设置确认计划的时间戳
 */
export function setResearchConfirmTime(time: number | null) {
  store.research.confirmTime = time
}

/**
 * 更新研究进度
 */
export function updateResearchProgress(progress: ResearchProgress | undefined) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    lastMessage.attachments = {
      ...lastMessage.attachments,
      researchProgress: progress
    }
    console.log('[Store] Research progress updated:', progress)
  }
}

/**
 * 追加研究进度日志（瀑布流显示）
 */
export function appendResearchProgressLog(entry: ResearchProgressLogEntry) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    if (!lastMessage.attachments.researchProgressLogs) {
      lastMessage.attachments.researchProgressLogs = []
    }
    
    // 检查是否已存在相同的日志（避免重复）
    const existingLogs = lastMessage.attachments.researchProgressLogs
    const lastLog = existingLogs[existingLogs.length - 1]
    if (lastLog && 
        lastLog.direction_id === entry.direction_id && 
        lastLog.phase === entry.phase &&
        lastLog.progress === entry.progress) {
      return // 跳过重复日志
    }
    
    // 追加新日志
    lastMessage.attachments.researchProgressLogs.push(entry)
    
    // 限制日志数量（最多保留 100 条）
    if (lastMessage.attachments.researchProgressLogs.length > 100) {
      lastMessage.attachments.researchProgressLogs = 
        lastMessage.attachments.researchProgressLogs.slice(-100)
    }
    
    console.log('[Store] Research progress log appended:', entry)
  }
}

/**
 * 清除研究进度日志
 */
export function clearResearchProgressLogs() {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant' && lastMessage.attachments) {
    lastMessage.attachments.researchProgressLogs = []
  }
}

/**
 * 设置研究计划确认
 */
export function setResearchPlan(plan: ResearchPlanConfirmEvent | undefined) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    lastMessage.attachments = {
      ...lastMessage.attachments,
      researchPlan: plan
    }
    console.log('[Store] Research plan set:', plan)
  }
}

/**
 * 设置澄清问题
 */
export function setClarificationQuestions(taskId: string, questions: ClarificationQuestion[]) {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    if (!lastMessage.attachments) {
      lastMessage.attachments = {}
    }
    lastMessage.attachments = {
      ...lastMessage.attachments,
      clarification: {
        task_id: taskId,
        questions: questions,
      }
    }
    console.log('[Store] Clarification questions set:', questions.length, 'for task:', taskId)
  }
}

/**
 * 清除澄清问题
 */
export function clearClarification() {
  const lastMessage = store.chat.messages[store.chat.messages.length - 1]
  if (lastMessage && lastMessage.attachments?.clarification) {
    delete lastMessage.attachments.clarification
    console.log('[Store] Clarification cleared')
  }
}

/**
 * 清除研究状态
 */
export function clearResearch() {
  store.research.taskId = null
  store.research.isResearching = false
  store.research.confirmTime = null
  store.settings.researchMode = 'standard'
}

// ==================== Export Store ====================

export { store }
