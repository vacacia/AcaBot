<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import EditableListField from "../components/EditableListField.vue"
import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

const SYSTEM_CONFIGURATION_PATH = "/api/system/configuration"

type ApplyStatus = "applied" | "restart_required" | "apply_failed"
type FeedbackTone = "is-ok" | "is-warning" | "is-error"

type ApplyResult = {
  apply_status?: ApplyStatus | string
  restart_required?: boolean
  message?: string
  technical_detail?: string
}

type GatewayConfig = {
  host: string
  port: number
  timeout: number
  token: string
}

type RenderConfig = {
  width: number
  device_scale_factor: number
}

type ResolvedCatalogDir = {
  host_root_path: string
  scope: string
}

type FilesystemConfig = {
  enabled: boolean
  base_dir: string
  skill_catalog_dirs: string[]
  subagent_catalog_dirs: string[]
  configured_skill_catalog_dirs: string[] | null
  configured_subagent_catalog_dirs: string[] | null
  default_skill_catalog_dirs: string[]
  default_subagent_catalog_dirs: string[]
  resolved_skill_catalog_dirs: ResolvedCatalogDir[]
  resolved_subagent_catalog_dirs: ResolvedCatalogDir[]
}

type AdminsConfig = {
  admin_actor_ids: string[]
}

type PathOverview = {
  config_path: string
  filesystem_base_dir: string
  prompts_dir: string
  sessions_dir: string
  computer_root_dir: string
  sticky_notes_dir: string
  long_term_memory_storage_dir: string
  resolved_skill_catalog_dirs: string[]
  resolved_subagent_catalog_dirs: string[]
  backend_session_path: string
}

type SystemConfigurationSnapshot = {
  meta: {
    config_path: string
  }
  gateway: GatewayConfig
  render: RenderConfig
  filesystem: FilesystemConfig
  admins: AdminsConfig
  paths: PathOverview
}

type SystemDraft = {
  gateway: GatewayConfig
  render: RenderConfig
  filesystem: FilesystemConfig
  admins: AdminsConfig
}

type FeedbackState = {
  tone: FeedbackTone
  message: string
  detail: string
}

