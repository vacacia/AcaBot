<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiDelete, apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"
import CustomSelect from "../components/CustomSelect.vue"

type ShellTab = "session" | "agent"
type CapabilityModalKind = "model" | "image_caption" | "tools" | "skills" | "subagents" | "environment"
type AdmissionMode = "respond" | "record_only" | "silent_drop"

type SurfaceEntry = {
  admission?: { default: { mode: string } }
  [key: string]: unknown
}

type SessionTemplateOption = {
  template_id: string
  label: string
}

const ADMISSION_MODES: Array<{ value: AdmissionMode; label: string }> = [
  { value: "respond", label: "回复" },
  { value: "record_only", label: "仅记录" },
  { value: "silent_drop", label: "忽略" },
]

const EVENT_TYPE_LABELS: Record<string, string> = {
  message: "普通消息",
  message_mention: "被@",
  message_reply: "引用回复",
  poke: "戳一戳",
  recall: "消息撤回",
  member_join: "成员加入",
  member_leave: "成员离开",
  admin_change: "管理员变更",
  file_upload: "文件上传",
  friend_added: "新增好友",
  mute_change: "禁言变更",
  honor_change: "群荣誉变更",
  title_change: "头衔变更",
  lucky_king: "运气王",
}

const TEMPLATE_EVENT_TYPES: Record<string, string[]> = {
  qq_private: ["message", "poke", "recall"],
  qq_group: ["message", "message_mention", "message_reply", "poke", "recall", "member_join", "member_leave", "admin_change", "file_upload", "mute_change", "honor_change", "title_change", "lucky_king"],
  custom: Object.keys(EVENT_TYPE_LABELS),
}

const TEMPLATE_SURFACE_STORAGE: Record<string, Record<string, string>> = {
  qq_private: {
    message: "message.private",
    poke: "notice.notify",
    recall: "notice.friend_recall",
  },
  qq_group: {
    message: "message.plain",
    message_mention: "message.mention",
    message_reply: "message.reply_to_bot",
    poke: "notice.notify",
    recall: "notice.group_recall",
    member_join: "notice.group_increase",
    member_leave: "notice.group_decrease",
    admin_change: "notice.group_admin",
    file_upload: "notice.group_upload",
    mute_change: "notice.group_ban",
    honor_change: "notice.notify",
    title_change: "notice.notify",
    lucky_king: "notice.notify",
  },
}

const SURFACE_TO_VIEW_EVENT_TYPES: Record<string, string[]> = {
  message: ["message"],
  "message.private": ["message"],
  "message.plain": ["message"],
  message_mention: ["message_mention"],
  "message.mention": ["message_mention"],
  message_reply: ["message_reply"],
  "message.reply_to_bot": ["message_reply"],
  poke: ["poke"],
  "notice.notify": ["poke", "honor_change", "title_change", "lucky_king"],
  recall: ["recall"],
  "notice.recall": ["recall"],
  "notice.group_recall": ["recall"],
  "notice.friend_recall": ["recall"],
  member_join: ["member_join"],
  "notice.group_increase": ["member_join"],
  member_leave: ["member_leave"],
  "notice.group_decrease": ["member_leave"],
  admin_change: ["admin_change"],
  "notice.group_admin": ["admin_change"],
  file_upload: ["file_upload"],
  "notice.group_upload": ["file_upload"],
  mute_change: ["mute_change"],
  "notice.group_ban": ["mute_change"],
  friend_added: ["friend_added"],
  "notice.friend_add": ["friend_added"],
  honor_change: ["honor_change"],
  title_change: ["title_change"],
  lucky_king: ["lucky_king"],
}

type SessionSummary = {
  session_id: string
  title: string
  template_id: string
  frontstage_agent_id: string
}

type SessionDetail = {
  session: {
    session_id: string
    title: string
    template_id: string
    frontstage_agent_id: string
  }
  surfaces: Record<string, SurfaceEntry>
  agent: {
    agent_id: string
    prompt_ref: string
    model_target?: string
    visible_tools: string[]
    visible_skills: string[]
    visible_subagents: string[]
    computer_policy?: {
      backend?: string
      allow_exec?: boolean
      allow_sessions?: boolean
      auto_stage_attachments?: boolean
      network_mode?: string
    }
  }
  paths: {
    session_dir: string
    session_config_path: string
    agent_config_path: string
  }
}

type UiCatalog = {
  prompts?: Array<{ prompt_ref: string; prompt_name: string; source?: string }>
  tools?: Array<{ name: string; description?: string; source?: string }>
  skills?: Array<{ skill_name: string; display_name?: string; description?: string }>
  subagents?: Array<{ subagent_name: string; description?: string }>
}

type ModelPresetRecord = {
  preset_id: string
  provider_id: string
  model: string
  task_kind: string
}

type ModelBindingSnapshot = {
  binding: {
    binding_id: string
    target_id: string
    preset_ids: string[]
    timeout_sec?: number | null
  }
  binding_state: string
  target_present: boolean
  message: string
}

type SessionDraft = { title: string; template_id: string; context_strategy: "truncate" | "summarize"; context_preserve_recent: number }
type AgentDraft = {
  prompt_ref: string
  reply_model_preset_ids: string[]
  image_caption_preset_ids: string[]
  visible_tools: string[]
  visible_skills: string[]
  visible_subagents: string[]
  backend: string
  allow_exec: boolean
  allow_sessions: boolean
}
type CreateSessionDraft = { session_id: string; title: string }

const TEMPLATE_OPTIONS: SessionTemplateOption[] = [
  { template_id: "qq_private", label: "QQ 私聊" },
  { template_id: "qq_group", label: "QQ 群聊" },
  { template_id: "custom", label: "自定义" },
]

// region 状态
const cachedSessions = peekCachedGet<SessionSummary[]>("/api/sessions") ?? []
const cachedCatalog = peekCachedGet<UiCatalog>("/api/ui/catalog")
const cachedModelPresets = peekCachedGet<ModelPresetRecord[]>("/api/models/presets") ?? []

const sessions = ref<SessionSummary[]>(cachedSessions)
const catalog = ref<UiCatalog>(cachedCatalog ?? {})
const modelPresets = ref<ModelPresetRecord[]>(cachedModelPresets)
const selectedSessionId = ref(cachedSessions[0]?.session_id ?? "")
const selectedDetail = ref<SessionDetail | null>(null)
const activeTab = ref<ShellTab>("session")
const activeCapabilityModal = ref<CapabilityModalKind | null>(null)

