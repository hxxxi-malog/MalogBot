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
} from './stores'
import { sessionApi, knowledgeApi, webSearchApi, chatApi, teamApi } from './api'
import { useResearch } from './composables/useResearch'
import { parseSSEStream } from './composables/useStream'
import { generateId } from './utils'
import { restoreCompletedResearch, restoreInProgressResearch } from './utils/researchRestore'
import type { ResearchTaskRestoreData } from './utils/researchRestore'

const { startResearch: researchStart, connectSSE: researchConnectSSE } = useResearch()

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

    // 恢复研究状态
    if (infoData.research_tasks && Array.isArray(infoData.research_tasks)) {
      let restoredCount = 0
      let inProgressCount = 0
      for (const researchTask of infoData.research_tasks) {
        const taskData = researchTask as ResearchTaskRestoreData
        // 先尝试恢复已完成的研究
        if (restoreCompletedResearch(store.chat.messages, taskData)) {
          restoredCount++
          continue
        }
        // 再尝试恢复进行中的研究，返回 task_id 表示需要 SSE 重连
        const reconnectTaskId = restoreInProgressResearch(store.chat.messages, taskData)
        if (reconnectTaskId) {
          inProgressCount++
          // 设置研究状态
          setResearchTaskId(reconnectTaskId)
          setResearching(true)
          setStreaming(true)
          console.log('[App] Restoring in-progress research, reconnecting SSE for task:', reconnectTaskId)
          // 异步重连 SSE（利用 Redis STREAM 回放获取缺失事件）
          researchConnectSSE(reconnectTaskId).catch((err: unknown) => {
            console.error('[App] SSE reconnect failed for task:', reconnectTaskId, err)
            setResearching(false)
            setStreaming(false)
          })
        }
      }
      console.log('[App] Restored', restoredCount, 'completed research reports,', inProgressCount, 'in-progress research tasks')
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

    // 乐观更新：立即将新会话插入侧边栏列表头部，不等 loadSessions() 刷新
    store.session.list.unshift({
      session_id: data.session_id,
      message_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
    console.log('[App] Optimistic sidebar update: new session added to list')

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

// 启动研究（标准或深度）- 委托给 useResearch
async function startResearch(query: string, mode: 'standard' | 'deep') {
  console.log('[App] Starting research:', mode, query.substring(0, 50) + '...')

  accumulatedContent = ''

  setStreaming(true)
  setResearching(true)

  addMessage({
    id: generateId(),
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
  })

  await researchStart(query, mode, async () => {
    if (!store.session.currentId) {
      const data = await sessionApi.create()
      if (data.session_id) {
        setSessionId(data.session_id)
      }
    }
  })

  await loadSessions()
}

// 发送消息给 LLM
async function sendMessageToLLM(content: string) {
  // 重置累积内容
  accumulatedContent = ''
  
  const controller = new AbortController()
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
    for await (const event of parseSSEStream(response)) {
      eventCount++
      console.log('[App] Received event:', event.type, eventCount)
      
      if (!getAbortController()) break
      handleStreamEvent(event)
    }
    
    console.log('[App] Stream completed, total events:', eventCount)
  } catch (error: unknown) {
    console.error('[App] Stream error:', error)
    if (error instanceof Error) {
      // AbortError 和浏览器中断流的 TypeError（如 BodyStreamBuffer was aborted）都视为用户主动中断
      if (error.name === 'AbortError' || error.message?.includes('aborted')) {
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
