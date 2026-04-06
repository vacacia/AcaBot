<script setup lang="ts">
import { onMounted, ref, reactive } from "vue"

import { apiGet, apiPost, apiPut, apiDelete } from "../lib/api"

// ── 类型定义 ──

interface PluginPackageInfo {
  display_name: string
  version: string
  entrypoint: string
  default_config: Record<string, unknown>
  config_schema: Record<string, unknown> | null
}

interface PluginSpecInfo {
  enabled: boolean
  config: Record<string, unknown>
}

interface PluginStatusInfo {
  phase: "disabled" | "loaded" | "failed" | "uninstalled"
  load_error: string
  registered_tools: string[]
  registered_hooks: string[]
  updated_at: string
}

interface PluginView {
  plugin_id: string
  package: PluginPackageInfo | null
  spec: PluginSpecInfo | null
  status: PluginStatusInfo | null
  effective_config: Record<string, unknown>
}

interface SchemaProperty {
  type?: string
  description?: string
  default?: unknown
  items?: { type?: string }
}

// ── 状态 ──

const plugins = ref<PluginView[]>([])
const loading = ref(true)
const reconciling = ref(false)
const expandedId = ref<string | null>(null)
const editConfigs = reactive<Record<string, Record<string, unknown>>>({})
const togglingIds = ref<Set<string>>(new Set())
const savingIds = ref<Set<string>>(new Set())
const toast = ref<{ message: string; type: "ok" | "error" } | null>(null)
const errorModal = ref<{ pluginId: string; error: string } | null>(null)

// ── 方法 ──

async function fetchPlugins(): Promise<void> {
  loading.value = true
  try {
    const payload = await apiGet<{ plugins: PluginView[] }>("/api/system/plugins")
    plugins.value = payload.plugins ?? []
  } catch (error) {
    showToast(error instanceof Error ? error.message : "加载插件列表失败", "error")
  } finally {
    loading.value = false
  }
}

function toggleExpand(pluginId: string): void {
  if (expandedId.value === pluginId) {
    expandedId.value = null
    return
  }
  expandedId.value = pluginId
  const plugin = plugins.value.find((p) => p.plugin_id === pluginId)
  if (plugin) {
    editConfigs[pluginId] = { ...(plugin.spec?.config ?? {}) }
  }
}

async function toggleEnabled(plugin: PluginView): Promise<void> {
  const id = plugin.plugin_id
  togglingIds.value.add(id)
  const currentEnabled = plugin.spec?.enabled ?? false
  const newEnabled = !currentEnabled
  try {
    const result = await apiPut<PluginView>(`/api/system/plugins/${id}/spec`, {
      enabled: newEnabled,
      config: plugin.spec?.config ?? {},
    })
    updatePlugin(result)
    showToast(`${displayName(plugin)} 已${newEnabled ? "启用" : "禁用"}`, "ok")
  } catch (error) {
    showToast(error instanceof Error ? error.message : "切换失败", "error")
  } finally {
    togglingIds.value.delete(id)
  }
}

async function saveConfig(plugin: PluginView): Promise<void> {
  const id = plugin.plugin_id
  savingIds.value.add(id)
  try {
    const configToSave = prepareConfig(plugin)
    const result = await apiPut<PluginView>(`/api/system/plugins/${id}/spec`, {
      enabled: plugin.spec?.enabled ?? true,
      config: configToSave,
    })
    updatePlugin(result)
    editConfigs[id] = { ...(result.spec?.config ?? {}) }
    showToast(`${displayName(plugin)} 配置已保存`, "ok")
  } catch (error) {
    showToast(error instanceof Error ? error.message : "保存失败", "error")
  } finally {
    savingIds.value.delete(id)
  }
}

function prepareConfig(plugin: PluginView): Record<string, unknown> {
  const raw = editConfigs[plugin.plugin_id] ?? {}
  const schema = plugin.package?.config_schema as { properties?: Record<string, SchemaProperty> } | null
  if (!schema?.properties) return raw

  const result: Record<string, unknown> = { ...raw }
  for (const [key, prop] of Object.entries(schema.properties)) {
    if (prop.type === "array" && prop.items?.type === "string" && typeof result[key] === "string") {
      result[key] = (result[key] as string).split(",").map((s) => s.trim()).filter(Boolean)
    }
    if (prop.type === "number" && typeof result[key] === "string") {
      result[key] = Number(result[key])
    }
  }
  return result
}

