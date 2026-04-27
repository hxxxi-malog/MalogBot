<script setup lang="ts">
import { computed } from 'vue'
import { Plus, Plug, BookOpen, Trash2, MessageSquare, Bot } from 'lucide-vue-next'
import { store, isWelcomeMode } from '@/stores'
import { sessionApi } from '@/api'
import { formatTime } from '@/utils'
import type { Session } from '@/types'

const emit = defineEmits<{
  (e: 'newChat'): void
  (e: 'openMCP'): void
  (e: 'openKnowledge'): void
  (e: 'selectSession', id: string): void
}>()

const currentSessionId = computed(() => store.session.currentId)
const sessions = computed(() => store.session.list)

function handleNewChat() {
  emit('newChat')
}

async function handleSelectSession(session: Session) {
  if (session.session_id === currentSessionId.value && !isWelcomeMode.value) return
  emit('selectSession', session.session_id)
}

async function handleDeleteSession(e: Event, sessionId: string) {
  e.stopPropagation()
  if (!confirm('确定要删除这个对话吗？')) return
  try {
    console.log('[Sidebar] Deleting session:', sessionId)
    const data = await sessionApi.delete(sessionId)
    if (data.status === 'ok') {
      if (sessionId === currentSessionId.value) {
        store.session.isWelcomeMode = true
        store.session.currentId = null
      }
      const listData = await sessionApi.list()
      store.session.list = listData.sessions || []
      console.log('[Sidebar] Session deleted, remaining:', listData.sessions?.length || 0)
    } else {
      alert(data.error || '删除失败')
    }
  } catch (error) {
    console.error('[Sidebar] Delete session error:', error)
  }
}

function getSessionTitle(session: Session): string {
  return `对话 ${session.session_id.substring(0, 8)}`
}
</script>

<template>
  <aside class="sidebar">
    <!-- 头部 -->
    <header class="sidebar-header">
      <h1 class="sidebar-title">
        <div class="sidebar-icon">
          <MessageSquare class="w-3.5 h-3.5" />
        </div>
        对话列表
      </h1>
      <div class="sidebar-actions">
        <button
          class="btn-icon"
          title="MCP 服务管理"
          aria-label="MCP 服务管理"
          @click="emit('openMCP')"
        >
          <Plug class="w-[18px] h-[18px]" />
        </button>
        <button
          class="btn-icon"
          title="知识库管理"
          aria-label="知识库管理"
          @click="emit('openKnowledge')"
        >
          <BookOpen class="w-[18px] h-[18px]" />
        </button>
        <button
          class="btn-icon btn-icon-primary"
          title="新建对话"
          aria-label="新建对话"
          @click="handleNewChat"
        >
          <Plus class="w-[18px] h-[18px]" />
        </button>
      </div>
    </header>

    <!-- 分隔线 -->
    <div class="divider mx-4" />

    <!-- 会话列表 -->
    <div class="sidebar-content">
      <!-- 空状态 -->
      <div v-if="sessions.length === 0" class="empty-state py-12">
        <div class="empty-state-icon">
          <MessageSquare class="w-12 h-12" />
        </div>
        <p class="text-sm leading-relaxed">
          暂无对话记录<br />
          <span class="text-xs">点击 "+" 开始聊天</span>
        </p>
      </div>

      <!-- 会话项 -->
      <div
        v-for="session in sessions"
        :key="session.session_id"
        :class="[
          'session-item',
          { 'session-item-active': session.session_id === currentSessionId && !isWelcomeMode }
        ]"
        @click="handleSelectSession(session)"
      >
        <!-- 激活指示器 -->
        <div
          v-if="session.session_id === currentSessionId && !isWelcomeMode"
          class="session-indicator"
        />

        <div class="session-info">
          <div :class="['session-title', { 'text-gray-100': session.session_id === currentSessionId && !isWelcomeMode }]">
            {{ getSessionTitle(session) }}
          </div>
          <div class="session-meta">
            {{ formatTime(new Date(session.updated_at)) }} · {{ session.message_count }} 条消息
          </div>
        </div>

        <button
          :class="['session-delete', { 'opacity-100': session.session_id === currentSessionId && !isWelcomeMode }]"
          title="删除对话"
          aria-label="删除对话"
          @click="(e: Event) => handleDeleteSession(e, session.session_id)"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 底部品牌栏 -->
    <div class="sidebar-footer">
      <div class="flex items-center gap-2.5 px-2">
        <div class="sidebar-brand-icon">
          <Bot class="w-3.5 h-3.5 text-white" />
        </div>
        <div>
          <div class="text-xs font-medium text-gray-300">MalogBot</div>
          <div class="text-[11px] text-gray-600">AI Assistant</div>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: linear-gradient(180deg, #0F1220 0%, #0A0E1A 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.05);
}

.sidebar-header {
  padding: 20px 20px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sidebar-title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}

.sidebar-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(124, 58, 237, 0.25), rgba(6, 182, 212, 0.15));
  color: var(--primary-400);
}

.sidebar-actions {
  display: flex;
  gap: 2px;
}

.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

/* 会话项 */
.session-item {
  position: relative;
  padding: 14px 16px;
  border-radius: 12px;
  cursor: pointer;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: transparent;
  border: 1px solid transparent;
  transition: all 200ms var(--ease-default);
}

.session-item:hover {
  background: rgba(255, 255, 255, 0.03);
}

.session-item-active {
  background: rgba(124, 58, 237, 0.1);
  border: 1px solid rgba(124, 58, 237, 0.2);
}

.session-indicator {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 28px;
  border-radius: 0 4px 4px 0;
  background: var(--primary-500);
}

.session-info {
  flex: 1;
  min-width: 0;
  padding-left: 4px;
}

.session-title {
  font-size: 14px;
  font-weight: 500;
  truncate: true;
  color: var(--text-muted);
}

.session-meta {
  font-size: 12px;
  margin-top: 2px;
  color: var(--text-faint);
}

.session-item-active .session-title {
  color: var(--text-primary);
}

.session-item-active .session-meta {
  color: var(--text-dim);
}

.session-delete {
  padding: 6px;
  border-radius: 8px;
  opacity: 0;
  color: var(--text-faint);
  transition: all 150ms var(--ease-default);
}

.session-item:hover .session-delete {
  opacity: 1;
}

.session-delete:hover {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger-400);
}

/* 底部品牌栏 */
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.sidebar-brand-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  box-shadow: var(--shadow-sm);
}

/* 按钮样式 */
.btn-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  transition: all 200ms var(--ease-default);
}

.btn-icon:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.btn-icon-primary:hover {
  background: rgba(124, 58, 237, 0.1);
  color: var(--primary-400);
}

/* 空状态 */
.empty-state {
  padding: 48px 24px;
  text-align: center;
  color: var(--text-faint);
}

.empty-state-icon {
  margin-bottom: 12px;
  color: var(--text-faint);
  opacity: 0.5;
}
</style>
