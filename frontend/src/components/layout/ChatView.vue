<script setup lang="ts">
import { ref, computed, nextTick, watch, onUnmounted } from 'vue'
import { Globe, BookOpen, Send, Square, Bot } from 'lucide-vue-next'
import MessageList from '@/components/chat/MessageList.vue'
import {
  store,
  webSearchEnabled,
  knowledgeBases,
  messages,
  isStreaming,
  setWebSearchEnabled,
  setKnowledgeBaseId,
  setStreaming,
  setAbortController,
  getAbortController,
  setOriginalUserMessage,
  setOnboardingMode,
  onboardingMode,
  addMessage,
  updateLastMessage,
  clearMessages,
  setSessionId,
  updateLastMessageAttachments,
  clearLastMessageConfirmation,
  updateTeamStatus,
  setTeamPhase,
  setIntegratingContent,
  researchMode,
  isResearching,
  researchTaskId,
  setResearchMode,
  setResearchTaskId,
  setResearching,
  updateResearchProgress,
  setResearchPlan,
  setClarificationQuestions,
  clearClarification,
  clearResearch,
} from '@/stores'
import { chatApi, sessionApi, webSearchApi, teamApi, researchApi } from '@/api'
import { useStream } from '@/composables/useStream'
import { generateId } from '@/utils'
import type { DirectionSpec, ClarificationQuestion, ResearchProgress } from '@/types'

const { streamEvents, abort, createAbortController, reset } = useStream()
const inputText = ref('')
const messageListRef = ref<HTMLElement | null>(null)

// 团队模式轮询
let teamPollingTimer: ReturnType<typeof setInterval> | null = null

// 当前累积的内容（用于流式输出）
let accumulatedContent = ''

const selectedKnowledgeBase = computed({
  get: () => store.settings.knowledgeBaseId || '',
  set: (value: string) => {
    setKnowledgeBaseId(value || null)
    if (store.session.currentId) {
      sessionApi.setKnowledgeBase(store.session.currentId, value || null).catch(console.error)
    }
  },
})

async function sendMessage(content: string, isNewSession = false) {
  if (!content.trim()) return
  console.log('[ChatView] Sending message:', content.substring(0, 50) + '...')
  setOriginalUserMessage(content)
  
  // 重置累积内容
  accumulatedContent = ''

  if (onboardingMode.value) {
    await handleOnboardingReply(content)
    return
  }

  if (isNewSession || !store.session.currentId) {
    await createNewSession()
    if (store.settings.knowledgeBaseId && store.session.currentId) {
      try {
        await sessionApi.setKnowledgeBase(store.session.currentId, store.settings.knowledgeBaseId)
      } catch (e) {
        console.error('[ChatView] Sync knowledge base error:', e)
      }
    }
  }

  // 添加用户消息
  addMessage({
    id: generateId(),
    role: 'user',
    content: content,
    timestamp: new Date().toISOString()
  })
  inputText.value = ''
  setStreaming(true)

  const controller = createAbortController()
  setAbortController(controller)
  
  try {
    console.log('[ChatView] Starting stream request...')
    const response = await chatApi.stream(content, controller.signal)
    
    // 检查响应状态
    if (!response.ok) {
      console.error('[ChatView] Stream response not ok:', response.status, response.statusText)
      updateLastMessage(`请求失败: ${response.status} ${response.statusText}`)
      return
    }
    
    // 添加 AI 消息占位
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    })
    console.log('[ChatView] AI message placeholder added, processing stream...')

    // 处理流式响应
    let eventCount = 0
    for await (const event of streamEvents(response)) {
      eventCount++
      console.log('[ChatView] Received event:', event.type, event)
      
      // 检查是否被取消
      if (!getAbortController()) {
        console.log('[ChatView] Stream aborted')
        break
      }
      
      handleStreamEvent(event)
    }
    
    console.log('[ChatView] Stream completed, total events:', eventCount)
  } catch (error: unknown) {
    console.error('[ChatView] Stream error:', error)
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        console.log('[ChatView] Request aborted by user')
      } else {
        updateLastMessage(`发生错误: ${error.message}`)
      }
    } else {
      updateLastMessage('发生错误，请重试')
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
    console.log('[ChatView] Stream finished')
  }

  await loadSessions()
}

