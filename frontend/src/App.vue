<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppSidebar from './components/layout/AppSidebar.vue'
import WelcomePage from './components/layout/WelcomePage.vue'
import ChatView from './components/layout/ChatView.vue'
import MCPManagerModal from './components/modal/MCPManagerModal.vue'
import KnowledgeManagerModal from './components/modal/KnowledgeManagerModal.vue'
import {
  store,
  isWelcomeMode,
  setSessions,
  setKnowledgeBases,
  setWebSearchEnabled,
  setSessionId,
  clearMessages,
  setOnboardingMode,
  addMessage,
  setStreaming,
  setAbortController,
  getAbortController,
  updateLastMessage,
  updateLastMessageAttachments,
  updateTeamStatus,
  setTeamPhase,
  setIntegratingContent,
  researchMode,
  setResearching,
  setResearchTaskId,
  clearResearch,
  setClarificationQuestions,
  setResearchPlan,
} from './stores'
import { sessionApi, knowledgeApi, webSearchApi, chatApi, teamApi, researchApi } from './api'
import { useStream } from './composables/useStream'
import { generateId } from './utils'
// 不需要额外导入类型

const { streamEvents, createAbortController, reset } = useStream()

// 模态框状态
const showMCPModal = ref(false)
const showKnowledgeModal = ref(false)

// 团队模式轮询
let teamPollingTimer: ReturnType<typeof setInterval> | null = null

// 当前累积的内容
let accumulatedContent = ''

// 加载数据
onMounted(async () => {
  console.log('[App] Initializing application...')
  await loadSessions()
  await loadKnowledgeBases()
  await loadWebSearchStatus()
})

async function loadSessions() {
  try {
    console.log('[App] Loading sessions...')
    const data = await sessionApi.list()
    setSessions(data.sessions || [])

    // 如果有当前会话且有消息，切换到聊天视图
    if (data.current_session_id) {
      const currentSession = data.sessions?.find(
        (s) => s.session_id === data.current_session_id
      )
      if (currentSession && currentSession.message_count > 0) {
        store.session.currentId = data.current_session_id
        store.session.isWelcomeMode = false

        // 加载历史消息
        await loadSessionHistory(data.current_session_id)
        console.log('[App] Restored session:', data.current_session_id)
      }
    }
  } catch (error) {
    console.error('[App] Load sessions error:', error)
  }
}

async function loadSessionHistory(sessionId: string) {
  try {
    console.log('[App] Loading session history for:', sessionId)
    clearMessages()
    const infoData = await sessionApi.info(sessionId)
    if (infoData.messages && Array.isArray(infoData.messages)) {
      // 只加载 user 和 assistant 消息
      const displayMessages = infoData.messages.filter(
        (msg: { role: string }) => msg.role === 'user' || msg.role === 'assistant'
      )
      displayMessages.forEach((msg: { role: string; content: string; timestamp?: string }) => {
        addMessage({
          id: generateId(),
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          timestamp: msg.timestamp || new Date().toISOString(),
        })
      })
      console.log('[App] Loaded', displayMessages.length, 'messages')
    }
  } catch (error) {
    console.error('[App] Load session history error:', error)
  }
}

async function loadKnowledgeBases() {
  try {
    console.log('[App] Loading knowledge bases...')
    const data = await knowledgeApi.list()
    setKnowledgeBases(data.knowledge_bases || [])
  } catch (error) {
    console.error('[App] Load knowledge bases error:', error)
  }
}

async function loadWebSearchStatus() {
  try {
    const data = await webSearchApi.status()
    setWebSearchEnabled(data.enabled || false)
  } catch (error) {
    console.error('[App] Load web search status error:', error)
  }
}

// 新建对话
function handleNewChat() {
  console.log('[App] Creating new chat...')
  // 停止团队轮询
  stopTeamPolling()
  store.session.isWelcomeMode = true
  store.session.currentId = null
  clearMessages()
  setOnboardingMode(false)
}

// 选择会话
async function handleSelectSession(sessionId: string) {
  try {
    console.log('[App] Selecting session:', sessionId)
    // 停止团队轮询
    stopTeamPolling()
    await sessionApi.switch(sessionId)
    setSessionId(sessionId)
    
    // 加载历史消息
    await loadSessionHistory(sessionId)
    
    store.session.isWelcomeMode = false

    // 加载该会话的联网搜索状态
    await loadWebSearchStatus()
  } catch (error) {
    console.error('[App] Switch session error:', error)
  }
}