const loading = ref(cachedSessions.length === 0)
const detailLoading = ref(false)
const errorMessage = ref("")
const saveMessage = ref("")
const showCreateModal = ref(false)
const creating = ref(false)
const createError = ref("")

const sessionDraft = ref<SessionDraft>({
  title: "",
  template_id: TEMPLATE_OPTIONS[0]?.template_id ?? "qq_private",
  context_strategy: "truncate",
  context_preserve_recent: 12,
})
const agentDraft = ref<AgentDraft>({
  prompt_ref: "",
  reply_model_preset_ids: [],
  image_caption_preset_ids: [],
  visible_tools: [],
  visible_skills: [],
  visible_subagents: [],
  backend: "host",
  allow_exec: true,
  allow_sessions: true,
})
const surfacesDraft = ref<Record<string, AdmissionMode>>({})

const createDraft = ref<CreateSessionDraft>({
  session_id: "",
  title: "",
})

// region 计算属性
const promptOptions = computed(() => catalog.value.prompts ?? [])
const availableReplyModels = computed(() => modelPresets.value.filter((item) => item.task_kind === "chat"))
const toolOptions = computed(() => catalog.value.tools ?? [])
const skillOptions = computed(() => catalog.value.skills ?? [])
const subagentOptions = computed(() => catalog.value.subagents ?? [])
const selectedSummary = computed(() => sessions.value.find((item) => item.session_id === selectedSessionId.value) ?? null)

const promptSelectOptions = computed(() => promptOptions.value.map((p) => ({ value: p.prompt_ref, label: p.prompt_name })))
const backendSelectOptions = [{ value: "host", label: "host" }, { value: "docker", label: "docker" }]

const currentEventTypes = computed(() => {
  const templateId = selectedDetail.value?.session.template_id || "custom"
  return TEMPLATE_EVENT_TYPES[templateId] || TEMPLATE_EVENT_TYPES.custom
})

// region overlay 管理
watch(
  () => showCreateModal.value || activeCapabilityModal.value !== null,
  (open) => {
    if (typeof document !== "undefined") document.body.classList.toggle("overlay-active", open)
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  if (typeof document !== "undefined") document.body.classList.remove("overlay-active")
})

// region helpers
function normalizeSessionDraft(detail: SessionDetail): SessionDraft {
  const ctx = (detail as any).context || {}
  return {
    title: detail.session.title || "",
    template_id: detail.session.template_id || inferTemplate(detail.session.session_id),
    context_strategy: ctx.strategy === "summarize" ? "summarize" : "truncate",
    context_preserve_recent: typeof ctx.preserve_recent === "number" ? ctx.preserve_recent : 12,
  }
}

function storageSurfaceIdForEventType(templateId: string, eventType: string): string {
  return TEMPLATE_SURFACE_STORAGE[templateId]?.[eventType] || eventType
}

function viewEventTypesForSurfaceId(surfaceId: string): string[] {
  return SURFACE_TO_VIEW_EVENT_TYPES[surfaceId] || [surfaceId]
}

function normalizeSurfacesDraft(detail: SessionDetail): Record<string, AdmissionMode> {
  const result: Record<string, AdmissionMode> = {}
  for (const [surfaceId, surface] of Object.entries(detail.surfaces || {})) {
    const mode = surface?.admission?.default?.mode
    if (mode !== "respond" && mode !== "record_only" && mode !== "silent_drop") continue
    for (const eventType of viewEventTypesForSurfaceId(surfaceId)) {
      result[eventType] = mode
    }
  }
  return result
}

function getSurfaceMode(eventType: string): AdmissionMode {
  return surfacesDraft.value[eventType] || "silent_drop"
}

function setSurfaceMode(eventType: string, mode: AdmissionMode): void {
  surfacesDraft.value[eventType] = mode
}

function normalizeAgentDraft(detail: SessionDetail): AgentDraft {
  return {
    prompt_ref: detail.agent.prompt_ref || promptOptions.value[0]?.prompt_ref || "",
    reply_model_preset_ids: [],
    image_caption_preset_ids: [],
    visible_tools: [...(detail.agent.visible_tools ?? [])],
    visible_skills: [...(detail.agent.visible_skills ?? [])],
    visible_subagents: [...(detail.agent.visible_subagents ?? [])],
    backend: detail.agent.computer_policy?.backend || "host",
    allow_exec: detail.agent.computer_policy?.allow_exec ?? true,
    allow_sessions: detail.agent.computer_policy?.allow_sessions ?? true,
  }
}

function inferTemplate(sessionId: string): string {
  if (sessionId.startsWith("qq:group:")) return "qq_group"
  if (sessionId.startsWith("qq:user:") || sessionId.startsWith("qq:private:")) return "qq_private"
  return "custom"
}

function templateLabel(templateId: string): string {
  return TEMPLATE_OPTIONS.find((item) => item.template_id === templateId)?.label || templateId || "—"
}

function sessionDisplayTitle(item: SessionSummary): string {
  return item.title || item.session_id
}

function resetCreateDraft(): void {
  createDraft.value = { session_id: "", title: "" }
  createError.value = ""
}