function handleStreamEvent(event: { type: string; [key: string]: unknown }) {
  console.log('[ChatView] Handling event:', event.type, JSON.stringify(event).substring(0, 200))
  
  switch (event.type) {
    // 流式内容输出
    case 'content':
      if (typeof event.accumulated === 'string') {
        accumulatedContent = event.accumulated
        updateLastMessage(accumulatedContent)
      } else if (typeof event.content === 'string') {
        accumulatedContent += event.content
        updateLastMessage(accumulatedContent)
      }
      break
    
    // 工具调用结果
    case 'tool_result':
      if (typeof event.content === 'string') {
        // 追加工具结果到当前内容
        accumulatedContent += '\n\n' + event.content
        updateLastMessage(accumulatedContent)
      }
      break
    
    // 取消
    case 'cancelled':
      if (typeof event.content === 'string' && event.content) {
        updateLastMessage(event.content)
      } else if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      break
    
    // 确认请求
    case 'confirmation_required':
    case 'dangerous_command':
      console.log('[ChatView] Confirmation required:', event)
      // 先更新当前内容
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      // 设置确认卡片
      updateLastMessageAttachments({
        confirmation: {
          command: event.command as string || '',
          working_dir: event.working_dir as string || '',
          is_dangerous: event.is_dangerous as boolean || false,
          reason: event.reason as string || '',
          command_type: event.command_type as string || '',
          operation: event.operation as string || '',
        }
      })
      setStreaming(false)
      setAbortController(null)
      break
    
    // 递归限制
    case 'recursion_limit_reached':
    case 'context_limit_reached':
      console.log('[ChatView] Recursion/Context limit reached:', event.type)
      // 先更新当前内容
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      updateLastMessageAttachments({
        recursionLimit: {
          message: (event.message as string) || '已达到最大执行步数限制',
          partial_output: (event.partial_output as string) || accumulatedContent,
        }
      })
      setStreaming(false)
      setAbortController(null)
      break
    
    // 完成
    case 'done':
      console.log('[ChatView] Done event received')
      // 更新最终内容
      if (typeof event.content === 'string' && event.content) {
        updateLastMessage(event.content)
      } else if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      // 只有非团队模式才停止轮询和清除团队状态
      // 团队模式的 done 事件会在 team_complete 后发送，此时轮询已经停止
      // 如果是单Agent模式收到 done，需要检查是否在团队模式中
      const lastMsg = store.chat.messages[store.chat.messages.length - 1]
      const isInTeamMode = lastMsg?.attachments?.teamPhase !== undefined
      if (!isInTeamMode) {
        stopTeamPolling()
        setTeamPhase(undefined)
      }
      break
    
    // 错误
    case 'error':
      console.error('[ChatView] Error event:', event)
      const errorMsg = (event.content as string) || (event.output as string) || '发生错误'
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent + '\n\n❌ ' + errorMsg)
      } else {
        updateLastMessage('❌ ' + errorMsg)
      }
      break
    
    // 首次对话引导
    case 'onboarding_required':
      if (typeof event.message === 'string') {
        updateLastMessage(event.message)
      }
      setStreaming(false)
      setOnboardingMode(true)
      break
    
    // 团队模式开始（任务拆解已完成）
    case 'team_mode_start':
      console.log('[ChatView] Team mode started, tasks ready', event)
      // 设置 teamPhase 为 running（任务已拆解完成）
      setTeamPhase('running')
      const decisionData = (event.decision as Record<string, unknown>) || {}
      updateTeamStatus({
        status: 'active',
        total_tasks: (event.total_tasks as number) || 0,
        parallel_groups: (event.parallel_groups as number) || 0,
        completed: 0,
        in_progress: 0,
        tasks: [],
        complexity_score: (decisionData.complexity_score as number) || undefined,
      })
      // 开始轮询团队状态
      startTeamPolling()
      break

    // 团队开始执行（任务拆解完成）
    case 'team_start':
      console.log('[ChatView] Team start, tasks decomposed', event)
      // 更新任务信息并切换到 running 阶段
      setTeamPhase('running')
      updateTeamStatus({
        status: 'active',
        total_tasks: (event.total_tasks as number) || 0,
        parallel_groups: (event.parallel_groups as number) || 0,
        completed: 0,
        in_progress: 0,
        tasks: [],
      })
      break

    // 并行组开始
    case 'group_start':
      console.log('[ChatView] Group start', event)
      // 不需要特殊处理，轮询会更新状态
      break

    // 任务完成
    case 'task_complete':
      console.log('[ChatView] Task complete', event)
      // 不需要特殊处理，轮询会更新状态
      break

    // 并行组完成
    case 'group_complete':
      console.log('[ChatView] Group complete', event)
      // 不需要特殊处理，轮询会更新状态
      break

    // 团队整合开始
    case 'team_integrating':
      console.log('[ChatView] Team integrating', event)
      stopTeamPolling()
      setTeamPhase('integrating')
      break
    
    // 单Agent模式切换（后端决定使用单Agent）
    case 'single_agent_mode':
      console.log('[ChatView] Backend switched to single agent mode')
      // 停止团队轮询
      stopTeamPolling()
      // 清除团队状态
      setTeamPhase(undefined)
      // 不做其他处理，让后续的 content 事件正常处理
      break
    
    // 任务拆解
    case 'task_decomposition':
      console.log('[ChatView] Task decomposition')
      break
    
    // 团队进度事件（带 stage 字段的兼容格式）
    case 'team_progress':
      console.log('[ChatView] Team progress event', event)
      // 处理带 stage 字段的兼容格式
      const stage = event.stage as string
      if (stage === 'decomposition') {
        // 任务拆解中，保持 init 阶段
        console.log('[ChatView] Task decomposition stage')
      } else if (stage === 'start') {
        // 任务拆解完成，切换到 running 阶段
        console.log('[ChatView] Team start stage, switching to running')
        setTeamPhase('running')
        updateTeamStatus({
          status: 'active',
          total_tasks: (event.total_tasks as number) || 0,
          parallel_groups: (event.parallel_groups as number) || 0,
          completed: 0,
          in_progress: 0,
          tasks: [],
        })
      } else if (stage === 'group_start') {
        // 并行组开始，切换到 running 阶段（确保）
        if (store.chat.messages[store.chat.messages.length - 1]?.attachments?.teamPhase !== 'running') {
          setTeamPhase('running')
        }
      } else if (stage === 'task_start' || stage === 'task_complete') {
        // 任务状态变化，轮询会更新
      } else if (stage === 'integrating') {
        stopTeamPolling()
        setTeamPhase('integrating')
      }
      break
    
    // 团队整合内容
    case 'team_integrating_content':
      // 整合结果 - 停止轮询
      stopTeamPolling()
      setTeamPhase('integrating')
      console.log('[ChatView] Team integrating content')
      if (typeof event.accumulated === 'string') {
        setIntegratingContent(event.accumulated)
        // 同时更新主消息内容
        updateLastMessage(event.accumulated)
      } else if (typeof event.content === 'string') {
        setIntegratingContent(event.content)
      }
      break
    
    // 团队完成
    case 'team_complete':
      console.log('[ChatView] Team complete')
      stopTeamPolling()
      if (typeof event.content === 'string') {
        updateLastMessage(event.content)
      }
      setTeamPhase('done')
      break
    
    // 默认处理：记录未知类型
    default:
      console.log('[ChatView] Unknown event type:', event.type, event)
      // 尝试处理可能有 content 的情况
      if (typeof event.content === 'string') {
        accumulatedContent += event.content
        updateLastMessage(accumulatedContent)
      }
  }
}

