<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import { Bot, User } from 'lucide-vue-next'
import { renderMarkdown, highlightCode } from '@/utils'
import ConfirmationCard from './ConfirmationCard.vue'
import RecursionLimitCard from './RecursionLimitCard.vue'
import TeamProgressCard from './TeamProgressCard.vue'
import ResearchProgressCard from './ResearchProgressCard.vue'
import ClarificationCard from './ClarificationCard.vue'
import PlanConfirmCard from './PlanConfirmCard.vue'
import ResearchCompletedCard from './ResearchCompletedCard.vue'
import type { Message, DirectionSpec } from '@/types'

interface Props {
  message: Message
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

const contentRef = ref<HTMLElement | null>(null)

const isUser = computed(() => props.message.role === 'user')

const renderedContent = computed(() => {
  return isUser.value ? props.message.content : renderMarkdown(props.message.content)
})

// 是否有确认卡片
const hasConfirmation = computed(() => {
  return props.message.attachments?.confirmation
})

// 是否有递归限制卡片
const hasRecursionLimit = computed(() => {
  return props.message.attachments?.recursionLimit
})

// 是否有团队进度（包括初始化阶段）
const hasTeamStatus = computed(() => {
  const teamStatus = props.message.attachments?.teamStatus
  const teamPhase = props.message.attachments?.teamPhase
  // 有 teamPhase 或者 teamStatus 且不是 idle
  return teamPhase || (teamStatus && teamStatus.status !== 'idle')
})

// 团队阶段
const teamPhase = computed(() => {
  return props.message.attachments?.teamPhase
})

// 整合内容
const integratingContent = computed(() => {
  return props.message.attachments?.integratingContent
})

// 获取团队状态（确保有默认值）
const teamStatus = computed(() => {
  return props.message.attachments?.teamStatus || {
    status: 'running' as const,
    total_tasks: 0,
    completed: 0,
    in_progress: 0,
    tasks: []
  }
})

// 是否有研究进度
const hasResearchProgress = computed(() => {
  return props.message.attachments?.researchProgress
})

// 研究进度
const researchProgress = computed(() => {
  return props.message.attachments?.researchProgress
})

// 研究进度日志
const researchProgressLogs = computed(() => {
  return props.message.attachments?.researchProgressLogs
})

// 是否有研究计划确认
const hasResearchPlan = computed(() => {
  return props.message.attachments?.researchPlan
})

// 研究计划
const researchPlan = computed(() => {
  return props.message.attachments?.researchPlan
})

// 是否有澄清问题
const hasClarificationQuestions = computed(() => {
  const clarification = props.message.attachments?.clarification
  return clarification && clarification.questions && clarification.questions.length > 0
})

// 澄清问题数据
const clarificationData = computed(() => {
  return props.message.attachments?.clarification
})

// 澄清问题列表
const clarificationQuestions = computed(() => {
  return props.message.attachments?.clarification?.questions || []
})

// 是否有研究完成信息
const hasResearchCompleted = computed(() => {
  return props.message.attachments?.researchCompleted
})

// 研究完成数据
const researchCompleted = computed(() => {
  return props.message.attachments?.researchCompleted
})

// 高亮代码块
watch(() => props.message.content, () => {
  nextTick(() => {
    if (contentRef.value) {
      highlightCode(contentRef.value)
    }
  })
}, { immediate: true })

function handleConfirm(command: string, userMessage: string) {
  emit('confirm', command, userMessage)
}

function handleCancel(command: string, userMessage: string) {
  emit('cancel', command, userMessage)
}

function handleContinue() {
  emit('continue')
}

function handleResearchCancel() {
  if (researchProgress.value?.task_id) {
    emit('research-cancel', researchProgress.value.task_id)
  }
}

function handleResearchConfirmPlan() {
  const taskId = researchPlan.value?.task_id
  if (taskId) {
    emit('research-confirm-plan', taskId)
  }
}

function handleResearchModifyPlan(directions: DirectionSpec[]) {
  const taskId = researchPlan.value?.task_id
  if (taskId) {
    emit('research-modify-plan', taskId, directions)
  }
}

function handleResearchClarify(answers: Record<number, string>) {
  const taskId = clarificationData.value?.task_id
  if (taskId) {
    emit('research-clarify', taskId, answers)
  }
}

function handleResearchClarifySkip() {
  const taskId = clarificationData.value?.task_id
  if (taskId) {
    emit('research-clarify-skip', taskId)
  }
}

function handleResearchDownload(taskId: string, format: 'markdown' | 'pdf') {
  emit('research-download', taskId, format)
}
</script>

<template>
  <div :class="['message-item', isUser ? 'message-user' : 'message-assistant']">
    <!-- AI 头像 -->
    <div v-if="!isUser" class="message-avatar">
      <div class="avatar-ai">
        <Bot class="w-4 h-4" />
      </div>
    </div>

