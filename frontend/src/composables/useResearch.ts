/**
 * 研究流程编排组合式函数
 *
 * 从 ChatView.vue 剥离研究流程逻辑，统一管理：
 * - SSE 连接生命周期（通过 useStream）
 * - lastSeqNo 事件序号维护
 * - accumulatedContent 报告累积内容
 * - 研究事件分发到 store
 */

import { ref } from 'vue'
import { useStream } from './useStream'
import { researchApi } from '@/api'
import {
  store,
  setResearchTaskId,
  setResearching,
  setResearchConfirmTime,
  setStreaming,
  setAbortController,
  updateLastMessage,
  updateResearchProgress,
  updateLastMessageAttachments,
  appendResearchProgressLog,
  setResearchPlan,
  setClarificationQuestions,
  clearClarification,
  clearResearch,
  researchTaskId,
  researchMode,
} from '@/stores'
import type {
  ResearchProgress,
  ClarificationQuestion,
  DirectionSpec,
  StreamEvent,
} from '@/types'

export function useResearch() {
  const { streamEvents, abort, reset } = useStream()

  // 事件序号（Redis STREAM ID），用于增量回放
  const lastSeqNo = ref('0-0')
  // 报告流式内容累积
  const accumulatedContent = ref('')

  /**
   * 连接 SSE 事件流
   */
  async function connectSSE(taskId: string) {
    const url = researchApi.eventsUrl(taskId)
    console.log('[useResearch] Connecting SSE:', url, 'lastSeqNo:', lastSeqNo.value)

    await streamEvents(url, {
      headers: {
        'Last-Event-Seq-No': lastSeqNo.value,
      },
      onEvent(event: StreamEvent) {
        // 更新 lastSeqNo
        if (event.seq_no && event.seq_no !== '0-0') {
          lastSeqNo.value = event.seq_no
        }
        handleResearchEvent(event)
      },
      onError(error: unknown) {
        console.error('[useResearch] SSE error:', error)
      },
    })
  }

  /**
   * 断开 SSE 连接
   */
  function disconnectSSE() {
    abort()
    console.log('[useResearch] SSE disconnected, lastSeqNo:', lastSeqNo.value)
  }

  /**
   * 处理研究事件
   */
  function handleResearchEvent(event: StreamEvent) {
    console.log('[useResearch] Research event:', event.type)

    switch (event.type) {
      case 'research_task_created':
        if (event.task_id) {
          setResearchTaskId(event.task_id as string)
        }
        updateLastMessage('正在分析您的问题...')
        updateResearchProgress({
          task_id: (event.task_id as string) || researchTaskId.value || '',
          status: 'analyzing',
          mode: researchMode.value as 'standard' | 'deep',
          progress_pct: 0,
          elapsed_seconds: 0,
          directions: [],
          current_action: '正在分析您的问题...',
        })
        break

      case 'research_analyzing':
        updateLastMessage('正在深度分析您的问题...')
        if (event.progress) {
          updateResearchProgress(event.progress as ResearchProgress)
        } else {
          updateResearchProgress({
            task_id: researchTaskId.value || '',
            status: 'analyzing',
            mode: researchMode.value as 'standard' | 'deep',
            progress_pct: 0,
            elapsed_seconds: 0,
            directions: [],
            current_action: '正在深度分析您的问题...',
          })
        }
        break

      case 'research_clarification_needed':
        if (event.questions && event.task_id) {
          setClarificationQuestions(event.task_id as string, event.questions as ClarificationQuestion[])
        }
        break

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

      case 'research_progress': {
        const progressData = event.progress as ResearchProgress | undefined
        if (progressData) {
          updateResearchProgress(progressData)
          if (progressData.current_action) {
            updateLastMessage(progressData.current_action)
          }
          // 为每个方向追加日志
          if (progressData.directions && progressData.directions.length > 0) {
            for (const dir of progressData.directions) {
              appendResearchProgressLog({
                id: `${dir.direction_id}-init-${Date.now()}`,
                timestamp: new Date(),
                direction_id: dir.direction_id,
                direction_name: dir.direction_name,
                phase: dir.status as 'started' | 'exploring' | 'analyzing' | 'synthesizing' | 'completed' | 'failed',
                message: dir.current_action || '',
                progress: dir.progress,
                learnings_count: dir.learnings_count,
                sources_count: dir.sources_count,
              })
            }
          }
        }
        break
      }

      case 'research_direction_progress': {
        const dirProgress = event.direction_progress as {
          direction_id: string
          direction_name: string
          status: string
          progress: number
          current_action: string
          learnings_count: number
          sources_count: number
        } | undefined
        if (dirProgress) {
          updateResearchProgress({
            task_id: researchTaskId.value || '',
            status: 'executing',
            mode: researchMode.value as 'standard' | 'deep',
            progress_pct: 0,
            elapsed_seconds: 0,
            directions: [{
              direction_id: dirProgress.direction_id,
              direction_name: dirProgress.direction_name,
              status: dirProgress.status as 'pending' | 'exploring' | 'analyzing' | 'synthesizing' | 'completed' | 'failed',
              progress: dirProgress.progress,
              current_action: dirProgress.current_action,
              learnings_count: dirProgress.learnings_count,
              sources_count: dirProgress.sources_count,
            }],
            current_action: dirProgress.current_action,
            estimated_remaining: event.estimated_remaining as string | undefined,
          })
          appendResearchProgressLog({
            id: `${dirProgress.direction_id}-${Date.now()}`,
            timestamp: new Date(),
            direction_id: dirProgress.direction_id,
            direction_name: dirProgress.direction_name,
            phase: dirProgress.status as 'started' | 'exploring' | 'analyzing' | 'synthesizing' | 'completed' | 'failed',
            message: dirProgress.current_action || '',
            progress: dirProgress.progress,
            learnings_count: dirProgress.learnings_count,
            sources_count: dirProgress.sources_count,
          })
        }
        break
      }

      case 'research_report_stream':
        // 报告开始流式输出时，清除进度卡片
        if (!accumulatedContent.value) {
          updateResearchProgress(undefined)
        }
        if (typeof event.accumulated === 'string') {
          accumulatedContent.value = event.accumulated
          updateLastMessage(accumulatedContent.value)
        } else if (typeof event.content === 'string') {
          accumulatedContent.value += event.content
          updateLastMessage(accumulatedContent.value)
        }
        break

      case 'research_report_complete':
        console.log('[useResearch] Report generation complete')
        break

      case 'research_completed':
        if (accumulatedContent.value) {
          updateLastMessage(accumulatedContent.value)
        } else if (event.content) {
          updateLastMessage(event.content as string)
        }
        if (event.task_id) {
          updateLastMessageAttachments({
            researchProgress: undefined,
            researchCompleted: {
              task_id: event.task_id as string,
              source_count: (event.source_count as number) || 0,
              duration_seconds: (event.duration_seconds as number) || 0,
              report_id: event.report_id as string | undefined,
              word_count: event.word_count as number | undefined,
            }
          })
        }
        clearResearch()
        // 研究完成时提前解除 streaming 状态，不等 SSE 连接关闭
        setStreaming(false)
        break

      case 'research_error': {
        const errorMsg = (event.error_message as string) || '研究过程中发生错误'
        if (accumulatedContent.value) {
          updateLastMessage(accumulatedContent.value + '\n\n' + errorMsg)
        } else {
          updateLastMessage(errorMsg)
        }
        clearResearch()
        // 研究出错时提前解除 streaming 状态，不等 SSE 连接关闭
        setStreaming(false)
        break
      }

      case 'content':
        if (typeof event.accumulated === 'string') {
          accumulatedContent.value = event.accumulated
          updateLastMessage(accumulatedContent.value)
        } else if (typeof event.content === 'string') {
          accumulatedContent.value += event.content
          updateLastMessage(accumulatedContent.value)
        }
        break

      case 'research_connected':
        console.log('[useResearch] SSE connection established')
        break

      case 'done':
        if (typeof event.content === 'string' && event.content) {
          updateLastMessage(event.content)
        } else if (accumulatedContent.value) {
          updateLastMessage(accumulatedContent.value)
        }
        break

      default:
        console.log('[useResearch] Unknown research event:', event.type)
    }
  }

  /**
   * 发起研究（单阶段启动）
   */
  async function startResearch(query: string, mode: 'standard' | 'deep', createNewSession: () => Promise<void>) {
    console.log('[useResearch] Starting research:', mode)
    accumulatedContent.value = ''
    lastSeqNo.value = '0-0'

    if (!await ensureSession(createNewSession)) return

    setStreaming(true)
    setResearching(true)

    try {
      // POST /start 获取 task_id
      const startResponse = await researchApi.start(query, mode, new AbortController().signal)

      if (!startResponse.ok) {
        updateLastMessage(`研究启动失败: ${startResponse.status}`)
        return
      }

      const startData = await startResponse.json() as { task_id?: string; error?: string }
      if (!startData.task_id) {
        updateLastMessage('研究启动失败: 未获取到任务ID')
        return
      }

      const taskId = startData.task_id
      setResearchTaskId(taskId)
      updateLastMessage(mode === 'deep' ? '研究任务已创建，正在分析问题...' : '研究任务已创建，正在搜索分析...')

      // 创建初始进度卡片
      updateResearchProgress({
        task_id: taskId,
        status: 'analyzing',
        mode: mode as 'standard' | 'deep',
        progress_pct: 0,
        elapsed_seconds: 0,
        directions: [],
        current_action: mode === 'deep' ? '正在分析问题...' : '正在生成研究计划...',
      })

      // 建立 SSE 连接
      await connectSSE(taskId)

    } catch (error: unknown) {
      console.error('[useResearch] Start research error:', error)
      if (error instanceof Error && error.name !== 'AbortError' && !error.message?.includes('aborted')) {
        updateLastMessage(`研究出错: ${error.message}`)
      }
    } finally {
      setStreaming(false)
      setAbortController(null)
      reset()
    }
  }

  /**
   * 确认研究计划（不断开 SSE 连接）
   */
  async function confirmPlan(taskId: string) {
    console.log('[useResearch] Confirming plan:', taskId)
    // 注意：确认后保持 SSE 连接，不需要重连
    // Redis STREAM 回放机制确保不丢失事件
    try {
      // 确认后保持计划卡片可见，标记为已确认（不可修改）
      const lastMessage = store.chat.messages[store.chat.messages.length - 1]
      const currentPlan = lastMessage?.attachments?.researchPlan
      if (currentPlan) {
        setResearchPlan({ ...currentPlan, can_modify: false })
      }

      // 记录确认时间，用于从确认后开始计时
      setResearchConfirmTime(Date.now())

      setStreaming(true)
      updateLastMessage('研究计划已确认，正在启动研究...')
      updateResearchProgress({
        task_id: taskId,
        status: 'executing',
        mode: researchMode.value as 'standard' | 'deep',
        progress_pct: 0,
        elapsed_seconds: 0,
        directions: [],
        current_action: '研究计划已确认，正在启动研究...',
      })

      await researchApi.confirmPlan(taskId)
      console.log('[useResearch] Plan confirmed, SSE connection maintained')
    } catch (error: unknown) {
      console.error('[useResearch] Confirm plan error:', error)
      if (error instanceof Error) {
        updateLastMessage('确认计划失败: ' + error.message)
      }
    }
  }

  /**
   * 回答澄清问题
   */
  async function clarify(taskId: string, answers: Record<number, string>) {
    console.log('[useResearch] Submitting clarification:', taskId)
    clearClarification()
    setStreaming(true)
    accumulatedContent.value = ''

    try {
      const answerText = Object.entries(answers)
        .map(([idx, ans]) => `Q${parseInt(idx) + 1}: ${ans}`)
        .join('\n')

      const resumeResponse = await researchApi.resume(taskId, answerText, new AbortController().signal)
      if (!resumeResponse.ok) {
        updateLastMessage(`恢复研究失败: ${resumeResponse.status}`)
        return
      }

      updateLastMessage('研究已恢复，正在连接事件流...')
      await connectSSE(taskId)
    } catch (error: unknown) {
      console.error('[useResearch] Clarify error:', error)
      if (error instanceof Error && error.name !== 'AbortError' && !error.message?.includes('aborted')) {
        updateLastMessage('提交答案失败: ' + error.message)
      }
    } finally {
      setStreaming(false)
      setAbortController(null)
      reset()
    }
  }

  /**
   * 跳过澄清问题
   */
  async function clarifySkip(taskId: string) {
    console.log('[useResearch] Skipping clarification:', taskId)
    clearClarification()
    setStreaming(true)
    accumulatedContent.value = ''

    try {
      const resumeResponse = await researchApi.resume(taskId, '使用默认设置继续', new AbortController().signal)
      if (!resumeResponse.ok) {
        updateLastMessage(`继续研究失败: ${resumeResponse.status}`)
        return
      }

      updateLastMessage('研究已恢复，正在连接事件流...')
      await connectSSE(taskId)
    } catch (error: unknown) {
      console.error('[useResearch] Skip clarification error:', error)
      if (error instanceof Error && error.name !== 'AbortError' && !error.message?.includes('aborted')) {
        updateLastMessage('继续研究失败: ' + error.message)
      }
    } finally {
      setStreaming(false)
      setAbortController(null)
      reset()
    }
  }

  /**
   * 取消研究
   */
  async function cancelResearch(taskId: string) {
    console.log('[useResearch] Cancelling research:', taskId)
    try {
      await researchApi.cancel(taskId)
      clearResearch()
      disconnectSSE()
      updateLastMessage('研究已取消')
    } catch (error) {
      console.error('[useResearch] Cancel research error:', error)
    }
    setStreaming(false)
    setAbortController(null)
  }

  /**
   * 发送干预消息
   */
  async function sendIntervention(taskId: string, message: string) {
    console.log('[useResearch] Sending intervention:', taskId)
    try {
      await researchApi.intervene(taskId, message, new AbortController().signal)
    } catch (error) {
      console.error('[useResearch] Intervention error:', error)
    }
  }

  /**
   * 修改研究计划
   */
  async function modifyPlan(taskId: string, directions: DirectionSpec[]) {
    console.log('[useResearch] Modifying plan:', taskId)
    try {
      await researchApi.updatePlan(taskId, directions)
      await confirmPlan(taskId)
    } catch (error) {
      console.error('[useResearch] Modify plan error:', error)
      if (error instanceof Error) {
        updateLastMessage('修改计划失败: ' + error.message)
      }
    }
  }

  // 内部辅助
  async function ensureSession(createNewSession: () => Promise<void>): Promise<boolean> {
    try {
      await createNewSession()
      return true
    } catch (error: unknown) {
      // session 可能已存在（409 Conflict 等），这种情况可以继续
      // 但网络错误等不可恢复异常应记录日志
      if (error instanceof TypeError && error.message.includes('fetch')) {
        console.error('[useResearch] Network error during session creation:', error)
        return false
      }
      // 其他错误（如 session 已存在）可安全忽略
      console.warn('[useResearch] Session creation warning (session may already exist):', error)
      return true
    }
  }

  return {
    lastSeqNo,
    accumulatedContent,
    startResearch,
    confirmPlan,
    clarify,
    clarifySkip,
    cancelResearch,
    sendIntervention,
    modifyPlan,
    connectSSE,
    disconnectSSE,
    handleResearchEvent,
  }
}