type ReloadResult = {
  session_count: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function isString(value: unknown): value is string {
  return typeof value === "string"
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean"
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function isNullableStringArray(value: unknown): value is string[] | null {
  return value === null || isStringArray(value)
}

function isResolvedCatalogDir(value: unknown): value is ResolvedCatalogDir {
  if (!isRecord(value)) {
    return false
  }
  return isString(value.host_root_path) && isString(value.scope)
}

function isResolvedCatalogDirArray(value: unknown): value is ResolvedCatalogDir[] {
  return Array.isArray(value) && value.every((item) => isResolvedCatalogDir(item))
}

function isGatewayConfig(value: unknown): value is GatewayConfig {
  if (!isRecord(value)) {
    return false
  }
  return (
    isString(value.host)
    && Number.isFinite(value.port)
    && Number.isFinite(value.timeout)
    && isString(value.token)
  )
}

function isRenderConfig(value: unknown): value is RenderConfig {
  if (!isRecord(value)) {
    return false
  }
  return Number.isFinite(value.width) && Number.isFinite(value.device_scale_factor)
}

function isFilesystemConfig(value: unknown): value is FilesystemConfig {
  if (!isRecord(value)) {
    return false
  }
  return (
    (value.enabled === undefined || isBoolean(value.enabled))
    && (value.base_dir === undefined || isString(value.base_dir))
    && isStringArray(value.skill_catalog_dirs)
    && isStringArray(value.subagent_catalog_dirs)
    && isNullableStringArray(value.configured_skill_catalog_dirs)
    && isNullableStringArray(value.configured_subagent_catalog_dirs)
    && isStringArray(value.default_skill_catalog_dirs)
    && isStringArray(value.default_subagent_catalog_dirs)
    && isResolvedCatalogDirArray(value.resolved_skill_catalog_dirs)
    && isResolvedCatalogDirArray(value.resolved_subagent_catalog_dirs)
  )
}

function isAdminsConfig(value: unknown): value is AdminsConfig {
  if (!isRecord(value)) {
    return false
  }
  return isStringArray(value.admin_actor_ids)
}

function isPathOverview(value: unknown): value is PathOverview {
  if (!isRecord(value)) {
    return false
  }
  return (
    isString(value.config_path)
    && isString(value.filesystem_base_dir)
    && isString(value.prompts_dir)
    && isString(value.sessions_dir)
    && isString(value.computer_root_dir)
    && isString(value.sticky_notes_dir)
    && isString(value.long_term_memory_storage_dir)
    && isStringArray(value.resolved_skill_catalog_dirs)
    && isStringArray(value.resolved_subagent_catalog_dirs)
    && isString(value.backend_session_path)
  )
}

function canBootstrapSystemConfigurationSnapshot(value: unknown): value is SystemConfigurationSnapshot {
  if (!isRecord(value) || !isRecord(value.meta)) {
    return false
  }
  return (
    isString(value.meta.config_path)
    && isGatewayConfig(value.gateway)
    && isRenderConfig(value.render)
    && isFilesystemConfig(value.filesystem)
    && isAdminsConfig(value.admins)
    && isPathOverview(value.paths)
  )
}

const cachedSnapshot = peekCachedGet<SystemConfigurationSnapshot>(
  SYSTEM_CONFIGURATION_PATH,
  canBootstrapSystemConfigurationSnapshot,
)
const draft = ref<SystemDraft | null>(cachedSnapshot ? cloneSnapshot(cachedSnapshot) : null)
const pathOverview = ref<PathOverview | null>(cachedSnapshot?.paths ?? null)
const feedback = ref<FeedbackState | null>(null)
const loading = ref(!cachedSnapshot)
const refreshing = ref(false)
const activeAction = ref("")
const advancedOpen = ref(false)
const pathsOpen = ref(false)

const skillCatalogDirs = computed<string[]>({
  get() {
    return draft.value?.filesystem.skill_catalog_dirs ?? []
  },
  set(value) {
    updateDraft((current) => ({
      ...current,
      filesystem: {
        ...current.filesystem,
        skill_catalog_dirs: [...value],
      },
    }))
  },
})

const subagentCatalogDirs = computed<string[]>({
  get() {
    return draft.value?.filesystem.subagent_catalog_dirs ?? []
  },
  set(value) {
    updateDraft((current) => ({
      ...current,
      filesystem: {
        ...current.filesystem,
        subagent_catalog_dirs: [...value],
      },
    }))
  },
})

const adminActorIds = computed<string[]>({
  get() {
    return draft.value?.admins.admin_actor_ids ?? []
  },
  set(value) {
    updateDraft((current) => ({
      ...current,
      admins: {
        admin_actor_ids: [...value],
      },
    }))
  },
})

function cloneSnapshot(snapshot: SystemConfigurationSnapshot): SystemDraft {
  return {
    gateway: {
      ...snapshot.gateway,
    },
    render: {
      ...snapshot.render,
    },
    filesystem: {
      ...snapshot.filesystem,
      skill_catalog_dirs: [...snapshot.filesystem.skill_catalog_dirs],
      subagent_catalog_dirs: [...snapshot.filesystem.subagent_catalog_dirs],
      configured_skill_catalog_dirs: [...(snapshot.filesystem.configured_skill_catalog_dirs ?? [])],
      configured_subagent_catalog_dirs: [...(snapshot.filesystem.configured_subagent_catalog_dirs ?? [])],
      default_skill_catalog_dirs: [...snapshot.filesystem.default_skill_catalog_dirs],
      default_subagent_catalog_dirs: [...snapshot.filesystem.default_subagent_catalog_dirs],
      resolved_skill_catalog_dirs: snapshot.filesystem.resolved_skill_catalog_dirs.map((item) => ({ ...item })),
      resolved_subagent_catalog_dirs: snapshot.filesystem.resolved_subagent_catalog_dirs.map((item) => ({ ...item })),
    },
    admins: {
      admin_actor_ids: [...snapshot.admins.admin_actor_ids],
    },
  }
}

function applySnapshot(snapshot: SystemConfigurationSnapshot): void {
  draft.value = cloneSnapshot(snapshot)
  pathOverview.value = {
    ...snapshot.paths,
    resolved_skill_catalog_dirs: [...snapshot.paths.resolved_skill_catalog_dirs],
    resolved_subagent_catalog_dirs: [...snapshot.paths.resolved_subagent_catalog_dirs],
  }
}

function updateDraft(updater: (current: SystemDraft) => SystemDraft): void {
  if (!draft.value) {
    return
  }
  draft.value = updater(draft.value)
}

function normalizeErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return "请求失败，请稍后再试。"
}

function setFeedback(tone: FeedbackTone, message: string, detail = ""): void {
  feedback.value = {
    tone,
    message,
    detail,
  }
}

function setApplyFeedback(scopeLabel: string, payload: ApplyResult): void {
  const applyStatus = String(payload.apply_status || "")
  const detail = String(payload.technical_detail || "")
  if (applyStatus === "restart_required" || payload.restart_required) {
    setFeedback("is-warning", `${scopeLabel}：${payload.message || "已保存，但需重启"}`, detail)
    return
  }
  if (applyStatus === "apply_failed") {
    setFeedback("is-warning", `${scopeLabel}：${payload.message || "已写入，但应用失败"}`, detail)
    return
  }
  setFeedback("is-ok", `${scopeLabel}：${payload.message || "已保存并已生效"}`, detail)
}

async function refreshSnapshot(): Promise<void> {
  const snapshot = await apiGet<SystemConfigurationSnapshot>(
    SYSTEM_CONFIGURATION_PATH,
    canBootstrapSystemConfigurationSnapshot,
  )
  applySnapshot(snapshot)
}

async function loadPage(): Promise<void> {
  if (draft.value) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  try {
    await refreshSnapshot()
  } catch (error) {
    setFeedback(
      "is-error",
      "系统页加载失败。请检查 runtime 是否正常启动。",
      normalizeErrorMessage(error),
    )
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function refreshAfterMutation(): Promise<void> {
  try {
    await refreshSnapshot()
  } catch (error) {
    const detail = normalizeErrorMessage(error)
    if (!feedback.value) {
      setFeedback("is-warning", "保存已完成，重新同步页面状态失败。", detail)
      return
    }
    feedback.value = {
      ...feedback.value,
      detail: feedback.value.detail ? `${feedback.value.detail}\n${detail}` : detail,
    }
  }
}

async function saveGateway(): Promise<void> {
  if (!draft.value) {
    return
  }
  activeAction.value = "gateway"
  feedback.value = null
  try {
    const saved = await apiPut<GatewayConfig & ApplyResult>("/api/gateway/config", {
      host: draft.value.gateway.host,
      port: draft.value.gateway.port,
      timeout: draft.value.gateway.timeout,
      token: draft.value.gateway.token,
    })
    setApplyFeedback("共享网关设置", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback(
      "is-error",
      "共享网关设置保存失败。",
      normalizeErrorMessage(error),
    )
  } finally {
    activeAction.value = ""
  }
}

async function saveRender(): Promise<void> {
  if (!draft.value) {
    return
  }
  activeAction.value = "render"
  feedback.value = null
  try {
    const saved = await apiPut<RenderConfig & ApplyResult>("/api/render/config", {
      width: draft.value.render.width,
      device_scale_factor: draft.value.render.device_scale_factor,
    })
    setApplyFeedback("渲染配置", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback("is-error", "渲染配置保存失败。", normalizeErrorMessage(error))
  } finally {
    activeAction.value = ""
  }
}

async function saveFilesystemConfig(): Promise<void> {
  if (!draft.value) {
    return
  }
  activeAction.value = "filesystem"
  feedback.value = null
  try {
    const saved = await apiPut<FilesystemConfig & ApplyResult>("/api/filesystem/config", {
      skill_catalog_dirs: draft.value.filesystem.skill_catalog_dirs,
      subagent_catalog_dirs: draft.value.filesystem.subagent_catalog_dirs,
    })
    setApplyFeedback("扫描目录设置", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback(
      "is-error",
      "扫描目录设置保存失败。",
      normalizeErrorMessage(error),
    )
  } finally {
    activeAction.value = ""
  }
}

async function saveAdmins(): Promise<void> {
  if (!draft.value) {
    return
  }
  activeAction.value = "admins"
  feedback.value = null
  try {
    const saved = await apiPut<AdminsConfig & ApplyResult>("/api/admins", {
      admin_actor_ids: draft.value.admins.admin_actor_ids,
    })
    setApplyFeedback("管理员", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback(
      "is-error",
      "管理员保存失败。",
      normalizeErrorMessage(error),
    )
  } finally {
    activeAction.value = ""
  }
}

async function reloadConfiguration(): Promise<void> {
  activeAction.value = "reload"
  feedback.value = null
  try {
    const result = await apiPost<ReloadResult>("/api/runtime/reload-config", {})
    setFeedback(
      "is-ok",
      `配置已重新读取，当前 ${result.session_count} 个 session。`,
    )
    await refreshAfterMutation()
  } catch (error) {
    setFeedback(
      "is-error",
      "重新读取配置失败。",
      normalizeErrorMessage(error),
    )
  } finally {
    activeAction.value = ""
  }
}

function scopeLabel(scope: string): string {
  return scope === "project" ? "项目级" : "用户级"
}

function syncAdvancedOpen(event: Event): void {
  const target = event.target
  if (target instanceof HTMLDetailsElement) {
    advancedOpen.value = target.open
  }
}

function syncPathsOpen(event: Event): void {
  const target = event.target
  if (target instanceof HTMLDetailsElement) {
    pathsOpen.value = target.open
  }
}

onMounted(() => {
  void loadPage()
})
</script>

<template>
  <section class="sys-page">
    <!-- Page Header -->
    <header class="sys-header">
      <div class="sys-header-text">
        <p class="sys-eyebrow">System</p>
        <h1 class="sys-title">系统设置</h1>
      </div>
      <div class="sys-header-meta">
        <span v-if="refreshing" class="sys-badge">正在同步</span>
        <span v-if="pathOverview" class="sys-badge sys-badge--mono">{{ pathOverview.config_path }}</span>
      </div>
    </header>

    <!-- Feedback -->
    <div v-if="feedback" class="sys-feedback">
      <p class="sys-status" :class="feedback.tone">{{ feedback.message }}</p>
      <details v-if="feedback.detail" class="sys-feedback-detail">
        <summary>技术详情</summary>
        <pre class="sys-mono">{{ feedback.detail }}</pre>
      </details>
    </div>

    <p v-if="loading" class="sys-empty">正在加载系统配置...</p>

    <template v-else-if="draft && pathOverview">
      <!-- Gateway Section -->
      <section class="sys-section">
        <div class="sys-section-label">
          <h2 class="sys-section-title">共享网关</h2>
          <p class="sys-section-desc">OneBot / 网关客户端连接配置。</p>
        </div>
        <div class="sys-fields">
          <div class="sys-field-row">
            <label class="sys-field">
              <span class="sys-field-label">监听地址</span>
              <input v-model="draft.gateway.host" class="sys-input sys-mono" type="text" placeholder="0.0.0.0" />
            </label>
            <label class="sys-field">
              <span class="sys-field-label">端口</span>
              <input v-model.number="draft.gateway.port" class="sys-input sys-mono" type="number" min="1" />
            </label>
            <label class="sys-field">
              <span class="sys-field-label">超时（秒）</span>
              <input v-model.number="draft.gateway.timeout" class="sys-input sys-mono" type="number" min="0" step="0.5" />
            </label>
          </div>
          <div class="sys-field-row">
            <label class="sys-field sys-field--wide">
              <span class="sys-field-label">访问 Token</span>
              <input v-model="draft.gateway.token" class="sys-input sys-mono" type="text" placeholder="留空表示不鉴权" />
            </label>
          </div>
        </div>
        <div class="sys-section-action">
          <button class="sys-btn-primary" type="button" :disabled="activeAction !== ''" @click="void saveGateway()">
            {{ activeAction === "gateway" ? "保存中..." : "保存" }}
          </button>
        </div>
      </section>

      <!-- Render Section -->
      <section class="sys-section">
        <div class="sys-section-label">
          <h2 class="sys-section-title">渲染配置</h2>
          <p class="sys-section-desc">Message 工具渲染网页时的 viewport 设置。</p>
        </div>
        <div class="sys-fields">
          <div class="sys-field-row">
            <label class="sys-field">
              <span class="sys-field-label">页面宽度</span>
              <input v-model.number="draft.render.width" class="sys-input sys-mono" type="number" min="320" />
            </label>
            <label class="sys-field">
              <span class="sys-field-label">缩放系数</span>
              <input v-model.number="draft.render.device_scale_factor" class="sys-input sys-mono" type="number" min="1" step="0.1" />
            </label>
          </div>
        </div>
        <div class="sys-section-action">
          <button class="sys-btn-primary" type="button" :disabled="activeAction !== ''" @click="void saveRender()">
            {{ activeAction === "render" ? "保存中..." : "保存" }}
          </button>
        </div>
      </section>

      <!-- Catalog Section -->
      <section class="sys-section">
        <div class="sys-section-label">
          <h2 class="sys-section-title">扩展扫描</h2>
          <p class="sys-section-desc">AcaBot 扫描技能和子代理的目录列表。</p>
        </div>

        <!-- Skills -->
        <div class="sys-catalog-block">
          <div class="sys-catalog-header">
            <h3 class="sys-catalog-title">技能目录</h3>
            <span class="sys-catalog-count">{{ draft.filesystem.skill_catalog_dirs.length }} 个路径</span>
          </div>
          <EditableListField
            v-model="skillCatalogDirs"
            placeholder="添加技能目录，按回车确认"
            empty-title="未配置"
            empty-description="添加目录后，AcaBot 会解析实际生效位置。"
            :disabled="activeAction !== ''"
          />
          <div v-if="draft.filesystem.resolved_skill_catalog_dirs.length" class="sys-resolved">
            <span class="sys-resolved-label">已生效</span>
            <ul class="sys-resolved-list">
              <li v-for="item in draft.filesystem.resolved_skill_catalog_dirs" :key="`${item.scope}:${item.host_root_path}`" class="sys-resolved-item">
                <span class="sys-chip">{{ scopeLabel(item.scope) }}</span>
                <code class="sys-mono sys-resolved-path">{{ item.host_root_path }}</code>
              </li>
            </ul>
          </div>
          <p v-else class="sys-hint">使用默认路径：{{ draft.filesystem.default_skill_catalog_dirs.join("、") || "./extensions/skills" }}</p>
        </div>

        <!-- Subagents -->
        <div class="sys-catalog-block">
          <div class="sys-catalog-header">
            <h3 class="sys-catalog-title">子代理目录</h3>
            <span class="sys-catalog-count">{{ draft.filesystem.subagent_catalog_dirs.length }} 个路径</span>
          </div>
          <EditableListField
            v-model="subagentCatalogDirs"
            placeholder="添加子代理目录，按回车确认"
            empty-title="未配置"
            empty-description="添加目录后，AcaBot 会解析实际生效位置。"
            :disabled="activeAction !== ''"
          />
          <div v-if="draft.filesystem.resolved_subagent_catalog_dirs.length" class="sys-resolved">
            <span class="sys-resolved-label">已生效</span>
            <ul class="sys-resolved-list">
              <li v-for="item in draft.filesystem.resolved_subagent_catalog_dirs" :key="`${item.scope}:${item.host_root_path}`" class="sys-resolved-item">
                <span class="sys-chip">{{ scopeLabel(item.scope) }}</span>
                <code class="sys-mono sys-resolved-path">{{ item.host_root_path }}</code>
              </li>
            </ul>
          </div>
          <p v-else class="sys-hint">使用默认路径：{{ draft.filesystem.default_subagent_catalog_dirs.join("、") || "./extensions/subagents" }}</p>
        </div>

        <div class="sys-section-action">
          <button class="sys-btn-primary" type="button" :disabled="activeAction !== ''" @click="void saveFilesystemConfig()">
            {{ activeAction === "filesystem" ? "保存中..." : "保存" }}
          </button>
        </div>
      </section>

      <!-- Admins Section -->
      <section class="sys-section">
        <div class="sys-section-label">
          <h2 class="sys-section-title">管理员</h2>
          <p class="sys-section-desc">拥有管理权限的账号 ID 列表。</p>
        </div>
        <div class="sys-fields">
          <div class="sys-field-row">
            <label class="sys-field sys-field--wide">
              <span class="sys-field-label">管理员 ID</span>
              <EditableListField
                v-model="adminActorIds"
                placeholder="添加管理员 ID"
                empty-title="未配置管理员"
                empty-description="添加后权限立即生效。"
                :disabled="activeAction !== ''"
              />
            </label>
          </div>
        </div>
        <div class="sys-section-action">
          <button class="sys-btn-primary" type="button" :disabled="activeAction !== ''" @click="void saveAdmins()">
            {{ activeAction === "admins" ? "保存中..." : "保存" }}
          </button>
        </div>
      </section>

      <!-- Maintenance Section -->
      <section class="sys-section sys-section--compact">
        <div class="sys-section-label">
          <h2 class="sys-section-title">维护</h2>
        </div>
        <div class="sys-maintenance">
          <div class="sys-maintenance-info">
            <p class="sys-maintenance-hint">直接改过配置文件或怀疑热更新未生效时，可从磁盘重读确认。注意：gateway 等需重启的设置，重读不能替代重启。</p>
          </div>
          <button class="sys-btn-secondary" type="button" :disabled="activeAction !== ''" @click="void reloadConfiguration()">
            {{ activeAction === "reload" ? "重读中..." : "从磁盘重读配置" }}
          </button>
        </div>
      </section>

      <!-- Paths Overview (Collapsible) -->
      <details class="sys-paths" :open="pathsOpen" @toggle="syncPathsOpen">
        <summary class="sys-paths-summary">
          <span class="sys-paths-title">路径总览</span>
          <span class="sys-paths-toggle">{{ pathsOpen ? "收起" : "展开" }}</span>
        </summary>

        <div class="sys-paths-content">
          <!-- Key Paths -->
          <div class="sys-paths-grid">
            <div class="sys-path-item">
              <span class="sys-path-label">配置文件</span>
              <code class="sys-mono sys-path-value">{{ pathOverview.config_path }}</code>
            </div>
            <div class="sys-path-item">
              <span class="sys-path-label">Backend 会话</span>
              <code class="sys-mono sys-path-value">{{ pathOverview.backend_session_path }}</code>
            </div>
            <div class="sys-path-item">
              <span class="sys-path-label">文件系统根目录</span>
              <code class="sys-mono sys-path-value">{{ pathOverview.filesystem_base_dir }}</code>
            </div>
          </div>

          <!-- Runtime Paths -->
          <div class="sys-path-group">
            <h3 class="sys-path-group-title">运行时数据落点</h3>
            <div class="sys-paths-grid sys-paths-grid--2">
              <div class="sys-path-item">
                <span class="sys-path-label">Prompts 目录</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.prompts_dir }}</code>
              </div>
              <div class="sys-path-item">
                <span class="sys-path-label">Sessions 目录</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.sessions_dir }}</code>
              </div>
              <div class="sys-path-item">
                <span class="sys-path-label">Sticky Notes</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.sticky_notes_dir }}</code>
              </div>
              <div class="sys-path-item">
                <span class="sys-path-label">LTM 存储</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.long_term_memory_storage_dir }}</code>
              </div>
              <div class="sys-path-item">
                <span class="sys-path-label">Computer 工作区</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.computer_root_dir }}</code>
              </div>
            </div>
          </div>

          <!-- Resolved Catalogs -->
          <div class="sys-path-group">
            <h3 class="sys-path-group-title">已解析的扩展目录</h3>
            <div class="sys-paths-grid sys-paths-grid--2">
              <div class="sys-path-item">
                <span class="sys-path-label">技能目录</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.resolved_skill_catalog_dirs.join("、") || "无" }}</code>
              </div>
              <div class="sys-path-item">
                <span class="sys-path-label">子代理目录</span>
                <code class="sys-mono sys-path-value">{{ pathOverview.resolved_subagent_catalog_dirs.join("、") || "无" }}</code>
              </div>
            </div>
          </div>
        </div>
      </details>
    </template>

    <p v-else class="sys-empty">系统配置加载失败。请检查 runtime 状态后重试。</p>
  </section>