// 开始聊天（从欢迎页）
async function handleStartChat(message: string) {
  try {
    console.log('[App] Starting new chat with message:', message.substring(0, 50) + '...', 'mode:', researchMode.value)

    // 创建新会话
    const data = await sessionApi.create()
    if (!data.session_id) {
      console.error('[App] Failed to create session')
      return
    }

    setSessionId(data.session_id)
    clearMessages()

    // 切换到聊天视图
    store.session.isWelcomeMode = false

    // 添加用户消息
    addMessage({
      id: generateId(),
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    })

    // 根据 researchMode 选择处理方式
    if (researchMode.value === 'standard') {
      // 标准研究模式：直接执行多轮搜索分析
      console.log('[App] Starting standard research...')
      await startResearch(message, 'standard')
    } else if (researchMode.value === 'deep') {
      // 深度研究模式：先分析问题、澄清、生成计划确认后执行
      console.log('[App] Starting deep research...')
      await startResearch(message, 'deep')
    } else {
      // 普通对话模式
      // 同步联网搜索状态
      if (store.settings.webSearchEnabled) {
        await webSearchApi.toggle(true)
      }

      // 同步知识库设置
      if (store.settings.knowledgeBaseId) {
        await sessionApi.setKnowledgeBase(data.session_id, store.settings.knowledgeBaseId)
      }

      // 发送消息给 LLM
      await sendMessageToLLM(message)
    }

  } catch (error) {
    console.error('[App] Start chat error:', error)
  }
}

// 启动研究（标准或深度）- 使用两阶段启动模式
async function startResearch(query: string, mode: 'standard' | 'deep') {
  console.log('[App] Starting research:', mode, query.substring(0, 50) + '...')

  // 重置累积内容
  accumulatedContent = ''

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
      timestamp: new Date().toISOString(),
    })

    // ========== 两阶段启动模式 ==========
    // 阶段1: 准备任务（创建任务但不执行）
    console.log('[App] Phase 1: Preparing task with mode:', mode)
    const prepareResponse = await researchApi.prepare(query, mode, controller.signal)

    if (!prepareResponse.ok) {
      console.error('[App] Prepare task failed:', prepareResponse.status)
      updateLastMessage(`研究准备失败: ${prepareResponse.status} ${prepareResponse.statusText}`)
      return
    }

    const prepareData = await prepareResponse.json() as { task_id?: string; status?: string; error?: string }
    console.log('[App] /prepare response:', prepareData)

    if (!prepareData.task_id) {
      console.error('[App] No task_id in /prepare response:', prepareData)
      updateLastMessage('研究准备失败: 未获取到任务ID')
      return
    }

    const taskId = prepareData.task_id
    console.log('[App] Got task_id:', taskId)

    // 设置 task_id
    setResearchTaskId(taskId)
    updateLastMessage('研究任务已创建，正在建立连接...')

    // 阶段2: 建立 SSE 连接
    console.log('[App] Phase 2: Establishing SSE connection...')
    const eventsResponse = await researchApi.events(taskId, controller.signal)

    if (!eventsResponse.ok) {
      console.error('[App] Events connection failed:', eventsResponse.status)
      updateLastMessage(`事件流连接失败: ${eventsResponse.status} ${eventsResponse.statusText}`)
      return
    }
    console.log('[App] SSE connection established')

    // 阶段3: 启动任务执行
    console.log('[App] Phase 3: Starting task execution...')
    const startResponse = await researchApi.startWithTaskId(taskId, controller.signal)

    if (!startResponse.ok) {
      console.error('[App] Start task failed:', startResponse.status)
      updateLastMessage(`研究启动失败: ${startResponse.status} ${startResponse.statusText}`)
      return
    }

    const startData = await startResponse.json() as { task_id?: string; task_status?: string; error?: string }
    console.log('[App] /start response:', startData)

    // 更新消息状态
    updateLastMessage(mode === 'deep' ? '正在分析问题...' : '正在搜索分析...')

    // 处理研究 SSE 事件
    for await (const event of streamEvents(eventsResponse)) {
      if (!getAbortController()) {
        console.log('[App] Research stream aborted')
        break
      }
      handleResearchEvent(event)
    }

    console.log('[App] Research stream completed')
  } catch (error: unknown) {
    console.error('[App] Research error:', error)
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        console.log('[App] Research aborted by user')
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
  console.log('[App] Research event:', event.type, event)

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
      console.log('[App] Clarification needed:', event.questions, 'task_id:', event.task_id)
      // 将澄清问题添加到消息 attachments 中，触发 ClarificationCard 显示
      if (event.questions && Array.isArray(event.questions) && event.task_id) {
        const questions = event.questions as Array<{ question: string; options?: string[] }>
        const taskId = event.task_id as string
        setClarificationQuestions(taskId, questions.map(q => ({
          question: q.question,
          options: q.options || [],
        })))
        updateLastMessage('请回答以下问题以帮助我更好地理解您的需求')
      }
      break

    // 研究计划生成
    case 'research_plan_generated':
      console.log('[App] Plan generated:', event.task_id, event.directions)
      // 将研究计划添加到消息 attachments 中，触发 PlanConfirmCard 显示
      if (event.directions && Array.isArray(event.directions) && event.task_id) {
        const directions = event.directions as Array<{
          name: string
          description: string
          keywords: string[]
          expected_findings?: string
        }>
        const taskId = event.task_id as string
        setResearchPlan({
          task_id: taskId,
          directions: directions.map((d, i) => ({
            id: `dir-${i}`,
            name: d.name,
            description: d.description,
            keywords: d.keywords,
            priority: i + 1,
          })),
          estimated_time: '约 2-5 分钟',
          can_modify: true,
        })
        updateLastMessage('研究计划已生成，请确认后开始研究')
      }
      break

    // 研究进度更新
    case 'research_progress':
      if (event.progress) {
        console.log('[App] Progress:', event.progress)
      }
      if (event.content) {
        accumulatedContent = event.content as string
        updateLastMessage(accumulatedContent)
      }
      break

    // 研究方向进度
    case 'research_direction_progress':
      console.log('[App] Direction progress:', event.direction_progress)
      break

    // 报告流式内容
    case 'research_report_stream':
      if (event.content) {
        accumulatedContent += event.content as string
        updateLastMessage(accumulatedContent)
      }
      break

    // 研究完成
    case 'research_completed':
      console.log('[App] Research completed')
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
          },
        })
      }
      clearResearch()
      break

    // 错误
    case 'research_error':
      console.error('[App] Research error event:', event.message)
      updateLastMessage(`研究出错: ${event.message || '未知错误'}`)
      clearResearch()
      break

    default:
      console.log('[App] Unhandled research event:', event.type)
  }
}