// 团队状态轮询
function startTeamPolling() {
  if (teamPollingTimer) {
    clearInterval(teamPollingTimer)
  }
  console.log('[ChatView] Starting team polling...')
  
  // 立即执行一次
  pollTeamStatus()
  
  // 每500ms轮询一次（与 index.html 保持一致）
  teamPollingTimer = setInterval(() => {
    console.log('[ChatView] Polling interval triggered')
    pollTeamStatus()
  }, 500)
  console.log('[ChatView] Polling timer set:', teamPollingTimer)
}

async function pollTeamStatus() {
  console.log('[ChatView] pollTeamStatus called, timer:', teamPollingTimer)
  try {
    const data = await teamApi.status()
    console.log('[ChatView] Team status response:', data)
    if (data.team_status) {
      console.log('[ChatView] Team status polled:', data.team_status)
      
      // 更新团队状态
      updateTeamStatus(data.team_status)
      
      // 根据轮询数据自动切换 phase
      // 如果有任务数据（total_tasks > 0），切换到 running 阶段
      if (data.team_status.total_tasks > 0 && data.team_status.tasks && data.team_status.tasks.length > 0) {
        const lastMessage = store.chat.messages[store.chat.messages.length - 1]
        const currentPhase = lastMessage?.attachments?.teamPhase
        if (currentPhase === 'init') {
          console.log('[ChatView] Auto switching phase to running from polling')
          setTeamPhase('running')
        }
      }
      
      // 只有在 completed 时停止轮询，idle 时不停止（任务可能还在拆解中）
      if (data.team_status.status === 'completed') {
        console.log('[ChatView] Team completed, stopping polling')
        stopTeamPolling()
      }
    } else {
      console.log('[ChatView] No team_status in response')
    }
  } catch (e) {
    console.error('[ChatView] Team polling error:', e)
  }
}

function stopTeamPolling() {
  console.log('[ChatView] stopTeamPolling called, timer:', teamPollingTimer)
  if (teamPollingTimer) {
    clearInterval(teamPollingTimer)
    teamPollingTimer = null
  }
}