</template>

<style scoped>
/* ─── Page Structure ─────────────────────────────── */
.sys-page {
  display: grid;
  gap: 0;
  padding: 32px 40px 64px;
  max-width: 960px;
}

/* ─── Header ─────────────────────────────────────── */
.sys-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 40px;
  padding-bottom: 28px;
  border-bottom: 1px solid var(--line);
}

.sys-eyebrow {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.sys-title {
  margin: 0;
  font-size: 28px;
  font-weight: 800;
  color: var(--heading-strong);
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.sys-header-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.sys-badge {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  background: var(--panel-strong);
  border: 1px solid var(--line);
}

.sys-badge--mono {
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ─── Feedback ────────────────────────────────────── */
.sys-feedback {
  display: grid;
  gap: 8px;
  margin-bottom: 28px;
}

.sys-status {
  margin: 0;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.sys-status.is-ok {
  background: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--success);
}

.sys-status.is-warning {
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  color: var(--warning);
}

.sys-status.is-error {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
}

.sys-feedback-detail {
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--panel-strong);
  border: 1px solid var(--line);
  font-size: 12px;
  cursor: pointer;
}

.sys-feedback-detail summary {
  font-weight: 700;
  color: var(--heading-soft);
}

.sys-mono {
  margin: 10px 0 0;
  font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
  font-size: 11px;
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-all;
}

/* ─── Section ─────────────────────────────────────── */
.sys-section {
  padding: 32px 0;
  border-bottom: 1px solid var(--line);
  display: grid;
  gap: 20px;
}

.sys-section:last-of-type {
  border-bottom: none;
}

.sys-section--compact {
  padding: 24px 0;
}

.sys-section-label {
  display: grid;
  gap: 4px;
}

.sys-section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: var(--heading-strong);
  letter-spacing: -0.02em;
}

.sys-section-desc {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.sys-section-action {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
}

/* ─── Fields ──────────────────────────────────────── */
.sys-fields {
  display: grid;
  gap: 20px;
}

.sys-field-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.sys-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-width: 160px;
}

.sys-field--wide {
  flex: 2;
}

.sys-field-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--heading-soft);
  letter-spacing: 0.02em;
}