// 发送消息给 LLM
async function sendMessageToLLM(content: string) {
  // 重置累积内容
  accumulatedContent = ''
  
  const controller = createAbortController()
  setStreaming(true)
  setAbortController(controller)
  
  try {
    console.log('[App] Sending message to LLM...')
    const response = await chatApi.stream(content, controller.signal)
    
    // 检查响应状态
    if (!response.ok) {
      console.error('[App] Stream response not ok:', response.status, response.statusText)
      updateLastMessage(`请求失败: ${response.status} ${response.statusText}`)
      return
    }
    
    // 添加 AI 消息占位
    addMessage({
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    })

    // 处理流式响应
    let eventCount = 0
    for await (const event of streamEvents(response)) {
      eventCount++
      console.log('[App] Received event:', event.type, eventCount)
      
      if (!getAbortController()) break
      handleStreamEvent(event)
    }
    
    console.log('[App] Stream completed, total events:', eventCount)
  } catch (error: unknown) {
    console.error('[App] Stream error:', error)
    if (error instanceof Error) {
      if (error.name === 'AbortError') {
        console.log('[App] Request aborted by user')
      } else {
        updateLastMessage(`发生错误: ${error.message}`)
      }
    } else {
      updateLastMessage('发生错误，请重试')
    }
  } finally {
    store.chat.isStreaming = false
    setAbortController(null)
    reset()
  }

  // 刷新会话列表
  await loadSessions()
}