// 确认命令
async function handleConfirm(command: string, userMessage: string) {
  console.log('[ChatView] Confirming command:', command)
  
  // 清除确认卡片
  clearLastMessageConfirmation()
  setStreaming(true)
  
  // 重置累积内容
  accumulatedContent = ''
  
  const controller = createAbortController()
  setAbortController(controller)
  
  try {
    const response = await chatApi.confirm(command, userMessage, controller.signal)
    
    // 添加新的 AI 消息
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    })
    
    for await (const event of streamEvents(response)) {
      if (!getAbortController()) break
      handleStreamEvent(event)
    }
  } catch (error) {
    if (error instanceof Error && error.name !== 'AbortError') {
      console.error('[ChatView] Confirm error:', error)
      updateLastMessage('执行命令失败: ' + error.message)
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
  
  await loadSessions()
}

// 取消命令
async function handleCancel(command: string, userMessage: string) {
  console.log('[ChatView] Cancelling command:', command)
  
  // 清除确认卡片
  clearLastMessageConfirmation()
  setStreaming(true)
  
  // 重置累积内容
  accumulatedContent = ''
  
  const controller = createAbortController()
  setAbortController(controller)
  
  try {
    const response = await chatApi.cancel(command, userMessage, controller.signal)
    
    // 添加新的 AI 消息
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    })
    
    for await (const event of streamEvents(response)) {
      if (!getAbortController()) break
      handleStreamEvent(event)
    }
  } catch (error) {
    if (error instanceof Error && error.name !== 'AbortError') {
      console.error('[ChatView] Cancel error:', error)
      updateLastMessage('取消命令失败')
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
}

// 继续递归任务
async function handleContinue() {
  console.log('[ChatView] Continuing task...')
  
  // 清除递归限制卡片
  updateLastMessageAttachments({ recursionLimit: undefined })
  setStreaming(true)
  
  // 重置累积内容
  accumulatedContent = ''
  
  const controller = createAbortController()
  setAbortController(controller)
  
  try {
    const response = await chatApi.continue(controller.signal)
    
    for await (const event of streamEvents(response)) {
      if (!getAbortController()) break
      handleStreamEvent(event)
    }
  } catch (error) {
    if (error instanceof Error && error.name !== 'AbortError') {
      console.error('[ChatView] Continue error:', error)
      updateLastMessage('继续执行失败')
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
  
  await loadSessions()
}

async function handleOnboardingReply(message: string) {
  setOnboardingMode(false)
  addMessage({
    id: generateId(),
    role: 'user',
    content: message,
    timestamp: new Date().toISOString()
  })
  inputText.value = ''
  setStreaming(true)

  try {
    const data = await chatApi.onboardingReply(message)
    setStreaming(false)

    if (data.type === 'response') {
      addMessage({
        id: generateId(),
        role: 'assistant',
        content: data.output || '',
        timestamp: new Date().toISOString()
      })
    } else if (data.type === 'onboarding_required' && data.need_retry) {
      addMessage({
        id: generateId(),
        role: 'assistant',
        content: data.message || '',
        timestamp: new Date().toISOString()
      })
      setOnboardingMode(true)
    } else if (data.type === 'error') {
      addMessage({
        id: generateId(),
        role: 'assistant',
        content: '错误: ' + (data.output || '未知错误'),
        timestamp: new Date().toISOString()
      })
    }
    console.log('[ChatView] Onboarding reply processed')
  } catch (error) {
    console.error('[ChatView] Onboarding reply error:', error)
    setStreaming(false)
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '发生错误，请重试',
      timestamp: new Date().toISOString()
    })
  }
}

async function createNewSession() {
  try {
    const data = await sessionApi.create()
    if (data.session_id) {
      setSessionId(data.session_id)
      clearMessages()
      if (webSearchEnabled.value) {
        await toggleWebSearch(true)
      }
      console.log('[ChatView] New session created:', data.session_id)
    }
  } catch (error) {
    console.error('[ChatView] Create session error:', error)
  }
}

async function loadSessions() {
  try {
    const data = await sessionApi.list()
    store.session.list = data.sessions || []
  } catch (error) {
    console.error('[ChatView] Load sessions error:', error)
  }
}

async function stopGeneration() {
  console.log('[ChatView] Stopping generation...')
  if (getAbortController()) {
    try {
      await chatApi.stop()
      console.log('[ChatView] Stop request sent')
    } catch (e) {
      console.error('[ChatView] Stop request error:', e)
    }
    abort()
  }
  stopTeamPolling()
  setStreaming(false)
  setAbortController(null)
}

async function toggleWebSearch(enabled?: boolean) {
  const newValue = enabled ?? !webSearchEnabled.value
  setWebSearchEnabled(newValue)
  if (store.session.currentId) {
    try {
      await webSearchApi.toggle(newValue)
      console.log('[ChatView] Web search toggled:', newValue)
    } catch (error) {
      console.error('[ChatView] Toggle web search error:', error)
      setWebSearchEnabled(!newValue)
    }
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleSend() {
  const text = inputText.value.trim()
  if (!text) return

  // 如果正在研究中，发送干预消息
  if (isResearching.value && researchTaskId.value) {
    sendResearchIntervention(text)
    return
  }

  if (isStreaming.value) return

  // 根据研究模式选择发送方式
  if (researchMode.value === 'standard') {
    // 标准研究模式
    startResearch(text, 'standard')
  } else if (researchMode.value === 'deep') {
    // 深度研究模式
    startResearch(text, 'deep')
  } else {
    // 普通对话
    sendMessage(text, false)
  }
}

// 发送研究干预消息
async function sendResearchIntervention(message: string) {
  console.log('[ChatView] Sending research intervention:', message.substring(0, 50) + '...')

  const taskId = researchTaskId.value
  if (!taskId) {
    console.error('[ChatView] No research task ID for intervention')
    return
  }

  // 添加用户消息
  addMessage({
    id: generateId(),
    role: 'user',
    content: message,
    timestamp: new Date().toISOString()
  })
  inputText.value = ''

  const controller = createAbortController()
  setAbortController(controller)

  try {
    // 第一步：POST /intervene 获取响应（JSON）
    console.log('[ChatView] Step 1: Calling /intervene endpoint...')
    const interveneResponse = await researchApi.intervene(taskId, message, controller.signal)

    if (!interveneResponse.ok) {
      console.error('[ChatView] Intervention failed:', interveneResponse.status)
      updateLastMessage(`发送干预消息失败: ${interveneResponse.status} ${interveneResponse.statusText}`)
      return
    }

    // 解析 JSON 响应
    const interveneData = await interveneResponse.json() as { task_id?: string; status?: string; error?: string }
    console.log('[ChatView] /intervene response:', interveneData)

    if (!interveneData.task_id) {
      console.error('[ChatView] No task_id in /intervene response:', interveneData)
      updateLastMessage('发送干预消息失败: 未获取到任务ID')
      return
    }

    updateLastMessage('干预消息已发送，正在连接事件流...')

    // 第二步：GET /events 建立 SSE 连接
    console.log('[ChatView] Step 2: Connecting to /events endpoint...')
    const eventsResponse = await researchApi.events(taskId, controller.signal)

    if (!eventsResponse.ok) {
      console.error('[ChatView] Events connection failed:', eventsResponse.status)
      updateLastMessage(`事件流连接失败: ${eventsResponse.status} ${eventsResponse.statusText}`)
      return
    }

    // 处理干预响应的事件流
    for await (const event of streamEvents(eventsResponse)) {
      if (!getAbortController()) break
      handleResearchEvent(event)
    }

    console.log('[ChatView] Intervention processed')
  } catch (error: unknown) {
    console.error('[ChatView] Intervention error:', error)
    if (error instanceof Error && error.name !== 'AbortError') {
      updateLastMessage('发送干预消息失败: ' + error.message)
    }
  } finally {
    setAbortController(null)
    reset()
  }
}

// 研究模式下拉选择
const selectedMode = computed({
  get: () => researchMode.value,
  set: (value: 'chat' | 'standard' | 'deep') => {
    setResearchMode(value)
    console.log('[ChatView] Research mode changed to:', value)
  }
})

// 循环切换模式（已废弃，使用下拉选择）
// function cycleResearchMode() {
//   const modes: Array<'chat' | 'standard' | 'deep'> = ['chat', 'standard', 'deep']
//   const currentIndex = modes.indexOf(researchMode.value as 'chat' | 'standard' | 'deep')
//   const nextIndex = (currentIndex + 1) % modes.length
//   const newMode = modes[nextIndex]
//   setResearchMode(newMode)
//   console.log('[ChatView] Research mode cycled to:', newMode)
// }

// 快速切换深度研究（已废弃，使用下拉选择）
// function toggleDeepResearch() {
//   if (researchMode.value === 'deep') {
//     setResearchMode('chat')
//   } else {
//     setResearchMode('deep')
//   }
//   console.log('[ChatView] Deep research toggled:', researchMode.value)
// }

// 开始研究（标准或深度）
async function startResearch(query: string, mode: 'standard' | 'deep') {
  console.log('[ChatView] Starting research:', mode, query.substring(0, 50) + '...')

  // 重置累积内容
  accumulatedContent = ''

  if (!store.session.currentId) {
    await createNewSession()
  }

  // 添加用户消息
  addMessage({
    id: generateId(),
    role: 'user',
    content: query,
    timestamp: new Date().toISOString()
  })
  inputText.value = ''
  setStreaming(true)
  setResearching(true)

  const controller = createAbortController()
  setAbortController(controller)

  try {
    // 添加 AI 消息占位
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString()
    })

    // 第一步：POST /start 获取 task_id（JSON 响应）
    console.log('[ChatView] Step 1: Calling /start endpoint with mode:', mode)
    const startResponse = await researchApi.start(query, mode, controller.signal)

    if (!startResponse.ok) {
      console.error('[ChatView] Research start failed:', startResponse.status)
      updateLastMessage(`研究启动失败: ${startResponse.status} ${startResponse.statusText}`)
      return
    }

    // 解析 JSON 响应，提取 task_id
    const startData = await startResponse.json() as { task_id?: string; status?: string; error?: string }
    console.log('[ChatView] /start response:', startData)

    if (!startData.task_id) {
      console.error('[ChatView] No task_id in /start response:', startData)
      updateLastMessage('研究启动失败: 未获取到任务ID')
      return
    }

    const taskId = startData.task_id
    console.log('[ChatView] Got task_id:', taskId)

    // 提前设置 task_id，确保后续事件处理可用
    setResearchTaskId(taskId)
    updateLastMessage(mode === 'deep' ? '研究任务已创建，正在分析问题...' : '研究任务已创建，正在搜索分析...')

    // 第二步：GET /events 建立 SSE 连接
    console.log('[ChatView] Step 2: Connecting to /events endpoint...')
    const eventsResponse = await researchApi.events(taskId, controller.signal)

    if (!eventsResponse.ok) {
      console.error('[ChatView] Events connection failed:', eventsResponse.status)
      updateLastMessage(`事件流连接失败: ${eventsResponse.status} ${eventsResponse.statusText}`)
      return
    }

    // 处理研究 SSE 事件
    for await (const event of streamEvents(eventsResponse)) {
      if (!getAbortController()) {
        console.log('[ChatView] Research stream aborted')
        break
      }
      handleResearchEvent(event)
    }

    console.log('[ChatView] Research stream completed')
  } catch (error: unknown) {
    console.error('[ChatView] Research error:', error)
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        console.log('[ChatView] Research aborted by user')
      } else {
        updateLastMessage(`研究出错: ${error.message}`)
      }
    } else {
      updateLastMessage('研究出错，请重试')
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }

  await loadSessions()
}