    <!-- 消息内容区域 -->
    <div class="message-content-wrapper">
      <!-- 主消息气泡 -->
      <div
        v-if="message.content || isUser"
        ref="contentRef"
        :class="['message-bubble', isUser ? 'bubble-user' : 'bubble-assistant']"
      >
        <div v-if="isUser" class="user-text">{{ message.content }}</div>
        <div v-else class="markdown-content" v-html="renderedContent" />
      </div>

      <!-- 团队进度卡片 -->
      <TeamProgressCard
        v-if="hasTeamStatus"
        :status="teamStatus"
        :phase="teamPhase"
        :integrating-content="integratingContent"
        class="attachment-card"
      />

<!-- 研究计划确认卡片（计划应在进度之上，符合 spec FR-1 约定） -->
<PlanConfirmCard
  v-if="hasResearchPlan && researchPlan"
  :plan="researchPlan"
  class="attachment-card"
  @confirm="handleResearchConfirmPlan"
  @modify="handleResearchModifyPlan"
  @cancel="handleResearchCancel"
/>

      <!-- 研究进度卡片 -->
      <ResearchProgressCard
        v-if="hasResearchProgress && researchProgress"
        :progress="researchProgress"
        :progress-logs="researchProgressLogs"
        class="attachment-card"
        @cancel="handleResearchCancel"
      />

      <!-- 澄清问题卡片 -->
      <ClarificationCard
        v-if="hasClarificationQuestions"
        :questions="clarificationQuestions"
        class="attachment-card"
        @submit="handleResearchClarify"
        @skip="handleResearchClarifySkip"
      />

      <!-- 研究完成卡片 -->
      <ResearchCompletedCard
        v-if="hasResearchCompleted && researchCompleted"
        :data="researchCompleted"
        :markdown-content="message.content"
        class="attachment-card"
        @download="handleResearchDownload"
      />

      <!-- 命令确认卡片 -->
      <ConfirmationCard
        v-if="hasConfirmation"
        :command="message.attachments!.confirmation!.command"
        :working-dir="message.attachments!.confirmation!.working_dir"
        :is-dangerous="message.attachments!.confirmation!.is_dangerous"
        :reason="message.attachments!.confirmation!.reason"
        class="attachment-card"
        @confirm="handleConfirm"
        @cancel="handleCancel"
      />

      <!-- 递归限制卡片 -->
      <RecursionLimitCard
        v-if="hasRecursionLimit"
        :message="message.attachments!.recursionLimit!.message"
        :partial-output="message.attachments!.recursionLimit!.partial_output"
        class="attachment-card"
        @continue="handleContinue"
      />
    </div>

    <!-- 用户头像 -->
    <div v-if="isUser" class="message-avatar">
      <div class="avatar-user">
        <User class="w-4 h-4" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  animation: messageSlideIn 250ms ease-out;
}

.message-user {
  justify-content: flex-end;
}

.message-assistant {
  justify-content: flex-start;
}