async function resetConfig(plugin: PluginView): Promise<void> {
  const id = plugin.plugin_id
  savingIds.value.add(id)
  try {
    const result = await apiPut<PluginView>(`/api/system/plugins/${id}/spec`, {
      enabled: plugin.spec?.enabled ?? true,
      config: {},
    })
    updatePlugin(result)
    editConfigs[id] = { ...(result.spec?.config ?? {}) }
    showToast(`${displayName(plugin)} 已恢复默认配置`, "ok")
  } catch (error) {
    showToast(error instanceof Error ? error.message : "重置失败", "error")
  } finally {
    savingIds.value.delete(id)
  }
}

async function deleteSpec(plugin: PluginView): Promise<void> {
  const confirmed = window.confirm(`确定要移除并禁用 ${displayName(plugin)} 吗?`)
  if (!confirmed) return
  const id = plugin.plugin_id
  savingIds.value.add(id)
  try {
    const result = await apiDelete<PluginView>(`/api/system/plugins/${id}/spec`)
    updatePlugin(result)
    showToast(`${displayName(plugin)} 已移除`, "ok")
  } catch (error) {
    showToast(error instanceof Error ? error.message : "移除失败", "error")
  } finally {
    savingIds.value.delete(id)
  }
}

async function reconcile(): Promise<void> {
  reconciling.value = true
  try {
    const result = await apiPost<{ plugins: PluginView[] }>("/api/system/plugins/reconcile", {})
    plugins.value = result.plugins ?? []
    showToast("插件已重新扫描", "ok")
  } catch (error) {
    showToast(error instanceof Error ? error.message : "扫描失败", "error")
  } finally {
    reconciling.value = false
  }
}

function updatePlugin(updated: PluginView): void {
  const index = plugins.value.findIndex((p) => p.plugin_id === updated.plugin_id)
  if (index >= 0) {
    plugins.value[index] = updated
  } else {
    plugins.value.push(updated)
  }
}

let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(message: string, type: "ok" | "error"): void {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { message, type }
  toastTimer = setTimeout(() => {
    toast.value = null
  }, 3000)
}

function displayName(plugin: PluginView): string {
  return plugin.package?.display_name || plugin.plugin_id
}

function phaseBadgeClass(phase: string | undefined): string {
  switch (phase) {
    case "loaded": return "badge badge-loaded"
    case "disabled": return "badge badge-disabled"
    case "failed": return "badge badge-failed"
    case "uninstalled": return "badge badge-uninstalled"
    default: return "badge badge-disabled"
  }
}

function phaseLabel(phase: string | undefined): string {
  switch (phase) {
    case "loaded": return "已加载"
    case "disabled": return "已禁用"
    case "failed": return "失败"
    case "uninstalled": return "未安装"
    default: return "未知"
  }
}

function currentPhase(plugin: PluginView): string | undefined {
  return plugin.status?.phase
}

function getSchemaProperties(plugin: PluginView): [string, SchemaProperty][] {
  const schema = plugin.package?.config_schema as { properties?: Record<string, SchemaProperty> } | null
  if (!schema?.properties) return []
  return Object.entries(schema.properties)
}

function hasSchema(plugin: PluginView): boolean {
  return getSchemaProperties(plugin).length > 0
}

function getEditValue(pluginId: string, key: string): unknown {
  return editConfigs[pluginId]?.[key] ?? ""
}

function setEditValue(pluginId: string, key: string, value: unknown): void {
  if (!editConfigs[pluginId]) editConfigs[pluginId] = {}
  editConfigs[pluginId][key] = value
}

function placeholderFor(plugin: PluginView, key: string): string {
  const def = plugin.package?.default_config?.[key]
  if (def === undefined || def === null) return ""
  return String(def)
}

function effectiveConfigJson(plugin: PluginView): string {
  return JSON.stringify(plugin.effective_config, null, 2)
}

onMounted(() => {
  void fetchPlugins()
})
</script>