// region 数据操作
async function loadSessions(preferredId = ""): Promise<void> {
  // Use SWR pattern: restore from cache first, then refresh
  const cachedCatalog = peekCachedGet<UiCatalog>("/api/ui/catalog")
  const cachedSessions = peekCachedGet<SessionSummary[]>("/api/sessions")
  const cachedPresets = peekCachedGet<ModelPresetRecord[]>("/api/models/presets")

  if (cachedCatalog) catalog.value = cachedCatalog
  if (cachedSessions) sessions.value = cachedSessions
  if (cachedPresets) modelPresets.value = cachedPresets

  // If we have cached sessions, we don't need a full-screen loading state
  loading.value = sessions.value.length === 0
  
  errorMessage.value = ""
  try {
    const [catalogPayload, sessionList, presetList] = await Promise.all([
      apiGet<UiCatalog>("/api/ui/catalog"),
      apiGet<SessionSummary[]>("/api/sessions"),
      apiGet<ModelPresetRecord[]>("/api/models/presets"),
    ])
    catalog.value = catalogPayload
    sessions.value = sessionList
    modelPresets.value = presetList
    const targetId = preferredId || selectedSessionId.value || sessionList[0]?.session_id || ""
    if (!targetId) {
      selectedSessionId.value = ""
      selectedDetail.value = null
      sessionDraft.value = { title: "", template_id: TEMPLATE_OPTIONS[0]?.template_id ?? "qq_private", context_strategy: "truncate", context_preserve_recent: 12 }
      agentDraft.value = {
        prompt_ref: promptOptions.value[0]?.prompt_ref || "",
        reply_model_preset_ids: [],
        image_caption_preset_ids: [],
        visible_tools: [],
        visible_skills: [],
        visible_subagents: [],
        backend: "host",
        allow_exec: true,
        allow_sessions: true,
      }
      return
    }
    await selectSession(targetId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败"
  } finally {
    loading.value = false
  }
}

async function selectSession(sessionId: string): Promise<void> {
  const sessionPath = `/api/sessions/${encodeURIComponent(sessionId)}`
  
  // SWR: Try to restore everything from cache first for instant feedback
  const cachedDetail = peekCachedGet<SessionDetail>(sessionPath)
  if (cachedDetail) {
    const agentId = `session:${sessionId}`
    selectedSessionId.value = sessionId
    selectedDetail.value = cachedDetail
    sessionDraft.value = normalizeSessionDraft(cachedDetail)
    surfacesDraft.value = normalizeSurfacesDraft(cachedDetail)
    agentDraft.value = normalizeAgentDraft(cachedDetail)
    
    // Peek binding IDs for instant sub-page switch
    const replyIds = getCachedBindingPresetIds(agentId, "")
    const imageIds = getCachedBindingPresetIds(agentId, ":image_caption")
    if (replyIds) agentDraft.value.reply_model_preset_ids = replyIds
    if (imageIds) agentDraft.value.image_caption_preset_ids = imageIds
    
    // We already have some detail to show, don't show the big spinner
    detailLoading.value = false
  }

  // Only show the heavy blocking spinner if we have absolutely nothing in cache
  if (!cachedDetail) {
    detailLoading.value = true
  }
  
  errorMessage.value = ""
  saveMessage.value = ""
  try {
    // Parallelize detailed data fetching
    const [payload, replyPresetIds, imageCaptionPresetIds] = await Promise.all([
      apiGet<SessionDetail>(sessionPath),
      loadBindingPresetIdsForAgent(sessionId, ""),
      loadBindingPresetIdsForAgent(sessionId, ":image_caption"),
    ])

    selectedSessionId.value = sessionId
    selectedDetail.value = payload
    sessionDraft.value = normalizeSessionDraft(payload)
    surfacesDraft.value = normalizeSurfacesDraft(payload)
    agentDraft.value = normalizeAgentDraft(payload)
    agentDraft.value.reply_model_preset_ids = replyPresetIds
    agentDraft.value.image_caption_preset_ids = imageCaptionPresetIds
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "读取详情失败"
  } finally {
    detailLoading.value = false
  }
}

// Optimized helper that derives target IDs from session bundle indirectly or predicts them
// Note: In SessionsView.vue, the binding ID depends on the internal agent_id.
// Since we are parallelizing, we might need to know the agent_id beforehand or fetch it with session detail.
// BUT, usually AcaBot's agent_id for a session is predictable: "session:<session_id>" -> "agent:session:<session_id>"
// Let's check how loadBindingPresetIds originally worked.
async function loadBindingPresetIdsForAgent(sessionId: string, suffix: string): Promise<string[]> {
  const agentId = `session:${sessionId}` // This matches current AcaBot convention for session-owned agents
  return await loadBindingPresetIds(agentId, suffix)
}

async function createSession(): Promise<void> {
  const sessionId = createDraft.value.session_id.trim()
  if (!sessionId) { createError.value = "Session ID 不能为空"; return }
  creating.value = true
  createError.value = ""
  try {
    const created = await apiPost<SessionDetail>("/api/sessions", {
      session_id: sessionId,
      template_id: inferTemplate(sessionId),
      title: createDraft.value.title.trim(),
    })
    showCreateModal.value = false
    saveMessage.value = "已创建"
    activeTab.value = "session"
    await loadSessions(created.session.session_id)
  } catch (error) {
    createError.value = error instanceof Error ? error.message : "创建失败"
  } finally {
    creating.value = false
  }
}

async function saveSession(): Promise<void> {
  if (!selectedDetail.value) return
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    const surfacesPayload: Record<string, unknown> = {}
    const templateId = sessionDraft.value.template_id
    for (const [eventType, mode] of Object.entries(surfacesDraft.value)) {
      const surfaceId = storageSurfaceIdForEventType(templateId, eventType)
      surfacesPayload[surfaceId] = { admission: { default: { mode } } }
    }
    const payload = await apiPut<SessionDetail>(
      `/api/sessions/${encodeURIComponent(selectedDetail.value.session.session_id)}`,
      {
        title: sessionDraft.value.title.trim(),
        template_id: sessionDraft.value.template_id,
        surfaces: surfacesPayload,
        context: {
          strategy: sessionDraft.value.context_strategy,
          preserve_recent: sessionDraft.value.context_preserve_recent,
        },
      },
    )
    selectedDetail.value = payload
    sessionDraft.value = normalizeSessionDraft(payload)
    sessions.value = sessions.value.map((item) =>
      item.session_id === payload.session.session_id
        ? { session_id: payload.session.session_id, title: payload.session.title, template_id: payload.session.template_id, frontstage_agent_id: payload.session.frontstage_agent_id }
        : item,
    )
    saveMessage.value = "已保存"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function saveAgent(): Promise<void> {
  if (!selectedDetail.value) return
  const promptRef = agentDraft.value.prompt_ref.trim()
  if (!promptRef) { errorMessage.value = "Prompt 不能为空"; saveMessage.value = ""; return }
  if (agentDraft.value.reply_model_preset_ids.length === 0) { errorMessage.value = "至少选择一个回复模型"; saveMessage.value = ""; return }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    const agentId = selectedDetail.value.agent.agent_id
    const payload = await apiPut<SessionDetail["agent"]>(
      `/api/sessions/${encodeURIComponent(selectedDetail.value.session.session_id)}/agent`,
      {
        prompt_ref: promptRef,
        model_target: selectedDetail.value.agent.model_target ?? "",
        visible_tools: agentDraft.value.visible_tools,
        visible_skills: agentDraft.value.visible_skills,
        visible_subagents: agentDraft.value.visible_subagents,
        computer_policy: {
          backend: agentDraft.value.backend,
          allow_exec: agentDraft.value.allow_exec,
          allow_sessions: agentDraft.value.allow_sessions,
        },
      },
    )
    await apiPut(`/api/models/bindings/${encodeURIComponent(bindingIdForAgent(agentId, ""))}`, {
      target_id: targetIdForAgent(agentId),
      preset_ids: agentDraft.value.reply_model_preset_ids,
    })
    if (agentDraft.value.image_caption_preset_ids.length > 0) {
      await apiPut(`/api/models/bindings/${encodeURIComponent(bindingIdForAgent(agentId, ":image_caption"))}`, {
        target_id: `${targetIdForAgent(agentId)}:image_caption`,
        preset_ids: agentDraft.value.image_caption_preset_ids,
      })
    } else {
      await apiDelete(`/api/models/bindings/${encodeURIComponent(bindingIdForAgent(agentId, ":image_caption"))}`).catch(() => {/* ignore if binding doesn't exist */})
    }
    selectedDetail.value = { ...(selectedDetail.value as SessionDetail), agent: { ...selectedDetail.value.agent, ...payload } }
    agentDraft.value = normalizeAgentDraft(selectedDetail.value)
    const replyPresetIds = await loadBindingPresetIds(agentId, "")
    const imageCaptionPresetIds = await loadBindingPresetIds(agentId, ":image_caption")
    agentDraft.value.reply_model_preset_ids = replyPresetIds
    agentDraft.value.image_caption_preset_ids = imageCaptionPresetIds
    saveMessage.value = "已保存"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

function strippableModelName(model: string): string {
  const n = String(model || "").trim()
  if (!n) return ""
  const s = n.split("/")
  return s[s.length - 1] || n
}

function targetIdForAgent(agentId: string): string { return `agent:${agentId}` }
function bindingIdForAgent(agentId: string, suffix: string): string { return `binding:${targetIdForAgent(agentId)}${suffix}` }

function getCachedBindingPresetIds(agentId: string, suffix: string): string[] | null {
  const bindingId = bindingIdForAgent(agentId, suffix)
  const cached = peekCachedGet<ModelBindingSnapshot>(`/api/models/bindings/${encodeURIComponent(bindingId)}`)
  return cached ? (cached.binding.preset_ids || []) : null
}

async function loadBindingPresetIds(agentId: string, suffix: string): Promise<string[]> {
  try {
    const snapshot = await apiGet<ModelBindingSnapshot>(`/api/models/bindings/${encodeURIComponent(bindingIdForAgent(agentId, suffix))}`)
    return snapshot.binding.preset_ids || []
  } catch { return [] }
}

function presetLabel(presetId: string): string {
  const m = availableReplyModels.value.find((item) => item.preset_id === presetId)
  return m ? strippableModelName(m.model) : presetId
}

function movePreset(list: string[], index: number, direction: -1 | 1): void {
  const target = index + direction
  if (target < 0 || target >= list.length) return
  const tmp = list[index]
  list[index] = list[target]
  list[target] = tmp
}

function removePreset(list: string[], index: number): void {
  list.splice(index, 1)
}

// region 能力弹窗
function capabilityItems(kind: Exclude<CapabilityModalKind, "environment">): Array<{ value: string; label: string; description: string }> {
  if (kind === "tools") return toolOptions.value.map((item) => ({ value: item.name, label: item.name, description: item.description || item.source || "" }))
  if (kind === "skills") return skillOptions.value.map((item) => ({ value: item.skill_name, label: item.display_name || item.skill_name, description: item.description || "" }))
  return subagentOptions.value.map((item) => ({ value: item.subagent_name, label: item.subagent_name, description: item.description || "" }))
}

function capabilityValues(kind: Exclude<CapabilityModalKind, "environment">): string[] {
  if (kind === "tools") return agentDraft.value.visible_tools
  if (kind === "skills") return agentDraft.value.visible_skills
  return agentDraft.value.visible_subagents
}

function setCapabilityValues(kind: Exclude<CapabilityModalKind, "environment">, values: string[]): void {
  if (kind === "tools") { agentDraft.value.visible_tools = values; return }
  if (kind === "skills") { agentDraft.value.visible_skills = values; return }
  agentDraft.value.visible_subagents = values
}

function toggleCapabilityValue(kind: Exclude<CapabilityModalKind, "environment">, value: string): void {
  const current = capabilityValues(kind)
  if (current.includes(value)) { setCapabilityValues(kind, current.filter((item) => item !== value)); return }
  setCapabilityValues(kind, [...current, value])
}

const capabilityModalTitle: Record<CapabilityModalKind, string> = {
  model: "添加回复模型",
  image_caption: "添加识图模型",
  tools: "工具",
  skills: "技能",
  subagents: "子代理",
  environment: "执行环境",
}

onMounted(() => { void loadSessions() })
</script>

<template>
  <section class="sv-page">
    <!-- 顶栏 -->
    <header class="sv-header">
      <div class="sv-header-left">
        <h1>会话</h1>
        <span class="sv-count" v-if="sessions.length">{{ sessions.length }} 个</span>
      </div>
      <button class="sv-btn sv-btn-accent" type="button" :disabled="creating" @click="resetCreateDraft(); showCreateModal = true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        {{ creating ? "创建中..." : "新建" }}
      </button>
    </header>

    <p v-if="saveMessage" class="sv-toast sv-toast-ok">{{ saveMessage }}</p>
    <p v-if="errorMessage" class="sv-toast sv-toast-err">{{ errorMessage }}</p>

    <!-- 主体 -->
    <div class="sv-body">
      <!-- 左侧列表 -->
      <aside class="sv-sidebar">
        <p v-if="loading && sessions.length === 0" class="sv-empty-hint">加载中...</p>
        <p v-else-if="sessions.length === 0" class="sv-empty-hint">暂无会话。发送消息给 bot 即可自动创建会话。</p>
        <button
          v-for="(item, i) in sessions"
          :key="item.session_id"
          class="sv-session-item"
          :class="{ 'is-active': item.session_id === selectedSessionId, 'session-entrance': true, [`session-entrance-${i}`]: true }"
          type="button"
          @click="void selectSession(item.session_id)"
        >
          <span class="sv-session-title">{{ sessionDisplayTitle(item) }}</span>
          <span class="sv-session-meta">
            <span class="sv-template-badge">{{ templateLabel(item.template_id) }}</span>
            <code>{{ item.session_id }}</code>
          </span>
        </button>
      </aside>

      <!-- 右侧详情 -->
      <div class="sv-detail">
        <template v-if="detailLoading && !selectedDetail">
          <div class="sv-empty-hint">加载中...</div>
        </template>

        <template v-else-if="selectedDetail">
          <!-- Tab 切换 -->
          <div class="sv-tab-bar">
            <button
              class="sv-tab" :class="{ 'is-active': activeTab === 'session' }"
              type="button" @click="activeTab = 'session'"
            >会话配置</button>
            <button
              class="sv-tab" :class="{ 'is-active': activeTab === 'agent' }"
              type="button" @click="activeTab = 'agent'"
            >Agent</button>
          </div>

          <!-- Session Tab -->
          <div v-if="activeTab === 'session'" class="sv-form-area">
            <div class="sv-form-grid">
              <label class="sv-field">
                <span class="sv-label">Session ID</span>
                <input class="sv-input mono" type="text" :value="selectedDetail.session.session_id" readonly />
              </label>
              <label class="sv-field">
                <span class="sv-label">标题</span>
                <input v-model="sessionDraft.title" class="sv-input" type="text" placeholder="显示名称" />
              </label>
              <label class="sv-field">
                <span class="sv-label">模板</span>
                <input class="sv-input" type="text" :value="templateLabel(sessionDraft.template_id)" readonly />
              </label>
              <label class="sv-field">
                <span class="sv-label">前台 Agent</span>
                <input class="sv-input mono" type="text" :value="selectedDetail.session.frontstage_agent_id" readonly />
              </label>
            </div>

            <div class="sv-path-row">
              <span class="sv-path-label">配置目录</span>
              <code class="sv-path-value">{{ selectedDetail.paths.session_dir }}</code>
            </div>

            <!-- 消息响应方式 -->
            <div class="sv-section">
              <div class="sv-section-head">
                <span class="sv-section-title">消息响应</span>
              </div>
              <div class="sv-surface-grid">
                <div class="sv-surface-row" v-for="eventType in currentEventTypes" :key="eventType">
                  <span class="sv-surface-label">{{ EVENT_TYPE_LABELS[eventType] || eventType }}</span>
                  <div class="sv-surface-modes">
                    <button
                      v-for="mode in ADMISSION_MODES"
                      :key="mode.value"
                      class="sv-mode-btn"
                      :class="{ 'is-active': getSurfaceMode(eventType) === mode.value, [`is-${mode.value}`]: getSurfaceMode(eventType) === mode.value }"
                      type="button"
                      @click="setSurfaceMode(eventType, mode.value)"
                    >{{ mode.label }}</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 上下文管理 -->
            <div class="sv-section">
              <div class="sv-context-card">
                <div class="sv-context-card-title">上下文管理</div>
                <div class="sv-context-body">
                  <div class="sv-context-field">
                    <span class="sv-context-field-label">策略</span>
                    <div class="sv-surface-modes">
                      <button
                        class="sv-mode-btn" type="button"
                        :class="{ 'is-active': sessionDraft.context_strategy === 'truncate', 'is-respond': sessionDraft.context_strategy === 'truncate' }"
                        @click="sessionDraft.context_strategy = 'truncate'"
                      >截断</button>
                      <button
                        class="sv-mode-btn" type="button"
                        :class="{ 'is-active': sessionDraft.context_strategy === 'summarize', 'is-respond': sessionDraft.context_strategy === 'summarize' }"
                        @click="sessionDraft.context_strategy = 'summarize'"
                      >压缩</button>
                    </div>
                    <span class="sv-context-hint">
                      {{ sessionDraft.context_strategy === 'truncate' ? '超出保留数的旧消息直接丢弃' : '超出保留数的旧消息用回复模型生成摘要' }}
                    </span>
                  </div>
                  <div class="sv-context-divider"></div>
                  <div class="sv-context-field">
                    <span class="sv-context-field-label">保留消息数</span>
                    <input
                      class="sv-input sv-input-narrow"
                      type="number"
                      min="1"
                      max="100"
                      :value="sessionDraft.context_preserve_recent"
                      @input="sessionDraft.context_preserve_recent = Math.max(1, parseInt(($event.target as HTMLInputElement).value) || 12)"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div class="sv-actions">
              <button class="sv-btn sv-btn-accent" type="button" :disabled="loading" @click="void saveSession()">
                {{ loading ? "保存中..." : "保存" }}
              </button>
            </div>
          </div>

          <!-- Agent Tab -->
          <div v-if="activeTab === 'agent'" class="sv-form-area">
            <!-- 回复模型 fallback 链 -->
            <div class="sv-section">
              <div class="sv-section-head">
                <span class="sv-section-title">回复模型</span>
                <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="activeCapabilityModal = 'model'">+ 添加</button>
              </div>
              <div v-if="agentDraft.reply_model_preset_ids.length" class="sv-model-list">
                <div class="sv-model-item" v-for="(pid, idx) in agentDraft.reply_model_preset_ids" :key="pid">
                  <span class="sv-model-rank">{{ idx + 1 }}</span>
                  <span class="sv-model-name">{{ presetLabel(pid) }}</span>
                  <span class="sv-model-id">{{ pid }}</span>
                  <div class="sv-model-actions">
                    <button class="sv-icon-btn" type="button" :disabled="idx === 0" @click="movePreset(agentDraft.reply_model_preset_ids, idx, -1)">↑</button>
                    <button class="sv-icon-btn" type="button" :disabled="idx === agentDraft.reply_model_preset_ids.length - 1" @click="movePreset(agentDraft.reply_model_preset_ids, idx, 1)">↓</button>
                    <button class="sv-icon-btn sv-icon-btn-danger" type="button" @click="removePreset(agentDraft.reply_model_preset_ids, idx)">×</button>
                  </div>
                </div>
              </div>
              <span v-else class="sv-cap-empty">未选择回复模型</span>
            </div>

            <!-- 识图模型 fallback 链 -->
            <div class="sv-section">
              <div class="sv-section-head">
                <span class="sv-section-title">识图模型</span>
                <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="activeCapabilityModal = 'image_caption'">+ 添加</button>
              </div>
              <div v-if="agentDraft.image_caption_preset_ids.length" class="sv-model-list">
                <div class="sv-model-item" v-for="(pid, idx) in agentDraft.image_caption_preset_ids" :key="pid">
                  <span class="sv-model-rank">{{ idx + 1 }}</span>
                  <span class="sv-model-name">{{ presetLabel(pid) }}</span>
                  <span class="sv-model-id">{{ pid }}</span>
                  <div class="sv-model-actions">
                    <button class="sv-icon-btn" type="button" :disabled="idx === 0" @click="movePreset(agentDraft.image_caption_preset_ids, idx, -1)">↑</button>
                    <button class="sv-icon-btn" type="button" :disabled="idx === agentDraft.image_caption_preset_ids.length - 1" @click="movePreset(agentDraft.image_caption_preset_ids, idx, 1)">↓</button>
                    <button class="sv-icon-btn sv-icon-btn-danger" type="button" @click="removePreset(agentDraft.image_caption_preset_ids, idx)">×</button>
                  </div>
                </div>
              </div>
              <span v-else class="sv-cap-empty">使用回复模型</span>
            </div>

            <!-- Prompt -->
            <div class="sv-section">
              <div class="sv-section-head">
                <span class="sv-section-title">Prompt</span>
              </div>
              <CustomSelect v-model="agentDraft.prompt_ref" :options="promptSelectOptions" placeholder="选择 Prompt" />
            </div>

            <!-- 能力 -->
            <div class="sv-cap-grid">
              <div class="sv-cap-card" v-for="kind in (['tools', 'skills', 'subagents'] as const)" :key="kind">
                <div class="sv-cap-head">
                  <span class="sv-cap-title">{{ { tools: '工具', skills: '技能', subagents: '子代理' }[kind] }}</span>
                  <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="activeCapabilityModal = kind">
                    {{ capabilityValues(kind).length || '选择' }}
                    <template v-if="capabilityValues(kind).length"> 项</template>
                  </button>
                </div>
                <div class="sv-chip-wrap" v-if="capabilityValues(kind).length">
                  <span class="sv-chip sv-chip-sm" v-for="v in capabilityValues(kind)" :key="v">
                    {{ capabilityItems(kind).find(i => i.value === v)?.label || v }}
                  </span>
                </div>
                <span v-else class="sv-cap-empty">未限制</span>
              </div>

              <div class="sv-cap-card">
                <div class="sv-cap-head">
                  <span class="sv-cap-title">执行环境</span>
                  <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="activeCapabilityModal = 'environment'">编辑</button>
                </div>
                <div class="sv-chip-wrap">
                  <span class="sv-chip sv-chip-sm">{{ agentDraft.backend }}</span>
                  <span class="sv-chip sv-chip-sm" :class="agentDraft.allow_exec ? 'sv-chip-on' : 'sv-chip-off'">exec</span>
                  <span class="sv-chip sv-chip-sm" :class="agentDraft.allow_sessions ? 'sv-chip-on' : 'sv-chip-off'">shell</span>
                </div>
              </div>
            </div>

            <div class="sv-actions">
              <button class="sv-btn sv-btn-accent" type="button" :disabled="loading" @click="void saveAgent()">
                {{ loading ? "保存中..." : "保存 Agent" }}
              </button>
            </div>
          </div>
        </template>

        <div v-else class="sv-empty-state">
          <div class="sv-empty-icon">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <rect x="4" y="8" width="32" height="24" rx="4" stroke="currentColor" stroke-width="1.5" opacity=".35"/>
              <path d="M4 14h32" stroke="currentColor" stroke-width="1.5" opacity=".2"/>
              <circle cx="10" cy="11" r="1.5" fill="currentColor" opacity=".25"/>
              <circle cx="15" cy="11" r="1.5" fill="currentColor" opacity=".25"/>
            </svg>
          </div>
          <p>选择一个会话开始配置</p>
        </div>
      </div>
    </div>

    <!-- 新建弹窗 -->
    <Teleport to="body">
      <Transition name="sv-modal">
      <div v-if="showCreateModal" class="sv-overlay" @click.self="showCreateModal = false" role="dialog" aria-modal="true">
        <div class="sv-modal">
          <div class="sv-modal-head">
            <h2>新建会话</h2>
            <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="showCreateModal = false">✕</button>
          </div>
          <div class="sv-modal-body">
            <label class="sv-field">
              <span class="sv-label">Session ID</span>
              <input v-model="createDraft.session_id" class="sv-input mono" type="text" placeholder="qq:group:123456" />
              <span class="sv-field-hint" v-if="createDraft.session_id.trim()">
                模板: {{ templateLabel(inferTemplate(createDraft.session_id.trim())) }}
              </span>
            </label>
            <label class="sv-field">
              <span class="sv-label">标题 <span class="sv-optional">(可选)</span></span>
              <input v-model="createDraft.title" class="sv-input" type="text" placeholder="显示名称" />
            </label>
            <p v-if="createError" class="sv-toast sv-toast-err">{{ createError }}</p>
          </div>
          <div class="sv-modal-foot">
            <button class="sv-btn sv-btn-ghost" type="button" @click="showCreateModal = false">取消</button>
            <button class="sv-btn sv-btn-accent" type="button" :disabled="creating" @click="void createSession()">
              {{ creating ? "创建中..." : "创建" }}
            </button>
          </div>
        </div>
      </div>
      </Transition>
    </Teleport>

    <!-- 能力弹窗 -->
    <Teleport to="body">
      <Transition name="sv-modal">
      <div v-if="activeCapabilityModal" class="sv-overlay" @click.self="activeCapabilityModal = null" role="dialog" aria-modal="true">
        <div class="sv-modal sv-modal-lg">
          <div class="sv-modal-head">
            <h2>{{ capabilityModalTitle[activeCapabilityModal] }}</h2>
            <button class="sv-btn sv-btn-ghost sv-btn-sm" type="button" @click="activeCapabilityModal = null">✕</button>
          </div>
          <div class="sv-modal-body">
            <!-- 添加回复模型 -->
            <template v-if="activeCapabilityModal === 'model'">
              <p v-if="availableReplyModels.length === 0" class="sv-empty-hint">没有可用模型, 先去模型页配置</p>
              <button
                v-for="item in availableReplyModels"
                :key="item.preset_id"
                class="sv-choice-row"
                :class="{ 'is-disabled': agentDraft.reply_model_preset_ids.includes(item.preset_id) }"
                type="button"
                :disabled="agentDraft.reply_model_preset_ids.includes(item.preset_id)"
                @click="agentDraft.reply_model_preset_ids.push(item.preset_id); activeCapabilityModal = null"
              >
                <div>
                  <strong>{{ strippableModelName(item.model) }}</strong>
                  <small class="sv-choice-meta">{{ item.preset_id }}</small>
                </div>
                <span v-if="agentDraft.reply_model_preset_ids.includes(item.preset_id)" class="sv-choice-added">已添加</span>
              </button>
            </template>

            <!-- 添加识图模型 -->
            <template v-else-if="activeCapabilityModal === 'image_caption'">
              <p v-if="availableReplyModels.length === 0" class="sv-empty-hint">没有可用模型, 先去模型页配置</p>
              <button
                v-for="item in availableReplyModels"
                :key="item.preset_id"
                class="sv-choice-row"
                :class="{ 'is-disabled': agentDraft.image_caption_preset_ids.includes(item.preset_id) }"
                type="button"
                :disabled="agentDraft.image_caption_preset_ids.includes(item.preset_id)"
                @click="agentDraft.image_caption_preset_ids.push(item.preset_id); activeCapabilityModal = null"
              >
                <div>
                  <strong>{{ strippableModelName(item.model) }}</strong>
                  <small class="sv-choice-meta">{{ item.preset_id }}</small>
                </div>
                <span v-if="agentDraft.image_caption_preset_ids.includes(item.preset_id)" class="sv-choice-added">已添加</span>
              </button>
            </template>

            <!-- 工具/技能/子代理 -->
            <template v-else-if="activeCapabilityModal === 'tools' || activeCapabilityModal === 'skills' || activeCapabilityModal === 'subagents'">
              <p v-if="capabilityItems(activeCapabilityModal).length === 0" class="sv-empty-hint">目录为空</p>
              <label v-for="item in capabilityItems(activeCapabilityModal)" :key="item.value" class="sv-choice-row">
                <div>
                  <strong>{{ item.label }}</strong>
                  <small class="sv-choice-meta" v-if="item.description">{{ item.description }}</small>
                </div>
                <input :checked="capabilityValues(activeCapabilityModal).includes(item.value)" type="checkbox" @change="toggleCapabilityValue(activeCapabilityModal, item.value)" />
              </label>
            </template>

            <!-- 执行环境 -->
            <template v-else>
              <label class="sv-field">
                <span class="sv-label">Backend</span>
                <CustomSelect v-model="agentDraft.backend" :options="backendSelectOptions" />
              </label>
              <label class="sv-toggle-row">
                <span>允许执行命令</span>
                <input v-model="agentDraft.allow_exec" type="checkbox" />
              </label>
              <label class="sv-toggle-row">
                <span>允许 Shell Session</span>
                <input v-model="agentDraft.allow_sessions" type="checkbox" />
              </label>
            </template>
          </div>
          <div class="sv-modal-foot">
            <button class="sv-btn sv-btn-accent" type="button" @click="activeCapabilityModal = null">完成</button>
          </div>
        </div>
      </div>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
/* region 页面布局 */
.sv-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.sv-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px;
}

.sv-header-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.sv-header h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--heading-strong);
}

