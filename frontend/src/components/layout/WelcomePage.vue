<script setup lang="ts">
import { ref, computed } from 'vue'
import { Globe, BookOpen, MessageSquare, Send, Clock, Sparkles } from 'lucide-vue-next'
import {
  store,
  webSearchEnabled,
  knowledgeBases,
  researchMode,
  setWebSearchEnabled,
  setKnowledgeBaseId,
  setResearchMode,
  setSessionId,
  clearMessages,
  addMessage,
} from '@/stores'
import { sessionApi, webSearchApi } from '@/api'
import { formatTime, generateId } from '@/utils'
import { restoreCompletedResearch } from '@/utils/researchRestore'
import type { ResearchTaskRestoreData } from '@/utils/researchRestore'
import type { Session } from '@/types'

const emit = defineEmits<{
  (e: 'startChat', message: string): void
}>()

const inputText = ref('')

const recentSessions = computed(() => {
  return store.session.list
    .filter((s) => s.message_count > 0)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 3)
})

const selectedKnowledgeBase = computed({
  get: () => store.settings.knowledgeBaseId || '',
  set: (value: string) => {
    setKnowledgeBaseId(value || null)
  },
})

// 研究模式下拉选择
const selectedMode = computed({
  get: () => researchMode.value,
  set: (value: 'chat' | 'standard' | 'deep') => {
    setResearchMode(value)
    console.log('[WelcomePage] Research mode changed to:', value)
  }
})

// 是否为研究模式（标准或深度）
const isResearchMode = computed(() => researchMode.value !== 'chat')

