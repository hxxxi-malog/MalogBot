<script setup lang="ts">
import { Play, AlertTriangle, StopCircle } from 'lucide-vue-next'

interface Props {
  message?: string
  partialOutput?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'continue'): void
  (e: 'stop'): void
}>()

function handleContinue() {
  console.log('[RecursionLimitCard] Continuing...')
  emit('continue')
}

function handleStop() {
  console.log('[RecursionLimitCard] Stopping...')
  emit('stop')
}
</script>

<template>
  <div class="recursion-card">
    <!-- 标题 -->
    <div class="card-header">
      <div class="card-icon">
        <AlertTriangle class="w-5 h-5" />
      </div>
      <div>
        <h4 class="card-title">达到递归限制</h4>
        <p class="card-subtitle">AI 已达到最大思考深度</p>
      </div>
    </div>

    <!-- 消息 -->
    <p v-if="message" class="card-desc">
      {{ message }}
    </p>
    <p v-else class="card-desc">
      AI 在处理过程中已达到递归限制。您可以选择继续让它思考，或者重新描述您的需求。
    </p>

    <!-- 部分输出 -->
    <div v-if="partialOutput" class="partial-output">
      <div class="partial-label">部分输出:</div>
      <div class="partial-content">{{ partialOutput.substring(0, 500) }}{{ partialOutput.length > 500 ? '...' : '' }}</div>
    </div>

    <!-- 操作按钮 -->
    <div class="actions">
      <button class="btn-continue" @click="handleContinue">
        <Play class="w-4 h-4" />
        继续思考
      </button>
      <button class="btn-stop" @click="handleStop">
        <StopCircle class="w-4 h-4" />
        停止
      </button>
    </div>
  </div>
</template>

<style scoped>
.recursion-card {
  padding: 20px;
  border-radius: 20px;
  margin-bottom: 24px;
  width: fit-content;
  max-width: 65%;
  background: rgba(17, 24, 39, 0.75);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(245, 158, 11, 0.2);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  animation: fadeIn 300ms ease-out;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.card-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(245, 158, 11, 0.08));
  color: var(--warning-400);
}

.card-title {
  font-weight: 600;
  font-size: 15px;
  margin: 0;
  color: var(--text-primary);
}

.card-subtitle {
  font-size: 12px;
  color: var(--text-faint);
  margin: 2px 0 0;
}

.card-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 16px;
  line-height: 1.6;
}

.partial-output {
  padding: 14px;
  border-radius: 14px;
  margin-bottom: 16px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.partial-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-faint);
  margin-bottom: 8px;
}

.partial-content {
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
  white-space: pre-wrap;
}

.actions {
  display: flex;
  gap: 12px;
}

.btn-continue {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 14px;
  font-size: 14px;
  font-weight: 500;
  background: var(--gradient-brand);
  color: white;
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.25);
  transition: all 200ms var(--ease-default);
}

.btn-continue:hover {
  transform: translateY(-2px);
}

.btn-continue:active {
  transform: translateY(0);
}

.btn-stop {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 14px;
  font-size: 14px;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
  transition: all 200ms var(--ease-default);
}

.btn-stop:hover {
  background: rgba(239, 68, 68, 0.15);
  color: var(--danger-400);
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
