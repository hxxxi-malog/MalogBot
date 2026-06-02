<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { 
  Search, 
  Brain, 
  FileText, 
  CheckCircle, 
  Clock, 
  XCircle,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  BookOpen,
  Lightbulb,
  Loader2,
  Timer
} from 'lucide-vue-next'
import type { ResearchProgress, ResearchDirectionProgress, ResearchProgressLogEntry } from '@/types'

const props = defineProps<{
  progress: ResearchProgress
  progressLogs?: ResearchProgressLogEntry[]
}>()

const emit = defineEmits<{
  cancel: []
}>()

// 本地计时器：基于后端推送的 elapsed_seconds 作为基准，本地持续递增
// 深度研究模式下，计时从研究方向到达后开始（后端已开始执行）
// 标准研究模式下，计时从任务创建后开始
const localElapsedSeconds = ref(0)
let timerInterval: ReturnType<typeof setInterval> | null = null
const isTimerRunning = ref(false)

// 判断计时是否应启动
function shouldTimerRun(): boolean {
  // 标准研究模式：一开始就计时
  if (props.progress.mode === 'standard') return true
  // 深度研究模式：研究方向到达后才计时（后端已开始执行，elapsed_seconds 由后端计算）
  return props.progress.directions.length > 0
}

// 启动计时器
function startTimer() {
  if (isTimerRunning.value) return
  isTimerRunning.value = true

  // 使用后端推送的 elapsed_seconds 作为初始值
  // 深度研究模式下，计时从研究方向到达时才开始，后端已在计时
  localElapsedSeconds.value = props.progress.elapsed_seconds || 0

  timerInterval = setInterval(() => {
    localElapsedSeconds.value++
  }, 1000)
}

// 停止计时器
function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  isTimerRunning.value = false
}

// 监听后端推送的 elapsed_seconds 更新本地基准
// 后端每 5 秒推送一次，用于校正本地计时漂移
watch(() => props.progress.elapsed_seconds, (newVal) => {
  if (newVal && newVal > localElapsedSeconds.value) {
    localElapsedSeconds.value = newVal
  }
})

// 监听是否应启动计时器
watch(() => shouldTimerRun(), (shouldRun) => {
  if (shouldRun) {
    startTimer()
  }
}, { immediate: true })

onMounted(() => {
  if (shouldTimerRun()) {
    startTimer()
  }
})

onUnmounted(() => {
  stopTimer()
})

// 展开/折叠状态
const expandedDirections = ref<Set<string>>(new Set())

// 时间线日志记录（从 props 传入或本地生成）
interface TimelineLog {
  id: string
  directionId: string
  directionName: string
  timestamp: Date
  phase: string
  message: string
  progress: number
  learnings_count?: number
  sources_count?: number
}

const logsContainerRef = ref<HTMLElement | null>(null)

// 之前的方向状态，用于检测变化（当没有外部日志时使用）
const previousDirections = ref<Map<string, ResearchDirectionProgress>>(new Map())

// 本地生成的日志（当没有外部日志时使用）
const localTimelineLogs = ref<TimelineLog[]>([])

// 使用外部日志或本地日志
const timelineLogs = computed<TimelineLog[]>(() => {
  if (props.progressLogs && props.progressLogs.length > 0) {
    return props.progressLogs.map(log => ({
      id: log.id,
      directionId: log.direction_id,
      directionName: log.direction_name,
      timestamp: log.timestamp instanceof Date ? log.timestamp : new Date(log.timestamp),
      phase: log.phase,
      message: log.message,
      progress: log.progress,
      learnings_count: log.learnings_count,
      sources_count: log.sources_count,
    }))
  }
  return localTimelineLogs.value
})

// 监听方向变化，添加日志（仅在没有外部日志时使用）
// 使用 computed 生成方向摘要字符串，避免 deep: true 的全量递归比较
const directionsSnapshot = computed(() =>
  props.progress.directions
    .map(d => `${d.direction_id}:${d.status}:${d.progress}`)
    .join('|')
)