.sys-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.sys-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.sys-input::placeholder {
  color: var(--muted);
  opacity: 0.6;
}

/* ─── Buttons ─────────────────────────────────────── */
.sys-btn-primary,
.sys-btn-secondary {
  border-radius: 10px;
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 120ms ease, box-shadow 120ms ease;
}

.sys-btn-primary:hover,
.sys-btn-secondary:hover {
  transform: translateY(-1px);
}

.sys-btn-primary:active,
.sys-btn-secondary:active {
  transform: translateY(0);
}

.sys-btn-primary {
  border: none;
  background: linear-gradient(135deg, var(--button-primary-start), var(--button-primary-end));
  color: #fff;
  box-shadow: 0 4px 14px var(--button-shadow-color);
}

.sys-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.sys-btn-secondary {
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--text);
}

.sys-btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

/* ─── Catalog Blocks ──────────────────────────────── */
.sys-catalog-block {
  display: grid;
  gap: 12px;
  padding: 20px;
  border-radius: 12px;
  background: var(--panel-strong);
  border: 1px solid var(--panel-line-soft);
}

.sys-catalog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.sys-catalog-title {
  margin: 0;
  font-size: 13px;
  font-weight: 800;
  color: var(--heading-strong);
}

.sys-catalog-count {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
}