async function handleSend() {
  const text = inputText.value.trim()
  if (!text) return
  console.log('[WelcomePage] Starting chat with message:', text.substring(0, 50) + '...', 'mode:', researchMode.value)
  emit('startChat', text)
  inputText.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function toggleWebSearch() {
  const newValue = !webSearchEnabled.value
  setWebSearchEnabled(newValue)
  if (store.session.currentId) {
    try {
      await webSearchApi.toggle(newValue)
      console.log('[WelcomePage] Web search toggled:', newValue)
    } catch (error) {
      console.error('[WelcomePage] Toggle web search error:', error)
      setWebSearchEnabled(!newValue)
    }
  }
}

// 快速切换深度研究（已移除，使用下拉选择）
// function toggleDeepResearch() {
//   if (researchMode.value === 'deep') {
//     setResearchMode('chat')
//   } else {
//     setResearchMode('deep')
//   }
//   console.log('[WelcomePage] Deep research toggled:', researchMode.value)
// }

async function handleSelectSession(sessionId: string) {
  try {
    console.log('[WelcomePage] Selecting session:', sessionId)
    await sessionApi.switch(sessionId)
    setSessionId(sessionId)
    clearMessages()
    const data = await sessionApi.info(sessionId)
    if (data.messages) {
      // 只加载 user 和 assistant 消息
      const displayMessages = (data.messages as Array<{ role: string; content: string; timestamp?: string }>).filter(
        (msg) => msg.role === 'user' || msg.role === 'assistant'
      )
      displayMessages.forEach((msg) => {
        addMessage({
          id: generateId(),
          role: msg.role as 'user' | 'assistant',
          content: msg.content,
          timestamp: msg.timestamp || new Date().toISOString(),
        })
      })

      // 恢复完成的研究报告
      if (data.research_tasks && Array.isArray(data.research_tasks)) {
        let restoredCount = 0
        for (const researchTask of data.research_tasks) {
          if (restoreCompletedResearch(store.chat.messages, researchTask as ResearchTaskRestoreData)) {
            restoredCount++
          }
        }
        console.log('[WelcomePage] Restored', restoredCount, 'research reports')
      }
    }
    store.session.isWelcomeMode = false
  } catch (error) {
    console.error('[WelcomePage] Switch session error:', error)
  }
}

async function handleDeleteSession(e: Event, sessionId: string) {
  e.stopPropagation()
  if (!confirm('确定要删除这个对话吗？')) return
  try {
    await sessionApi.delete(sessionId)
    const data = await sessionApi.list()
    store.session.list = data.sessions || []
    console.log('[WelcomePage] Session deleted')
  } catch (error) {
    console.error('[WelcomePage] Delete session error:', error)
  }
}

function getSessionTitle(session: Session): string {
  return `对话 ${session.session_id.substring(0, 8)}`
}
</script>

<template>
  <div class="welcome-page">
    <!-- 背景装饰 -->
    <div class="welcome-bg" aria-hidden="true">
      <div class="glow glow-purple" />
      <div class="glow glow-cyan" />
      <div class="glow glow-emerald" />
      <div class="grid-pattern" />
    </div>

    <!-- 主内容区 -->
    <div class="welcome-content">
      <!-- Hero 区域 -->
      <div class="hero">
        <!-- 标签 -->
        <div class="hero-badge">
          <Sparkles class="w-3.5 h-3.5" />
          <span>AI-Powered Assistant</span>
        </div>

        <!-- 大标题 -->
        <h1 class="hero-title">
          MalogBot
        </h1>

        <!-- 副标题 -->
        <p class="hero-subtitle">
          您的智能助手，随时准备为您解答问题
        </p>
      </div>
    </div>

    <!-- 底部输入区域 -->
    <div class="input-section">
      <div class="input-container">
        <!-- 输入框 -->
        <div class="input-wrapper" :class="{ 'input-wrapper-focused': inputText }">
          <input
            v-model="inputText"
            type="text"
            class="input-field"
            :placeholder="isResearchMode ? '输入您的研究问题...' : '输入您的问题，开始新对话...'"
            autocomplete="off"
            @keydown="handleKeydown"
          />
          <button
            class="send-btn"
            :disabled="!inputText.trim()"
            aria-label="发送消息"
            @click="handleSend"
          >
            <Send class="w-[18px] h-[18px]" />
          </button>
        </div>

        <!-- 选项栏 -->
        <div class="options-bar">
          <!-- 研究模式下拉选择器 -->
          <div class="mode-selector">
            <select v-model="selectedMode" class="mode-select">
              <option value="chat">普通对话</option>
              <option value="standard">标准研究</option>
              <option value="deep">深度研究</option>
            </select>
          </div>

          <!-- 普通对话模式下显示联网搜索和知识库 -->
          <template v-if="!isResearchMode">
            <!-- 联网搜索开关 -->
            <button
              class="option-btn"
              :class="{ 'option-btn-active': webSearchEnabled }"
              @click="toggleWebSearch"
            >
              <Globe class="w-4 h-4" />
              <span>联网搜索</span>
              <label class="toggle">
                <input type="checkbox" :checked="webSearchEnabled" class="sr-only" @change="toggleWebSearch" />
                <span class="toggle-track" :class="{ 'toggle-track-on': webSearchEnabled }">
                  <span class="toggle-thumb" :class="{ 'toggle-thumb-on': webSearchEnabled }" />
                </span>
              </label>
            </button>

            <!-- 知识库选择 -->
            <div class="option-btn">
              <BookOpen class="w-4 h-4" />
              <select v-model="selectedKnowledgeBase" class="kb-select">
                <option value="">不使用知识库</option>
                <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">
                  {{ kb.name }} ({{ kb.document_count }}个文档)
                </option>
              </select>
            </div>
          </template>

          <!-- 研究模式下的提示 -->
          <div v-else class="research-hint">
            <span>研究过程中将自动联网搜索</span>
          </div>
        </div>
      </div>

      <!-- 历史对话 -->
      <div v-if="recentSessions.length > 0" class="history-section">
        <header class="history-header">
          <Clock class="w-3.5 h-3.5" />
          <span>历史对话</span>
        </header>
        <div class="history-list">
          <div
            v-for="session in recentSessions"
            :key="session.session_id"
            class="history-item"
            @click="handleSelectSession(session.session_id)"
          >
            <div class="history-icon">
              <MessageSquare class="w-4 h-4" />
            </div>
            <div class="history-info">
              <div class="history-title">{{ getSessionTitle(session) }}</div>
              <div class="history-meta">
                {{ formatTime(new Date(session.updated_at)) }} · {{ session.message_count }} 条消息
              </div>
            </div>
            <button
              class="history-delete"
              title="删除"
              aria-label="删除对话"
              @click="(e: Event) => handleDeleteSession(e, session.session_id)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcome-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: relative;
  overflow: hidden;
  background: var(--bg-base);
}

/* 背景装饰 */
.welcome-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(140px);
}

