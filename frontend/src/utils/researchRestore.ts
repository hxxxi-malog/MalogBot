/**
 * 研究状态恢复工具
 *
 * 用于从后端获取的 research_tasks 数据恢复前端消息中的研究状态
 * （报告内容、计划卡片、完成卡片），解决刷新后数据丢失的问题。
 */
import type { DirectionSpec, Message } from '@/types'

/** 后端返回的研究任务历史数据 */
export interface ResearchTaskRestoreData {
  task_id: string
  query: string
  mode: string
  status: string
  report_content: string | null
  report_word_count: number | null
  report_source_count: number | null
  duration_seconds: number | null
  plan: { directions: DirectionSpec[]; is_confirmed: boolean } | null
}

/**
 * 将已完成的研究报告恢复到前端消息中
 *
 * 策略：找到用户问题对应的 assistant 消息，将报告内容和研究元数据注入其 attachments。
 * 此函数会直接修改 messages 数组中的对象（Vue reactive 可追踪）。
 *
 * @param messages - 前端消息列表
 * @param researchTask - 后端返回的研究任务数据
 * @returns true 表示恢复成功，false 表示跳过（未完成/无报告/找不到对应消息）
 */
export function restoreCompletedResearch(
  messages: Message[],
  researchTask: ResearchTaskRestoreData
): boolean {
  // 仅处理已完成且包含报告内容的研究任务
  if (researchTask.status !== 'completed' || !researchTask.report_content) {
    return false
  }

  // 找到与该研究问题对应的用户消息（跳过已恢复的，避免重复 query 时匹配到错误位置）
  const userMsgIndex = messages.findIndex(
    (m) => m.role === 'user' && m.content === researchTask.query && !((m as unknown as Record<string, unknown>)._researchRestored)
  )
  if (userMsgIndex === -1) {
    console.warn('[researchRestore] Could not find user message for research:', researchTask.query.substring(0, 50))
    return false
  }

  // 标记该 user 消息已被恢复，防止后续重复 query 匹配到同一位置
  ;(messages[userMsgIndex] as unknown as Record<string, unknown>)._researchRestored = true

  // 找到用户消息之后的 assistant 消息
  const assistantMsg = messages[userMsgIndex + 1]
  if (!assistantMsg || assistantMsg.role !== 'assistant') {
    console.warn('[researchRestore] Could not find assistant message after user research query')
    return false
  }

  // 恢复报告内容
  assistantMsg.content = researchTask.report_content

  // 恢复研究 attachments
  if (!assistantMsg.attachments) {
    assistantMsg.attachments = {}
  }

  // 恢复研究计划卡片
  // 注意：需额外检查 length > 0，因为 JS 中空数组 [] 是 truthy（与 Python 中 [] 为 falsy 不同），
  // 若后端逻辑变更导致空 directions 被序列化为 []，前端需显式过滤
  if (researchTask.plan && researchTask.plan.directions && researchTask.plan.directions.length > 0) {
    assistantMsg.attachments.researchPlan = {
      task_id: researchTask.task_id,
      directions: researchTask.plan.directions as DirectionSpec[],
      estimated_time: '',
      can_modify: false,
    }
  }

  // 恢复研究完成卡片
  assistantMsg.attachments.researchCompleted = {
    task_id: researchTask.task_id,
    source_count: researchTask.report_source_count ?? 0,
    duration_seconds: researchTask.duration_seconds ?? 0,
    word_count: researchTask.report_word_count ?? undefined,
  }

  console.log('[researchRestore] Restored research report for task:', researchTask.task_id)
  return true
}