.sys-resolved {
  display: grid;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--panel-line-soft);
}

.sys-resolved-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.sys-resolved-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}

.sys-resolved-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sys-chip {
  display: inline-flex;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-soft);
  flex-shrink: 0;
}

.sys-resolved-path {
  font-size: 12px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sys-hint {
  margin: 0;
  font-size: 11px;
  color: var(--muted);
  font-style: italic;
}

/* ─── Maintenance ─────────────────────────────────── */
.sys-maintenance {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.sys-maintenance-info {
  flex: 1;
}

.sys-maintenance-hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

/* ─── Paths ───────────────────────────────────────── */
.sys-paths {
  margin-top: 24px;
  border-radius: 12px;
  background: var(--panel-strong);
  border: 1px solid var(--panel-line-soft);
  overflow: hidden;
}

.sys-paths-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  cursor: pointer;
  font-weight: 700;
  color: var(--heading-soft);
  user-select: none;
  list-style: none;
}

.sys-paths-summary::-webkit-details-marker {
  display: none;
}

.sys-paths-title {
  font-size: 13px;
  font-weight: 800;
  color: var(--heading-strong);
}

.sys-paths-toggle {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
}

.sys-paths-content {
  padding: 0 20px 20px;
  display: grid;
  gap: 24px;
}

.sys-paths-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.sys-paths-grid--2 {
  grid-template-columns: repeat(2, 1fr);
}

.sys-path-item {
  display: grid;
  gap: 4px;
}

.sys-path-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.sys-path-value {
  font-size: 11px;
  color: var(--text);
  word-break: break-all;
  line-height: 1.4;
}

.sys-path-group {
  display: grid;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--panel-line-soft);
}

