<script setup lang="ts">
import { ref, computed } from 'vue'
import { MessageCircleQuestion, Send, ChevronRight } from 'lucide-vue-next'
import type { ClarificationQuestion } from '@/types'

const props = defineProps<{
  questions: ClarificationQuestion[]
}>()

const emit = defineEmits<{
  submit: [answers: Record<number, string>]
  skip: []
}>()

// 存储每个问题的答案
const answers = ref<Record<number, string>>({})

// 检查是否所有问题都已回答
const allAnswered = computed(() => {
  return props.questions.every((_, index) => answers.value[index]?.trim())
})

// 提交答案
function handleSubmit() {
  if (allAnswered.value) {
    emit('submit', answers.value)
  }
}

// 选择选项
function selectOption(questionIndex: number, option: string) {
  answers.value[questionIndex] = option
}

// 检查选项是否被选中
function isSelected(questionIndex: number, option: string) {
  return answers.value[questionIndex] === option
}
</script>

<template>
  <div class="clarification-card">
    <!-- 标题 -->
    <div class="card-header">
      <div class="header-icon">
        <MessageCircleQuestion class="w-5 h-5" />
      </div>
      <div class="header-text">
        <h3 class="card-title">需要澄清</h3>
        <p class="card-subtitle">请回答以下问题以帮助我更好地理解您的需求</p>
      </div>
    </div>

    <!-- 问题列表 -->
    <div class="questions-list">
      <div
        v-for="(q, qIndex) in questions"
        :key="qIndex"
        class="question-item"
      >
        <div class="question-number">{{ qIndex + 1 }}</div>
        <div class="question-content">
          <p class="question-text">{{ q.question }}</p>
          
          <!-- 选项列表 -->
          <div class="options-grid">
            <button
              v-for="(option, oIndex) in q.options"
              :key="oIndex"
              class="option-btn"
              :class="{ 'option-selected': isSelected(qIndex, option) }"
              @click="selectOption(qIndex, option)"
            >
              <span class="option-text">{{ option }}</span>
              <ChevronRight v-if="isSelected(qIndex, option)" class="w-4 h-4 option-check" />
            </button>
          </div>

          <!-- 自定义输入 -->
          <div class="custom-input-wrapper">
            <input
              v-model="answers[qIndex]"
              type="text"
              class="custom-input"
              placeholder="或输入自定义答案..."
            />
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="actions">
      <button class="skip-btn" @click="emit('skip')">
        跳过，使用默认设置
      </button>
      <button
        class="submit-btn"
        :class="{ 'submit-btn-disabled': !allAnswered }"
        :disabled="!allAnswered"
        @click="handleSubmit"
      >
        <Send class="w-4 h-4" />
        <span>提交答案</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.clarification-card {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 16px;
  padding: 20px;
  margin: 12px 0;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #8B5CF6 0%, #A855F7 100%);
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

.questions-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.question-item {
  display: flex;
  gap: 12px;
}

.question-number {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(139, 92, 246, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #A78BFA;
  flex-shrink: 0;
}

.question-content {
  flex: 1;
}

.question-text {
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  margin-bottom: 12px;
  line-height: 1.5;
}

.options-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.option-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.option-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.12);
}

.option-selected {
  background: rgba(139, 92, 246, 0.15);
  border-color: rgba(139, 92, 246, 0.4);
  color: #C4B5FD;
}

.option-check {
  color: #A78BFA;
}

.custom-input-wrapper {
  margin-top: 8px;
}

.custom-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
  transition: all 200ms;
}

.custom-input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.custom-input:focus {
  outline: none;
  border-color: rgba(139, 92, 246, 0.4);
  background: rgba(255, 255, 255, 0.06);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.skip-btn {
  padding: 10px 16px;
  border-radius: 10px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.skip-btn:hover {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.7);
}

.submit-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 10px;
  background: linear-gradient(135deg, #8B5CF6 0%, #6366F1 100%);
  border: none;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms;
}

.submit-btn:hover:not(.submit-btn-disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

.submit-btn-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>
