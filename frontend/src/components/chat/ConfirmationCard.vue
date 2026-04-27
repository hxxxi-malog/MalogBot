<script setup lang="ts">
import { ref } from 'vue'
import { Play, X, AlertTriangle, Zap } from 'lucide-vue-next'

interface Props {
  command: string
  workingDir?: string
  isDangerous?: boolean
  reason?: string
  commandType?: string
  operation?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'confirm', command: string, userMessage: string): void
  (e: 'cancel', command: string, userMessage: string): void
}>()

const userMessage = ref('')

function handleConfirm() {
  console.log('[ConfirmationCard] Confirming command:', props.command)
  emit('confirm', props.command, userMessage.value || '继续执行')
}

function handleCancel() {
  console.log('[ConfirmationCard] Cancelling command:', props.command)
  emit('cancel', props.command, userMessage.value || '取消执行')
}
</script>

<template>
  <div class="confirm-card" :class="{ 'confirm-card-danger': isDangerous }">
    <!-- 标题 -->
    <div class="card-header">
      <div class="card-icon" :class="{ 'card-icon-danger': isDangerous }">
        <component :is="isDangerous ? AlertTriangle : Zap" class="w-5 h-5" />
      </div>
      <div>
        <h4 class="card-title">{{ isDangerous ? '危险命令确认' : '命令确认' }}</h4>
        <p class="card-subtitle">请确认是否执行以下命令</p>
      </div>
    </div>

    <!-- 命令显示 -->
    <div class="command-box">
      <code>{{ command }}</code>
    </div>

    <!-- 工作目录 -->
    <div v-if="workingDir" class="working-dir">
      <span>工作目录:</span>
      <code>{{ workingDir }}</code>
    </div>

    <!-- 操作类型 -->
    <div v-if="operation" class="operation-info">
      <span>操作:</span>
      <span>{{ operation }}</span>
    </div>

    <!-- 危险原因 -->
    <div v-if="isDangerous && reason" class="reason-box">
      <strong>风险:</strong> {{ reason }}
    </div>

    <!-- 输入框 -->
    <div class="input-wrapper">
      <input
        v-model="userMessage"
        type="text"
        placeholder="附加说明（可选）"
        class="input-field"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="actions">
      <button class="btn-confirm" @click="handleConfirm">
        <Play class="w-4 h-4" />
        确认执行
      </button>
      <button class="btn-cancel" @click="handleCancel">
        <X class="w-4 h-4" />
        取消
      </button>
    </div>
  </div>
</template>

<style scoped>
.confirm-card {
  padding: 20px;
  border-radius: 20px;
  margin-bottom: 24px;
  width: fit-content;
  max-width: 65%;
  background: rgba(17, 24, 39, 0.75);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  animation: fadeIn 300ms ease-out;
}

.confirm-card-danger {
  border-color: rgba(239, 68, 68, 0.2);
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

.card-icon-danger {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.08));
  color: var(--danger-400);
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

.command-box {
  padding: 16px;
  border-radius: 14px;
  margin-bottom: 16px;
  font-family: var(--font-mono);
  font-size: 14px;
  overflow-x: auto;
  background: linear-gradient(135deg, #111827, #1F2937);
  color: var(--text-secondary);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.working-dir,
.operation-info {
  font-size: 12px;
  color: var(--text-faint);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.working-dir code {
  padding: 2px 8px;
  border-radius: 6px;
  font-family: var(--font-mono);
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-muted);
}

.reason-box {
  padding: 10px 14px;
  border-radius: 14px;
  margin-bottom: 16px;
  font-size: 14px;
  color: var(--danger-400);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.15);
}

.input-wrapper {
  margin-bottom: 16px;
}

.input-field {
  width: 100%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  transition: all 200ms var(--ease-default);
}

.input-field::placeholder {
  color: var(--text-faint);
}

.input-field:focus {
  border-color: rgba(139, 92, 246, 0.35);
}

.actions {
  display: flex;
  gap: 12px;
}

.btn-confirm {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 14px;
  font-size: 14px;
  font-weight: 500;
  background: linear-gradient(135deg, #059669, #10B981);
  color: white;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2);
  transition: all 200ms var(--ease-default);
}

.btn-confirm:hover {
  transform: translateY(-2px);
}

.btn-confirm:active {
  transform: translateY(0);
}

.btn-cancel {
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

.btn-cancel:hover {
  background: rgba(255, 255, 255, 0.1);
  transform: translateY(-2px);
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
