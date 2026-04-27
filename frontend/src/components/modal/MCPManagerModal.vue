<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { X, Plus, RefreshCw, Download, Upload, Trash2, TestTube, Plug, Zap, Globe, Radio, Terminal } from 'lucide-vue-next'
import { mcpApi } from '@/api'
import type { MCPServer, MCPStats } from '@/types'

const emit = defineEmits<{ (e: 'close'): void }>()

const servers = ref<MCPServer[]>([])
const stats = ref<MCPStats | null>(null)

async function loadServers() {
  try {
    console.log('[MCPModal] Loading servers...')
    const data = await mcpApi.list()
    servers.value = data.servers || []
    stats.value = data.stats || null
    console.log('[MCPModal] Loaded', servers.value.length, 'servers')
  } catch (error) {
    console.error('[MCPModal] Load MCP servers error:', error)
  }
}

onMounted(() => loadServers())

async function handleToggle(name: string, enabled: boolean) {
  try {
    console.log('[MCPModal] Toggling server:', name, enabled)
    if (enabled) {
      await mcpApi.enable(name)
    } else {
      await mcpApi.disable(name)
    }
    await loadServers()
  } catch (error) {
    console.error('[MCPModal] Toggle MCP server error:', error)
  }
}

async function handleTest(name: string) {
  try {
    console.log('[MCPModal] Testing server:', name)
    const data = await mcpApi.test(name)
    if (data.success) {
      alert(`连接成功！发现 ${data.tools_count} 个工具`)
      await loadServers()
    } else {
      alert(`连接失败: ${data.message}`)
    }
  } catch (error) {
    console.error('[MCPModal] Test MCP server error:', error)
    alert('测试失败')
  }
}

async function handleRefresh(name: string) {
  try {
    console.log('[MCPModal] Refreshing server:', name)
    await mcpApi.refresh(name)
    await loadServers()
    alert('刷新成功')
  } catch (error) {
    console.error('[MCPModal] Refresh error:', error)
    alert('刷新失败')
  }
}

async function handleRefreshAll() {
  try {
    console.log('[MCPModal] Refreshing all servers')
    await mcpApi.refreshAll()
    await loadServers()
    alert('全部刷新完成')
  } catch (error) {
    console.error('[MCPModal] Refresh all error:', error)
    alert('刷新失败')
  }
}

async function handleDelete(name: string) {
  if (!confirm(`确定要删除服务 "${name}" 吗？`)) return
  try {
    console.log('[MCPModal] Deleting server:', name)
    await mcpApi.delete(name)
    await loadServers()
  } catch (error) {
    console.error('[MCPModal] Delete error:', error)
    alert('删除失败')
  }
}

async function handleExport() {
  try {
    console.log('[MCPModal] Exporting config')
    const data = await mcpApi.exportConfig()
    const blob = new Blob([JSON.stringify(data.config, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'mcp_servers_config.json'
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    console.error('[MCPModal] Export error:', error)
    alert('导出失败')
  }
}

function handleImport() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return
    try {
      console.log('[MCPModal] Importing config from:', file.name)
      const text = await file.text()
      const config = JSON.parse(text)
      const data = await mcpApi.importConfig(config)
      await loadServers()
      alert(`导入完成: 成功 ${data.success_count} 个，失败 ${data.fail_count} 个`)
    } catch (error) {
      console.error('[MCPModal] Import error:', error)
      alert('导入失败')
    }
  }
  input.click()
}

function getTypeInfo(type: string): { icon: any; label: string; gradient: string } {
  const map: Record<string, { icon: any; label: string; gradient: string }> = {
    'streamable-http': {
      icon: Zap,
      label: 'Streamable HTTP',
      gradient: 'linear-gradient(135deg, rgba(59,130,246,0.3), rgba(6,182,212,0.2))'
    },
    http: {
      icon: Globe,
      label: 'HTTP',
      gradient: 'linear-gradient(135deg, rgba(16,185,129,0.3), rgba(52,211,153,0.15))'
    },
    sse: {
      icon: Radio,
      label: 'SSE',
      gradient: 'linear-gradient(135deg, rgba(245,158,11,0.3), rgba(251,191,36,0.15))'
    },
    stdio: {
      icon: Terminal,
      label: 'STDIO',
      gradient: 'linear-gradient(135deg, rgba(139,92,246,0.3), rgba(99,102,241,0.2))'
    }
  }
  return map[type] || { icon: Plug, label: type, gradient: 'linear-gradient(135deg, rgba(139,92,246,0.3), rgba(99,102,241,0.2))' }
}

function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    enabled: '#10B981',
    connected: '#06B6D4',
    error: '#EF4444',
    disabled: '#6B7280'
  }
  return colors[status] || '#6B7280'
}

function getStatusText(status: string): string {
  const texts: Record<string, string> = {
    enabled: '已启用',
    connected: '已连接',
    error: '连接错误',
    disabled: '已禁用'
  }
  return texts[status] || status
}

function handleClose() {
  emit('close')
}

function handleBackdropClick(e: MouseEvent) {
  if (e.target === e.currentTarget) {
    handleClose()
  }
}
</script>

