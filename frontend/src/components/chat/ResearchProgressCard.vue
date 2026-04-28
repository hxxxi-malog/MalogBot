<script setup lang="ts">
import { computed } from 'vue'
import { Search, Brain, FileText, CheckCircle, Clock, XCircle } from 'lucide-vue-next'
import type { ResearchProgress } from '@/types'

const props = defineProps<{
  progress: ResearchProgress
}>()

const emit = defineEmits<{
  cancel: []
}>()

// 计算总进度
const totalProgress = computed(() => {
  if (props.progress.directions.length === 0) {
    return props.progress.progress_pct
  }
  const total = props.progress.directions.reduce((sum, d) => sum + d.progress, 0)
  return Math.round(total / props.progress.directions.length)
})

// 格式化时间
const formattedTime = computed(() => {
  const seconds = props.progress.elapsed_seconds
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
})

// 状态图标映射
function getStatusIcon(status: string) {
  switch (status) {
    case 'exploring':
      return Search
    case 'analyzing':
      return Brain
    case 'synthesizing':
      return FileText
    case 'completed':
      return CheckCircle
    case 'failed':
      return XCircle
    default:
      return Clock
  }
}

// 状态颜色映射
function getStatusColor(status: string) {
  switch (status) {
    case 'exploring':
      return 'text-blue-400'
    case 'analyzing':
      return 'text-purple-400'
    case 'synthesizing':
      return 'text-cyan-400'
    case 'completed':
      return 'text-green-400'
    case 'failed':
      return 'text-red-400'
    default:
      return 'text-gray-400'
  }
}

// 进度条颜色
function getProgressColor(progress: number) {
  if (progress >= 100) return 'bg-green-500'
  if (progress >= 50) return 'bg-cyan-500'
  return 'bg-blue-500'
}
</script>

<template>
  <div class="research-progress-card">
    <!-- 标题区 -->
    <div class="progress-header">
      <div class="header-left">
        <div class="research-icon">
          <Search class="w-4 h-4" />
        </div>
        <div class="header-info">
          <h3 class="research-title">正在研究</h3>
          <p class="research-mode">{{ progress.mode === 'deep' ? '深度研究' : '标准研究' }}</p>
        </div>
      </div>
      <button class="cancel-btn" @click="emit('cancel')">
        <XCircle class="w-4 h-4" />
        <span>取消</span>
      </button>
    </div>

    <!-- 进度信息 -->
    <div class="progress-info">
      <div class="time-display">
        <Clock class="w-4 h-4" />
        <span>已用时：{{ formattedTime }}</span>
      </div>
      <div class="overall-progress">
        <div class="progress-bar-bg">
          <div
            class="progress-bar-fill"
            :class="getProgressColor(totalProgress)"
            :style="{ width: `${totalProgress}%` }"
          />
        </div>
        <span class="progress-text">{{ totalProgress }}%</span>
      </div>
    </div>

    <!-- 当前操作 -->
    <div class="current-action" v-if="progress.current_action">
      <span class="action-label">当前操作：</span>
      <span class="action-text">{{ progress.current_action }}</span>
    </div>

    <!-- 研究方向进度 -->
    <div class="directions-list" v-if="progress.directions.length > 0">
      <div
        v-for="direction in progress.directions"
        :key="direction.direction_id"
        class="direction-item"
      >
        <div class="direction-header">
          <component
            :is="getStatusIcon(direction.status)"
            class="direction-icon"
            :class="getStatusColor(direction.status)"
          />
          <span class="direction-name">{{ direction.direction_name }}</span>
          <span class="direction-progress">{{ direction.progress }}%</span>
        </div>
        
        <div class="direction-progress-bar">
          <div
            class="direction-progress-fill"
            :class="getProgressColor(direction.progress)"
            :style="{ width: `${direction.progress}%` }"
          />
        </div>

        <div class="direction-stats" v-if="direction.current_action">
          <span class="stat-item">
            {{ direction.current_action }}
          </span>
          <span class="stat-divider" v-if="direction.learnings_count > 0">|</span>
          <span class="stat-item" v-if="direction.learnings_count > 0">
            {{ direction.learnings_count }} 条发现
          </span>
          <span class="stat-divider" v-if="direction.sources_count > 0">|</span>
          <span class="stat-item" v-if="direction.sources_count > 0">
            {{ direction.sources_count }} 个来源
          </span>
        </div>
      </div>
    </div>

    <!-- 加载动画 -->
    <div class="loading-indicator">
      <div class="loading-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <span class="loading-text">研究中，请稍候...</span>
    </div>
  </div>
</template>

<style scoped>
.research-progress-card {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 16px;
  padding: 20px;
  margin: 12px 0;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.research-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #8B5CF6 0%, #6366F1 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.header-info {
  display: flex;
  flex-direction: column;
}

.research-title {
  font-size: 16px;
  font-weight: 600;
  color: white;
}

.research-mode {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.cancel-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #EF4444;
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.cancel-btn:hover {
  background: rgba(239, 68, 68, 0.2);
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}

.time-display {
  display: flex;
  align-items: center;
  gap: 6px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.overall-progress {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-bar-bg {
  flex: 1;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 300ms ease;
}

.progress-text {
  font-size: 13px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.8);
  min-width: 40px;
  text-align: right;
}

.current-action {
  padding: 10px 14px;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
}

.action-label {
  color: rgba(255, 255, 255, 0.5);
}

.action-text {
  color: rgba(255, 255, 255, 0.9);
}

.directions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.direction-item {
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.direction-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.direction-icon {
  width: 16px;
  height: 16px;
}

.direction-name {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
}

.direction-progress {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.direction-progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 6px;
}

.direction-progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 300ms ease;
}

.direction-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.stat-divider {
  color: rgba(255, 255, 255, 0.2);
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: center;
  padding: 12px;
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #8B5CF6;
  animation: bounce 1.4s infinite ease-in-out both;
}

.loading-dots span:nth-child(1) {
  animation-delay: -0.32s;
}

.loading-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

.loading-text {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.6);
}
</style>