<template>
  <section class="ds-page">
    <!-- Hero -->
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Plugins</p>
        <h1>插件管理</h1>
      </div>
      <div class="ds-actions">
        <button
          class="ds-secondary-button"
          type="button"
          :disabled="reconciling"
          @click="void reconcile()"
        >
          <svg v-if="reconciling" class="pv-spin-icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
          </svg>
          {{ reconciling ? "扫描中..." : "重新扫描" }}
        </button>
      </div>
    </header>

    <!-- 加载状态 -->
    <p v-if="loading" class="ds-status">加载中...</p>
    <p v-if="!loading && plugins.length === 0" class="ds-empty">暂无插件。前往「插件市场」安装，或检查 runtime 是否已加载插件。</p>

    <!-- 插件列表 -->
    <section v-if="!loading && plugins.length > 0" class="ds-list" :class="{ reconciling: reconciling }">
      <div
        v-for="(plugin, idx) in plugins"
        :key="plugin.plugin_id"
        class="ds-list-item plugin-item"
        :style="{ '--i': idx }"
      >
        <!-- 头部行 -->
        <div class="plugin-header" @click="toggleExpand(plugin.plugin_id)" :aria-expanded="expandedId === plugin.plugin_id">
          <div class="plugin-header-left">
            <strong class="plugin-name">{{ displayName(plugin) }}</strong>
            <span :class="phaseBadgeClass(currentPhase(plugin))">
              {{ phaseLabel(currentPhase(plugin)) }}
            </span>
          </div>
          <div class="plugin-header-right" @click.stop>
            <svg
              class="expand-chevron"
              :class="{ 'is-open': expandedId === plugin.plugin_id }"
              width="16" height="16" viewBox="0 0 16 16" fill="none"
            >
              <path d="M4 6L8 10L12 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <label
              class="toggle"
              :class="{ 'is-loading': togglingIds.has(plugin.plugin_id) }"
            >
              <input
                type="checkbox"
                :checked="plugin.spec?.enabled ?? false"
                :disabled="togglingIds.has(plugin.plugin_id)"
                @change="void toggleEnabled(plugin)"
              />
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <!-- 展开面板 -->
        <Transition name="expand">
        <div v-if="expandedId === plugin.plugin_id" class="expand-panel">
          <!-- 基础信息 -->
          <div class="info-section">
            <div class="info-row">
              <span class="info-label">Plugin ID</span>
              <span class="ds-mono ds-kicker">{{ plugin.plugin_id }}</span>
            </div>
            <div v-if="plugin.package?.version" class="info-row">
              <span class="info-label">版本</span>
              <span class="ds-kicker">{{ plugin.package.version }}</span>
            </div>
            <div v-if="plugin.package?.entrypoint" class="info-row">
              <span class="info-label">入口</span>
              <span class="ds-mono ds-kicker">{{ plugin.package.entrypoint }}</span>
            </div>
          </div>

          <!-- 状态信息 -->
          <div v-if="plugin.status" class="status-section">
            <div v-if="plugin.status.registered_tools.length > 0" class="status-row">
              <span class="info-label">注册工具</span>
              <div class="ds-chip-row">
                <span v-for="tool in plugin.status.registered_tools" :key="tool" class="ds-chip">{{ tool }}</span>
              </div>
            </div>
            <div v-if="plugin.status.registered_hooks.length > 0" class="status-row">
              <span class="info-label">注册钩子</span>
              <div class="ds-chip-row">
                <span v-for="hook in plugin.status.registered_hooks" :key="hook" class="ds-chip">{{ hook }}</span>
              </div>
            </div>
            <div v-if="currentPhase(plugin) === 'failed'" class="status-row">
              <button class="ds-ghost-button error-button" type="button" @click="errorModal = { pluginId: plugin.plugin_id, error: plugin.status.load_error }">
                查看错误
              </button>
            </div>
          </div>

          <!-- 配置区域 -->
          <div class="config-section">
            <h3 class="config-title">配置</h3>
            <div v-if="hasSchema(plugin)" class="config-form">
              <div
                v-for="[key, prop] in getSchemaProperties(plugin)"
                :key="key"
                class="ds-field"
              >
                <label class="ds-field-label">
                  {{ key }}
                  <span v-if="prop.description" class="field-desc">{{ prop.description }}</span>
                </label>

                <!-- boolean -->
                <label v-if="prop.type === 'boolean'" class="toggle config-toggle">
                  <input
                    type="checkbox"
                    :checked="!!getEditValue(plugin.plugin_id, key)"
                    @change="setEditValue(plugin.plugin_id, key, ($event.target as HTMLInputElement).checked)"
                  />
                  <span class="slider"></span>
                </label>

                <!-- number -->
                <input
                  v-else-if="prop.type === 'number'"
                  type="number"
                  class="ds-input"
                  :value="getEditValue(plugin.plugin_id, key)"
                  :placeholder="placeholderFor(plugin, key)"
                  @input="setEditValue(plugin.plugin_id, key, ($event.target as HTMLInputElement).value)"
                />

                <!-- array of strings -->
                <input
                  v-else-if="prop.type === 'array' && prop.items?.type === 'string'"
                  type="text"
                  class="ds-input"
                  :value="Array.isArray(getEditValue(plugin.plugin_id, key)) ? (getEditValue(plugin.plugin_id, key) as string[]).join(', ') : getEditValue(plugin.plugin_id, key)"
                  :placeholder="placeholderFor(plugin, key) + ' (逗号分隔)'"
                  @input="setEditValue(plugin.plugin_id, key, ($event.target as HTMLInputElement).value)"
                />

                <!-- string (default) -->
                <input
                  v-else-if="prop.type === 'string' || !prop.type"
                  type="text"
                  class="ds-input"
                  :value="getEditValue(plugin.plugin_id, key)"
                  :placeholder="placeholderFor(plugin, key)"
                  @input="setEditValue(plugin.plugin_id, key, ($event.target as HTMLInputElement).value)"
                />
              </div>
            </div>

            <!-- 无 schema 时展示有效配置 JSON -->
            <div v-else class="config-json">
              <pre class="ds-mono config-pre">{{ effectiveConfigJson(plugin) }}</pre>
            </div>
          </div>

          <!-- 操作按钮 -->
          <div class="ds-actions panel-actions">
            <button
              class="ds-primary-button"
              type="button"
              :disabled="savingIds.has(plugin.plugin_id) || !hasSchema(plugin)"
              @click="void saveConfig(plugin)"
            >
              {{ savingIds.has(plugin.plugin_id) ? "保存中..." : "保存配置" }}
            </button>
            <button
              class="ds-secondary-button"
              type="button"
              :disabled="savingIds.has(plugin.plugin_id)"
              @click="void resetConfig(plugin)"
            >
              恢复默认
            </button>
            <button
              class="ds-danger-button"
              type="button"
              :disabled="savingIds.has(plugin.plugin_id)"
              @click="void deleteSpec(plugin)"
            >
              移除并禁用
            </button>
          </div>
        </div>
        </Transition>
      </div>
    </section>

    <!-- Toast -->
    <div v-if="toast" class="toast-container">
      <div class="toast" :class="toast.type === 'ok' ? 'ds-status is-ok' : 'ds-status is-error'">
        {{ toast.message }}
      </div>
    </div>

    <!-- 错误详情 Modal -->
    <Transition name="modal">
    <div v-if="errorModal" class="modal-overlay" @click.self="errorModal = null" role="dialog" aria-modal="true">
      <div class="modal-panel">
        <div class="modal-header">
          <h3>{{ errorModal.pluginId }} 加载错误</h3>
          <button class="ds-ghost-button" type="button" @click="errorModal = null">关闭</button>
        </div>
        <pre class="ds-mono error-pre">{{ errorModal.error }}</pre>
      </div>
    </div>
    </Transition>
  </section>