<template>
  <div class="modal-backdrop" @click="handleBackdropClick">
    <div class="modal-content modal-lg">
      <!-- Header -->
      <header class="modal-header">
        <h2 class="modal-title">
          <div class="title-icon" style="background: linear-gradient(135deg, #8B5CF6, #6366F1);">
            <Plug class="w-4 h-4" />
          </div>
          MCP 服务管理
        </h2>
        <button class="btn-icon" aria-label="关闭" @click="handleClose">
          <X class="w-5 h-5" />
        </button>
      </header>

      <!-- 内容 -->
      <div class="modal-body">
        <!-- 操作按钮 -->
        <div class="action-bar">
          <button class="btn-primary">
            <Plus class="w-4 h-4" />
            添加服务
          </button>
          <button class="btn-secondary" @click="handleRefreshAll">
            <RefreshCw class="w-4 h-4" />
            刷新全部
          </button>
          <button class="btn-secondary" @click="handleImport">
            <Upload class="w-4 h-4" />
            导入配置
          </button>
          <button class="btn-secondary" @click="handleExport">
            <Download class="w-4 h-4" />
            导出配置
          </button>
        </div>

        <!-- 统计 -->
        <div v-if="stats" class="stats-bar">
          <span>总服务: <strong>{{ stats.total_services }}</strong></span>
          <span class="stat-success">已启用: {{ stats.enabled_services }}</span>
          <span class="stat-info">已连接: {{ stats.connected_services }}</span>
          <span class="stat-danger">错误: {{ stats.error_services }}</span>
          <span>工具总数: <strong>{{ stats.total_tools }}</strong></span>
        </div>

        <!-- 空状态 -->
        <div v-if="servers.length === 0" class="empty-state">
          <Plug class="w-12 h-12 mb-3 opacity-50" />
          <span>暂无 MCP 服务</span>
          <span class="text-xs mt-1 block opacity-70">点击"添加服务"注册新的 MCP 服务</span>
        </div>

        <!-- 服务列表 -->
        <div v-else class="server-list">
          <div v-for="server in servers" :key="server.name" class="server-card">
            <div class="server-header" :class="{ 'server-disabled': !server.enabled }">
              <div class="server-main">
                <div class="server-icon" :style="{ background: getTypeInfo(server.transport_type).gradient }">
                  <component :is="getTypeInfo(server.transport_type).icon" class="w-5 h-5 text-white" />
                </div>
                <div class="server-info">
                  <div class="server-name">
                    {{ server.display_name || server.name }}
                    <span v-if="!server.enabled" class="disabled-badge">已禁用</span>
                  </div>
                  <div class="server-meta">
                    <span>{{ getTypeInfo(server.transport_type).label }}</span>
                    <span class="separator">|</span>
                    <span>{{ server.tools_count || 0 }} 个工具</span>
                    <span
                      class="status-badge"
                      :style="{
                        color: getStatusColor(server.status),
                        background: `${getStatusColor(server.status)}15`,
                        borderColor: `${getStatusColor(server.status)}30`
                      }"
                    >
                      {{ getStatusText(server.status) }}
                    </span>
                  </div>
                </div>
              </div>
              <div class="server-actions">
                <button class="btn-icon-sm" title="测试连接" @click="handleTest(server.name)">
                  <TestTube class="w-3.5 h-3.5" />
                </button>
                <button class="btn-icon-sm" title="刷新工具" @click="handleRefresh(server.name)">
                  <RefreshCw class="w-3.5 h-3.5" />
                </button>
                <button
                  :class="server.enabled ? 'btn-warning-sm' : 'btn-success-sm'"
                  @click="handleToggle(server.name, !server.enabled)"
                >
                  {{ server.enabled ? '禁用' : '启用' }}
                </button>
                <button class="btn-icon-sm" title="删除" @click="handleDelete(server.name)">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
            <div v-if="server.description" class="server-desc">
              {{ server.description }}
            </div>
            <div v-if="server.last_error" class="server-error">
              错误: {{ server.last_error }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-lg {
  width: 90%;
  max-width: 900px;
  max-height: 85vh;
}

.title-icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

/* 操作栏 */
.action-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

/* 统计栏 */
.stats-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  gap-y: 4px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border-radius: 14px;
  background: rgba(124, 58, 237, 0.06);
  border: 1px solid rgba(124, 58, 237, 0.1);
  font-size: 13px;
  color: var(--text-muted);
}

.stats-bar strong {
  color: var(--text-secondary);
}

.stat-success {
  color: var(--success-400);
}

.stat-info {
  color: var(--cyan-400);
}

.stat-danger {
  color: var(--danger-400);
}

/* 服务列表 */
.server-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.server-card {
  border-radius: 14px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  transition: all 200ms var(--ease-default);
}

.server-card:hover {
  border-color: rgba(255, 255, 255, 0.1);
}

.server-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.server-disabled {
  background: rgba(0, 0, 0, 0.15);
}

.server-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.server-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.server-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.disabled-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-faint);
}

.server-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-faint);
}

.separator {
  color: rgba(255, 255, 255, 0.15);
}

.status-badge {
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid;
}

.server-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.server-desc {
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text-muted);
  background: rgba(0, 0, 0, 0.15);
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.server-error {
  padding: 10px 16px;
  font-size: 12px;
  color: var(--danger-400);
  background: rgba(239, 68, 68, 0.06);
  border-top: 1px solid rgba(239, 68, 68, 0.1);
}

/* 按钮 */
.btn-icon-sm {
  padding: 6px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.07);
  color: var(--text-muted);
  transition: all 150ms var(--ease-default);
}

.btn-icon-sm:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

.btn-warning-sm {
  padding: 6px 14px;
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  color: var(--warning-400);
  font-size: 12px;
  font-weight: 500;
  transition: all 150ms var(--ease-default);
}

.btn-warning-sm:hover {
  background: rgba(245, 158, 11, 0.15);
}

.btn-success-sm {
  padding: 6px 14px;
  border-radius: 10px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: var(--success-400);
  font-size: 12px;
  font-weight: 500;
  transition: all 150ms var(--ease-default);
}

.btn-success-sm:hover {
  background: rgba(16, 185, 129, 0.15);
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px dashed rgba(255, 255, 255, 0.08);
  color: var(--text-faint);
  text-align: center;
}
</style>
