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

const summaryCards = computed(() => {
  if (!pathOverview.value) {
    return []
  }
  return [
    {
      title: "配置文件位置",
      value: pathOverview.value.config_path,
      helper: "系统页里的共享设置最终都会写回这一份配置文件。",
    },
    {
      title: "Backend 会话文件",
      value: pathOverview.value.backend_session_path,
      helper: "用于标记 backend 会话绑定和运行时状态落点。",
    },
  ]
})

const runtimePathRows = computed(() => {
  if (!pathOverview.value) {
    return []
  }
  return [
    {
      label: "文件系统根目录",
      helper: "相对路径会基于这里解析。",
      value: pathOverview.value.filesystem_base_dir,
    },
    {
      label: "Prompts 目录",
      helper: "文件系统 prompt 模式下实际读取的位置。",
      value: pathOverview.value.prompts_dir,
    },
    {
      label: "Sessions 目录",
      helper: "会话配置和运行时 session 数据会落在这里。",
      value: pathOverview.value.sessions_dir,
    },
    {
      label: "Sticky Notes 目录",
      helper: "短记忆的文件落点。",
      value: pathOverview.value.sticky_notes_dir,
    },
    {
      label: "LTM 存储目录",
      helper: "长期记忆向量/索引数据的主要落点。",
      value: pathOverview.value.long_term_memory_storage_dir,
    },
    {
      label: "Computer 工作区根目录",
      helper: "computer/workspace 相关能力会从这里派生工作目录。",
      value: pathOverview.value.computer_root_dir,
    },
  ]
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
      "系统页加载失败。请检查 runtime 是否正常启动，然后再试一次。",
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
      setFeedback("is-warning", "保存已经完成，但重新同步页面状态失败。", detail)
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
      "共享网关设置保存失败。请检查输入项，必要时展开技术详情查看具体原因。",
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
    setApplyFeedback("Render 默认配置", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback("is-error", "Render 默认配置保存失败。", normalizeErrorMessage(error))
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
      "扫描目录设置保存失败。请检查输入项，必要时展开技术详情查看具体原因。",
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
      "管理员保存失败。请检查输入项，必要时展开技术详情查看具体原因。",
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
      `系统配置已重新读取。当前 ${result.session_count} 个 session。`,
    )
    await refreshAfterMutation()
  } catch (error) {
    setFeedback(
      "is-error",
      "重新读取配置失败。请检查配置文件内容，必要时展开技术详情查看具体原因。",
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

onMounted(() => {
  void loadPage()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">System</p>
        <h1>系统设置</h1>
        <p class="ds-summary">保存后即时生效，需重启的项目会明确提示。</p>
      </div>
      <div class="ds-actions">
        <span v-if="refreshing" class="ds-chip">正在同步最新配置</span>
      </div>
    </header>

    <div v-if="feedback" class="feedback-stack">
      <p class="ds-status" :class="feedback.tone">{{ feedback.message }}</p>
      <details v-if="feedback.detail" class="feedback-detail">
        <summary>查看技术细节</summary>
        <pre class="ds-mono feedback-code">{{ feedback.detail }}</pre>
      </details>
    </div>

    <p v-if="loading" class="ds-empty">正在加载系统配置...</p>

    <template v-else-if="draft && pathOverview">
      <section class="ds-card-grid-3">
        <article v-for="card in summaryCards" :key="card.title" class="ds-surface ds-card-padding-sm summary-card">
          <p class="summary-label">{{ card.title }}</p>
          <code class="ds-mono summary-value">{{ card.value }}</code>
          <p class="ds-summary">{{ card.helper }}</p>
        </article>
      </section>

      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <div>
              <h2>共享网关设置</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-primary-button" type="button" :disabled="activeAction !== ''" @click="void saveGateway()">
              {{ activeAction === "gateway" ? "保存中..." : "保存并尝试生效" }}
            </button>
          </div>
        </div>

        <div class="ds-form-grid">
          <label class="ds-field">
            <span>监听地址</span>
            <p class="ds-helper">决定 gateway 对外监听在哪个地址。</p>
            <input v-model="draft.gateway.host" class="ds-input ds-mono" type="text" placeholder="例如 0.0.0.0" />
          </label>
          <label class="ds-field">
            <span>监听端口</span>
            <p class="ds-helper">OneBot 或网关客户端最终会连到这个端口。</p>
            <input v-model.number="draft.gateway.port" class="ds-input ds-mono" type="number" min="1" step="1" />
          </label>
          <label class="ds-field">
            <span>超时时间（秒）</span>
            <p class="ds-helper">连接和请求超时的基础阈值。</p>
            <input v-model.number="draft.gateway.timeout" class="ds-input ds-mono" type="number" min="0" step="0.5" />
          </label>
          <label class="ds-field">
            <span>访问 Token</span>
            <p class="ds-helper">如果你的 gateway 需要鉴权，就在这里维护共享 token。</p>
            <input v-model="draft.gateway.token" class="ds-input ds-mono" type="text" placeholder="留空表示不配置 token" />
          </label>
        </div>
      </article>

      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <div>
              <h2>Render 默认配置</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-primary-button" type="button" :disabled="activeAction !== ''" @click="void saveRender()">
              {{ activeAction === "render" ? "保存中..." : "保存并尝试生效" }}
            </button>
          </div>
        </div>

        <div class="ds-form-grid">
          <label class="ds-field">
            <span>Render 宽度</span>
            <p class="ds-helper">控制渲染页面的基础 viewport 宽度，越大通常能容纳更多内容。</p>
            <input v-model.number="draft.render.width" class="ds-input ds-mono" type="number" min="320" step="1" />
          </label>
          <label class="ds-field">
            <span>Device scale factor</span>
            <p class="ds-helper">控制截图像素密度。最终是否清晰以真实 QQ 客户端为准。</p>
            <input
              v-model.number="draft.render.device_scale_factor"
              class="ds-input ds-mono"
              type="number"
              min="1"
              step="0.1"
            />
          </label>
        </div>
      </article>

      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <div>
              <h2>Catalog 扫描目录</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button
              class="ds-primary-button"
              type="button"
              :disabled="activeAction !== ''"
              @click="void saveFilesystemConfig()"
            >
              {{ activeAction === "filesystem" ? "保存中..." : "保存并尝试生效" }}
            </button>
          </div>
        </div>

        <div class="catalog-stack">
          <div class="catalog-item">
            <EditableListField
              v-model="skillCatalogDirs"
              label="Skill 扫描目录"
              helper="一次添加一个目录。可以写相对路径，也可以写绝对路径；保存后会在下方显示当前实际扫描到的目录。"
              placeholder="添加技能目录，按回车确认添加"
              empty-title="还没有显式配置技能扫描目录"
              empty-description="先添加一项，AcaBot 会在保存后解析实际生效位置，并在下方展示预览。"
              :disabled="activeAction !== ''"
            />

            <div class="ds-surface ds-card-padding-sm preview-block">
              <div class="preview-head">
                <div>
                  <h3>当前实际扫描到的技能目录</h3>
                  <p class="ds-summary">
                    这里显示的是已经生效的目录，不是你尚未保存的草稿。留空时会回退到默认值：{{ draft.filesystem.default_skill_catalog_dirs.join("、") || "./extensions/skills" }}。
                  </p>
                </div>
              </div>
              <ul v-if="draft.filesystem.resolved_skill_catalog_dirs.length" class="preview-list">
                <li
                  v-for="item in draft.filesystem.resolved_skill_catalog_dirs"
                  :key="`${item.scope}:${item.host_root_path}`"
                  class="ds-list-item ds-list-item-padding preview-item"
                >
                  <span class="ds-chip">{{ scopeLabel(item.scope) }}</span>
                  <code class="ds-mono preview-value">{{ item.host_root_path }}</code>
                </li>
              </ul>
              <p v-else class="ds-empty">当前还没有任何已生效的技能扫描目录。</p>
            </div>
          </div>

          <div class="catalog-item">
            <EditableListField
              v-model="subagentCatalogDirs"
              label="Subagent 扫描目录"
              helper="这里控制系统会到哪里寻找可用的子代理定义包。"
              placeholder="添加子代理目录，按回车确认添加"
              empty-title="还没有显式配置子代理扫描目录"
              empty-description="先添加一项，AcaBot 会在保存后解析实际生效位置，并在下方展示预览。"
              :disabled="activeAction !== ''"
            />

            <div class="ds-surface ds-card-padding-sm preview-block">
              <div class="preview-head">
                <div>
                  <h3>当前实际扫描到的子代理目录</h3>
                  <p class="ds-summary">
                    如果你没有显式填写，系统会回退到默认值：{{ draft.filesystem.default_subagent_catalog_dirs.join("、") || "./extensions/subagents" }}。
                  </p>
                </div>
              </div>
              <ul v-if="draft.filesystem.resolved_subagent_catalog_dirs.length" class="preview-list">
                <li
                  v-for="item in draft.filesystem.resolved_subagent_catalog_dirs"
                  :key="`${item.scope}:${item.host_root_path}`"
                  class="ds-list-item ds-list-item-padding preview-item"
                >
                  <span class="ds-chip">{{ scopeLabel(item.scope) }}</span>
                  <code class="ds-mono preview-value">{{ item.host_root_path }}</code>
                </li>
              </ul>
              <p v-else class="ds-empty">当前还没有任何已生效的子代理扫描目录。</p>
            </div>
          </div>
        </div>
      </article>

      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <div>
              <h2>管理员</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-primary-button" type="button" :disabled="activeAction !== ''" @click="void saveAdmins()">
              {{ activeAction === "admins" ? "保存中..." : "保存并尝试生效" }}
            </button>
          </div>
        </div>

        <EditableListField
          v-model="adminActorIds"
          label="管理员"
          helper="一次添加一个管理员标识。保存后，系统权限判断会立刻使用这一份列表。"
          placeholder="添加管理员标识，按回车确认添加"
          empty-title="还没有配置任何管理员"
          empty-description="先添加一项，AcaBot 保存后会立刻把它纳入管理员列表。"
          :disabled="activeAction !== ''"
        />
      </article>

      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <div>
              <h2>维护动作</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button
              class="ds-secondary-button"
              type="button"
              :disabled="activeAction !== ''"
              @click="void reloadConfiguration()"
            >
              {{ activeAction === "reload" ? "重新读取中..." : "重新读取配置" }}
            </button>
          </div>
        </div>

        <div class="ds-card-grid-2">
          <article class="ds-surface ds-card-padding-sm maintenance-card">
            <p class="summary-label">什么时候需要手动重读</p>
            <p class="ds-summary">
              主要用于你直接改过配置文件、怀疑热更新没有走到，或者想主动确认当前默认 agent / profile 装配状态的时候。
            </p>
          </article>
          <article class="ds-surface ds-card-padding-sm maintenance-card">
            <p class="summary-label">这一步不会替代重启</p>
            <p class="ds-summary">
              像 gateway 这种明确标成“已保存，但需重启”的设置，重新读取配置也不会替代真正的 runtime 重启。
            </p>
          </article>
        </div>
      </article>

      <article class="ds-panel ds-panel-padding">
        <details class="advanced-disclosure" :open="advancedOpen" @toggle="syncAdvancedOpen">
          <summary class="advanced-summary">高级信息 / 路径总览</summary>
          <p class="ds-summary advanced-copy">
            这里展示当前真正生效的文件和目录位置。技术细节可以看，但主标签都翻成了人话，方便你快速判断“配置写到哪了、运行时实际扫了哪、数据最终落到哪”。
          </p>

          <section class="ds-card-grid-3 advanced-cards">
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">当前配置文件位置</p>
              <code class="ds-mono summary-value">{{ pathOverview.config_path }}</code>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">文件系统根目录</p>
              <code class="ds-mono summary-value">{{ pathOverview.filesystem_base_dir }}</code>
            </article>
          </section>

          <section class="advanced-section">
            <div class="ds-section-head">
              <div class="ds-section-title">
                <div>
                  <h3>运行时数据落点</h3>
                  <p class="ds-summary">下面这些路径能帮助你快速确认 session、短记忆、LTM 和 computer 相关数据实际落在哪里。</p>
                </div>
              </div>
            </div>

            <div class="advanced-grid">
              <article v-for="row in runtimePathRows" :key="row.label" class="ds-surface ds-card-padding-sm path-card">
                <p class="summary-label">{{ row.label }}</p>
                <p class="ds-summary">{{ row.helper }}</p>
                <code class="ds-mono path-value">{{ row.value }}</code>
              </article>
            </div>
          </section>

          <section class="advanced-section">
            <div class="ds-section-head">
              <div class="ds-section-title">
                <div>
                  <h3>当前实际扫描到的目录</h3>
                  <p class="ds-summary">这里给你看的是最后解析成的绝对路径，方便排查“为什么页面没扫到技能 / 子代理”。</p>
                </div>
              </div>
            </div>

            <div class="ds-card-grid-2">
              <article class="ds-surface ds-card-padding-sm">
                <p class="summary-label">技能目录</p>
                <ul v-if="pathOverview.resolved_skill_catalog_dirs.length" class="advanced-list">
                  <li v-for="item in pathOverview.resolved_skill_catalog_dirs" :key="item">
                    <code class="ds-mono path-value">{{ item }}</code>
                  </li>
                </ul>
                <p v-else class="ds-empty">当前没有解析出任何技能目录。</p>
              </article>
              <article class="ds-surface ds-card-padding-sm">
                <p class="summary-label">子代理目录</p>
                <ul v-if="pathOverview.resolved_subagent_catalog_dirs.length" class="advanced-list">
                  <li v-for="item in pathOverview.resolved_subagent_catalog_dirs" :key="item">
                    <code class="ds-mono path-value">{{ item }}</code>
                  </li>
                </ul>
                <p v-else class="ds-empty">当前没有解析出任何子代理目录。</p>
              </article>
            </div>
          </section>
        </details>
      </article>
    </template>

    <p v-else class="ds-empty">系统配置还没有准备好。可以稍后重试，或者先检查 runtime 是否已经正常启动。</p>
  </section>
</template>

<style scoped>
.feedback-stack {
  display: grid;
  gap: 10px;
}

.feedback-detail {
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 12px 14px;
  background: var(--panel-strong);
}

.feedback-detail summary,
.advanced-summary {
  cursor: pointer;
  font-weight: 700;
  color: var(--heading-soft);
}

.feedback-code {
  margin: 12px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.summary-card,
.maintenance-card,
.path-card {
  display: grid;
  gap: 10px;
  opacity: 0;
  transform: translateY(8px);
  animation: sys-card-in 320ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.summary-card:nth-child(1) { animation-delay: 40ms; }
.summary-card:nth-child(2) { animation-delay: 80ms; }
.maintenance-card:nth-child(1) { animation-delay: 120ms; }
.maintenance-card:nth-child(2) { animation-delay: 160ms; }
.path-card {
  animation-delay: 200ms;
}

.ds-panel {
  opacity: 0;
  transform: translateY(8px);
  animation: sys-card-in 320ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.ds-panel:nth-of-type(1) { animation-delay: 80ms; }
.ds-panel:nth-of-type(2) { animation-delay: 140ms; }
.ds-panel:nth-of-type(3) { animation-delay: 200ms; }
.ds-panel:nth-of-type(4) { animation-delay: 260ms; }
.ds-panel:nth-of-type(5) { animation-delay: 320ms; }
.ds-panel:nth-of-type(6) { animation-delay: 380ms; }

@keyframes sys-card-in {
  to { opacity: 1; transform: translateY(0); }
}

.summary-label {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.summary-value,
.path-value,
.preview-value {
  color: var(--text);
  overflow-wrap: anywhere;
}

.catalog-stack,
.advanced-section {
  display: grid;
  gap: 16px;
}

.catalog-stack {
  margin-top: 8px;
}

.catalog-item {
  padding: 12px 14px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.preview-block {
  display: grid;
  gap: 12px;
}

.preview-head h3 {
  margin: 0;
  color: var(--heading-soft);
}

.preview-list,
.advanced-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.preview-list {
  display: grid;
  gap: 10px;
}

.preview-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.advanced-disclosure {
  display: grid;
  gap: 18px;
}

.advanced-copy {
  margin: 0;
}

.advanced-cards {
  margin-top: 4px;
}

.advanced-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.advanced-list {
  display: grid;
  gap: 10px;
}

@media (max-width: 960px) {
  .advanced-grid {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .summary-card,
  .maintenance-card,
  .path-card,
  .ds-panel {
    opacity: 1;
    transform: none;
    animation: none;
  }
}

@media (max-width: 860px) {
  .preview-item {
    flex-direction: column;
  }
}
</style>
