<script setup lang="ts">
import { ref } from 'vue'
import { ClipboardList, Play, Edit3, X, Check, Clock, Compass } from 'lucide-vue-next'
import type { ResearchPlanConfirmEvent, DirectionSpec } from '@/types'

const props = defineProps<{
  plan: ResearchPlanConfirmEvent
}>()

const emit = defineEmits<{
  confirm: []
  modify: [directions: DirectionSpec[]]
  cancel: []
}>()

// 是否处于编辑模式
const isEditing = ref(false)
// 编辑中的研究方向
const editingDirections = ref<DirectionSpec[]>([])
// 编辑中的关键词文本（每个方向对应一个字符串）
const editingKeywordsText = ref<Record<string, string>>({})

// 开始编辑
function startEdit() {
  // 使用 structuredClone 替代 JSON.parse(JSON.stringify)
  editingDirections.value = structuredClone(props.plan.directions)
  // 初始化关键词文本
  editingKeywordsText.value = {}
  for (const dir of editingDirections.value) {
    editingKeywordsText.value[dir.id] = dir.keywords.join(', ')
  }
  isEditing.value = true
}

// 取消编辑
function cancelEdit() {
  isEditing.value = false
  editingDirections.value = []
}

// 保存修改
function saveModification() {
  emit('modify', editingDirections.value)
  isEditing.value = false
}

// 删除研究方向
function removeDirection(index: number) {
  editingDirections.value.splice(index, 1)
}

// 解析关键词文本为数组（支持中英文逗号）
function parseKeywords(text: string): string[] {
  return text.split(/[,，]/).map(k => k.trim()).filter(Boolean)
}

// 更新方向的关键词
function updateDirectionKeywords(directionId: string, text: string) {
  editingKeywordsText.value[directionId] = text
  const dir = editingDirections.value.find(d => d.id === directionId)
  if (dir) {
    dir.keywords = parseKeywords(text)
  }
}

// 获取优先级样式
function getPriorityClass(priority: number) {
  if (priority >= 8) return 'priority-high'
  if (priority >= 5) return 'priority-medium'
  return 'priority-low'
}

// 获取优先级文本
function getPriorityText(priority: number) {
  if (priority >= 8) return '高'
  if (priority >= 5) return '中'
  return '低'
}
</script>

<template>
  <div class="plan-confirm-card">
    <!-- 标题 -->
    <div class="card-header">
      <div class="header-icon" :class="{ 'header-icon-confirmed': !plan.can_modify }">
        <Check v-if="!plan.can_modify" class="w-5 h-5" />
        <ClipboardList v-else class="w-5 h-5" />
      </div>
      <div class="header-text">
        <h3 class="card-title">{{ plan.can_modify ? '研究计划确认' : '研究计划已确认' }}</h3>
        <p class="card-subtitle">{{ plan.can_modify ? '以下是针对您问题的研究方向，请确认后开始研究' : '研究方向已确认，正在执行中' }}</p>
      </div>
    </div>

    <!-- 计划概览 -->
    <div class="plan-overview">
      <div class="overview-item">
        <Compass class="w-4 h-4" />
        <span>{{ plan.directions.length }} 个研究方向</span>
      </div>
      <div class="overview-item">
        <Clock class="w-4 h-4" />
        <span>预计耗时：{{ plan.estimated_time }}</span>
      </div>
    </div>

    <!-- 研究方向列表 -->
    <div class="directions-list">
      <template v-if="!isEditing">
        <div
          v-for="(direction, index) in plan.directions"
          :key="direction.id"
          class="direction-item"
        >
          <div class="direction-header">
            <span class="direction-index">{{ index + 1 }}</span>
            <div class="direction-info">
              <h4 class="direction-name">{{ direction.name }}</h4>
              <p class="direction-desc">{{ direction.description }}</p>
            </div>
            <span class="direction-priority" :class="getPriorityClass(direction.priority)">
              {{ getPriorityText(direction.priority) }}优先级
            </span>
          </div>
          <div class="direction-keywords" v-if="direction.keywords.length > 0">
            <span
              v-for="keyword in direction.keywords"
              :key="keyword"
              class="keyword-tag"
            >
              {{ keyword }}
            </span>
          </div>
        </div>
      </template>

      <!-- 编辑模式 -->
      <template v-else>
        <div
          v-for="(direction, index) in editingDirections"
          :key="direction.id"
          class="direction-item editing"
        >
          <div class="direction-header">
            <span class="direction-index">{{ index + 1 }}</span>
            <input
              v-model="direction.name"
              class="edit-name"
              placeholder="方向名称"
            />
            <button class="remove-btn" @click="removeDirection(index)">
              <X class="w-4 h-4" />
            </button>
          </div>
          <textarea
            v-model="direction.description"
            class="edit-desc"
            placeholder="方向描述"
            rows="2"
          />
          <input
            :value="editingKeywordsText[direction.id] || ''"
            class="edit-keywords"
            placeholder="关键词（逗号分隔，支持中英文逗号）"
            @input="updateDirectionKeywords(direction.id, ($event.target as HTMLInputElement).value)"
          />
        </div>
      </template>
    </div>

    <!-- 操作按钮（已确认时隐藏） -->
    <div class="actions" v-if="plan.can_modify">
      <template v-if="!isEditing">
        <button class="cancel-btn" @click="emit('cancel')">
          <X class="w-4 h-4" />
          <span>取消研究</span>
        </button>
        <button class="modify-btn" @click="startEdit">
          <Edit3 class="w-4 h-4" />
          <span>修改计划</span>
        </button>
        <button class="confirm-btn" @click="emit('confirm')">
          <Play class="w-4 h-4" />
          <span>开始研究</span>
        </button>
      </template>
      <template v-else>
        <button class="cancel-edit-btn" @click="cancelEdit">
          取消
        </button>
        <button class="save-btn" @click="saveModification">
          <Check class="w-4 h-4" />
          <span>保存并开始</span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.plan-confirm-card {
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
  margin-bottom: 16px;
}