</template>

<style scoped>
/* ── 插件列表行 ── */
.plugin-item {
  opacity: 0;
  transform: translateY(10px);
  animation: plugin-item-in 300ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
  animation-delay: calc(var(--i, 0) * 50ms);
}

@keyframes plugin-item-in {
  to { opacity: 1; transform: translateY(0); }
}

.plugin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  padding: 14px 16px;
  transition: background 120ms ease;
}

.plugin-header:hover {
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}

.plugin-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.plugin-name {
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.plugin-header-right {
  flex-shrink: 0;
}

/* ── Phase 徽章 ── */
.badge {
  display: inline-flex;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
}

.badge-loaded {
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
}

.badge-disabled {
  background: color-mix(in srgb, var(--muted) 15%, transparent);
  color: var(--muted);
}

.badge-failed {
  background: color-mix(in srgb, var(--danger) 15%, transparent);
  color: var(--danger);
}

.badge-uninstalled {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
}

/* ── Toggle 开关 ── */
.toggle {
  position: relative;
  display: inline-flex;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle .slider {
  position: absolute;
  inset: 0;
  background: var(--line);
  border-radius: 22px;
  cursor: pointer;
  transition: background 200ms;
}

.toggle .slider::before {
  content: "";
  position: absolute;
  width: 16px;
  height: 16px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: transform 200ms;
}

.toggle input:checked + .slider {
  background: var(--accent);
}

.toggle input:checked + .slider::before {
  transform: translateX(18px);
}

.toggle.is-loading .slider {
  opacity: 0.5;
}

.config-toggle {
  width: 40px;
}

/* ── 展开面板 ── */
.expand-panel {
  padding: 0 16px 16px;
  display: grid;
  gap: 16px;
  border-top: 1px solid var(--line);
}

/* ── 信息行 ── */
.info-section,
.status-section {
  display: grid;
  gap: 8px;
  padding-top: 12px;
}

.info-row,
.status-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.info-label {
  color: var(--heading-soft);
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.error-button {
  color: var(--danger);
  font-size: 13px;
  padding: 6px 12px;
}

/* ── 配置区域 ── */
.config-section {
  display: grid;
  gap: 12px;
}

.config-title {
  margin: 0;
  font-size: 14px;
  color: var(--heading-soft);
  letter-spacing: -0.01em;
}

.config-form {
  display: grid;
  gap: 12px;
}

.field-desc {
  font-weight: 400;
  color: var(--muted);
  margin-left: 6px;
  font-size: 12px;
}

.config-json {
  border-radius: 14px;
  background: var(--panel-strong);
  padding: 14px;
  overflow-x: auto;
}

.config-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── 操作按钮区 ── */
.panel-actions {
  padding-top: 4px;
}

.ds-danger-button {
  border-radius: 16px;
  padding: 10px 14px;
  cursor: pointer;
  border: 1px solid color-mix(in srgb, var(--danger) 40%, var(--line));
  background: color-mix(in srgb, var(--danger) 8%, var(--panel-strong));
  color: var(--danger);
  font-weight: 600;
  transition:
    transform 180ms cubic-bezier(0.25, 1, 0.5, 1),
    background-color 180ms ease,
    box-shadow 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.ds-danger-button:hover {
  transform: translateY(-2px) scale(1.02);
  background: color-mix(in srgb, var(--danger) 15%, var(--panel-strong));
  box-shadow: 0 8px 20px color-mix(in srgb, var(--danger) 25%, transparent);
}

.ds-danger-button:active:not(:disabled) {
  transform: translateY(1px) scale(0.98);
  box-shadow: 0 2px 8px color-mix(in srgb, var(--danger) 20%, transparent);
  transition-duration: 80ms;
}

.ds-danger-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

/* ── Reconciling 动画 ── */
.reconciling .badge {
  animation: pulse-badge 1.2s ease-in-out infinite;
}

@keyframes pulse-badge {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── Toast ── */
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
}

.toast {
  animation: toast-in 200ms ease, toast-out 200ms ease 2.8s forwards;
  min-width: 200px;
  max-width: 400px;
}

@keyframes toast-in {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes toast-out {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-10px); }
}

/* ── 错误 Modal ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-panel {
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  padding: 24px;
  max-width: 640px;
  width: 90%;
  max-height: 80vh;
  overflow: auto;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.modal-header h3 {
  margin: 0;
  font-size: 16px;
}

.error-pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 6%, var(--panel-strong));
  border-radius: 14px;
  padding: 14px;
}

/* ── Expand chevron ── */
.expand-chevron {
  flex-shrink: 0;
  color: var(--muted);
  transition: transform 220ms cubic-bezier(0.25, 1, 0.5, 1);
}

.expand-chevron.is-open {
  transform: rotate(180deg);
}

/* ── Expand panel transition ── */
.expand-enter-active {
  animation: expand-in 260ms cubic-bezier(0.25, 1, 0.5, 1);
}

.expand-leave-active {
  animation: expand-out 180ms cubic-bezier(0.4, 0, 1, 1);
}

@keyframes expand-in {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes expand-out {
  from { opacity: 1; transform: translateY(0); }
  to   { opacity: 0; transform: translateY(-4px); }
}

/* ── Modal transition ── */
.modal-enter-active {
  animation: modal-in 220ms cubic-bezier(0.25, 1, 0.5, 1);
}

.modal-leave-active {
  animation: modal-out 160ms cubic-bezier(0.4, 0, 1, 1);
}

.modal-enter-active .modal-panel {
  animation: modal-panel-in 280ms cubic-bezier(0.25, 1, 0.5, 1);
}

.modal-leave-active .modal-panel {
  animation: modal-panel-out 200ms cubic-bezier(0.4, 0, 1, 1);
}

@keyframes modal-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes modal-out {
  from { opacity: 1; }
  to   { opacity: 0; }
}

@keyframes modal-panel-in {
  from { opacity: 0; transform: scale(0.94) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes modal-panel-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(0.96) translateY(4px); }
}

/* ── Toggle focus ring ── */
.toggle input:focus-visible + .slider {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .expand-enter-active,
  .expand-leave-active,
  .modal-enter-active,
  .modal-leave-active,
  .modal-enter-active .modal-panel,
  .modal-leave-active .modal-panel {
    animation: none;
  }
  .expand-chevron {
    transition: none;
  }
}

/* ── Loading spinner ── */
.pv-spin-icon,
.spin-icon {
  flex-shrink: 0;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .pv-spin-icon,
  .spin-icon {
    animation: none;
  }
}
</style>