// 处理研究事件
function handleResearchEvent(event: { type: string; [key: string]: unknown }) {
  console.log('[ChatView] Research event:', event.type, event)
  
  switch (event.type) {
    // 研究任务创建
    case 'research_task_created':
      if (event.task_id) {
        setResearchTaskId(event.task_id as string)
      }
      updateLastMessage('正在分析您的问题...')
      break
    
    // 分析中
    case 'research_analyzing':
      updateLastMessage('正在深度分析您的问题...')
      break
    
    // 需要澄清
    case 'research_clarification_needed':
      if (event.questions && event.task_id) {
        setClarificationQuestions(event.task_id as string, event.questions as ClarificationQuestion[])
      }
      break
    
    // 研究计划生成
    case 'research_plan_generated':
      if (event.task_id && event.directions) {
        setResearchPlan({
          task_id: event.task_id as string,
          directions: event.directions as DirectionSpec[],
          estimated_time: (event.estimated_time as string) || '约 2-5 分钟',
          can_modify: (event.can_modify as boolean) !== false,
        })
        updateLastMessage('研究计划已生成，请确认后开始研究')
      }
      break
    
    // 研究进度更新
    case 'research_progress':
      // 后端推送的是 summary 和 progress_pct，不是 progress
      if (event.summary) {
        updateLastMessage(event.summary as string)
      }
      if (event.progress) {
        updateResearchProgress(event.progress as ResearchProgress)
      }
      break
    
    // 研究方向进度
    case 'research_direction_progress':
      // 更新研究进度中的方向信息
      if (event.direction_progress) {
        const currentProgress = store.chat.messages[store.chat.messages.length - 1]?.attachments?.researchProgress
        if (currentProgress && event.direction_progress) {
          const dirProgress = event.direction_progress as { direction_id: string; direction_name: string; status: string; progress: number; current_action: string; learnings_count: number; sources_count: number }
          const updatedDirections = currentProgress.directions.map(d => 
            d.direction_id === dirProgress.direction_id ? { ...d, ...dirProgress } as typeof d : d
          )
          updateResearchProgress({ ...currentProgress, directions: updatedDirections })
        }
      }
      break
    
    // 研究完成
    case 'research_completed':
      console.log('[ChatView] Research completed')
      stopTeamPolling()
      if (event.content) {
        updateLastMessage(event.content as string)
      }
      // 更新消息附件，添加下载按钮
      if (event.task_id) {
        updateLastMessageAttachments({
          researchCompleted: {
            task_id: event.task_id as string,
            report_url: event.report_url as string | undefined,
            source_count: (event.source_count as number) || 0,
            duration_seconds: (event.duration_seconds as number) || 0,
          }
        })
      }
      clearResearch()
      break
    
    // 研究错误
    case 'research_error':
      console.error('[ChatView] Research error event:', event)
      const errorMsg = (event.error_message as string) || '研究过程中发生错误'
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent + '\n\n' + errorMsg)
      } else {
        updateLastMessage(errorMsg)
      }
      clearResearch()
      break
    
    // 内容输出
    case 'content':
      if (typeof event.accumulated === 'string') {
        accumulatedContent = event.accumulated
        updateLastMessage(accumulatedContent)
      } else if (typeof event.content === 'string') {
        accumulatedContent += event.content
        updateLastMessage(accumulatedContent)
      }
      break
    
    // 完成
    case 'done':
      if (typeof event.content === 'string' && event.content) {
        updateLastMessage(event.content)
      } else if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      break
    
    // 默认处理
    default:
      console.log('[ChatView] Unknown research event:', event.type)
  }
}