watch(directionsSnapshot, () => {
  // 如果有外部日志，不生成本地日志
  if (props.progressLogs && props.progressLogs.length > 0) {
    return
  }
  
  props.progress.directions.forEach(dir => {
    const prevDir = previousDirections.value.get(dir.direction_id)
    if (!prevDir) {
      // 新方向开始
      addLocalLog(dir.direction_id, dir.direction_name, 'started', '开始研究', 0)
    } else if (prevDir.status !== dir.status || prevDir.progress !== dir.progress) {
      // 状态或进度变化
      if (prevDir.progress !== dir.progress) {
        addLocalLog(dir.direction_id, dir.direction_name, dir.status, dir.current_action, dir.progress)
      }
    }
    // 更新之前的状态
    previousDirections.value.set(dir.direction_id, { ...dir })
  })
})

function addLocalLog(directionId: string, directionName: string, phase: string, message: string, progress: number) {
  // 防止重复日志
  const lastLog = localTimelineLogs.value[localTimelineLogs.value.length - 1]
  if (lastLog && 
      lastLog.directionId === directionId && 
      lastLog.phase === phase &&
      lastLog.progress === progress) {
    return
  }
  
  const log: TimelineLog = {
    id: `${directionId}-${Date.now()}`,
    directionId,
    directionName,
    timestamp: new Date(),
    phase,
    message: message || '处理中',
    progress
  }
  localTimelineLogs.value.push(log)
  
  // 限制日志数量
  if (localTimelineLogs.value.length > 50) {
    localTimelineLogs.value = localTimelineLogs.value.slice(-50)
  }
  
  // 自动滚动到底部
  scrollToBottom()
}

// 自动滚动到底部
watch(() => timelineLogs.value.length, () => {
  scrollToBottom()
})

function scrollToBottom() {
  setTimeout(() => {
    if (logsContainerRef.value) {
      logsContainerRef.value.scrollTop = logsContainerRef.value.scrollHeight
    }
  }, 50)
}

// 已完成方向数
const completedCount = computed(() => 
  props.progress.directions.filter(d => d.status === 'completed').length
)

// 进行中方向数
const activeCount = computed(() => 
  props.progress.directions.filter(d => d.status !== 'completed' && d.status !== 'pending' && d.status !== 'failed').length
)

// 格式化时间（使用本地计时器）
const formattedTime = computed(() => {
  const seconds = localElapsedSeconds.value
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

// 阶段标签
function getPhaseLabel(phase: string): string {
  switch (phase) {
    case 'exploring': return '搜索中'
    case 'analyzing': return '分析中'
    case 'synthesizing': return '总结中'
    case 'completed': return '已完成'
    case 'failed': return '失败'
    case 'started': return '已启动'
    default: return '等待中'
  }
}

// 切换方向展开状态
function toggleDirection(directionId: string) {
  if (expandedDirections.value.has(directionId)) {
    expandedDirections.value.delete(directionId)
  } else {
    expandedDirections.value.add(directionId)
  }
}

// 格式化时间戳
function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { 
    hour: '2-digit', 
    minute: '2-digit', 
    second: '2-digit' 
  })
}
</script>