/* 头像 */
.message-avatar {
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

.avatar-user {
  width: 32px;
  height: 32px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #374151, #4B5563);
  color: var(--text-muted);
}

/* 消息内容包装器 */
.message-content-wrapper {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 70%;
}

/* 消息气泡 */
.message-bubble {
  padding: 14px 20px;
  border-radius: 20px;
  word-break: break-word;
  line-height: 1.7;
  transition: all 200ms var(--ease-default);
}

.bubble-user {
  border-radius: 20px 20px 4px 20px;
  background: linear-gradient(135deg, #7C3AED 0%, #6D28D9 100%);
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.2);
  color: white;
}

.user-text {
  white-space: pre-wrap;
}

.bubble-assistant {
  border-radius: 20px 20px 20px 4px;
  background: rgba(30, 41, 59, 0.65);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

/* 附加组件卡片 */
.attachment-card {
  margin-top: 4px;
}

/* 整合区域 */
.integrating-section {
  padding: 16px 20px;
  border-radius: 20px;
  background: rgba(30, 41, 59, 0.65);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(139, 92, 246, 0.15);
}

.integrating-header {
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}

.integrating-content {
  line-height: 1.7;
  color: var(--text-secondary);
}

/* Markdown 内容样式 */
.message-bubble :deep(.markdown-content),
.integrating-section :deep(.markdown-content) {
  line-height: 1.7;
}

.message-bubble :deep(.markdown-content h1),
.message-bubble :deep(.markdown-content h2),
.message-bubble :deep(.markdown-content h3),
.message-bubble :deep(.markdown-content h4),
.message-bubble :deep(.markdown-content h5),
.message-bubble :deep(.markdown-content h6) {
  margin-top: 1.2em;
  margin-bottom: 0.6em;
  font-weight: 600;
  line-height: 1.3;
  color: var(--text-primary);
}

.message-bubble :deep(.markdown-content h1) { font-size: 1.6em; }
.message-bubble :deep(.markdown-content h2) { font-size: 1.4em; }
.message-bubble :deep(.markdown-content h3) { font-size: 1.2em; }

.message-bubble :deep(.markdown-content p) {
  margin-bottom: 0.8em;
}

.message-bubble :deep(.markdown-content p:last-child) {
  margin-bottom: 0;
}

.message-bubble :deep(.markdown-content ul),
.message-bubble :deep(.markdown-content ol) {
  margin-bottom: 0.8em;
  padding-left: 1.5em;
}

.message-bubble :deep(.markdown-content li) {
  margin-bottom: 0.4em;
}

.message-bubble :deep(.markdown-content code) {
  padding: 2px 6px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.9em;
  background: rgba(0, 0, 0, 0.3);
  color: #e879f9;
}

.message-bubble :deep(.markdown-content pre) {
  margin: 1em 0;
  padding: 16px;
  border-radius: 14px;
  overflow-x: auto;
  background: linear-gradient(135deg, #111827, #1F2937);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.message-bubble :deep(.markdown-content pre code) {
  padding: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.875em;
}

.message-bubble :deep(.markdown-content blockquote) {
  margin: 1em 0;
  padding: 12px 16px;
  border-left: 3px solid var(--primary-500);
  border-radius: 0 8px 8px 0;
  background: rgba(124, 58, 237, 0.08);
  color: var(--text-muted);
}

.message-bubble :deep(.markdown-content a) {
  color: var(--primary-400);
  text-decoration: none;
}

.message-bubble :deep(.markdown-content a:hover) {
  text-decoration: underline;
}

.message-bubble :deep(.markdown-content table) {
  width: 100%;
  margin: 1em 0;
  border-collapse: collapse;
}

.message-bubble :deep(.markdown-content th),
.message-bubble :deep(.markdown-content td) {
  padding: 8px 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  text-align: left;
}

.message-bubble :deep(.markdown-content th) {
  background: rgba(255, 255, 255, 0.05);
  font-weight: 600;
}

.message-bubble :deep(.markdown-content hr) {
  margin: 1.5em 0;
  border: none;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

/* 动画 */
@keyframes messageSlideIn {
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