// 取消研究
async function handleResearchCancel(taskId: string) {
  console.log('[ChatView] Cancelling research:', taskId)
  try {
    await researchApi.cancel(taskId)
    clearResearch()
    updateLastMessage('研究已取消')
  } catch (error) {
    console.error('[ChatView] Cancel research error:', error)
  }
  setStreaming(false)
  setAbortController(null)
}

// 确认研究计划
async function handleResearchConfirmPlan(taskId: string) {
  console.log('[ChatView] Confirming research plan:', taskId)
  
  // 清除计划卡片
  setResearchPlan(undefined)
  setStreaming(true)
  
  const controller = createAbortController()
  setAbortController(controller)
  
  try {
    // ========== 两阶段模式：先建立 SSE 连接，再确认计划 ==========
    // 阶段1：建立 SSE 连接
    console.log('[ChatView] Phase 1: Establishing SSE connection...')
    const eventResponse = await researchApi.events(taskId, controller.signal)
    console.log('[ChatView] SSE connection established')
    
    // 阶段2：确认计划（会启动异步任务）
    console.log('[ChatView] Phase 2: Confirming plan...')
    const response = await researchApi.confirmPlan(taskId)
    console.log('[ChatView] Plan confirmed:', response)
    
    updateLastMessage('研究计划已确认，开始执行研究...')
    
    // 处理研究事件
    for await (const event of streamEvents(eventResponse)) {
      if (!getAbortController()) break
      handleResearchEvent(event)
    }
  } catch (error) {
    console.error('[ChatView] Confirm plan error:', error)
    if (error instanceof Error) {
      updateLastMessage('确认计划失败: ' + error.message)
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
}

// 修改研究计划
async function handleResearchModifyPlan(taskId: string, directions: DirectionSpec[]) {
  console.log('[ChatView] Modifying research plan:', taskId, directions)
  
  try {
    await researchApi.updatePlan(taskId, directions)
    // 修改成功后直接确认
    await handleResearchConfirmPlan(taskId)
  } catch (error) {
    console.error('[ChatView] Modify plan error:', error)
    if (error instanceof Error) {
      updateLastMessage('修改计划失败: ' + error.message)
    }
  }
}

// 回答澄清问题
async function handleResearchClarify(taskId: string, answers: Record<number, string>) {
  console.log('[ChatView] Submitting clarification answers:', taskId, answers)

  // 清除澄清问题卡片
  clearClarification()
  setStreaming(true)

  const controller = createAbortController()
  setAbortController(controller)

  try {
    // 将答案组合成文本
    const answerText = Object.entries(answers)
      .map(([idx, ans]) => `Q${parseInt(idx) + 1}: ${ans}`)
      .join('\n')

    // 第一步：POST /resume 获取响应（JSON）
    console.log('[ChatView] Step 1: Calling /resume endpoint...')
    const resumeResponse = await researchApi.resume(taskId, answerText, controller.signal)

    if (!resumeResponse.ok) {
      console.error('[ChatView] Resume failed:', resumeResponse.status)
      updateLastMessage(`恢复研究失败: ${resumeResponse.status} ${resumeResponse.statusText}`)
      return
    }

    // 解析 JSON 响应
    const resumeData = await resumeResponse.json() as { task_id?: string; status?: string; error?: string }
    console.log('[ChatView] /resume response:', resumeData)

    if (!resumeData.task_id) {
      console.error('[ChatView] No task_id in /resume response:', resumeData)
      updateLastMessage('恢复研究失败: 未获取到任务ID')
      return
    }

    // 清空之前的内容
    accumulatedContent = ''
    updateLastMessage('研究已恢复，正在连接事件流...')

    // 第二步：GET /events 建立 SSE 连接
    console.log('[ChatView] Step 2: Connecting to /events endpoint...')
    const eventsResponse = await researchApi.events(taskId, controller.signal)

    if (!eventsResponse.ok) {
      console.error('[ChatView] Events connection failed:', eventsResponse.status)
      updateLastMessage(`事件流连接失败: ${eventsResponse.status} ${eventsResponse.statusText}`)
      return
    }

    for await (const event of streamEvents(eventsResponse)) {
      if (!getAbortController()) break
      handleResearchEvent(event)
    }
  } catch (error) {
    console.error('[ChatView] Clarify error:', error)
    if (error instanceof Error) {
      updateLastMessage('提交答案失败: ' + error.message)
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
}

// 跳过澄清问题
async function handleResearchClarifySkip(taskId: string) {
  console.log('[ChatView] Skipping clarification:', taskId)

  // 清除澄清问题卡片
  clearClarification()
  setStreaming(true)

  const controller = createAbortController()
  setAbortController(controller)

  try {
    // 第一步：POST /resume 获取响应（JSON）
    console.log('[ChatView] Step 1: Calling /resume endpoint (skip)...')
    const resumeResponse = await researchApi.resume(taskId, '使用默认设置继续', controller.signal)

    if (!resumeResponse.ok) {
      console.error('[ChatView] Resume (skip) failed:', resumeResponse.status)
      updateLastMessage(`继续研究失败: ${resumeResponse.status} ${resumeResponse.statusText}`)
      return
    }

    // 解析 JSON 响应
    const resumeData = await resumeResponse.json() as { task_id?: string; status?: string; error?: string }
    console.log('[ChatView] /resume (skip) response:', resumeData)

    accumulatedContent = ''
    updateLastMessage('研究已恢复，正在连接事件流...')

    // 第二步：GET /events 建立 SSE 连接
    console.log('[ChatView] Step 2: Connecting to /events endpoint...')
    const eventsResponse = await researchApi.events(taskId, controller.signal)

    if (!eventsResponse.ok) {
      console.error('[ChatView] Events connection failed:', eventsResponse.status)
      updateLastMessage(`事件流连接失败: ${eventsResponse.status} ${eventsResponse.statusText}`)
      return
    }

    for await (const event of streamEvents(eventsResponse)) {
      if (!getAbortController()) break
      handleResearchEvent(event)
    }
  } catch (error) {
    console.error('[ChatView] Skip clarification error:', error)
    if (error instanceof Error) {
      updateLastMessage('继续研究失败: ' + error.message)
    }
  } finally {
    setStreaming(false)
    setAbortController(null)
    reset()
  }
}

// 下载研究报告
async function handleResearchDownload(taskId: string, format: 'markdown' | 'pdf') {
  console.log('[ChatView] Downloading research report:', taskId, format)
  try {
    const response = await researchApi.downloadReport(taskId, format)
    if (!response.ok) {
      console.error('[ChatView] Download failed:', response.status)
      return
    }
    // 获取文件名
    const contentDisposition = response.headers.get('Content-Disposition')
    let filename = `research-report-${taskId}.${format === 'pdf' ? 'pdf' : 'md'}`
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^"]+)"?/)
      if (match) {
        filename = match[1]
      }
    }
    // 下载文件
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    console.log('[ChatView] Report downloaded:', filename)
  } catch (error) {
    console.error('[ChatView] Download error:', error)
  }
}

// 清理
onUnmounted(() => {
  stopTeamPolling()
})

// 滚动到底部
watch(messages, () => {
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}, { deep: true })
</script>

<template>
  <div class="chat-view">
    <!-- 背景光晕 -->
    <div class="chat-bg" aria-hidden="true">
      <div class="glow glow-purple" />
      <div class="glow glow-cyan" />
    </div>

    <!-- Header -->
    <header class="chat-header">
      <div class="header-icon">
        <Bot class="w-4 h-4" />
      </div>
      <h1 class="header-title">MalogBot</h1>
      <span class="header-badge">AI 助手</span>
    </header>

    <!-- 消息列表 -->
    <MessageList 
      ref="messageListRef" 
      :messages="messages" 
      :is-streaming="isStreaming"
      @confirm="handleConfirm"
      @cancel="handleCancel"
      @continue="handleContinue"
      @research-cancel="handleResearchCancel"
      @research-confirm-plan="handleResearchConfirmPlan"
      @research-modify-plan="handleResearchModifyPlan"
      @research-clarify="handleResearchClarify"
      @research-clarify-skip="handleResearchClarifySkip"
      @research-download="handleResearchDownload"
    />

    <!-- 输入区域 -->
    <footer class="chat-footer">
      <div class="input-bar">
        <!-- 研究模式下拉选择器 -->
        <div class="mode-selector">
          <select v-model="selectedMode" class="mode-select">
            <option value="chat">普通对话</option>
            <option value="standard">标准研究</option>
            <option value="deep">深度研究</option>
          </select>
        </div>

        <!-- 联网搜索和知识库只在普通对话模式显示 -->
        <template v-if="researchMode === 'chat'">
          <!-- 联网搜索开关 -->
          <button
            class="option-btn"
            :class="{ 'option-btn-active': webSearchEnabled }"
            @click="() => toggleWebSearch()"
          >
            <Globe class="w-4 h-4" />
            <span>联网搜索</span>
            <label class="toggle">
              <input type="checkbox" :checked="webSearchEnabled" class="sr-only" @change="() => toggleWebSearch()" />
              <span class="toggle-track" :class="{ 'toggle-track-on': webSearchEnabled }">
                <span class="toggle-thumb" :class="{ 'toggle-thumb-on': webSearchEnabled }" />
              </span>
            </label>
          </button>

          <!-- 知识库选择 -->
          <div class="option-btn">
            <BookOpen class="w-4 h-4" />
            <select
              v-model="selectedKnowledgeBase"
              class="kb-select"
            >
              <option value="">不使用知识库</option>
              <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
                {{ kb.name }} ({{ kb.document_count }}个文档)
              </option>
            </select>
          </div>
        </template>

        <!-- 研究模式提示 -->
        <div v-if="researchMode !== 'chat'" class="research-hint">
          <span>研究过程中将自动联网搜索</span>
        </div>
      </div>

      <!-- 输入框和按钮 -->
      <div class="input-group">
        <input
          v-model="inputText"
          type="text"
          class="input-field"
          :class="{ 'input-field-focused': inputText }"
          placeholder="输入消息..."
          autocomplete="off"
          :disabled="isStreaming"
          @keydown="handleKeydown"
        />
        <button
          v-if="!isStreaming"
          class="send-btn"
          :disabled="!inputText.trim()"
          @click="handleSend"
        >
          <Send class="w-4 h-4" />
        </button>
        <button
          v-else
          class="stop-btn"
          @click="stopGeneration"
        >
          <Square class="w-3.5 h-3.5" />
          <span>停止</span>
        </button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.chat-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: relative;
  overflow: hidden;
  background: var(--bg-base);
}

/* 背景光晕 */
.chat-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(130px);
}