.glow-purple {
  top: -20%;
  left: -10%;
  width: 600px;
  height: 600px;
  background: rgba(124, 58, 237, 0.15);
}

.glow-cyan {
  top: 30%;
  right: -15%;
  width: 500px;
  height: 500px;
  background: rgba(6, 182, 212, 0.1);
}

.glow-emerald {
  bottom: -20%;
  left: 30%;
  width: 450px;
  height: 450px;
  background: rgba(16, 185, 129, 0.08);
}

.grid-pattern {
  position: absolute;
  inset: 0;
  opacity: 0.03;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
  background-size: 60px 60px;
}

/* 主内容 */
.welcome-content {
  position: relative;
  z-index: 10;
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}

/* Hero */
.hero {
  text-align: center;
  animation: fadeIn 500ms ease-out;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: 9999px;
  border: 1px solid rgba(124, 58, 237, 0.25);
  background: rgba(124, 58, 237, 0.1);
  backdrop-filter: blur(8px);
  margin-bottom: 32px;
  color: var(--primary-300);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.hero-title {
  font-size: 4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.1;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #C4B5FD 0%, #67E8F9 50%, #6EE7B7 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: gradientShift 6s ease infinite;
}

@media (min-width: 768px) {
  .hero-title {
    font-size: 4.5rem;
  }
}

.hero-subtitle {
  font-size: 1.125rem;
  color: var(--text-muted);
  font-weight: 400;
  max-width: 400px;
  margin: 0 auto;
  line-height: 1.6;
}

/* 输入区域 */
.input-section {
  position: relative;
  z-index: 10;
  padding-bottom: 32px;
  padding-left: 24px;
  padding-right: 24px;
  animation: slideUp 500ms ease-out 200ms both;
}

.input-container {
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
}

.input-wrapper {
  position: relative;
  border-radius: 20px;
  background: rgba(17, 24, 39, 0.7);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.35);
  transition: all 300ms var(--ease-default);
}

.input-wrapper-focused {
  border-color: rgba(139, 92, 246, 0.35);
  box-shadow: 0 0 30px rgba(139, 92, 246, 0.15), 0 8px 40px rgba(0, 0, 0, 0.35);
}

.input-field {
  width: 100%;
  padding: 20px 60px 20px 24px;
  border: none;
  background: transparent;
  font-size: 16px;
  color: var(--text-primary);
  outline: none;
}

.input-field::placeholder {
  color: var(--text-faint);
}

.send-btn {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  color: white;
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.35);
  transition: all 200ms var(--ease-default);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-50%) scale(1.05);
}

.send-btn:active:not(:disabled) {
  transform: translateY(-50%) scale(0.95);
}

.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 选项栏 */
.options-bar {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

/* 研究模式下拉选择器 */
.mode-selector {
  position: relative;
}

.mode-select {
  padding: 8px 32px 8px 14px;
  border-radius: 14px;
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

.option-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.07);
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
  background: rgba(124, 58, 237, 0.15);
  border-color: rgba(124, 58, 237, 0.3);
  color: var(--primary-300);
}

/* 研究模式按钮（已废弃，使用下拉选择器） */
/* .mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.07);
  color: var(--text-dim);
  font-size: 14px;
  font-weight: 500;
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

/* 深度研究提示 */
.research-hint {
  font-size: 13px;
  color: var(--text-faint);
  padding: 8px 14px;
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

/* 历史对话 */
.history-section {
  width: 100%;
  max-width: 720px;
  margin: 28px auto 0;
  animation: fadeIn 600ms ease-out 400ms both;
}

.history-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 4px;
  margin-bottom: 12px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-faint);
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: flex;
  align-items: center;
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  transition: all 200ms var(--ease-default);
}

.history-item:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
  transform: translateY(-2px);
}

.history-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  margin-right: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.2), rgba(6, 182, 212, 0.15));
  color: var(--primary-400);
  flex-shrink: 0;
}

.history-info {
  flex: 1;
  min-width: 0;
}

.history-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  font-size: 12px;
  color: var(--text-faint);
  margin-top: 2px;
}

.history-delete {
  padding: 8px;
  border-radius: 10px;
  opacity: 0;
  color: var(--text-faint);
  transition: all 150ms var(--ease-default);
}

.history-item:hover .history-delete {
  opacity: 1;
}

.history-delete:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger-400);
}
</style>