.header-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.header-icon-confirmed {
  background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
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

.plan-overview {
  display: flex;
  gap: 16px;
  padding: 12px 16px;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 10px;
  margin-bottom: 16px;
}

.overview-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.7);
}

.directions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.direction-item {
  padding: 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.direction-item.editing {
  border-color: rgba(139, 92, 246, 0.3);
  background: rgba(139, 92, 246, 0.05);
}

.direction-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}

.direction-index {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: #A5B4FC;
  flex-shrink: 0;
}

.direction-info {
  flex: 1;
}

.direction-name {
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  margin-bottom: 4px;
}

.direction-desc {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.5;
}

.direction-priority {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 6px;
  flex-shrink: 0;
}

.priority-high {
  background: rgba(239, 68, 68, 0.15);
  color: #FCA5A5;
}

.priority-medium {
  background: rgba(234, 179, 8, 0.15);
  color: #FDE047;
}

.priority-low {
  background: rgba(34, 197, 94, 0.15);
  color: #86EFAC;
}

.direction-keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.keyword-tag {
  padding: 4px 10px;
  background: rgba(139, 92, 246, 0.12);
  border-radius: 6px;
  font-size: 12px;
  color: #C4B5FD;
}

/* 编辑模式样式 */
.edit-name {
  flex: 1;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: white;
  font-size: 14px;
  font-weight: 500;
}

.edit-desc {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
  resize: none;
  margin-bottom: 8px;
}

.edit-keywords {
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
}

.remove-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #F87171;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 200ms;
}

.remove-btn:hover {
  background: rgba(239, 68, 68, 0.2);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.cancel-btn,
.cancel-edit-btn {
  padding: 10px 16px;
  border-radius: 10px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
  display: flex;
  align-items: center;
  gap: 6px;
}

.cancel-btn:hover,
.cancel-edit-btn:hover {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.7);
}

.modify-btn {
  padding: 10px 16px;
  border-radius: 10px;
  background: rgba(139, 92, 246, 0.12);
  border: 1px solid rgba(139, 92, 246, 0.25);
  color: #C4B5FD;
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
  display: flex;
  align-items: center;
  gap: 6px;
}

.modify-btn:hover {
  background: rgba(139, 92, 246, 0.18);
}

.confirm-btn,
.save-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
  border: none;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 200ms;
}

.confirm-btn:hover,
.save-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
</style>
