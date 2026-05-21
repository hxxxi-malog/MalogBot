/**
 * SSE 流处理组合式函数
 *
 * 双模式支持：
 * 1. GET SSE（研究模式）：使用 @microsoft/fetch-event-source 建立 SSE 连接
 * 2. POST SSE（普通聊天流）：使用 parseSSEStream 异步生成器解析响应体
 *
 * 统一使用 AbortController.signal 管理 abort 状态。
 */

import { ref } from 'vue'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import type { StreamEvent } from '@/types'

export interface StreamOptions {
  /** 请求头（如 Last-Event-Seq-No） */
  headers?: Record<string, string>
  /** 事件回调 */
  onEvent?: (event: StreamEvent) => void
  /** 连接打开回调 */
  onOpen?: () => void
  /** 错误回调 */
  onError?: (error: unknown) => void
}

/**
 * 将后端 SSE 事件数据展平为前端 StreamEvent 格式
 *
 * 后端 research SSE 格式：
 *   event: progress
 *   data: {"event": "progress", "task_id": "xxx", "data": {...}, ...}
 *
 * 展平规则：
 * - 如果有 eventType（SSE event: 行），type 加 "research_" 前缀
 * - 外层 data 字段如果是对象，展开到顶层（展平嵌套）
 * - 外层 event 字段丢弃（与 SSE event: 行重复）
 * - 如果 data 不是对象（如字符串），保留在 data 字段中并打印警告
 *
 * @param parsedData - JSON 解析后的原始数据
 * @param eventType - SSE event: 行的值
 * @returns 展平后的 StreamEvent
 */
export function flattenSSEEvent(
  parsedData: Record<string, unknown>,
  eventType: string,
): StreamEvent {
  if (eventType) {
    const { data: nestedData, event: _eventField, ...restFields } = parsedData

    // 类型守卫：data 字段应为对象，否则保留原值并警告
    if (nestedData !== undefined && typeof nestedData !== 'object') {
      console.warn(
        `[useStream] SSE event data field is not an object (type: ${typeof nestedData}), keeping as-is. Event: research_${eventType}`,
      )
    }

    return {
      type: 'research_' + eventType,
      ...restFields,
      ...(typeof nestedData === 'object' && nestedData !== null ? nestedData : {}),
    } as StreamEvent
  }

  // 旧格式：纯 data 行（无 event: 行），直接透传
  return parsedData as StreamEvent
}

/**
 * 解析 POST SSE 响应体的异步生成器
 *
 * 适用于 /chat/stream、/confirm/stream 等 POST 请求返回的 SSE 流。
 * 与 streamEvents (GET) 不同，此函数直接读取 Response body。
 *
 * @param response fetch 返回的 Response 对象
 */
export async function* parseSSEStream(response: Response): AsyncGenerator<StreamEvent> {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('Response body is not readable')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // 按双换行分割 SSE 事件块
      const parts = buffer.split('\n\n')
      // 最后一部分可能不完整，保留在 buffer 中
      buffer = parts.pop() || ''

      for (const part of parts) {
        if (!part.trim()) continue

        let eventType = ''
        let dataLines: string[] = []

        for (const line of part.split('\n')) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trim())
          }
        }

        if (dataLines.length === 0) continue
        const payload = dataLines.join('\n')

        try {
          const parsedData = JSON.parse(payload) as Record<string, unknown>

          if (eventType === 'connected' || eventType === 'task_created') {
            console.log('[useStream] System event:', eventType)
            continue
          }

          const event = flattenSSEEvent(parsedData, eventType)
          yield event
        } catch (e) {
          console.warn('[useStream] Failed to parse SSE chunk:', payload, e)
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export function useStream() {
  const isStreaming = ref(false)
  let abortController: AbortController | null = null

  /**
   * 创建新的 AbortController
   */
  function createAbortController(): AbortController {
    abortController = new AbortController()
    return abortController
  }

  /**
   * 建立 GET SSE 连接并处理事件流
   *
   * 使用 @microsoft/fetch-event-source 处理 SSE 连接和解析，
   * 适用于研究模式的 SSE 端点（GET 请求）。
   *
   * @param url SSE 端点 URL
   * @param options 流选项（headers、事件回调等）
   */
  async function streamEvents(url: string, options?: StreamOptions): Promise<void> {
    // 每次建立新连接时创建新的 AbortController
    abortController = new AbortController()
    isStreaming.value = true

    console.log('[useStream] Starting SSE connection to:', url)

    try {
      await fetchEventSource(url, {
        signal: abortController.signal,
        headers: options?.headers,

        async onopen(response) {
          // 验证 content-type
          const contentType = response.headers.get('content-type') || ''
          if (!contentType.includes('text/event-stream')) {
            throw new Error(`Expected content-type text/event-stream, got: ${contentType}`)
          }
          console.log('[useStream] SSE connection opened')
          options?.onOpen?.()
        },

        onmessage(ev) {
          // ev.event 是 SSE event: 行的值（如 "progress"、"connected"）
          // ev.data 是 SSE data: 行的值（JSON 字符串）
          const eventType = ev.event
          const payload = ev.data

          if (!payload || payload.trim() === '') return

          try {
            const parsedData = JSON.parse(payload) as Record<string, unknown>

            // 跳过非业务事件（connected、heartbeat 等）
            if (eventType === 'connected' || eventType === 'task_created') {
              console.log('[useStream] System event:', eventType)
              return
            }

            const event = flattenSSEEvent(parsedData, eventType)

            if (event.type.startsWith('research_')) {
              console.log('[useStream] Parsed SSE event:', event.type)
            } else {
              console.log('[useStream] Parsed event (legacy):', event.type)
            }

            options?.onEvent?.(event)
          } catch (e) {
            console.warn('[useStream] Failed to parse SSE event:', payload, e)
          }
        },

        onerror(error) {
          console.error('[useStream] SSE connection error:', error)
          options?.onError?.(error)
          // 不自动重连，由 useResearch 控制重连逻辑
          throw error
        },

        // 页面隐藏时不自动关闭连接
        openWhenHidden: true,
      })
    } catch (error: unknown) {
      // AbortError 是主动取消，不需要报错
      if (error instanceof DOMException && error.name === 'AbortError') {
        console.log('[useStream] SSE connection aborted by user')
      } else if (error instanceof TypeError && String(error).includes('content-type')) {
        console.error('[useStream] Invalid content-type, SSE connection failed:', error)
        options?.onError?.(error)
      } else {
        console.error('[useStream] SSE connection error:', error)
        options?.onError?.(error)
      }
    } finally {
      isStreaming.value = false
      console.log('[useStream] SSE connection closed')
    }
  }

  /**
   * 中止流
   */
  function abort() {
    console.log('[useStream] Abort called')
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    isStreaming.value = false
  }

  /**
   * 重置状态
   */
  function reset() {
    console.log('[useStream] Reset called')
    if (abortController) {
      abortController.abort()
    }
    abortController = null
    isStreaming.value = false
  }

  return {
    isStreaming,
    createAbortController,
    streamEvents,
    abort,
    reset,
  }
}