// 处理流事件
function handleStreamEvent(event: { type: string; [key: string]: unknown }) {
  console.log('[App] Handling event:', event.type)
  
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
        accumulatedContent += '\n\n' + event.content
        updateLastMessage(accumulatedContent)
      }
      break
    
    case 'cancelled':
      if (typeof event.content === 'string' && event.content) {
        updateLastMessage(event.content)
      } else if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      break
    
    case 'confirmation_required':
    case 'dangerous_command':
      console.log('[App] Confirmation required:', event)
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
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
    
    case 'recursion_limit_reached':
    case 'context_limit_reached':
      console.log('[App] Limit reached:', event.type)
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
    
    case 'done':
      console.log('[App] Done event received')
      stopTeamPolling()
      if (typeof event.content === 'string' && event.content) {
        updateLastMessage(event.content)
      } else if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      setTeamPhase(undefined)
      break
    
    case 'error':
      console.error('[App] Error event:', event)
      const errorMsg = (event.content as string) || (event.output as string) || '发生错误'
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent + '\n\n❌ ' + errorMsg)
      } else {
        updateLastMessage('❌ ' + errorMsg)
      }
      break
    
    case 'onboarding_required':
      if (typeof event.message === 'string') {
        updateLastMessage(event.message)
      }
      store.chat.onboardingMode = true
      store.chat.isStreaming = false
      break
    
    case 'team_mode_start':
      console.log('[App] Team mode started')
      if (accumulatedContent) {
        updateLastMessage(accumulatedContent)
      }
      setTeamPhase('init')
      updateTeamStatus({
        status: 'running',
        total_tasks: 0,
        completed: 0,
        in_progress: 0,
        tasks: []
      })
      startTeamPolling()
      break
    
    // 单Agent模式切换（后端决定使用单Agent）
    case 'single_agent_mode':
      console.log('[App] Backend switched to single agent mode')
      // 停止团队轮询
      stopTeamPolling()
      // 清除团队状态
      setTeamPhase(undefined)
      // 不做其他处理，让后续的 content 事件正常处理
      break
    
    case 'task_decomposition':
      console.log('[App] Task decomposition')
      break
    
    case 'team_progress':
      // 忽略 SSE 事件，完全由轮询处理（与 index.html 保持一致）
      // event 格式: { stage: 'group_start', tasks: [...], ... }
      break
    
    case 'team_integrating_content':
      // 整合结果 - 停止轮询
      stopTeamPolling()
      setTeamPhase('integrating')
      if (typeof event.accumulated === 'string') {
        setIntegratingContent(event.accumulated)
        updateLastMessage(event.accumulated)
      } else if (typeof event.content === 'string') {
        setIntegratingContent(event.content)
      }
      break
    
    case 'team_complete':
      console.log('[App] Team complete')
      stopTeamPolling()
      if (typeof event.content === 'string') {
        updateLastMessage(event.content)
      }
      setTeamPhase('done')
      break
    
    default:
      console.log('[App] Unknown event type:', event.type, event)
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
  console.log('[App] Starting team polling...')
  
  // 立即执行一次
  pollTeamStatus()
  
  // 每500ms轮询一次（与 index.html 保持一致）
  teamPollingTimer = setInterval(pollTeamStatus, 500)
}

async function pollTeamStatus() {
  try {
    const data = await teamApi.status()
    if (data.team_status) {
      console.log('[App] Team status polled:', data.team_status)
      updateTeamStatus(data.team_status)
      // 如果状态变为 completed 或 idle，停止轮询
      if (data.team_status.status === 'completed' || data.team_status.status === 'idle') {
        stopTeamPolling()
      }
    }
  } catch (e) {
    console.error('[App] Team polling error:', e)
  }
}

function stopTeamPolling() {
  if (teamPollingTimer) {
    clearInterval(teamPollingTimer)
    teamPollingTimer = null
  }
}
</script>

<template>
  <div class="app-container">
    <!-- 侧边栏 -->
    <AppSidebar
      class="flex-shrink-0"
      @new-chat="handleNewChat"
      @open-m-c-p="showMCPModal = true"
      @open-knowledge="showKnowledgeModal = true"
      @select-session="handleSelectSession"
    />

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 欢迎页 -->
      <WelcomePage
        v-if="isWelcomeMode"
        @start-chat="handleStartChat"
      />

      <!-- 聊天视图 -->
      <ChatView v-else />
    </main>

    <!-- MCP 管理模态框 -->
    <MCPManagerModal
      v-if="showMCPModal"
      @close="showMCPModal = false"
    />

    <!-- 知识库管理模态框 -->
    <KnowledgeManagerModal
      v-if="showKnowledgeModal"
      @close="showKnowledgeModal = false"
    />
  </div>
</template>

<style>
.app-container {
  display: flex;
  height: 100vh;
  background: var(--bg-base);
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