.sv-count {
  font-size: 13px;
  color: var(--muted);
  font-weight: 500;
}

.sv-body {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
}

/* region 左侧列表 */
.sv-sidebar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: calc(100vh - 160px);
  overflow-y: auto;
  padding-right: 4px;
}

.sv-sidebar::-webkit-scrollbar { width: 4px; }
.sv-sidebar::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }

.sv-session-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  transition: all 140ms ease;
}

.sv-session-item:hover {
  background: var(--panel-white);
  border-color: var(--panel-line-soft);
}

.sv-session-item.is-active {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 30%, transparent);
}

.sv-session-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--heading-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sv-session-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--muted);
}

.sv-session-meta code {
  font-size: 10px;
  opacity: .7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sv-template-badge {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
  background: var(--panel-strong);
  border: 1px solid var(--panel-line-soft);
  color: var(--muted);
}

/* region 右侧详情 */
.sv-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--panel);
  backdrop-filter: var(--blur-card);
  -webkit-backdrop-filter: var(--blur-card);
  min-height: 400px;
}

/* region Tab 切换 */
.sv-tab-bar {
  display: flex;
  gap: 2px;
  padding: 3px;
  background: var(--panel-strong);
  border-radius: 12px;
  width: fit-content;
}

.sv-tab {
  padding: 7px 18px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 140ms ease;
}