.glow-purple {
  top: -80px;
  right: -64px;
  width: 400px;
  height: 400px;
  background: rgba(124, 58, 237, 0.1);
}

.glow-cyan {
  bottom: -64px;
  left: -64px;
  width: 350px;
  height: 350px;
  background: rgba(6, 182, 212, 0.06);
}

/* Header */
.chat-header {
  position: relative;
  z-index: 10;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.header-icon {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.25);
  color: white;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.header-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 10px;
  border-radius: 9999px;
  background: rgba(124, 58, 237, 0.12);
  color: var(--primary-300);
  border: 1px solid rgba(124, 58, 237, 0.2);
}

/* Footer */
.chat-footer {
  position: relative;
  z-index: 10;
  padding: 12px 24px;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(20px);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.input-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  max-width: 900px;
  margin: 0 auto;
}

/* 选项按钮 */
.option-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  color: var(--text-dim);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms var(--ease-default);
}

.option-btn:hover {
  background: rgba(255, 255, 255, 0.06);
}

.option-btn-active {
  background: rgba(124, 58, 237, 0.12);
  border-color: rgba(124, 58, 237, 0.25);
  color: var(--primary-300);
}

/* 研究模式按钮特殊样式 */
.research-mode-btn.option-btn-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.15) 0%, rgba(139, 92, 246, 0.15) 100%);
  border-color: rgba(139, 92, 246, 0.35);
  color: #C4B5FD;
}