<template>
  <div class="research-progress-card">
    <!-- 标题区 -->
    <div class="progress-header">
      <div class="header-left">
        <div class="research-icon">
          <Search class="w-5 h-5" />
        </div>
        <div class="header-info">
          <h3 class="research-title">正在研究</h3>
          <p class="research-mode">{{ progress.mode === 'deep' ? '深度研究' : '标准研究' }}</p>
        </div>
      </div>
      <div class="header-right">
        <div class="time-display" v-if="isTimerRunning">
          <Clock class="w-4 h-4" />
          <span>{{ formattedTime }}</span>
        </div>
        <div class="estimated-remaining" v-if="progress.estimated_remaining">
          <Timer class="w-4 h-4" />
          <span>{{ progress.estimated_remaining }}</span>
        </div>
        <button class="cancel-btn" @click="emit('cancel')">
          <XCircle class="w-4 h-4" />
          <span>取消</span>
        </button>
      </div>
    </div>

    <!-- 当前状态摘要 -->
    <div class="status-summary-section">
      <p class="current-action" v-if="progress.current_action">{{ progress.current_action }}</p>
      <div class="status-meta" v-if="progress.directions.length > 0">
        <span class="meta-item completed-meta">
          {{ completedCount }}/{{ progress.directions.length }} 方向已完成
        </span>
        <span class="meta-divider" v-if="activeCount > 0">|</span>
        <span class="meta-item active-meta" v-if="activeCount > 0">
          {{ activeCount }} 个进行中
        </span>
      </div>
      <div class="status-meta" v-else>
        <span class="meta-item">
          <Loader2 class="w-3 h-3 inline-block animate-spin" />
          正在规划研究方向...
        </span>
      </div>
    </div>

    <!-- 研究方向卡片列表 -->
    <div class="directions-section" v-if="progress.directions.length > 0">
      <h4 class="section-title">
        <BookOpen class="w-4 h-4" />
        研究方向 ({{ progress.directions.length }})
      </h4>
      
      <div class="directions-list">
        <div
          v-for="direction in progress.directions"
          :key="direction.direction_id"
          class="direction-card"
          :class="{ 'is-expanded': expandedDirections.has(direction.direction_id) }"
        >
          <!-- 方向头部 -->
          <div 
            class="direction-header"
            @click="toggleDirection(direction.direction_id)"
          >
            <div class="direction-status">
              <component
                :is="getStatusIcon(direction.status)"
                class="status-icon"
                :class="getStatusColor(direction.status)"
              />
              <div class="direction-info">
                <span class="direction-name">{{ direction.direction_name }}</span>
                <span class="direction-phase">{{ getPhaseLabel(direction.status) }}</span>
              </div>
            </div>
            
            <div class="direction-meta">
              <span class="direction-status-text" :class="getStatusColor(direction.status)">
                {{ getPhaseLabel(direction.status) }}
              </span>
              <component
                :is="expandedDirections.has(direction.direction_id) ? ChevronUp : ChevronDown"
                class="expand-icon"
              />
            </div>
          </div>
          
          <!-- 方向详情（展开时显示） -->
          <div class="direction-details" v-if="expandedDirections.has(direction.direction_id)">
            <div class="detail-item" v-if="direction.current_action">
              <span class="detail-label">当前操作</span>
              <span class="detail-value">{{ direction.current_action }}</span>
            </div>
            <div class="detail-stats">
              <div class="stat-item" v-if="direction.learnings_count > 0">
                <Lightbulb class="w-4 h-4" />
                <span>{{ direction.learnings_count }} 条发现</span>
              </div>
              <div class="stat-item" v-if="direction.sources_count > 0">
                <ExternalLink class="w-4 h-4" />
                <span>{{ direction.sources_count }} 个来源</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 实时日志瀑布屏 -->
    <div class="timeline-logs-section" v-if="timelineLogs.length > 0">
      <h4 class="section-title">
        <Clock class="w-4 h-4" />
        实时进度日志
      </h4>
      
      <div class="logs-container" ref="logsContainerRef">
        <div 
          v-for="log in timelineLogs" 
          :key="log.id"
          class="log-entry"
          :class="`phase-${log.phase}`"
        >
          <div class="log-time">{{ formatTimestamp(log.timestamp) }}</div>
          <div class="log-content">
            <span class="log-direction">[{{ log.directionName }}]</span>
            <component
              :is="getStatusIcon(log.phase)"
              class="log-icon"
              :class="getStatusColor(log.phase)"
            />
            <span class="log-message">{{ log.message }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 加载动画 -->
    <div class="loading-indicator" v-if="timelineLogs.length === 0 && progress.directions.length === 0">
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
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 16px;
  padding: 20px;
  margin: 12px 0;
  backdrop-filter: blur(10px);
}