.sv-tab:hover { color: var(--text); }
.sv-tab.is-active {
  background: var(--accent-soft);
  color: var(--heading-strong);
}

/* region 表单 */
.sv-form-area {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.sv-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.sv-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sv-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--heading-soft);
  letter-spacing: 0.02em;
}

.sv-optional {
  font-weight: 400;
  color: var(--muted);
}

.sv-field-hint {
  font-size: 11px;
  color: var(--accent);
  font-weight: 500;
}

.sv-input {
  width: 100%;
  box-sizing: border-box;
  padding: 9px 12px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.sv-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.sv-input[readonly] {
  opacity: .6;
  cursor: default;
}

.mono { font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace; font-size: 12px; }

.sv-path-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--panel-strong);
  font-size: 11px;
}

.sv-path-label {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 10px;
}

.sv-path-value {
  color: var(--text);
  font-size: 11px;
  overflow-wrap: anywhere;
}

/* region Section (Agent tab) */
.sv-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sv-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sv-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading-soft);
}

.sv-inline-value {
  display: flex;
  gap: 6px;
}

/* region 能力卡片 */
.sv-cap-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.sv-cap-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 14px;
  background: color-mix(in srgb, var(--panel-strong) 60%, transparent);
}

.sv-cap-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sv-cap-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--heading-soft);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sv-cap-empty {
  font-size: 12px;
  color: var(--muted);
  opacity: .6;
}