.kb-select {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  outline: none;
  max-width: 150px;
  appearance: none;
  padding-right: 4px;
}

/* Toggle 开关 */
.toggle {
  position: relative;
  width: 36px;
  height: 20px;
  cursor: pointer;
}

.toggle-track {
  position: absolute;
  inset: 0;
  border-radius: 9999px;
  background: var(--text-faint);
  transition: background 200ms var(--ease-default);
}

.toggle-track-on {
  background: var(--primary-600);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: white;
  box-shadow: var(--shadow-sm);
  transition: transform 200ms var(--ease-default);
}

.toggle-thumb-on {
  transform: translateX(16px);
}

/* 输入组 */
.input-group {
  flex: 1;
  display: flex;
  gap: 10px;
  min-width: 220px;
}

/* Sparkles 功能按钮 */
/* 研究模式下拉选择器 */
.mode-selector {
  position: relative;
}

.mode-select {
  padding: 8px 32px 8px 14px;
  border-radius: 12px;
  background: rgba(124, 58, 237, 0.1);
  border: 1px solid rgba(124, 58, 237, 0.25);
  color: #c4b5fd;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23c4b5fd' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  transition: all 200ms var(--ease-default);
}

.mode-select:hover {
  background-color: rgba(124, 58, 237, 0.15);
  border-color: rgba(124, 58, 237, 0.35);
}

.mode-select:focus {
  border-color: rgba(124, 58, 237, 0.5);
  box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.1);
}

.mode-select option {
  background: rgba(17, 24, 39, 0.95);
  color: var(--text-primary);
  padding: 8px;
}

/* 模式按钮（已废弃，使用下拉选择器） */
/* .mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  color: var(--text-dim);
  cursor: pointer;
  transition: all 200ms var(--ease-default);
}

.mode-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.mode-btn-active {
  background: rgba(124, 58, 237, 0.15);
  border-color: rgba(124, 58, 237, 0.3);
  color: #a78bfa;
}

.mode-btn-active:hover {
  background: rgba(124, 58, 237, 0.25);
  color: #c4b5fd;
}

.standard-btn.mode-btn-active {
  background: rgba(6, 182, 212, 0.15);
  border-color: rgba(6, 182, 212, 0.3);
  color: #67e8f9;
}

.standard-btn.mode-btn-active:hover {
  background: rgba(6, 182, 212, 0.25);
  color: #a5f3fc;
}

.deep-btn.mode-btn-active {
  background: rgba(124, 58, 237, 0.15);
  border-color: rgba(124, 58, 237, 0.3);
  color: #a78bfa;
}

.deep-btn.mode-btn-active:hover {
  background: rgba(124, 58, 237, 0.25);
  color: #c4b5fd;
}

.mode-label {
  font-size: 12px;
} */

/* 研究模式提示 */
.research-hint {
  font-size: 13px;
  color: var(--text-faint);
  padding: 8px 14px;
}

.input-field {
  flex: 1;
  padding: 14px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  font-size: 15px;
  transition: all 200ms var(--ease-default);
}

.input-field::placeholder {
  color: var(--text-faint);
}

.input-field-focused,
.input-field:focus {
  border-color: rgba(139, 92, 246, 0.35);
  box-shadow: 0 0 20px rgba(139, 92, 246, 0.1);
}

.send-btn {
  padding: 14px 20px;
  border-radius: 14px;
  background: var(--gradient-brand);
  color: white;
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 200ms var(--ease-default);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-2px);
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
}

.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.stop-btn {
  padding: 14px 20px;
  border-radius: 14px;
  background: linear-gradient(135deg, #DC2626 0%, #EF4444 100%);
  color: white;
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(220, 38, 38, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 200ms var(--ease-default);
}

.stop-btn:hover {
  transform: translateY(-2px);
}
</style>
