/**
 * 工具函数
 */

import { marked } from 'marked'
import hljs from 'highlight.js'

// 配置 marked（不使用已废弃的 highlight 选项）
marked.setOptions({
  breaks: true,
  gfm: true,
})

/**
 * 渲染 Markdown 为 HTML
 */
export function renderMarkdown(text: string): string {
  // 先解析 Markdown
  let html = marked.parse(text) as string

  // 然后高亮代码块
  // 使用 DOMParser 在浏览器环境中解析
  if (typeof document !== 'undefined') {
    const parser = new DOMParser()
    const doc = parser.parseFromString(`<div>${html}</div>`, 'text/html')
    const codeBlocks = doc.querySelectorAll('pre code')

    codeBlocks.forEach((block) => {
      const code = block.textContent || ''
      const lang = block.className.replace('language-', '')

      let highlighted: string
      if (lang && hljs.getLanguage(lang)) {
        try {
          highlighted = hljs.highlight(code, { language: lang }).value
        } catch {
          highlighted = hljs.highlightAuto(code).value
        }
      } else {
        highlighted = hljs.highlightAuto(code).value
      }

      block.innerHTML = highlighted
    })

    html = doc.body.innerHTML
  }

  return html
}

/**
 * 高亮代码块
 */
export function highlightCode(element: HTMLElement) {
  element.querySelectorAll('pre code').forEach((block) => {
    hljs.highlightElement(block as HTMLElement)
  })
}

/**
 * HTML 转义
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div')
  div.textContent = text
  return div.innerHTML
}

/**
 * 格式化时间
 */
export function formatTime(date: Date): string {
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  if (diff < 604800000) return Math.floor(diff / 86400000) + '天前'

  return date.toLocaleDateString('zh-CN')
}

/**
 * 生成唯一 ID
 */
export function generateId(): string {
  return Math.random().toString(36).substring(2, 9)
}

/**
 * 滚动到底部
 */
export function scrollToBottom(element: HTMLElement) {
  element.scrollTop = element.scrollHeight
}

/**
 * 复制文本到剪贴板
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
