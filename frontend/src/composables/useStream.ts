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
   */
  async function* streamEvents(response: Response): AsyncGenerator<StreamEvent> {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

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
          if (!line) continue

          if (line.startsWith('data: ')) {
            const payload = line.slice(6)

            // 跳过空数据
            if (!payload || payload.trim() === '') continue

            try {
              const event = JSON.parse(payload) as StreamEvent
              console.log('[useStream] Parsed event:', event.type)
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

      // 处理剩余的 buffer
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
