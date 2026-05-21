<script setup lang="ts">
import { ref } from 'vue'
import { Copy, Check, Clock, BookOpen } from 'lucide-vue-next'
import type { ResearchCompletedData } from '@/types'

const props = defineProps<{
  data: ResearchCompletedData
  markdownContent?: string
}>()

const emit = defineEmits<{
  download: [taskId: string, format: 'markdown' | 'pdf']
}>()

// 复制状态
const copyState = ref<'idle' | 'copying' | 'copied'>('idle')

// 格式化时长
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${mins} 分 ${secs} 秒` : `${mins} 分钟`
}

// 一键复制 Markdown 报告
async function copyMarkdown() {
  copyState.value = 'copying'
  console.log('[ResearchCompletedCard] Copying markdown report, taskId:', props.data.task_id)

  try {
    const content = props.markdownContent || ''
    if (!content) {
      console.warn('[ResearchCompletedCard] No markdown content to copy')
      copyState.value = 'idle'
      return
    }

    await navigator.clipboard.writeText(content)
    copyState.value = 'copied'
    console.log('[ResearchCompletedCard] Markdown copied successfully, length:', content.length)

    setTimeout(() => {
      copyState.value = 'idle'
    }, 2000)
  } catch (e) {
    console.error('[ResearchCompletedCard] Copy failed:', e)
    copyState.value = 'idle'
  }
}
</script>

<template>
  <div class="completed-card">
    <!-- 标题 -->
    <div class="card-header">
      <div class="header-icon">
        <Check class="w-5 h-5" />
      </div>
      <div class="header-text">
        <h3 class="card-title">研究完成</h3>
        <p class="card-subtitle">研究报告已生成</p>
      </div>
    </div>

    <!-- 统计信息 -->
    <div class="stats-grid">
      <div class="stat-item">
        <BookOpen class="w-4 h-4 stat-icon" />
        <span class="stat-value">{{ data.source_count }}</span>
        <span class="stat-label">信息来源</span>
      </div>
      <div class="stat-item">
        <Clock class="w-4 h-4 stat-icon" />
        <span class="stat-value">{{ formatDuration(data.duration_seconds) }}</span>
        <span class="stat-label">研究用时</span>
      </div>
    </div>

    <!-- 复制按钮 -->
    <button
      class="copy-btn"
      :class="{ 'copy-btn-done': copyState === 'copied' }"
      :disabled="copyState === 'copying'"
      @click="copyMarkdown"
    >
      <Check v-if="copyState === 'copied'" class="w-4 h-4" />
      <Copy v-else class="w-4 h-4" />
      <span>{{ copyState === 'copied' ? '已复制' : copyState === 'copying' ? '复制中...' : '复制 Markdown 报告' }}</span>
    </button>
  </div>
</template>

<style scoped>
.completed-card {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(34, 197, 94, 0.2);
  border-radius: 16px;
  padding: 20px;
  margin: 12px 0;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.header-text {
  flex: 1;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: white;
  margin-bottom: 2px;
}

.card-subtitle {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.stats-grid {
  display: flex;
  gap: 16px;
  padding: 12px 16px;
  background: rgba(34, 197, 94, 0.1);
  border-radius: 10px;
  margin-bottom: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stat-icon {
  color: #4ADE80;
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: white;
}

.stat-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
}

.copy-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px 20px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms;
  background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
  border: none;
  color: white;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.25);
}

.copy-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(34, 197, 94, 0.3);
}

.copy-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.copy-btn-done {
  background: linear-gradient(135deg, #16A34A 0%, #15803D 100%);
}
</style>