/* region Chips */
.sv-chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.sv-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-soft);
}

.sv-chip.is-placeholder {
  color: var(--muted);
  background: var(--panel-strong);
}

.sv-chip-sm {
  padding: 3px 8px;
  font-size: 11px;
  border-radius: 6px;
}

.sv-chip-on {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 14%, transparent);
}

.sv-chip-off {
  color: var(--muted);
  background: var(--panel-strong);
  opacity: .6;
  text-decoration: line-through;
}

/* region 按钮 */
.sv-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.sv-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 120ms ease;
}

.sv-btn:hover { transform: translateY(-1px); }
.sv-btn:active:not(:disabled) { transform: translateY(1px); }
.sv-btn:disabled { opacity: .5; cursor: not-allowed; transform: none; }

.sv-btn-accent {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  box-shadow: 0 6px 20px var(--button-shadow-color);
}

.sv-btn-ghost {
  background: var(--panel-strong);
  color: var(--text);
  border: 1px solid var(--panel-line-soft);
}

.sv-btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 8px; }

/* region 提示 & 空状态 */
.sv-toast {
  margin: 0;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
}

.sv-toast-ok { background: color-mix(in srgb, var(--success) 12%, transparent); color: var(--success); }
.sv-toast-err { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger); }

.sv-empty-hint {
  margin: 0;
  padding: 20px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}