.sys-path-group-title {
  margin: 0;
  font-size: 12px;
  font-weight: 800;
  color: var(--heading-soft);
}

/* ─── Empty State ─────────────────────────────────── */
.sys-empty {
  margin: 0;
  padding: 24px;
  border-radius: 12px;
  border: 1px dashed var(--line);
  background: var(--panel-strong);
  color: var(--muted);
  font-size: 13px;
}

/* ─── Animations ──────────────────────────────────── */
.sys-page > * {
  opacity: 0;
  transform: translateY(6px);
  animation: sys-fade-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.sys-page > *:nth-child(1) { animation-delay: 40ms; }
.sys-page > *:nth-child(2) { animation-delay: 80ms; }
.sys-page > .sys-section:nth-of-type(1) { animation-delay: 120ms; }
.sys-page > .sys-section:nth-of-type(2) { animation-delay: 180ms; }
.sys-page > .sys-section:nth-of-type(3) { animation-delay: 240ms; }
.sys-page > .sys-section:nth-of-type(4) { animation-delay: 300ms; }
.sys-page > .sys-section:nth-of-type(5) { animation-delay: 360ms; }
.sys-page > .sys-paths { animation-delay: 420ms; }

@keyframes sys-fade-in {
  to { opacity: 1; transform: translateY(0); }
}

/* ─── Responsive ──────────────────────────────────── */
@media (max-width: 768px) {
  .sys-page {
    padding: 24px 20px 48px;
  }

  .sys-header {
    flex-direction: column;
    gap: 16px;
  }

  .sys-header-meta {
    align-items: flex-start;
  }

  .sys-field-row {
    flex-direction: column;
  }

  .sys-field {
    min-width: unset;
  }

  .sys-paths-grid {
    grid-template-columns: 1fr;
  }

  .sys-paths-grid--2 {
    grid-template-columns: 1fr;
  }

  .sys-maintenance {
    flex-direction: column;
    align-items: flex-start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sys-page > * {
    opacity: 1;
    transform: none;
    animation: none;
  }
}
</style>
