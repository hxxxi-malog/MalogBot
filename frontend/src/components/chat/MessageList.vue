<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { Bot } from 'lucide-vue-next'
import MessageItem from './MessageItem.vue'
import type { Message, DirectionSpec } from '@/types'

interface Props {
  messages: Message[]
  isStreaming: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'confirm', command: string, userMessage: string): void
  (e: 'cancel', command: string, userMessage: string): void
  (e: 'continue'): void
  (e: 'research-cancel', taskId: string): void
  (e: 'research-confirm-plan', taskId: string): void
  (e: 'research-modify-plan', taskId: string, directions: DirectionSpec[]): void
  (e: 'research-clarify', taskId: string, answers: Record<number, string>): void
  (e: 'research-clarify-skip', taskId: string): void
  (e: 'research-download', taskId: string, format: 'markdown' | 'pdf'): void
}>()

const listRef = ref<HTMLElement | null>(null)

// 是否显示打字指示器
// 条件：正在流式输出 且 (没有消息 或 最后一条不是 assistant 或 最后一条 assistant 内容为空)
// 但是，如果处于团队模式（有 teamPhase），不显示打字指示器
const showTypingIndicator = computed(() => {
  if (!props.isStreaming) return false
  
  if (props.messages.length === 0) return true
  
  const lastMessage = props.messages[props.messages.length - 1]
  
  // 如果处于团队模式（有 teamPhase），不显示打字指示器
  // 因为团队模式有自己的进度展示
  if (lastMessage.attachments?.teamPhase) return false
  
  // 如果处于研究模式（有 researchProgress），不显示打字指示器
  if (lastMessage.attachments?.researchProgress) return false
  
  // 如果最后一条是用户消息，显示打字指示器
  if (lastMessage.role === 'user') return true
  
  // 如果最后一条是 assistant 但内容为空，显示打字指示器
  if (lastMessage.role === 'assistant' && !lastMessage.content?.trim()) return true
  
  return false
})

// 智能滚动：仅在用户处于底部附近时自动滚动，用户上滑查看历史时不被拉回
function isUserNearBottom(): boolean {
  const el = listRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 100
}

watch(() => props.messages, () => {
  nextTick(() => {
    if (listRef.value && isUserNearBottom()) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}, { deep: true })

function handleConfirm(command: string, userMessage: string) {
  emit('confirm', command, userMessage)
}

function handleCancel(command: string, userMessage: string) {
  emit('cancel', command, userMessage)
}

function handleContinue() {
  emit('continue')
}

function handleResearchCancel(taskId: string) {
  emit('research-cancel', taskId)
}

function handleResearchConfirmPlan(taskId: string) {
  emit('research-confirm-plan', taskId)
}

function handleResearchModifyPlan(taskId: string, directions: DirectionSpec[]) {
  emit('research-modify-plan', taskId, directions)
}

function handleResearchClarify(taskId: string, answers: Record<number, string>) {
  emit('research-clarify', taskId, answers)
}

function handleResearchClarifySkip(taskId: string) {
  emit('research-clarify-skip', taskId)
}

function handleResearchDownload(taskId: string, format: 'markdown' | 'pdf') {
  emit('research-download', taskId, format)
}
</script>

<template>
  <div ref="listRef" class="message-list">
    <!-- 消息列表 -->
    <MessageItem
      v-for="message in messages"
      :key="message.id"
      :message="message"
      @confirm="handleConfirm"
      @cancel="handleCancel"
      @continue="handleContinue"
      @research-cancel="handleResearchCancel"
      @research-confirm-plan="handleResearchConfirmPlan"
      @research-modify-plan="handleResearchModifyPlan"
      @research-clarify="handleResearchClarify"
      @research-clarify-skip="handleResearchClarifySkip"
      @research-download="handleResearchDownload"
    />

    <!-- 打字指示器 -->
    <div v-if="showTypingIndicator" class="typing-indicator">
      <div class="typing-avatar">
        <div class="avatar-ai">
          <Bot class="w-4 h-4" />
        </div>
      </div>
      <div class="typing-bubble">
        <div class="typing-dots">
          <span class="dot" />
          <span class="dot" style="animation-delay: 0.16s" />
          <span class="dot" style="animation-delay: 0.32s" />
        </div>
        <span class="typing-text">AI 正在思考...</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  position: relative;
  z-index: 10;
}

/* 打字指示器 */
.typing-indicator {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 20px;
  animation: fadeIn 300ms ease-out;
}

.typing-avatar {
  flex-shrink: 0;
  margin-top: 4px;
}

.avatar-ai {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
  color: white;
}

.typing-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-radius: 20px 20px 20px 4px;
  background: rgba(30, 41, 59, 0.65);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.typing-dots {
  display: flex;
  gap: 6px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary-400);
  animation: typingBounce 1.4s ease-in-out infinite;
}

.typing-text {
  font-size: 14px;
  color: var(--text-dim);
}

/* 动画 */
@keyframes typingBounce {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-6px);
    opacity: 1;
  }
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