.sv-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  flex: 1;
  color: var(--muted);
  font-size: 14px;
}

.sv-empty-icon { opacity: .4; }
.sv-empty-state p { margin: 0; }

/* region 弹窗 */
.sv-overlay {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0, 0, 0, .5);
  backdrop-filter: blur(12px);
  z-index: 100;
}

.sv-modal {
  width: min(520px, 100%);
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  padding: 24px;
  border-radius: 20px;
  border: 1px solid var(--border-strong);
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--panel);
  backdrop-filter: var(--blur-card);
  box-shadow: 0 32px 72px rgba(0, 0, 0, .4);
}

.sv-modal-lg { width: min(640px, 100%); }

.sv-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.sv-modal-head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--heading-strong);
}

.sv-modal-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sv-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}

/* region 弹窗选项列表 */
.sv-choice-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 14px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  cursor: pointer;
  transition: background 120ms ease;
}

.sv-choice-row:hover { background: var(--panel-white); }
.sv-choice-row strong { font-size: 13px; color: var(--heading-strong); }
.sv-choice-row input { flex-shrink: 0; }

.sv-choice-meta {
  display: block;
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}

.sv-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  font-size: 13px;
  color: var(--text);
  cursor: pointer;
}

.sv-toggle-row:hover { background: var(--panel-white); }
.sv-toggle-row input { flex-shrink: 0; }

