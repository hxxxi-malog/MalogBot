/**
 * SSE 流处理组合式函数
 */

import { ref } from 'vue'
import type { StreamEvent } from '@/types'

export function useStream() {
  const isStreaming = ref(false)
  let abortController: AbortController | null = null
  let isAborted = false

  /**
   * 解析 SSE 事件流
   *
   * 支持两种格式：
   * 1. 标准 SSE 格式：event: <type>\ndata: <json>\n\n
   * 2. 简化格式：data: <json>\n\n（向后兼容）
   */
  async function* streamEvents(response: Response): AsyncGenerator<StreamEvent> {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEventType: string | null = null

    console.log('[useStream] Starting to read stream...')

    try {
      while (true) {
        // 检查是否被取消
        if (isAborted) {
          console.log('[useStream] Stream aborted, breaking...')
          break
        }

        const { done, value } = await reader.read()

        if (done) {
          console.log('[useStream] Stream done')
          break
        }

        buffer += decoder.decode(value, { stream: true })

        // 按换行符分割
        const lines = buffer.split('\n')
        // 保留最后一个不完整的行
        buffer = lines.pop() || ''

        for (const lineRaw of lines) {
          const line = lineRaw.replace(/\r$/, '')
          if (!line) {
            // 空行表示事件结束，重置 event type
            currentEventType = null
            continue
          }

          // 解析 event: 行
          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim()
            console.log('[useStream] Detected event type:', currentEventType)
            continue
          }

          // 解析 data: 行
          if (line.startsWith('data: ')) {
            const payload = line.slice(6)

            // 跳过空数据
            if (!payload || payload.trim() === '') continue

            try {
              const parsedData = JSON.parse(payload) as Record<string, unknown>
              let event: StreamEvent

              // 如果有 event: 行，需要合并 event type
              if (currentEventType) {
                // 后端 research SSE 格式：
                // event: progress
                // data: {"event": "progress", "task_id": "xxx", "data": {...}, ...}
                // 需要转换为前端期望的格式：{type: "research_progress", ...data字段...}

                // 将 data 字段展开到顶层（后端把业务数据放在 data.data 里）
                const { data: nestedData, event: _eventField, ...restFields } = parsedData

                event = {
                  type: 'research_' + currentEventType, // 添加 research_ 前缀以匹配 handleResearchEvent
                  ...restFields,
                  ...(typeof nestedData === 'object' && nestedData !== null ? nestedData : {}),
                } as StreamEvent

                console.log('[useStream] Parsed SSE event with type:', event.type)
              } else {
                // 旧格式：纯 data: 行，data 中包含 type 字段
                event = parsedData as StreamEvent
                console.log('[useStream] Parsed event (legacy format):', event.type)
              }

              yield event
            } catch (e) {
              // 可能是 JSON 不完整，放回 buffer
              if (payload.trim().endsWith('{') || payload.trim().endsWith('[')) {
                buffer = line + '\n' + buffer
              } else {
                console.warn('[useStream] Failed to parse SSE event:', payload, e)
              }
            }
          }
        }
      }

      // 处理剩余的 buffer（兼容旧格式处理）
      if (buffer.trim().startsWith('data: ')) {
        const payload = buffer.trim().slice(6)
        try {
          const event = JSON.parse(payload) as StreamEvent
          console.log('[useStream] Parsed remaining event:', event.type)
          yield event
        } catch (e) {
          console.warn('[useStream] Failed to parse remaining buffer:', buffer)
        }
      }

    } finally {
      reader.releaseLock()
      console.log('[useStream] Stream reader released')
    }
  }

  /**
   * 中止流
   */
  function abort() {
    console.log('[useStream] Abort called')
    isAborted = true
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isStreaming.value = false
  }

  /**
   * 创建新的 AbortController
   */
  function createAbortController(): AbortController {
    console.log('[useStream] Creating new AbortController')
    isAborted = false
    abortController = new AbortController()
    isStreaming.value = true
    return abortController
  }

  /**
   * 获取当前 AbortController
   */
  function getSignal(): AbortSignal | undefined {
    return abortController?.signal
  }

  /**
   * 重置状态
   */
  function reset() {
    console.log('[useStream] Reset called')
    isAborted = false
    abortController = null
    isStreaming.value = false
  }

  return {
    isStreaming,
    streamEvents,
    abort,
    createAbortController,
    getSignal,
    reset,
  }
}
