<script setup lang="ts">
import { computed } from 'vue'
import type { TeamStatus, TaskInfo } from '@/types'

interface Props {
  status: TeamStatus
  phase?: 'init' | 'running' | 'integrating' | 'done'
  integratingContent?: string
}

const props = defineProps<Props>()

// 状态文本：有 complexity_score 时显示"复杂度评分: X"，否则显示任务统计
const statusText = computed(() => {
  if (props.phase === 'init') {
    if (props.status.complexity_score) {
      return `复杂度评分: ${props.status.complexity_score}`
    }
    return '正在初始化...'
  }
  const { total_tasks, parallel_groups } = props.status
  return `总任务: ${total_tasks}  并行组: ${parallel_groups || 0}`
})

// 是否显示任务拆解完成区域（有任务数据时）
const showTaskSummary = computed(() => {
  return props.status.total_tasks > 0 && (props.status.parallel_groups || 0) > 0
})

// 是否有任务组数据
const hasTasks = computed(() => {
  return props.status.tasks && props.status.tasks.length > 0
})

// 获取任务状态图标
function getTaskIcon(task: TaskInfo): string {
  switch (task.status) {
    case 'completed': return '✓'
    case 'in_progress': return 'spinner'
    case 'failed': return '✗'
    default: return '○'
  }
}

// 获取任务状态颜色
function getTaskColor(task: TaskInfo): string {
  switch (task.status) {
    case 'completed': return 'var(--success-600)'
    case 'in_progress': return 'var(--primary-600)'
    case 'failed': return 'var(--danger-600)'
    default: return 'var(--gray-400)'
  }
}

// 获取任务背景色
function getTaskBg(task: TaskInfo): string {
  switch (task.status) {
    case 'completed': return 'var(--success-50)'
    case 'in_progress': return 'var(--primary-50)'
    case 'failed': return 'var(--danger-50)'
    default: return 'var(--gray-100)'
  }
}
</script>

<template>
  <div class="team-progress-wrapper">
    <!-- 团队模式头部 -->
    <div class="team-header-row">
      <div class="team-icon-box">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary-600)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
          <circle cx="9" cy="7" r="4"></circle>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
        </svg>
      </div>
      <div class="team-header-info">
        <div class="team-title">团队协作模式</div>
        <div class="team-subtitle">{{ statusText }}</div>
      </div>
    </div>

    <!-- 进度容器 -->
    <div class="team-progress-container">
      <!-- 任务拆解完成摘要 -->
      <div v-if="showTaskSummary && phase !== 'init'" class="task-summary">
        <div class="summary-title">任务拆解完成</div>
        <div class="summary-stats">
          总任务: {{ status.total_tasks }}&nbsp;&nbsp;并行组: {{ status.parallel_groups }}
        </div>
      </div>

      <!-- 初始化中提示 -->
      <div v-if="phase === 'init' && !hasTasks" class="init-hint">
        <span class="spinner-small"></span>
        <span>正在拆解任务...</span>
      </div>

      <!-- 任务组列表 -->
      <div v-if="hasTasks" class="task-groups">
        <div v-for="group in status.tasks" :key="group.group_index" class="team-group">
          <!-- 组标题 -->
          <div class="group-label">并行组 {{ group.group_index }}/{{ group.total_groups }}</div>

          <!-- 任务列表 -->
          <div class="tasks-list">
            <div
              v-for="task in group.tasks"
              :key="task.id"
              class="task-item"
              :style="{ background: getTaskBg(task) }"
            >
              <!-- 进行中：Spinner -->
              <span v-if="task.status === 'in_progress'" class="spinner-small"></span>
              <!-- 其他状态：图标 -->
              <span v-else class="task-icon" :style="{ color: getTaskColor(task) }">{{ getTaskIcon(task) }}</span>

              <!-- 任务内容：优先 result，其次 description -->
              <span class="task-content">{{ task.result || task.description || task.id }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 整合结果 -->
    <div v-if="phase === 'integrating' && integratingContent" class="integrating-section">
      <div class="integrating-label">整合结果</div>
      <div class="integrating-body" v-html="integratingContent"></div>
    </div>
  </div>
</template>

<style scoped>
.team-progress-wrapper {
  margin-top: 12px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ========== 头部 ========== */
.team-header-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.team-icon-box {
  width: 32px;
  height: 32px;
  background: #ede9fe;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.team-header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.team-title {
  font-weight: 600;
  font-size: 14px;
  color: #1f2937;
}

.team-subtitle {
  font-size: 12px;
  color: #6b7280;
}

/* ========== 进度容器 ========== */
.team-progress-container {
  background: #f9fafb;
  border-radius: 10px;
  padding: 12px;
}

/* ========== 任务拆解摘要 ========== */
.task-summary {
  margin-bottom: 8px;
}

.summary-title {
  font-weight: 500;
  font-size: 13px;
  color: #374151;
  margin-bottom: 4px;
}

.summary-stats {
  font-size: 12px;
  color: #6b7280;
}

/* ========== 初始化提示 ========== */
.init-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 8px;
  color: #9ca3af;
  font-size: 13px;
  justify-content: center;
}

/* ========== 任务组 ========== */
.task-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.team-group {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  padding: 10px;
}

.group-label {
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
  margin-bottom: 6px;
}

/* ========== 任务项 ========== */
.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.task-icon {
  width: 15px;
  flex-shrink: 0;
  margin-top: 1px;
  font-size: 13px;
  text-align: center;
}

.task-content {
  flex: 1;
  color: #374151;
  white-space: pre-wrap;
}

/* ========== Spinner ========== */
.spinner-small {
  width: 14px;
  height: 14px;
  border: 2px solid #d1d5db;
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
  margin-top: 2px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ========== 整合结果 ========== */
.integrating-section {
  margin-top: 12px;
  background: #ffffff;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  padding: 12px;
}

.integrating-label {
  font-weight: 500;
  font-size: 13px;
  color: #374151;
  margin-bottom: 8px;
}

.integrating-body {
  font-size: 13px;
  line-height: 1.6;
  color: #1f2937;
  word-break: break-word;
}
</style>