/* region 模型 fallback 链 */
.sv-model-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  overflow: hidden;
}

.sv-model-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--panel-strong);
}

.sv-model-item:nth-child(even) {
  background: color-mix(in srgb, var(--panel-strong) 60%, var(--panel));
}

.sv-model-rank {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.sv-model-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--heading-strong);
}

.sv-model-id {
  font-size: 11px;
  color: var(--muted);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sv-model-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.sv-icon-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: all 100ms ease;
}

.sv-icon-btn:hover:not(:disabled) {
  background: var(--panel-white);
  color: var(--text);
}

.sv-icon-btn:disabled {
  opacity: .25;
  cursor: default;
}

.sv-icon-btn-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
}

.sv-choice-row.is-disabled {
  opacity: .4;
  cursor: default;
}

.sv-choice-added {
  font-size: 11px;
  color: var(--muted);
  flex-shrink: 0;
}

/* region 消息响应矩阵 */
.sv-surface-grid {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  overflow: hidden;
}

.sv-surface-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--panel-strong);
}

.sv-surface-row:nth-child(even) {
  background: color-mix(in srgb, var(--panel-strong) 60%, var(--panel));
}

.sv-surface-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}

.sv-surface-modes {
  display: flex;
  gap: 2px;
  padding: 2px;
  background: var(--panel);
  border-radius: 8px;
}

.sv-mode-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 100ms ease;
}

.sv-mode-btn:hover { color: var(--text); }

.sv-mode-btn.is-active.is-respond {
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
}

.sv-mode-btn.is-active.is-record_only {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
}

.sv-mode-btn.is-active.is-silent_drop {
  background: color-mix(in srgb, var(--muted) 12%, transparent);
  color: var(--muted);
}

/* region 上下文管理 */
.sv-context-card {
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  background: var(--panel-strong);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sv-context-card-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--heading);
}

.sv-context-body {
  display: flex;
  align-items: flex-start;
  gap: 24px;
}

.sv-context-divider {
  width: 1px;
  align-self: stretch;
  background: var(--panel-line-soft);
  flex-shrink: 0;
}

.sv-context-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sv-context-field-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sv-context-hint {
  font-size: 11px;
  color: var(--muted);
  opacity: 0.7;
}

.sv-input-narrow {
  width: 80px;
  text-align: center;
}

/* region 响应式 */
@media (max-width: 860px) {
  .sv-body { grid-template-columns: 1fr; }
  .sv-sidebar { max-height: 240px; }
  .sv-form-grid,
  .sv-cap-grid { grid-template-columns: 1fr; }
}

/* ── Session list stagger entrance ── */
.session-entrance {
  opacity: 0;
  transform: translateX(-8px);
  animation: sv-session-in 300ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}
.session-entrance-0 { animation-delay: 0ms; }
.session-entrance-1 { animation-delay: 50ms; }
.session-entrance-2 { animation-delay: 100ms; }
.session-entrance-3 { animation-delay: 150ms; }
.session-entrance-4 { animation-delay: 200ms; }
.session-entrance-5 { animation-delay: 250ms; }
.session-entrance-6 { animation-delay: 300ms; }
.session-entrance-7 { animation-delay: 350ms; }

@keyframes sv-session-in {
  to { opacity: 1; transform: translateX(0); }
}

/* ── Session item hover slide ── */
.sv-session-item {
  transition: all 140ms cubic-bezier(0.25, 1, 0.5, 1);
}

.sv-session-item:hover {
  transform: translateX(3px);
}

/* ── Tab content transition ── */
.sv-tab-content-enter-active {
  animation: sv-tab-in 220ms cubic-bezier(0.25, 1, 0.5, 1);
}

.sv-tab-content-leave-active {
  animation: sv-tab-out 140ms cubic-bezier(0.4, 0, 1, 1);
}

@keyframes sv-tab-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

@keyframes sv-tab-out {
  from { opacity: 1; transform: translateY(0); }
  to   { opacity: 0; transform: translateY(-4px); }
}

/* ── Modal transition ── */
.sv-modal-enter-active {
  animation: sv-overlay-in 200ms ease forwards;
}

.sv-modal-leave-active {
  animation: sv-overlay-out 160ms ease forwards;
}

.sv-modal-enter-active .sv-modal,
.sv-modal-enter-active .sv-modal-lg {
  animation: sv-modal-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.sv-modal-leave-active .sv-modal,
.sv-modal-leave-active .sv-modal-lg {
  animation: sv-modal-out 180ms cubic-bezier(0.4, 0, 1, 1) forwards;
}

@keyframes sv-overlay-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes sv-overlay-out {
  from { opacity: 1; }
  to   { opacity: 0; }
}

@keyframes sv-modal-in {
  from { opacity: 0; transform: scale(0.94) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes sv-modal-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(0.96) translateY(4px); }
}

/* ── Choice row hover ── */
.sv-choice-row {
  transition: background 120ms ease, transform 120ms ease;
}

.sv-choice-row:hover {
  transform: translateX(2px);
}

.sv-choice-row.is-disabled {
  transition: opacity 120ms ease;
}

/* ── Mode btn active ── */
.sv-mode-btn {
  transition: all 120ms cubic-bezier(0.25, 1, 0.5, 1);
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .session-entrance {
    opacity: 1;
    transform: none;
    animation: none;
  }
  .sv-session-item:hover {
    transform: none;
  }
  .sv-tab-content-enter-active,
  .sv-tab-content-leave-active,
  .sv-modal-enter-active,
  .sv-modal-leave-active,
  .sv-modal-enter-active .sv-modal,
  .sv-modal-leave-active .sv-modal,
  .sv-modal-enter-active .sv-modal-lg,
  .sv-modal-leave-active .sv-modal-lg {
    animation: none;
  }
  .sv-choice-row:hover {
    transform: none;
  }
}
</style>