/* 标题区 */
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.research-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.header-info {
  display: flex;
  flex-direction: column;
}

.research-title {
  font-size: 18px;
  font-weight: 600;
  color: white;
}

.research-mode {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.time-display {
  display: flex;
  align-items: center;
  gap: 6px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
}

.estimated-remaining {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #818CF8;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  padding: 6px 12px;
  background: rgba(129, 140, 248, 0.1);
  border-radius: 8px;
  border: 1px solid rgba(129, 140, 248, 0.15);
}

.cancel-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #F87171;
  font-size: 13px;
  cursor: pointer;
  transition: all 200ms;
}

.cancel-btn:hover {
  background: rgba(239, 68, 68, 0.2);
  transform: translateY(-1px);
}

/* 状态摘要 */
.status-summary-section {
  margin-bottom: 20px;
  padding: 16px;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 12px;
  border: 1px solid rgba(99, 102, 241, 0.15);
}

.current-action {
  font-size: 15px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  margin: 0 0 8px 0;
}

.current-action:only-child {
  margin-bottom: 0;
}

.status-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
}

.meta-divider {
  color: rgba(255, 255, 255, 0.2);
}

.completed-meta {
  color: #4ADE80;
}

.active-meta {
  color: #818CF8;
}

/* 研究方向列表 */
.directions-section {
  margin-bottom: 20px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 12px 0;
}

.directions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.direction-card {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 200ms;
}

.direction-card:hover {
  background: rgba(255, 255, 255, 0.05);
}

.direction-card.is-expanded {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(99, 102, 241, 0.2);
}

.direction-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  cursor: pointer;
}

.direction-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-icon {
  width: 20px;
  height: 20px;
}

.direction-info {
  display: flex;
  flex-direction: column;
}

.direction-name {
  font-size: 14px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.direction-phase {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.direction-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.direction-status-text {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}

.expand-icon {
  width: 18px;
  height: 18px;
  color: rgba(255, 255, 255, 0.4);
}

/* 方向详情 */
.direction-details {
  padding: 0 12px 12px 42px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 12px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.detail-label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.detail-value {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.8);
}

.detail-stats {
  display: flex;
  gap: 16px;
  margin-top: 8px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.stat-item svg {
  width: 14px;
  height: 14px;
}

/* 实时日志 */
.timeline-logs-section {
  margin-bottom: 16px;
}

.logs-container {
  max-height: 180px;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 8px;
}

.logs-container::-webkit-scrollbar {
  width: 4px;
}

.logs-container::-webkit-scrollbar-track {
  background: transparent;
}

.logs-container::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}

.log-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  transition: background 150ms;
  border-left: 2px solid transparent;
}

.log-entry:hover {
  background: rgba(255, 255, 255, 0.03);
}

.log-time {
  color: rgba(255, 255, 255, 0.4);
  font-variant-numeric: tabular-nums;
  min-width: 70px;
  flex-shrink: 0;
}

.log-content {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.log-direction {
  color: rgba(139, 92, 246, 0.8);
  white-space: nowrap;
}

.log-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.log-message {
  color: rgba(255, 255, 255, 0.8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


/* 阶段颜色 */
.phase-started {
  border-left-color: #6366F1;
}

.phase-exploring {
  border-left-color: #3B82F6;
}

.phase-analyzing {
  border-left-color: #A855F7;
}

.phase-synthesizing {
  border-left-color: #06B6D4;
}

.phase-completed {
  border-left-color: #22C55E;
}

.phase-failed {
  border-left-color: #EF4444;
}

/* 加载动画 */
.loading-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: center;
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  margin-top: 12px;
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366F1;
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
  color: rgba(255, 255, 255, 0.5);
}
</style>
