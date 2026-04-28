<script setup lang="ts">
import { Download, FileText, Clock, BookOpen, CheckCircle } from 'lucide-vue-next'
import type { ResearchCompletedData } from '@/types'

const props = defineProps<{
  data: ResearchCompletedData
}>()

const emit = defineEmits<{
  download: [taskId: string, format: 'markdown' | 'pdf']
}>()

// 格式化时长
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${mins} 分 ${secs} 秒` : `${mins} 分钟`
}

// 下载 Markdown 报告
function downloadMarkdown() {
  emit('download', props.data.task_id, 'markdown')
}

// 下载 PDF 报告
function downloadPdf() {
  emit('download', props.data.task_id, 'pdf')
}
</script>

<template>
  <div class="completed-card">
    <!-- 标题 -->
    <div class="card-header">
      <div class="header-icon">
        <CheckCircle class="w-5 h-5" />
      </div>
      <div class="header-text">
        <h3 class="card-title">研究完成</h3>
        <p class="card-subtitle">研究报告已生成，可下载查看</p>
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

    <!-- 下载按钮 -->
    <div class="download-actions">
      <button class="download-btn download-md" @click="downloadMarkdown">
        <FileText class="w-4 h-4" />
        <span>Markdown</span>
      </button>
      <button class="download-btn download-pdf" @click="downloadPdf">
        <Download class="w-4 h-4" />
        <span>PDF</span>
      </button>
    </div>
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

.download-actions {
  display: flex;
  gap: 12px;
}

.download-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 20px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms;
}

.download-md {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}

.download-md:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.15);
}

.download-pdf {
  background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
  border: none;
  color: white;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.25);
}

.download-pdf:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(34, 197, 94, 0.3);
}
</style>
