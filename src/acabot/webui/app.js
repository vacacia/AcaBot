const pageMeta = {
  dashboard: {
    title: "Dashboard",
    subtitle: "查看 runtime 当前状态、待处理 approvals 和基础运行健康度。",
  },
  approvals: {
    title: "Approvals",
    subtitle: "集中处理进入 waiting_approval 的 run。",
  },
  agents: {
    title: "Bot",
    subtitle: "管理主 Bot 的全局配置。Sessions 默认继承这里的模型、Prompt、Tools 和 Skills。",
  },
  subagents: {
    title: "Subagents",
    subtitle: "把本地 profile 当作 local subagent executor 管理，重点配置它们自己的 model、tools 和 skills。",
  },
  prompts: {
    title: "Prompts",
    subtitle: "管理 prompt 本体内容。其他页面引用它时再使用 prompt_ref。",
  },
  sessions: {
    title: "Sessions",
    subtitle: "按会话入口统一设置响应方式、AI 覆盖，以及记录与 memory 策略。",
  },
  "model-providers": {
    title: "Model Providers",
    subtitle: "维护 provider 接入层。这里只管供应商连接信息，不直接决定哪个 agent 用哪个模型。",
  },
  "model-presets": {
    title: "Model Presets",
    subtitle: "维护可复用的模型预设。preset 才是可以被 binding 复用的具体模型定义。",
  },
  gateway: {
    title: "Gateway",
    subtitle: "查看 NapCat 反向 WebSocket 是否已经连到 AcaBot，以及当前 self_id / call_api 能力状态。",
  },
  runtime: {
    title: "Runtime",
    subtitle: "查看 threads、runs、run steps、thread events，以及当前 thread override。",
  },
  plugins: {
    title: "Plugins",
    subtitle: "查看已加载 plugins、skills 和 subagent executors，并执行 reload。",
  },
  workspaces: {
    title: "Workspaces",
    subtitle: "查看 workspace、sandbox、sessions 和 staged attachments。",
  },
  references: {
    title: "References",
    subtitle: "管理 Reference Spaces，执行搜索，并向当前 space 添加文档。",
  },
}

const modelPages = {
  "model-providers": {
    kind: "providers",
    idKey: "provider_id",
    title: "Model Providers",
    note: "provider 保存 Base URL、API Key 等连接信息。实际可供 bot / subagent 使用的模型定义在 Model Presets。",
    help: `
      <strong>provider 是什么？</strong><br>
      provider 是供应商接入层，只负责连接信息，不直接表示某个具体模型。<br>
      当前 runtime 正式支持的 provider kind 只有:
      <div class="pill-row" style="margin-top:10px;">
        <span class="pill">openai_compatible</span>
        <span class="pill">anthropic</span>
        <span class="pill">google_gemini</span>
      </div>
    `,
  },
  "model-presets": {
    kind: "presets",
    idKey: "preset_id",
    title: "Model Presets",
    note: "preset 是具体模型定义。一个 preset 可以被多个 Model Binding 复用。",
    help: `
      <strong>preset 是什么？</strong><br>
      preset = provider + model + context_window + model_params。<br>
      真正决定谁会用到它的是 <strong>Model Bindings</strong>，不是 preset 本身。
    `,
  },
}

const modelFieldSpecs = {
  providers: [
    {
      key: "kind",
      label: "Provider Kind",
      type: "select",
      options: [
        { value: "openai_compatible", label: "openai_compatible" },
        { value: "anthropic", label: "anthropic" },
        { value: "google_gemini", label: "google_gemini" },
      ],
      help: "这里只允许 runtime 当前兼容的 kind。不要在前端发明新的 kind。",
    },
    {
      key: "base_url",
      label: "Base URL",
      type: "text",
      help: "OpenAI-compatible provider 通常必填。Anthropic / Google Gemini 只有在你需要自定义 endpoint 时才填写。",
    },
    {
      key: "api_key",
      label: "API Key",
      type: "text",
      help: "本地单机部署时可以直接填 API Key。这里不会故意隐藏你刚填进去的值。",
    },
    {
      key: "anthropic_version",
      label: "Anthropic Version",
      type: "text",
      visibleKinds: ["anthropic"],
      help: "只对 anthropic kind 有意义，例如 2023-06-01。",
    },
    {
      key: "api_version",
      label: "API Version",
      type: "text",
      visibleKinds: ["google_gemini"],
      help: "只对 google_gemini kind 有意义，格式应类似 v1。",
    },
    {
      key: "project_id",
      label: "Project ID",
      type: "text",
      visibleKinds: ["google_gemini"],
      help: "只对 google_gemini + Vertex AI 场景有意义。",
    },
    {
      key: "location",
      label: "Location",
      type: "text",
      visibleKinds: ["google_gemini"],
      help: "只对 google_gemini + Vertex AI 场景有意义。",
    },
    {
      key: "use_vertex_ai",
      label: "Use Vertex AI",
      type: "boolean",
      visibleKinds: ["google_gemini"],
      help: "只对 google_gemini kind 有意义。",
    },
    {
      key: "default_headers",
      label: "Default Headers",
      type: "readonly-json",
      help: "高级参数目前只读保留，不要求你在 WebUI 里手写 JSON。",
    },
  ],
  presets: [
    {
      key: "provider_id",
      label: "Provider ID",
      type: "select-free",
      help: "这个 preset 依附哪个 provider。",
    },
    {
      key: "model",
      label: "Model",
      type: "text",
      help: "具体模型名，例如 gpt-4o-mini、claude-3-7-sonnet、gemini-2.0-flash。",
    },
    {
      key: "context_window",
      label: "Context Window",
      type: "number",
      help: "这个 preset 声明的最大上下文窗口。",
    },
    {
      key: "supports_tools",
      label: "Supports Tools",
      type: "boolean",
      help: "该模型是否支持 tool calling。",
    },
    {
      key: "supports_vision",
      label: "Supports Vision",
      type: "boolean",
      help: "该模型是否支持视觉输入。",
    },
    {
      key: "max_output_tokens",
      label: "Max Output Tokens",
      type: "number",
      help: "可选。不填表示不显式声明。",
    },
    {
      key: "model_params",
      label: "Model Params",
      type: "readonly-json",
      help: "高级 model_params 目前只读保留，不要求你在 WebUI 里手写 JSON。",
    },
  ],
  bindings: [
    {
      key: "target_type",
      label: "Target Type",
      type: "select",
      options: [
        { value: "global", label: "global" },
        { value: "agent", label: "agent" },
        { value: "system", label: "system" },
      ],
      help: "binding 生效范围。当前正式支持 global、agent、system。",
    },
    {
      key: "target_id",
      label: "Target ID",
      type: "select-free",
      help: "global 必须是 default；system 目前只支持 compactor_summary；agent 时这里填 agent_id。",
    },
    {
      key: "preset_id",
      label: "Preset ID",
      type: "select-free",
      help: "global 和 agent 通常用这个字段绑定单个 preset。",
    },
    {
      key: "preset_ids",
      label: "Preset IDs",
      type: "list",
      help: "只对 system / compactor_summary 有意义，用来配置 fallback chain。",
    },
    {
      key: "timeout_sec",
      label: "Timeout Sec",
      type: "number",
      help: "可选。对这个 binding 注入 runtime timeout。",
    },
  ],
}

const state = {
  view: "dashboard",
  meta: null,
  status: null,
  catalog: null,
  profiles: [],
  selectedProfileId: "",
  botProfileId: "",
  selectedSubagentId: "",
  prompts: [],
  selectedPromptRef: "",
  modelEntities: { providers: [], presets: [], bindings: [] },
  selectedModelIds: { providers: "", presets: "", bindings: "" },
  currentModelDrafts: { providers: null, presets: null, bindings: null },
  botEventDefaults: {},
  botSection: "ai",
  sessionConfigs: [],
  selectedSessionKey: "",
  sessionSection: "ai",
  threads: [],
  selectedThreadId: "",
  runs: [],
  selectedRunId: "",
  plugins: [],
  workspaces: [],
  selectedWorkspaceId: "",
  referenceSpaces: [],
  selectedReferenceSpaceKey: "",
  selectedReferenceDocument: null,
  theme: localStorage.getItem("acabot-theme") || "light",
}

const SESSION_EVENT_TYPE_LABELS = {
  message: "普通消息",
  poke: "戳一戳",
  recall: "撤回消息",
  member_join: "成员加入",
  member_leave: "成员离开",
  admin_change: "管理员变更",
  file_upload: "文件上传",
  mute_change: "禁言变化",
  honor_change: "群荣誉变化",
  title_change: "头衔变化",
  lucky_king: "运气王变化",
}

const BOT_MEMORY_SCOPES = ["episodic", "relationship", "user", "channel", "global"]

const $ = (selector) => document.querySelector(selector)
const $$ = (selector) => Array.from(document.querySelectorAll(selector))

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2)
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? {}))
}

function formatTime(timestamp) {
  if (!timestamp) return "-"
  const date = new Date(Number(timestamp) * 1000)
  if (Number.isNaN(date.valueOf())) return "-"
  return date.toLocaleString("zh-CN")
}

function previewText(text, max = 88) {
  const normalized = String(text ?? "").replace(/\s+/g, " ").trim()
  if (!normalized) return "-"
  if (normalized.length <= max) return normalized
  return `${normalized.slice(0, max)}...`
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`
}

function showToast(message) {
  const toast = $("#toast")
  toast.textContent = message
  toast.hidden = false
  clearTimeout(showToast.timer)
  showToast.timer = setTimeout(() => {
    toast.hidden = true
  }, 2600)
}

function handleError(error) {
  console.error(error)
  showToast(error?.message || "操作失败")
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  })
  const json = await response.json().catch(() => ({}))
  if (!response.ok || !json.ok) {
    throw new Error(json.error || `request failed: ${path}`)
  }
  return json.data
}

async function ensureCatalog(force = false) {
  if (!force && state.catalog) {
    return state.catalog
  }
  state.catalog = await api("/api/ui/catalog")
  return state.catalog
}

function catalogOptions(key) {
  return state.catalog?.options?.[key] || []
}

function promptNameFromRef(promptRef) {
  return String(promptRef || "").replace(/^prompt\//, "") || ""
}

function promptRefFromName(promptName) {
  const normalized = String(promptName || "").trim()
  if (!normalized) return ""
  return normalized.startsWith("prompt/") ? normalized : `prompt/${normalized}`
}

function getBotAgentId() {
  return String(state.botProfileId || state.catalog?.bot?.agent_id || "")
}

function getBotProfile() {
  const botAgentId = getBotAgentId()
  return state.profiles.find((item) => item.agent_id === botAgentId) || null
}

function isManagedSessionProfile(profile) {
  const metadata = profile?.metadata || profile?.config?.metadata || {}
  return String(metadata.managed_by || "") === "webui_session"
}

function managedSessionProfileId(channelScope) {
  const normalized = String(channelScope || "")
    .trim()
    .replace(/[^A-Za-z0-9:_-]+/g, "_")
  return `session-profile:${normalized || "new"}`
}

function generatedProfileId(name, prefix) {
  const base = String(name || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
  const suffix = base || `${Date.now().toString(36)}`
  return `${prefix}:${suffix}`
}

function findAgentModelBinding(agentId) {
  const bindings = state.modelEntities.bindings || state.catalog?.model_bindings || []
  return bindings.find((item) => item.target_type === "agent" && item.target_id === agentId) || null
}

function generateInternalId(prefix) {
  return `${prefix}:${Date.now().toString(36)}:${Math.random().toString(36).slice(2, 8)}`
}

function sessionEventTypes() {
  const options = catalogOptions("event_types")
  if (Array.isArray(options) && options.length) {
    return options.filter((item) => item !== "friend_added")
  }
  return Object.keys(SESSION_EVENT_TYPE_LABELS)
}

function sessionEventTypeLabel(eventType) {
  return SESSION_EVENT_TYPE_LABELS[eventType] || eventType || "未命名事件"
}

function defaultSessionResponseModes() {
  return Object.fromEntries(sessionEventTypes().map((eventType) => [eventType, "respond"]))
}

function botEventTypes() {
  const options = catalogOptions("event_types")
  if (Array.isArray(options) && options.length) return options
  return Object.keys(SESSION_EVENT_TYPE_LABELS).concat("friend_added")
}

function eventTypeLabel(eventType) {
  if (eventType === "friend_added") return "新增好友"
  return SESSION_EVENT_TYPE_LABELS[eventType] || eventType || "未命名事件"
}

function defaultBotEventDefaults() {
  return Object.fromEntries(
    botEventTypes().map((eventType) => [
      eventType,
      {
        run_mode: "respond",
        persist_event: true,
        extract_to_memory: false,
        memory_scopes: eventType === "message" ? ["episodic"] : [],
        inbound_rule_id: "",
        event_policy_id: "",
      },
    ]),
  )
}

function isSimpleBotDefaultRule(item) {
  const match = item?.match || {}
  return (
    !match.channel_scope
    && !match.actor_id
    && !match.message_subtype
    && !match.notice_type
    && !match.notice_subtype
    && match.platform === "qq"
    && !!match.event_type
    && !match.targets_self
    && !match.mentioned_everyone
    && !(Array.isArray(match.sender_roles) && match.sender_roles.length)
  )
}

function buildBotEventDefaults(inboundRules, eventPolicies) {
  const defaults = defaultBotEventDefaults()
  for (const rule of inboundRules.filter(isSimpleBotDefaultRule)) {
    const eventType = String(rule.match?.event_type || "")
    if (!eventType || !Object.hasOwn(defaults, eventType)) continue
    defaults[eventType].run_mode = rule.run_mode || "respond"
    defaults[eventType].inbound_rule_id = rule.rule_id || ""
  }
  for (const policy of eventPolicies.filter(isSimpleBotDefaultRule)) {
    const eventType = String(policy.match?.event_type || "")
    if (!eventType || !Object.hasOwn(defaults, eventType)) continue
    defaults[eventType].persist_event = policy.persist_event !== false
    defaults[eventType].extract_to_memory = Boolean(policy.extract_to_memory)
    defaults[eventType].memory_scopes = Array.isArray(policy.memory_scopes) ? [...policy.memory_scopes] : []
    defaults[eventType].event_policy_id = policy.policy_id || ""
  }
  return defaults
}

function normalizeSessionResponseModes(responseModes) {
  const allowedModes = new Set(catalogOptions("run_modes").length ? catalogOptions("run_modes") : ["respond", "record_only", "silent_drop"])
  const normalized = defaultSessionResponseModes()
  for (const [eventType, mode] of Object.entries(responseModes || {})) {
    if (!Object.hasOwn(normalized, eventType)) continue
    normalized[eventType] = allowedModes.has(mode) ? mode : "respond"
  }
  return normalized
}

function parseSessionInboundRuleIds(rawValue) {
  const raw = String(rawValue || "").trim()
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return raw ? { message: raw } : {}
  }
}

function scopeToUiValue(channelScope) {
  const raw = String(channelScope || "").trim()
  if (!raw) {
    return { scope_type: "any", scope_value: "", channel_scope: "" }
  }
  if (raw.startsWith("qq:user:")) {
    return { scope_type: "private", scope_value: raw.slice("qq:user:".length), channel_scope: raw }
  }
  if (raw.startsWith("qq:group:")) {
    return { scope_type: "group", scope_value: raw.slice("qq:group:".length), channel_scope: raw }
  }
  return { scope_type: "custom", scope_value: raw, channel_scope: raw }
}

function uiScopeToChannelScope(scopeType, scopeValue) {
  const normalizedType = String(scopeType || "any")
  const normalizedValue = String(scopeValue || "").trim()
  if (normalizedType === "any" || !normalizedValue) return ""
  if (normalizedType === "private") return `qq:user:${normalizedValue}`
  if (normalizedType === "group") return `qq:group:${normalizedValue}`
  return normalizedValue
}

function setTheme(theme) {
  state.theme = theme
  document.documentElement.setAttribute("data-theme", theme)
  localStorage.setItem("acabot-theme", theme)
}

function isModelView(view) {
  return Object.hasOwn(modelPages, view)
}

function currentModelPage() {
  return modelPages[state.view]
}

function currentModelKind() {
  return currentModelPage()?.kind || "providers"
}

const legacyRoutingViews = new Set(["agent-routing", "inbound-rules", "event-policies"])

function visibleViewFor(view) {
  if (isModelView(view)) return "model-shell"
  if (legacyRoutingViews.has(view)) return "sessions"
  return view
}

function setSessionSection(section) {
  const allowed = new Set(["ai", "response", "memory", "summary"])
  state.sessionSection = allowed.has(section) ? section : "ai"
  $$("[data-session-section-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.sessionSectionTab === state.sessionSection)
  })
  $$("[data-session-section-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.sessionSectionPanel === state.sessionSection)
  })
}

function setBotSection(section) {
  const allowed = new Set(["ai", "events", "tools", "subagents", "sandbox", "summary"])
  state.botSection = allowed.has(section) ? section : "ai"
  $$("[data-bot-section-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.botSectionTab === state.botSection)
  })
  $$("[data-bot-section-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.botSectionPanel === state.botSection)
  })
}

function updatePageChrome() {
  const meta = pageMeta[state.view]
  $("#page-title").textContent = meta.title
  $("#page-subtitle").textContent = meta.subtitle

  if (isModelView(state.view)) {
    const page = currentModelPage()
    $("#model-page-heading").textContent = page.title
    $("#model-page-note").textContent = page.note
    $("#models-editor-title").textContent = `${page.title} Editor`
    $("#model-help-card").innerHTML = page.help
    $("#model-id-label").textContent = page.idKey
  }
}

function setView(view) {
  if (view === "model-bindings") {
    view = "model-presets"
  }
  state.view = view
  $$(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === view)
  })
  const visible = visibleViewFor(view)
  $$(".view").forEach((section) => {
    section.classList.toggle("active", section.dataset.view === visible)
  })
  if (visible === "sessions") {
    setSessionSection(state.sessionSection)
  }
  if (visible === "agents") {
    setBotSection(state.botSection)
  }
  updatePageChrome()
  window.location.hash = view
  refreshCurrentView(true).catch(handleError)
}

async function loadMetaAndStatus() {
  const [meta, status] = await Promise.all([
    api("/api/meta"),
    api("/api/status"),
  ])
  state.meta = meta
  state.status = status
  $("#meta-storage-mode").textContent = `storage: ${meta.storage_mode}`
  $("#meta-config-path").textContent = `config: ${meta.config_path}`
  $("#status-strip").innerHTML = [
    ["active runs", (status.active_runs || []).length],
    ["pending approvals", (status.pending_approvals || []).length],
    ["plugins", (status.loaded_plugins || []).length],
    ["skills", (status.loaded_skills || []).length],
  ]
    .map(([label, value]) => `<div class="status-pill">${escapeHtml(label)}: <strong>${escapeHtml(value)}</strong></div>`)
    .join("")
}

function renderSelectableList(container, items, activeId, getId, titleFn, metaFn) {
  if (!items.length) {
    container.innerHTML = emptyState("暂无数据")
    return
  }
  container.innerHTML = items
    .map((item) => {
      const id = getId(item)
      return `
        <div class="list-item ${id === activeId ? "active" : ""}" data-item-id="${escapeHtml(id)}">
          <div class="list-item-title">${titleFn(item)}</div>
          <div class="list-item-meta">${metaFn(item)}</div>
        </div>
      `
    })
    .join("")
}

function wireSelectableClicks(container, callback) {
  container.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => callback(node.dataset.itemId))
  })
}

async function loadDashboard() {
  const modelStatus = await api("/api/models/status").catch(() => null)
  const status = state.status || { active_runs: [], pending_approvals: [], loaded_skills: [] }
  $("#stat-active-runs").textContent = (status.active_runs || []).length
  $("#stat-pending-approvals").textContent = (status.pending_approvals || []).length
  $("#stat-loaded-skills").textContent = (status.loaded_skills || []).length
  $("#stat-model-providers").textContent = modelStatus?.provider_count ?? 0

  const activeRuns = status.active_runs || []
  $("#dashboard-active-runs").innerHTML = activeRuns.length
    ? activeRuns
        .map(
          (run) => `
            <div class="info-card">
              <div class="list-item-title mono">${escapeHtml(run.run_id)}</div>
              <div class="list-item-meta">agent=${escapeHtml(run.agent_id)} · status=${escapeHtml(run.status)} · thread=${escapeHtml(run.thread_id)}</div>
            </div>
          `,
        )
        .join("")
    : emptyState("当前没有 active run")

  const approvals = status.pending_approvals || []
  $("#dashboard-approvals").innerHTML = approvals.length
    ? approvals
        .slice(0, 5)
        .map(
          (item) => `
            <div class="info-card">
              <div class="list-item-title mono">${escapeHtml(item.run_id)}</div>
              <div class="list-item-meta">${escapeHtml(item.reason || "等待审批")}</div>
            </div>
          `,
        )
        .join("")
    : emptyState("当前没有 pending approval")
}

async function loadApprovals() {
  const approvals = state.status?.pending_approvals || []
  const box = $("#pending-approvals")
  if (!approvals.length) {
    box.innerHTML = emptyState("当前没有待审批项")
    return
  }
  box.innerHTML = approvals
    .map(
      (item) => `
        <div class="info-card">
          <div class="list-item-title mono">${escapeHtml(item.run_id)}</div>
          <div class="list-item-meta">${escapeHtml(item.reason || "")}</div>
          <div class="inline-actions" style="margin-top: 12px;">
            <button class="button button-primary" data-approval-action="approve" data-run-id="${escapeHtml(item.run_id)}">Approve</button>
            <button class="button button-danger" data-approval-action="reject" data-run-id="${escapeHtml(item.run_id)}">Reject</button>
          </div>
        </div>
      `,
    )
    .join("")

  box.querySelectorAll("[data-approval-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const runId = button.dataset.runId
      const action = button.dataset.approvalAction
      if (action === "approve") {
        await api("/api/approvals/approve", {
          method: "POST",
          body: JSON.stringify({ run_id: runId, metadata: { source: "webui" } }),
        })
        showToast(`已批准 ${runId}`)
      } else {
        await api("/api/approvals/reject", {
          method: "POST",
          body: JSON.stringify({ run_id: runId, reason: "rejected from webui", metadata: { source: "webui" } }),
        })
        showToast(`已拒绝 ${runId}`)
      }
      await loadMetaAndStatus()
      await loadApprovals()
    })
  })
}

function defaultComputerDraft() {
  return {
    backend: catalogOptions("computer_backends")[0] || "host",
    read_only: false,
    allow_write: true,
    allow_exec: true,
    allow_sessions: true,
    auto_stage_attachments: true,
    network_mode: catalogOptions("computer_network_modes")[0] || "enabled",
  }
}

function createEmptyProfile() {
  return {
    agent_id: "",
    name: "",
    description: "",
    prompt_ref: state.catalog?.prompts?.[0]?.prompt_ref || "prompt/default",
    summary_model_preset_id: "",
    default_model: "",
    enabled_tools: [],
    skill_assignments: [],
    computer: defaultComputerDraft(),
  }
}

function profileDraftFromSource(profile) {
  const guessedPresetId = (() => {
    const bound = profile?.agent_id ? findAgentModelBinding(profile.agent_id) : null
    if (bound?.preset_id) return bound.preset_id
    const legacyModel = String(profile?.default_model || "").trim()
    if (!legacyModel) return ""
    const matched = (state.catalog?.model_presets || []).filter((item) => item.model === legacyModel || item.preset_id === legacyModel)
    return matched[0]?.preset_id || ""
  })()
  const base = createEmptyProfile()
  return {
    ...base,
    ...deepClone(profile || {}),
    description: String(profile?.config?.description || profile?.description || ""),
    computer: {
      ...defaultComputerDraft(),
      ...(deepClone(profile?.computer || {})),
    },
    bound_preset_id: guessedPresetId,
  }
}

function renderSelectOptions(selectId, items, selectedValue, mapper, blankLabel = "未选择") {
  const select = $(`#${selectId}`)
  if (!select) return
  const options = []
  if (blankLabel !== null) {
    options.push(`<option value="">${escapeHtml(blankLabel)}</option>`)
  }
  options.push(
    ...items.map((item) => {
      const mapped = mapper(item)
      return `<option value="${escapeHtml(mapped.value)}" ${String(selectedValue || "") === String(mapped.value) ? "selected" : ""}>${escapeHtml(mapped.label)}</option>`
    }),
  )
  select.innerHTML = options.join("")
}

function renderToolOptions(containerId, selectedTools) {
  const container = $(`#${containerId}`)
  const tools = state.catalog?.tools || []
  if (!container) return
  container.classList.add("tool-groups-grid")
  if (!tools.length) {
    container.innerHTML = emptyState("当前没有可选 tool")
    return
  }
  const computerNames = new Set(["read", "write", "ls", "grep", "exec", "bash_open", "bash_write", "bash_read", "bash_close"])
  const groups = [
    {
      title: "通用工具",
      items: tools.filter((tool) => !computerNames.has(tool.name)),
    },
    {
      title: "Computer 工具",
      items: tools.filter((tool) => computerNames.has(tool.name)),
    },
  ].filter((group) => group.items.length)

  container.innerHTML = groups
    .map(
      (group) => `
        <div class="option-group">
          <div class="option-group-header">
            <div class="option-group-title">${escapeHtml(group.title)}</div>
            <span class="badge">${escapeHtml(group.items.length)} 个</span>
          </div>
          <div class="tool-option-grid">
            ${group.items
              .map(
                (tool) => `
                  <label class="checkbox-row tool-option-row">
                    <input type="checkbox" data-tool-name="${escapeHtml(tool.name)}" ${selectedTools.includes(tool.name) ? "checked" : ""}>
                    <span class="tool-option-copy">
                      <strong>${escapeHtml(tool.name)}</strong>
                      ${tool.description ? ` <span class="hint-badge" tabindex="0" data-tooltip="${escapeHtml(tool.description)}">?</span>` : ""}
                    </span>
                  </label>
                `,
              )
              .join("")}
          </div>
        </div>
      `,
    )
    .join("")
}

function selectedToolNames(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} [data-tool-name]:checked`)).map((node) => node.dataset.toolName)
}

function syncComputerPolicyUi(prefix) {
  const note = $(`#${prefix}-computer-policy-note`)
  const policyRoot = $(`#${prefix}-computer-policy`)
  if (!note || !policyRoot) return
  const selected = new Set(selectedToolNames(`${prefix}-enabled-tools-list`))
  const computerTools = ["read", "write", "ls", "grep", "exec", "bash_open", "bash_write", "bash_read", "bash_close"].filter((name) => selected.has(name))
  const active = computerTools.length > 0
  note.textContent = active
    ? `当前启用了 ${computerTools.join(", ")}。下面这些开关会限制这些 computer 工具的真实权限。`
    : "当前没有启用 computer 工具。下面这些权限设置会保留，但暂时不会影响普通工具。"
  policyRoot.querySelectorAll("select, input").forEach((node) => {
    node.disabled = !active
    node.closest(".checkbox-row")?.classList.toggle("is-muted", !active)
  })
}

function renderSkillAssignments(containerId, assignments) {
  const container = $(`#${containerId}`)
  const skills = state.catalog?.skills || []
  if (!container) return
  const rows = (assignments || []).map((item) => {
    if (typeof item === "string") return { skill_name: item }
    return { skill_name: String(item?.skill_name || "") }
  }).filter((item) => item.skill_name)
  if (!rows.length && (
    containerId === "profile-skill-assignments-list"
    || containerId === "subagent-skill-assignments-list"
    || containerId === "session-skill-assignments-list"
  )) {
    container.innerHTML = ""
    return
  }
  container.innerHTML = rows.length
    ? rows
        .map(
          (item, index) => `
            <div class="info-card" data-skill-row="${index}">
              <div class="form-grid compact-grid">
                <label>
                  <span>Skill</span>
                  <select data-skill-field="skill_name">
                    ${skills
                      .map(
                        (skill) => `
                          <option value="${escapeHtml(skill.skill_name)}" ${skill.skill_name === item.skill_name ? "selected" : ""}>
                            ${escapeHtml(skill.display_name || skill.skill_name)}
                          </option>
                        `,
                      )
                      .join("")}
                  </select>
                </label>
              </div>
              <div class="inline-actions" style="margin-top: 12px;">
                <button class="button button-danger" type="button" data-remove-skill-row="${index}">删除 skill</button>
              </div>
            </div>
          `,
        )
        .join("")
    : emptyState("当前没有 skills")
}

function readSkillAssignments(containerId) {
  const container = $(`#${containerId}`)
  if (!container) return []
  return Array.from(container.querySelectorAll("[data-skill-row]"))
    .map((row) => {
      const skillName = row.querySelector('[data-skill-field="skill_name"]')?.value || ""
      return skillName
    })
    .filter(Boolean)
}

function appendSkillAssignment(prefix, { withComputer }) {
  const nextAssignments = readSkillAssignments(`${prefix}-skill-assignments-list`)
  const firstSkill = state.catalog?.skills?.[0]?.skill_name || ""
  nextAssignments.push(firstSkill)
  renderProfileForm(prefix, { ...readProfileForm(prefix, { withComputer }), skill_assignments: nextAssignments }, { withComputer })
}

function renderProfileForm(prefix, draft, { withComputer }) {
  $(`#${prefix}-agent-id`).value = draft.agent_id || ""
  const nameInput = $(`#${prefix}-name`)
  if (nameInput) {
    nameInput.value = draft.name || ""
  }
  const promptNode = $(`#${prefix}-prompt-ref`)
  if (promptNode && promptNode.tagName === "SELECT") {
    renderSelectOptions(`${prefix}-prompt-ref`, state.catalog?.prompts || [], draft.prompt_ref || "", (item) => ({
      value: item.prompt_ref,
      label: item.prompt_name || promptNameFromRef(item.prompt_ref),
    }), "选择 Prompt")
  } else if (promptNode) {
    promptNode.value = draft.prompt_ref || state.catalog?.prompts?.[0]?.prompt_ref || "prompt/default"
  }
  renderSelectOptions(`${prefix}-model-preset`, state.catalog?.model_presets || [], draft.bound_preset_id || "", (item) => ({
    value: item.preset_id,
    label: item.model || item.preset_id,
  }), prefix === "profile" ? "选择模型" : null)
  if ($(`#${prefix}-summary-model-preset`)) {
    renderSelectOptions(`${prefix}-summary-model-preset`, state.catalog?.model_presets || [], draft.summary_model_preset_id || "", (item) => ({
      value: item.preset_id,
      label: item.model || item.preset_id,
    }), prefix === "profile" ? "沿用主模型 / 全局 summary" : "继承主 Bot Summary")
  }
  const descriptionInput = $(`#${prefix}-description`)
  if (descriptionInput) {
    descriptionInput.value = draft.description || ""
  }

  renderToolOptions(`${prefix}-enabled-tools-list`, draft.enabled_tools || [])
  renderSkillAssignments(`${prefix}-skill-assignments-list`, draft.skill_assignments || [])
  if (prefix === "profile") {
    renderBotEventDefaults(state.botEventDefaults)
    renderBotSubagents()
    const skillSection = $("#profile-skills-section")
    if (skillSection) {
      skillSection.hidden = !(draft.skill_assignments || []).length
    }
  } else if (prefix === "subagent") {
    const skillSection = $("#subagent-skills-section")
    if (skillSection) {
      skillSection.hidden = !(draft.skill_assignments || []).length
    }
  } else if (prefix === "session") {
    const skillSection = $("#session-skills-section")
    if (skillSection) {
      skillSection.hidden = !(draft.skill_assignments || []).length
    }
  }

  if (withComputer) {
    renderSelectOptions(`${prefix}-computer-backend`, catalogOptions("computer_backends"), draft.computer?.backend || "host", (item) => ({
      value: item,
      label: item,
    }), "选择 Backend")
    renderSelectOptions(`${prefix}-computer-network-mode`, catalogOptions("computer_network_modes"), draft.computer?.network_mode || "enabled", (item) => ({
      value: item,
      label: item,
    }), "选择 Network Mode")
    $(`#${prefix}-computer-read-only`).checked = Boolean(draft.computer?.read_only)
    $(`#${prefix}-computer-allow-write`).checked = draft.computer?.allow_write !== false
    $(`#${prefix}-computer-allow-exec`).checked = draft.computer?.allow_exec !== false
    $(`#${prefix}-computer-allow-sessions`).checked = draft.computer?.allow_sessions !== false
    $(`#${prefix}-computer-auto-stage`).checked = draft.computer?.auto_stage_attachments !== false
    syncComputerPolicyUi(prefix)
  }

  document.querySelectorAll(`#${prefix}-enabled-tools-list [data-tool-name]`).forEach((node) => {
    node.addEventListener("change", () => {
      if (withComputer) {
        syncComputerPolicyUi(prefix)
      }
    })
  })

  const skillBox = $(`#${prefix}-skill-assignments-list`)
  skillBox?.querySelectorAll("[data-remove-skill-row]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextAssignments = readSkillAssignments(`${prefix}-skill-assignments-list`)
      nextAssignments.splice(Number(button.dataset.removeSkillRow), 1)
      renderSkillAssignments(`${prefix}-skill-assignments-list`, nextAssignments)
      renderProfileForm(prefix, { ...readProfileForm(prefix, { withComputer }), skill_assignments: nextAssignments }, { withComputer })
    })
  })
}

function readProfileForm(prefix, { withComputer }) {
  const currentAgentId = $(`#${prefix}-agent-id`).value.trim()
  const existing = state.profiles.find((item) => item.agent_id === currentAgentId) || {}
  const enabledTools = Array.from(document.querySelectorAll(`#${prefix}-enabled-tools-list [data-tool-name]:checked`)).map((node) => node.dataset.toolName)
  const nameInput = $(`#${prefix}-name`)
  const resolvedAgentId = (() => {
    if (currentAgentId) return currentAgentId
    if (prefix === "profile") return getBotAgentId() || "default"
    return generatedProfileId($(`#${prefix}-name`).value, "subagent")
  })()
  const payload = {
    agent_id: resolvedAgentId,
    name: nameInput ? nameInput.value.trim() : String(existing.name || state.catalog?.bot?.name || "Bot"),
    description: $(`#${prefix}-description`)?.value.trim() || "",
    prompt_ref: $(`#${prefix}-prompt-ref`)?.value || existing.prompt_ref || state.catalog?.prompts?.[0]?.prompt_ref || "prompt/default",
    summary_model_preset_id: $(`#${prefix}-summary-model-preset`)?.value || "",
    default_model: "",
    enabled_tools: enabledTools,
    skill_assignments: readSkillAssignments(`${prefix}-skill-assignments-list`),
    bound_preset_id: $(`#${prefix}-model-preset`).value,
  }
  if (withComputer) {
    payload.computer = {
      backend: $(`#${prefix}-computer-backend`).value,
      read_only: $(`#${prefix}-computer-read-only`).checked,
      allow_write: $(`#${prefix}-computer-allow-write`).checked,
      allow_exec: $(`#${prefix}-computer-allow-exec`).checked,
      allow_sessions: $(`#${prefix}-computer-allow-sessions`).checked,
      auto_stage_attachments: $(`#${prefix}-computer-auto-stage`).checked,
      network_mode: $(`#${prefix}-computer-network-mode`).value,
    }
  } else if (existing.computer) {
    payload.computer = deepClone(existing.computer)
  }
  return payload
}

async function syncAgentBinding(agentId, presetId) {
  const existing = findAgentModelBinding(agentId)
  if (!presetId) {
    if (existing) {
      await api(`/api/models/bindings/${encodeURIComponent(existing.binding_id)}`, { method: "DELETE" })
    }
    return
  }
  const bindingId = existing?.binding_id || `agent-binding:${agentId}`
  await api(`/api/models/bindings/${encodeURIComponent(bindingId)}`, {
    method: "PUT",
    body: JSON.stringify({
      target_type: "agent",
      target_id: agentId,
      preset_id: presetId,
      timeout_sec: existing?.timeout_sec ?? null,
    }),
  })
}

async function loadEffectiveModelInto(boxId, agentId) {
  const box = $(`#${boxId}`)
  if (!box) return
  if (!agentId) {
    box.innerHTML = emptyState("保存后可预览 effective model")
    return
  }
  const result = await api(`/api/models/effective/agents/${encodeURIComponent(agentId)}`).catch(() => null)
  if (!result || !result.request) {
    box.innerHTML = emptyState("当前没有命中的 Model Binding。请先给这个 agent 绑定一个 Model Preset，或配置全局默认 Binding。")
    return
  }
  box.innerHTML = `
    <div class="info-card">
      <div class="list-item-title">source</div>
      <div class="list-item-meta mono">${escapeHtml(result.source || "-")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">resolved model</div>
      <div class="list-item-meta">${escapeHtml(result.request.model || "-")} · provider=${escapeHtml(result.request.provider_id || "-")} · preset=${escapeHtml(result.request.preset_id || "-")}</div>
    </div>
  `
}

async function loadProfiles() {
  await ensureCatalog()
  const [profiles, inboundRules, eventPolicies] = await Promise.all([
    api("/api/profiles"),
    api("/api/rules/inbound"),
    api("/api/rules/event-policies"),
  ])
  state.profiles = profiles
  state.botEventDefaults = buildBotEventDefaults(inboundRules, eventPolicies)
  state.botProfileId = getBotAgentId() || state.profiles[0]?.agent_id || ""
  state.selectedProfileId = state.botProfileId
  const botProfile = getBotProfile()
  const selected = profileDraftFromSource(botProfile)
  renderProfileForm("profile", selected, { withComputer: true })
  await loadEffectiveModelInto("profile-effective-model", selected.agent_id || state.botProfileId || "")
}

async function loadSubagents() {
  await ensureCatalog()
  state.profiles = await api("/api/profiles")
  const executorIds = new Set((state.catalog?.subagent_executors || []).map((item) => item.agent_id))
  const subagents = state.profiles.filter((item) => executorIds.has(item.agent_id) && item.agent_id !== getBotAgentId() && !isManagedSessionProfile(item))
  if (!state.selectedSubagentId && subagents.length) {
    state.selectedSubagentId = subagents[0].agent_id
  }
  renderSelectableList(
    $("#subagents-list"),
    subagents,
    state.selectedSubagentId,
    (item) => item.agent_id,
    (item) => escapeHtml(item.name || item.agent_id),
    (item) => {
      const binding = findAgentModelBinding(item.agent_id)
      const description = String(item.config?.description || item.description || "").trim()
      return `${escapeHtml(description || "未填写描述")} · 模型=${escapeHtml(binding?.preset_id || "未选择")} · tools=${escapeHtml((item.enabled_tools || []).length)} · skills=${escapeHtml((item.skill_assignments || []).length)}`
    },
  )
  wireSelectableClicks($("#subagents-list"), (id) => {
    state.selectedSubagentId = id
    loadSubagents().catch(handleError)
  })
  const selected = profileDraftFromSource(subagents.find((item) => item.agent_id === state.selectedSubagentId))
  renderProfileForm("subagent", selected, { withComputer: false })
  await loadEffectiveModelInto("subagent-effective-model", selected.agent_id || "")
}

async function saveProfileLike(prefix, { withComputer, setSelected }) {
  const payload = readProfileForm(prefix, { withComputer })
  const boundPresetId = payload.bound_preset_id || ""
  delete payload.bound_preset_id
  await api(`/api/profiles/${encodeURIComponent(payload.agent_id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
  await syncAgentBinding(payload.agent_id, boundPresetId)
  await ensureCatalog(true)
  state.modelEntities.bindings = await api("/api/models/bindings")
  setSelected(payload.agent_id)
  showToast(`已保存 agent: ${payload.agent_id}`)
}

async function saveBotEventDefaults() {
  const defaults = readBotEventDefaults()
  for (const eventType of botEventTypes()) {
    const item = defaults[eventType]
    const inboundRuleId = item.inbound_rule_id || `bot-default-inbound:${eventType}`
    const eventPolicyId = item.event_policy_id || `bot-default-policy:${eventType}`
    const metadata = {
      ui_scope: "bot_default",
      event_type: eventType,
    }
    await api(`/api/rules/inbound/${encodeURIComponent(inboundRuleId)}`, {
      method: "PUT",
      body: JSON.stringify({
        run_mode: item.run_mode || "respond",
        priority: 10,
        match: {
          platform: "qq",
          event_type: eventType,
        },
        metadata,
      }),
    })
    await api(`/api/rules/event-policies/${encodeURIComponent(eventPolicyId)}`, {
      method: "PUT",
      body: JSON.stringify({
        priority: 10,
        match: {
          platform: "qq",
          event_type: eventType,
        },
        persist_event: item.persist_event !== false,
        extract_to_memory: Boolean(item.extract_to_memory),
        memory_scopes: item.memory_scopes || [],
        tags: [],
        metadata,
      }),
    })
  }
}

async function saveProfile() {
  await saveProfileLike("profile", {
    withComputer: true,
    setSelected: (id) => {
      state.selectedProfileId = id
    },
  })
  await saveBotEventDefaults()
  await Promise.all([loadProfiles(), loadSubagents()])
}

async function saveSubagent() {
  const payload = readProfileForm("subagent", { withComputer: false })
  if (!payload.name) {
    throw new Error("Subagent 名称不能为空")
  }
  if (!payload.bound_preset_id) {
    throw new Error("Subagent 必须明确选择一个模型")
  }
  await saveProfileLike("subagent", {
    withComputer: false,
    setSelected: (id) => {
      state.selectedSubagentId = id
    },
  })
  await Promise.all([loadProfiles(), loadSubagents()])
}

async function deleteProfileLike(prefix, { selectedKey }) {
  const agentId = $(`#${prefix}-agent-id`).value.trim()
  if (!agentId) return
  await api(`/api/profiles/${encodeURIComponent(agentId)}`, { method: "DELETE" })
  const existing = findAgentModelBinding(agentId)
  if (existing) {
    await api(`/api/models/bindings/${encodeURIComponent(existing.binding_id)}`, { method: "DELETE" })
  }
  state[selectedKey] = ""
  await ensureCatalog(true)
  state.modelEntities.bindings = await api("/api/models/bindings")
  showToast(`已删除 agent: ${agentId}`)
}

async function deleteProfile() {
  await deleteProfileLike("profile", { selectedKey: "selectedProfileId" })
  await Promise.all([loadProfiles(), loadSubagents()])
}

async function deleteSubagent() {
  await deleteProfileLike("subagent", { selectedKey: "selectedSubagentId" })
  await Promise.all([loadProfiles(), loadSubagents()])
}

function isSimpleSessionRule(item) {
  const match = item?.match || {}
  return Boolean(match.channel_scope) && !match.actor_id
}

function humanizeSessionScope(channelScope) {
  const parsed = scopeToUiValue(channelScope)
  if (parsed.scope_type === "private") return `QQ 私聊 ${parsed.scope_value || ""}`.trim()
  if (parsed.scope_type === "group") return `QQ 群 ${parsed.scope_value || ""}`.trim()
  return parsed.channel_scope || "未命名会话"
}

function buildSessionConfigs(bindingRules, inboundRules, eventPolicies) {
  const grouped = new Map()
  const profilesById = new Map(state.profiles.map((item) => [item.agent_id, item]))
  const botAgentId = getBotAgentId()
  const botDraft = profileDraftFromSource(getBotProfile())
  const botEventDefaults = state.botEventDefaults || defaultBotEventDefaults()
  const ensureItem = (channelScope) => {
    if (!grouped.has(channelScope)) {
      const parsed = scopeToUiValue(channelScope)
      grouped.set(channelScope, {
        session_key: channelScope,
        session_name: "",
        scope_type: parsed.scope_type === "any" ? "custom" : parsed.scope_type,
        scope_value: parsed.scope_value || parsed.channel_scope,
        agent_id: botAgentId,
        managed_agent_id: "",
        ai_override_enabled: false,
        prompt_ref: botDraft.prompt_ref || "",
        bound_preset_id: botDraft.bound_preset_id || "",
        enabled_tools: [...(botDraft.enabled_tools || [])],
        skill_assignments: deepClone(botDraft.skill_assignments || []),
        response_modes: Object.fromEntries(sessionEventTypes().map((eventType) => [eventType, botEventDefaults[eventType]?.run_mode || "respond"])),
        persist_event: botEventDefaults.message?.persist_event !== false,
        extract_to_memory: Boolean(botEventDefaults.message?.extract_to_memory),
        memory_scopes: (botEventDefaults.message?.memory_scopes || []).length ? [...botEventDefaults.message.memory_scopes] : ["relationship", "user", "channel", "global"],
        tags: [],
        binding_rule_id: "",
        inbound_rule_ids: {},
        event_policy_id: "",
      })
    }
    return grouped.get(channelScope)
  }

  for (const rule of bindingRules.filter(isSimpleSessionRule)) {
    const item = ensureItem(rule.match.channel_scope)
    item.managed_agent_id = String(rule.metadata?.managed_agent_id || "")
    item.ai_override_enabled = Boolean(rule.metadata?.ai_override_enabled || item.managed_agent_id)
    item.agent_id = botAgentId
    item.binding_rule_id = rule.rule_id || ""
    item.session_name ||= rule.metadata?.display_name || ""
  }
  for (const rule of inboundRules.filter(isSimpleSessionRule)) {
    const item = ensureItem(rule.match.channel_scope)
    const eventType = String(rule.match?.event_type || "message")
    item.response_modes[eventType] = rule.run_mode || "respond"
    item.inbound_rule_ids[eventType] = rule.rule_id || ""
    item.session_name ||= rule.metadata?.display_name || ""
  }
  for (const policy of eventPolicies.filter(isSimpleSessionRule)) {
    const item = ensureItem(policy.match.channel_scope)
    item.persist_event = policy.persist_event !== false
    item.extract_to_memory = Boolean(policy.extract_to_memory)
    item.memory_scopes = Array.isArray(policy.memory_scopes) && policy.memory_scopes.length
      ? [...policy.memory_scopes]
      : ["relationship", "user", "channel", "global"]
    item.tags = Array.isArray(policy.tags) ? [...policy.tags] : []
    item.event_policy_id = policy.policy_id || ""
    item.session_name ||= policy.metadata?.display_name || ""
  }

  return Array.from(grouped.values())
    .map((item) => ({
      ...item,
      ...(profileDraftFromSource(
        item.ai_override_enabled
          ? profilesById.get(item.managed_agent_id) || getBotProfile()
          : profilesById.get(item.agent_id) || getBotProfile(),
      )),
      session_name: item.session_name || humanizeSessionScope(item.session_key),
    }))
    .sort((left, right) => left.session_name.localeCompare(right.session_name, "zh-CN"))
}

function createEmptySessionConfig() {
  const botDraft = profileDraftFromSource(getBotProfile())
  const botEventDefaults = state.botEventDefaults || defaultBotEventDefaults()
  return {
    session_key: "",
    session_name: "",
    scope_type: "private",
    scope_value: "",
    agent_id: getBotAgentId(),
    managed_agent_id: "",
    ai_override_enabled: false,
    prompt_ref: botDraft.prompt_ref || "",
    bound_preset_id: botDraft.bound_preset_id || "",
    summary_model_preset_id: botDraft.summary_model_preset_id || "",
    enabled_tools: [...(botDraft.enabled_tools || [])],
    skill_assignments: deepClone(botDraft.skill_assignments || []),
    response_modes: Object.fromEntries(sessionEventTypes().map((eventType) => [eventType, botEventDefaults[eventType]?.run_mode || "respond"])),
    persist_event: botEventDefaults.message?.persist_event !== false,
    extract_to_memory: Boolean(botEventDefaults.message?.extract_to_memory),
    memory_scopes: (botEventDefaults.message?.memory_scopes || []).length ? [...botEventDefaults.message.memory_scopes] : ["relationship", "user", "channel", "global"],
    tags: [],
    binding_rule_id: "",
    inbound_rule_ids: {},
    event_policy_id: "",
  }
}

function renderMemoryScopeOptions(selectedScopes) {
  const container = $("#session-memory-scopes")
  const scopes = ["relationship", "user", "channel", "global"]
  if (!container) return
  container.innerHTML = renderMemoryScopePickerMarkup("session-memory-scopes", selectedScopes, scopes)
}

function memoryScopeLabel(scope) {
  if (scope === "relationship") return "relationship"
  if (scope === "user") return "user"
  if (scope === "channel") return "channel"
  if (scope === "global") return "global"
  return scope
}

function memoryScopeSummary(selectedScopes) {
  if (!selectedScopes.length) return "未选择"
  return selectedScopes.map((scope) => memoryScopeLabel(scope)).join(" / ")
}

function renderMemoryScopePickerMarkup(pickerKey, selectedScopes, scopes = BOT_MEMORY_SCOPES) {
  const summary = memoryScopeSummary(selectedScopes || [])
  const options = scopes
    .map((scope) => `
      <label class="memory-scope-option">
        <input
          type="checkbox"
          data-memory-scope-option
          data-memory-scope-picker="${escapeHtml(pickerKey)}"
          value="${escapeHtml(scope)}"
          ${(selectedScopes || []).includes(scope) ? "checked" : ""}
        >
        <span>${escapeHtml(memoryScopeLabel(scope))}</span>
      </label>
    `)
    .join("")
  return `
    <details class="memory-scope-picker" data-memory-scope-picker="${escapeHtml(pickerKey)}">
      <summary class="memory-scope-picker-summary">
        <span class="memory-scope-picker-label">点击选择</span>
        <span class="memory-scope-picker-value" data-memory-scope-summary>${escapeHtml(summary)}</span>
      </summary>
      <div class="memory-scope-picker-menu">
        ${options}
      </div>
    </details>
  `
}

function updateMemoryScopePickerSummary(pickerRoot) {
  if (!pickerRoot) return
  const selectedScopes = Array.from(pickerRoot.querySelectorAll('[data-memory-scope-option]:checked')).map((node) => node.value)
  const summaryNode = pickerRoot.querySelector("[data-memory-scope-summary]")
  if (summaryNode) summaryNode.textContent = memoryScopeSummary(selectedScopes)
}

function bindMemoryScopePicker(container, onChange = null) {
  const picker = container?.querySelector?.(".memory-scope-picker")
  if (!picker) return
  picker.querySelectorAll("[data-memory-scope-option]").forEach((node) => {
    node.addEventListener("change", () => {
      updateMemoryScopePickerSummary(picker)
      if (typeof onChange === "function") onChange()
    })
  })
  updateMemoryScopePickerSummary(picker)
}

function readMemoryScopePicker(selector) {
  return Array.from(document.querySelectorAll(`${selector} [data-memory-scope-option]:checked`)).map((node) => node.value)
}

function renderBotEventDefaults(defaults) {
  const container = $("#profile-event-defaults")
  if (!container) return
  const normalized = defaults || defaultBotEventDefaults()
  const runModes = catalogOptions("run_modes").length ? catalogOptions("run_modes") : ["respond", "record_only", "silent_drop"]
  container.innerHTML = botEventTypes()
    .map((eventType) => {
      const item = normalized[eventType] || defaultBotEventDefaults()[eventType]
      const memoryPickerKey = `bot-event-${eventType}`
      return `
        <div class="info-card event-default-row">
          <div class="event-default-header">
            <div class="event-default-title">${escapeHtml(eventTypeLabel(eventType))}</div>
            <div class="event-default-meta">${escapeHtml(eventType)}</div>
          </div>
          <div class="form-grid compact-grid">
            <label>
              <span>默认行为</span>
              <select data-bot-event-field="run_mode" data-bot-event-type="${escapeHtml(eventType)}">
                ${runModes
                  .map((mode) => `
                    <option value="${escapeHtml(mode)}" ${item.run_mode === mode ? "selected" : ""}>${escapeHtml(responseStrategyLabel(mode))}</option>
                  `)
                  .join("")}
              </select>
            </label>
            <label class="checkbox-row"><input type="checkbox" data-bot-event-field="persist_event" data-bot-event-type="${escapeHtml(eventType)}" ${item.persist_event !== false ? "checked" : ""}> <span>保存事件</span></label>
            <label class="checkbox-row"><input type="checkbox" data-bot-event-field="extract_to_memory" data-bot-event-type="${escapeHtml(eventType)}" ${item.extract_to_memory ? "checked" : ""}> <span>提取到 memory</span></label>
            <label class="wide">
              <span>默认 Memory Scopes</span>
              <div data-bot-memory-scopes data-bot-event-type="${escapeHtml(eventType)}">${renderMemoryScopePickerMarkup(memoryPickerKey, item.memory_scopes || [], BOT_MEMORY_SCOPES)}</div>
            </label>
          </div>
        </div>
      `
    })
    .join("")
  container.querySelectorAll("[data-bot-memory-scopes]").forEach((node) => bindMemoryScopePicker(node))
}

function renderBotSubagents() {
  const container = $("#profile-subagents-list")
  if (!container) return
  const executors = state.catalog?.subagent_executors || []
  const profiles = new Map((state.profiles || []).map((item) => [item.agent_id, item]))
  const botAgentId = getBotAgentId()
  const visible = executors.filter((item) => item.agent_id !== botAgentId)
  if (!visible.length) {
    container.innerHTML = emptyState("当前没有可用的 subagents")
    return
  }
  container.innerHTML = visible
    .map((item) => {
      const profile = profiles.get(item.agent_id)
      const draft = profileDraftFromSource(profile || {})
      const binding = findAgentModelBinding(item.agent_id)
      return `
        <div class="info-card">
          <div class="list-item-title">${escapeHtml(profile?.name || item.agent_id)}</div>
          <div class="list-item-meta">${escapeHtml(draft.description || "未填写描述")} · 模型=${escapeHtml(binding?.preset_id || "未选择")} · tools=${escapeHtml((profile?.enabled_tools || []).length)} · skills=${escapeHtml((profile?.skill_assignments || []).length)}</div>
        </div>
      `
    })
    .join("")
}

function readBotEventDefaults() {
  const defaults = defaultBotEventDefaults()
  for (const eventType of botEventTypes()) {
    defaults[eventType].run_mode = document.querySelector(`[data-bot-event-field="run_mode"][data-bot-event-type="${eventType}"]`)?.value || "respond"
    defaults[eventType].persist_event = Boolean(document.querySelector(`[data-bot-event-field="persist_event"][data-bot-event-type="${eventType}"]`)?.checked)
    defaults[eventType].extract_to_memory = Boolean(document.querySelector(`[data-bot-event-field="extract_to_memory"][data-bot-event-type="${eventType}"]`)?.checked)
    defaults[eventType].memory_scopes = readMemoryScopePicker(`[data-bot-memory-scopes][data-bot-event-type="${eventType}"]`)
    defaults[eventType].inbound_rule_id = state.botEventDefaults?.[eventType]?.inbound_rule_id || ""
    defaults[eventType].event_policy_id = state.botEventDefaults?.[eventType]?.event_policy_id || ""
  }
  return defaults
}

function setSessionAiOverrideEnabled(enabled) {
  const active = Boolean(enabled)
  const panel = $("#session-ai-override-panel")
  panel?.classList.toggle("is-disabled", !active)
  const ids = [
    "session-model-preset",
    "session-summary-model-preset",
    "session-prompt-ref",
    "add-session-skill-btn",
  ]
  ids.forEach((id) => {
    const node = $(`#${id}`)
    if (node) node.disabled = !active
  })
  document.querySelectorAll("#session-enabled-tools-list input, #session-skill-assignments-list input, #session-skill-assignments-list select").forEach((node) => {
    node.disabled = !active
  })
}

async function loadSessionModelPreview(agentId) {
  const box = $("#session-model-preview")
  if (!agentId) {
    box.innerHTML = emptyState("当前会话没有可预览的模型配置")
    return
  }
  await loadEffectiveModelInto("session-model-preview", agentId)
}

function responseStrategyLabel(value) {
  if (value === "record_only") return "只记录，不回复"
  if (value === "silent_drop") return "静默忽略"
  return "正常回复"
}

function sessionResponseSummary(responseModes, compact = false) {
  const normalized = normalizeSessionResponseModes(responseModes)
  const entries = sessionEventTypes().map((eventType) => ({
    eventType,
    mode: normalized[eventType] || "respond",
  }))
  const visible = compact ? entries.filter((item) => item.mode !== "respond") : entries
  if (!visible.length) {
    return compact ? "全部正常回复" : entries.map((item) => `${sessionEventTypeLabel(item.eventType)}=${responseStrategyLabel(item.mode)}`).join(" · ")
  }
  return visible.map((item) => `${sessionEventTypeLabel(item.eventType)}=${responseStrategyLabel(item.mode)}`).join(" · ")
}

function renderSessionResponseStrategies(responseModes) {
  const container = $("#session-response-strategies")
  if (!container) return
  const normalized = normalizeSessionResponseModes(responseModes)
  const runModes = catalogOptions("run_modes").length ? catalogOptions("run_modes") : ["respond", "record_only", "silent_drop"]
  container.innerHTML = sessionEventTypes()
    .map((eventType) => `
      <div class="info-card">
        <div class="form-grid compact-grid">
          <label class="wide">
            <span>${escapeHtml(sessionEventTypeLabel(eventType))}</span>
            <select data-session-response-event="${escapeHtml(eventType)}">
              ${runModes
                .map((mode) => `
                  <option value="${escapeHtml(mode)}" ${normalized[eventType] === mode ? "selected" : ""}>${escapeHtml(responseStrategyLabel(mode))}</option>
                `)
                .join("")}
            </select>
          </label>
        </div>
      </div>
    `)
    .join("")
}

function renderSessionPreview(session) {
  const scope = uiScopeToChannelScope(session.scope_type, session.scope_value) || "未设置"
  const model = (state.catalog?.model_presets || []).find((item) => item.preset_id === session.bound_preset_id)?.model || "继承主 Bot"
  const summaryModel = (state.catalog?.model_presets || []).find((item) => item.preset_id === session.summary_model_preset_id)?.model || "跟随当前模型"
  const tags = (session.tags || []).length ? session.tags.join(", ") : "无"
  const scopes = (session.memory_scopes || []).length ? session.memory_scopes.join(", ") : "无"
  return `
    <div class="info-card">
      <div class="list-item-title">会话入口</div>
      <div class="list-item-meta">${escapeHtml(session.session_name || "未命名会话")} · ${escapeHtml(scope)}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">AI 配置</div>
      <div class="list-item-meta">${escapeHtml(session.ai_override_enabled ? "会话级覆盖已启用" : "继承主 Bot")} · Prompt=${escapeHtml(promptNameFromRef(session.prompt_ref || ""))} · 模型=${escapeHtml(model)} · Summary=${escapeHtml(summaryModel)} · tools=${escapeHtml((session.enabled_tools || []).length)} · skills=${escapeHtml((session.skill_assignments || []).length)}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">响应策略</div>
      <div class="list-item-meta">${escapeHtml(sessionResponseSummary(session.response_modes || {}, false))}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">记录与 Memory</div>
      <div class="list-item-meta">保存 event=${escapeHtml(session.persist_event !== false ? "是" : "否")} · 提取 memory=${escapeHtml(session.extract_to_memory ? "是" : "否")} · scopes=${escapeHtml(scopes)} · tags=${escapeHtml(tags)}</div>
    </div>
  `
}

function fillSessionForm(session) {
  $("#session-name").value = session.session_name || ""
  $("#session-scope-type").value = session.scope_type || "private"
  $("#session-scope-value").value = session.scope_value || ""
  $("#session-binding-rule-id").value = session.binding_rule_id || ""
  $("#session-inbound-rule-id").value = JSON.stringify(session.inbound_rule_ids || {})
  $("#session-event-policy-id").value = session.event_policy_id || ""
  $("#session-managed-agent-id").value = session.managed_agent_id || ""
  $("#session-ai-override-enabled").checked = Boolean(session.ai_override_enabled)
  renderSelectOptions("session-model-preset", state.catalog?.model_presets || [], session.bound_preset_id || "", (item) => ({
    value: item.preset_id,
    label: item.model || item.preset_id,
  }), "继承主 Bot 模型")
  renderSelectOptions("session-summary-model-preset", state.catalog?.model_presets || [], session.summary_model_preset_id || "", (item) => ({
    value: item.preset_id,
    label: item.model || item.preset_id,
  }), "继承主 Bot Summary")
  renderSelectOptions("session-prompt-ref", state.catalog?.prompts || [], session.prompt_ref || "", (item) => ({
    value: item.prompt_ref,
    label: item.prompt_name || promptNameFromRef(item.prompt_ref),
  }), "继承主 Bot Prompt")
  renderToolOptions("session-enabled-tools-list", session.enabled_tools || [])
  renderSkillAssignments("session-skill-assignments-list", session.skill_assignments || [])
  renderSessionResponseStrategies(session.response_modes || {})
  $("#session-persist-event").checked = session.persist_event !== false
  $("#session-extract-memory").checked = Boolean(session.extract_to_memory)
  $("#session-tags").value = (session.tags || []).join(", ")
  renderMemoryScopeOptions(session.memory_scopes || ["relationship", "user", "channel", "global"])
  document.querySelectorAll("#session-skill-assignments-list [data-remove-skill-row]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextAssignments = readSkillAssignments("session-skill-assignments-list")
      nextAssignments.splice(Number(button.dataset.removeSkillRow), 1)
      renderSkillAssignments("session-skill-assignments-list", nextAssignments)
      fillSessionForm({ ...readSessionForm(), skill_assignments: nextAssignments })
    })
  })
  bindMemoryScopePicker($("#session-memory-scopes"), () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  document.querySelectorAll("#session-response-strategies [data-session-response-event]").forEach((node) => {
    node.addEventListener("change", () => {
      $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
    })
  })
  setSessionAiOverrideEnabled(session.ai_override_enabled)
  $("#session-preview").innerHTML = renderSessionPreview(session)
  loadSessionModelPreview(session.agent_id || "").catch(handleError)
}

function readSessionForm() {
  return {
    session_name: $("#session-name").value.trim(),
    scope_type: $("#session-scope-type").value,
    scope_value: $("#session-scope-value").value.trim(),
    agent_id: getBotAgentId(),
    managed_agent_id: $("#session-managed-agent-id").value,
    ai_override_enabled: $("#session-ai-override-enabled").checked,
    prompt_ref: $("#session-prompt-ref").value || profileDraftFromSource(getBotProfile()).prompt_ref,
    bound_preset_id: $("#session-model-preset").value,
    summary_model_preset_id: $("#session-summary-model-preset").value,
    enabled_tools: Array.from(document.querySelectorAll("#session-enabled-tools-list [data-tool-name]:checked")).map((node) => node.dataset.toolName),
    skill_assignments: readSkillAssignments("session-skill-assignments-list"),
    response_modes: normalizeSessionResponseModes(
      Object.fromEntries(
        Array.from(document.querySelectorAll("#session-response-strategies [data-session-response-event]"))
          .map((node) => [node.dataset.sessionResponseEvent, node.value || "respond"]),
      ),
    ),
    persist_event: $("#session-persist-event").checked,
    extract_to_memory: $("#session-extract-memory").checked,
    memory_scopes: readMemoryScopePicker("#session-memory-scopes"),
    tags: $("#session-tags").value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    binding_rule_id: $("#session-binding-rule-id").value,
    inbound_rule_ids: parseSessionInboundRuleIds($("#session-inbound-rule-id").value),
    event_policy_id: $("#session-event-policy-id").value,
  }
}

async function loadSessions() {
  await ensureCatalog()
  state.profiles = await api("/api/profiles")
  state.botProfileId = getBotAgentId() || state.profiles[0]?.agent_id || ""
  const [bindingRules, inboundRules, eventPolicies] = await Promise.all([
    api("/api/rules/bindings"),
    api("/api/rules/inbound"),
    api("/api/rules/event-policies"),
  ])
  state.botEventDefaults = buildBotEventDefaults(inboundRules, eventPolicies)
  state.sessionConfigs = buildSessionConfigs(bindingRules, inboundRules, eventPolicies)
  if (!state.selectedSessionKey && state.sessionConfigs.length) {
    state.selectedSessionKey = state.sessionConfigs[0].session_key
  }
  renderSelectableList(
    $("#sessions-list"),
    state.sessionConfigs,
    state.selectedSessionKey,
    (item) => item.session_key,
    (item) => escapeHtml(item.session_name || humanizeSessionScope(item.session_key)),
    (item) => `${escapeHtml(humanizeSessionScope(item.session_key))} · ${escapeHtml(sessionResponseSummary(item.response_modes || {}, true))}`,
  )
  wireSelectableClicks($("#sessions-list"), (id) => {
    state.selectedSessionKey = id
    loadSessions().catch(handleError)
  })
  const selected = state.sessionConfigs.find((item) => item.session_key === state.selectedSessionKey) || createEmptySessionConfig()
  fillSessionForm(selected)
}

async function deleteManagedSessionProfile(agentId) {
  const normalized = String(agentId || "").trim()
  if (!normalized) return
  const existingBinding = findAgentModelBinding(normalized)
  if (existingBinding) {
    await api(`/api/models/bindings/${encodeURIComponent(existingBinding.binding_id)}`, { method: "DELETE" }).catch(() => null)
  }
  await api(`/api/profiles/${encodeURIComponent(normalized)}`, { method: "DELETE" }).catch(() => null)
}

async function saveSessionConfig() {
  const payload = readSessionForm()
  const channelScope = uiScopeToChannelScope(payload.scope_type, payload.scope_value)
  if (!channelScope) {
    throw new Error("会话对象 ID 不能为空")
  }
  const displayName = payload.session_name || humanizeSessionScope(channelScope)
  const botProfile = getBotProfile()
  const botAgentId = getBotAgentId()
  if (!botProfile || !botAgentId) {
    throw new Error("找不到主 Bot 配置")
  }
  const baseProfile = botProfile

  let routeAgentId = botAgentId
  let managedAgentId = payload.managed_agent_id || ""
  if (payload.ai_override_enabled) {
    managedAgentId ||= managedSessionProfileId(channelScope)
    await api(`/api/profiles/${encodeURIComponent(managedAgentId)}`, {
      method: "PUT",
      body: JSON.stringify({
        agent_id: managedAgentId,
        name: `${displayName} Session Override`,
        prompt_ref: payload.prompt_ref,
        summary_model_preset_id: payload.summary_model_preset_id,
        enabled_tools: payload.enabled_tools,
        skill_assignments: payload.skill_assignments,
        computer: deepClone(baseProfile.computer || botProfile?.computer || {}),
        metadata: {
          managed_by: "webui_session",
          session_key: channelScope,
          base_agent_id: botAgentId,
        },
      }),
    })
    await syncAgentBinding(managedAgentId, payload.bound_preset_id)
    routeAgentId = managedAgentId
  } else if (managedAgentId) {
    await deleteManagedSessionProfile(managedAgentId)
    managedAgentId = ""
  }

  const metadata = {
    display_name: displayName,
    ui_scope: "session",
    managed_agent_id: managedAgentId,
    ai_override_enabled: Boolean(payload.ai_override_enabled),
  }

  const bindingRuleId = payload.binding_rule_id || generateInternalId("session-binding")
  const eventPolicyId = payload.event_policy_id || generateInternalId("session-policy")
  const sessionMatch = {
    channel_scope: channelScope,
  }

  await api(`/api/rules/bindings/${encodeURIComponent(bindingRuleId)}`, {
    method: "PUT",
    body: JSON.stringify({
      agent_id: routeAgentId,
      priority: 100,
      match: sessionMatch,
      metadata,
    }),
  })
  await api(`/api/rules/event-policies/${encodeURIComponent(eventPolicyId)}`, {
    method: "PUT",
    body: JSON.stringify({
      priority: 100,
      match: sessionMatch,
      persist_event: payload.persist_event,
      extract_to_memory: payload.extract_to_memory,
      memory_scopes: payload.memory_scopes,
      tags: payload.tags,
      metadata,
    }),
  })
  const inboundRuleIds = payload.inbound_rule_ids || {}
  const responseModes = normalizeSessionResponseModes(payload.response_modes || {})
  for (const eventType of sessionEventTypes()) {
    const inboundRuleId = inboundRuleIds[eventType] || generateInternalId(`session-inbound:${eventType}`)
    await api(`/api/rules/inbound/${encodeURIComponent(inboundRuleId)}`, {
      method: "PUT",
      body: JSON.stringify({
        run_mode: responseModes[eventType] || "respond",
        priority: 100,
        match: {
          channel_scope: channelScope,
          event_type: eventType,
        },
        metadata: {
          ...metadata,
          event_type,
        },
      }),
    })
  }
  for (const [eventType, inboundRuleId] of Object.entries(inboundRuleIds)) {
    if (sessionEventTypes().includes(eventType) || !inboundRuleId) continue
    await api(`/api/rules/inbound/${encodeURIComponent(inboundRuleId)}`, { method: "DELETE" }).catch(() => null)
  }
  state.selectedSessionKey = channelScope
  showToast(`已保存会话配置: ${displayName}`)
  await loadSessions()
}

async function deleteSessionConfig() {
  const bindingRuleId = $("#session-binding-rule-id").value
  const inboundRuleIds = parseSessionInboundRuleIds($("#session-inbound-rule-id").value)
  const eventPolicyId = $("#session-event-policy-id").value
  const managedAgentId = $("#session-managed-agent-id").value
  if (!bindingRuleId && !Object.keys(inboundRuleIds).length && !eventPolicyId) {
    return
  }
  if (bindingRuleId) {
    await api(`/api/rules/bindings/${encodeURIComponent(bindingRuleId)}`, { method: "DELETE" })
  }
  for (const inboundRuleId of Object.values(inboundRuleIds)) {
    if (!inboundRuleId) continue
    await api(`/api/rules/inbound/${encodeURIComponent(inboundRuleId)}`, { method: "DELETE" })
  }
  if (eventPolicyId) {
    await api(`/api/rules/event-policies/${encodeURIComponent(eventPolicyId)}`, { method: "DELETE" })
  }
  if (managedAgentId) {
    await deleteManagedSessionProfile(managedAgentId)
  }
  state.selectedSessionKey = ""
  showToast("已删除会话配置")
  await loadSessions()
}

async function loadPrompts() {
  state.prompts = await api("/api/prompts")
  if (!state.selectedPromptRef && state.prompts.length) {
    state.selectedPromptRef = state.prompts[0].prompt_ref
  }
  renderSelectableList(
    $("#prompts-list"),
    state.prompts,
    state.selectedPromptRef,
    (item) => item.prompt_ref,
    (item) => escapeHtml(item.prompt_name || promptNameFromRef(item.prompt_ref)),
    (item) => `${escapeHtml(previewText(item.content || ""))} · source=${escapeHtml(item.source || "-")}`,
  )
  wireSelectableClicks($("#prompts-list"), (id) => {
    state.selectedPromptRef = id
    loadPrompts().catch(handleError)
  })
  const selected = state.prompts.find((item) => item.prompt_ref === state.selectedPromptRef)
  $("#prompt-name-input").value = selected ? promptNameFromRef(selected.prompt_ref) : "default"
  $("#prompt-content-input").value = selected?.content || ""
}

async function savePrompt() {
  const promptRef = promptRefFromName($("#prompt-name-input").value)
  const previousPromptRef = String(state.selectedPromptRef || "").trim()
  if (!promptRef) {
    throw new Error("Prompt 名称不能为空")
  }
  if (previousPromptRef && previousPromptRef !== promptRef) {
    const exists = state.prompts.some((item) => item.prompt_ref === promptRef)
    if (exists) {
      throw new Error("目标 Prompt 名称已存在，请换一个名字")
    }
  }
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, {
    method: "PUT",
    body: JSON.stringify({ content: $("#prompt-content-input").value }),
  })
  if (previousPromptRef && previousPromptRef !== promptRef) {
    await api(`/api/prompt?prompt_ref=${encodeURIComponent(previousPromptRef)}`, { method: "DELETE" })
  }
  state.selectedPromptRef = promptRef
  await ensureCatalog(true)
  showToast(previousPromptRef && previousPromptRef !== promptRef ? `已重命名 Prompt: ${promptNameFromRef(previousPromptRef)} -> ${promptNameFromRef(promptRef)}` : `已保存 Prompt: ${promptNameFromRef(promptRef)}`)
  await loadPrompts()
}

async function deletePrompt() {
  const promptRef = promptRefFromName($("#prompt-name-input").value)
  if (!promptRef) return
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, { method: "DELETE" })
  state.selectedPromptRef = ""
  await ensureCatalog(true)
  showToast(`已删除 prompt: ${promptRef}`)
  await loadPrompts()
}

function normalizeProviderEntity(item) {
  const config = item?.config || {}
  return {
    kind: item?.kind || "openai_compatible",
    base_url: config.base_url || "",
    api_key: config.api_key || "",
    anthropic_version: config.anthropic_version || "",
    api_version: config.api_version || "",
    project_id: config.project_id || "",
    location: config.location || "",
    use_vertex_ai: Boolean(config.use_vertex_ai),
    default_headers: config.default_headers || {},
  }
}

function emptyModelEntity(kind) {
  if (kind === "providers") {
    return normalizeProviderEntity(null)
  }
  if (kind === "presets") {
    return {
      provider_id: "",
      model: "",
      context_window: 128000,
      supports_tools: true,
      supports_vision: false,
      max_output_tokens: null,
      model_params: {},
    }
  }
  return {
    target_type: "agent",
    target_id: "",
    preset_id: "",
    preset_ids: [],
    timeout_sec: null,
  }
}

function modelListMeta(kind, item) {
  if (kind === "providers") {
    const config = item.config || {}
    return `kind=${escapeHtml(item.kind || "-")} · API Key=${escapeHtml(config.api_key ? "已填写" : (config.api_key_env ? "来自运行环境" : "未设置"))}`
  }
  if (kind === "presets") {
    return `provider=${escapeHtml(item.provider_id || "-")} · model=${escapeHtml(item.model || "-")}`
  }
  if (item.target_type === "system") {
    return `${escapeHtml(item.target_type)}:${escapeHtml(item.target_id)} -> [${escapeHtml((item.preset_ids || []).join(", "))}]`
  }
  return `${escapeHtml(item.target_type)}:${escapeHtml(item.target_id)} -> ${escapeHtml(item.preset_id || "-")}`
}

function dynamicFieldOptions(scope, field, data) {
  if (scope === "model") {
    if (field.key === "provider_id") {
      return (state.catalog?.model_providers || []).map((item) => ({
        value: item.provider_id,
        label: `${item.provider_id} · ${item.kind}`,
      }))
    }
    if (field.key === "target_id") {
      const targetType = data.target_type || "agent"
      if (targetType === "global") return [{ value: "default", label: "default" }]
      if (targetType === "system") return [{ value: "compactor_summary", label: "compactor_summary" }]
      return (state.catalog?.agents || []).map((item) => ({
        value: item.agent_id,
        label: `${item.name || item.agent_id} (${item.agent_id})`,
      }))
    }
    if (field.key === "preset_id" || field.key === "preset_ids") {
      return (state.catalog?.model_presets || []).map((item) => ({
        value: item.preset_id,
        label: `${item.preset_id} · ${item.model}`,
      }))
    }
  }
  if (scope === "routing") {
    if (field.key === "agent_id") {
      return (state.catalog?.agents || []).map((item) => ({
        value: item.agent_id,
        label: `${item.name || item.agent_id} (${item.agent_id})`,
      }))
    }
    if (field.key === "match.platform") {
      return [{ value: "qq", label: "qq" }]
    }
    if (field.key === "match.event_type") {
      return catalogOptions("event_types").map((item) => ({ value: item, label: item }))
    }
    if (field.key === "match.message_subtype") {
      return catalogOptions("message_subtypes").map((item) => ({ value: item, label: item }))
    }
    if (field.key === "match.notice_type") {
      return catalogOptions("notice_types").map((item) => ({ value: item, label: item }))
    }
    if (field.key === "match.notice_subtype") {
      return catalogOptions("notice_subtypes").map((item) => ({ value: item, label: item }))
    }
  }
  return []
}

function renderStructuredForm(container, fields, data, scope) {
  const visibleFields = fields.filter((field) => {
    if (!field.visibleKinds) return true
    const activeKind = String(data?.kind || "")
    return field.visibleKinds.includes(activeKind)
  })
  container.innerHTML = visibleFields
    .map((field) => {
      const value = getByPath(data, field.key)
      let control = ""
      if (field.type === "select") {
        control = `
          <select data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}">
            ${field.options
              .map(
                (option) => `
                  <option value="${escapeHtml(option.value)}" ${String(value ?? "") === option.value ? "selected" : ""}>
                    ${escapeHtml(option.label)}
                  </option>
                `,
              )
              .join("")}
          </select>
        `
      } else if (field.type === "select-free") {
        const options = dynamicFieldOptions(scope, field, data)
        const normalized = String(value ?? "")
        const hasCurrent = normalized && !options.some((item) => String(item.value) === normalized)
        control = `
          <select data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}">
            <option value="">未设置</option>
            ${options
              .map(
                (option) => `
                  <option value="${escapeHtml(option.value)}" ${String(option.value) === normalized ? "selected" : ""}>
                    ${escapeHtml(option.label)}
                  </option>
                `,
              )
              .join("")}
            ${hasCurrent ? `<option value="${escapeHtml(normalized)}" selected>${escapeHtml(normalized)}</option>` : ""}
          </select>
        `
      } else if (field.type === "boolean") {
        control = `
          <select data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}">
            <option value="true" ${value === true ? "selected" : ""}>true</option>
            <option value="false" ${value === false ? "selected" : ""}>false</option>
          </select>
        `
      } else if (field.type === "password") {
        control = `<input type="password" data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" value="" placeholder="留空表示保留已有 secret">`
      } else if (field.type === "number") {
        control = `<input type="number" data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" value="${value == null ? "" : escapeHtml(value)}">`
      } else if (field.type === "readonly-json") {
        control = `<pre class="code-block">${escapeHtml(pretty(value ?? {}))}</pre>`
      } else if (field.type === "scope") {
        const scopeValue = scopeToUiValue(value)
        control = `
          <div class="form-grid compact-grid">
            <label>
              <span>会话类型</span>
              <select data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" data-scope-part="type">
                <option value="any" ${scopeValue.scope_type === "any" ? "selected" : ""}>任意会话</option>
                <option value="private" ${scopeValue.scope_type === "private" ? "selected" : ""}>QQ 私聊</option>
                <option value="group" ${scopeValue.scope_type === "group" ? "selected" : ""}>QQ 群聊</option>
                <option value="custom" ${scopeValue.scope_type === "custom" ? "selected" : ""}>自定义 channel_scope</option>
              </select>
            </label>
            <label>
              <span>目标值</span>
              <input type="text" data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" data-scope-part="value" value="${escapeHtml(scopeValue.scope_value)}" placeholder="用户 ID / 群 ID / 自定义 scope">
            </label>
          </div>
        `
      } else if (field.type === "list") {
        const joined = Array.isArray(value) ? value.join(", ") : ""
        control = `<input type="text" data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" value="${escapeHtml(joined)}">`
      } else {
        control = `<input type="text" data-form-scope="${scope}" data-field-key="${escapeHtml(field.key)}" value="${escapeHtml(value ?? "")}">`
      }
      const wide = field.type === "readonly-json" || field.type === "scope" ? "wide" : ""
      return `
        <label class="${wide}">
          <span>${escapeHtml(field.label)}${field.help ? ` <span class="hint-badge" tabindex="0" data-tooltip="${escapeHtml(field.help)}">?</span>` : ""}</span>
          ${control}
        </label>
      `
    })
    .join("")
}

function getByPath(source, path) {
  return String(path)
    .split(".")
    .reduce((current, key) => (current == null ? undefined : current[key]), source)
}

function setByPath(target, path, value) {
  const parts = String(path).split(".")
  let current = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      current[part] = value
      return
    }
    if (current[part] == null || typeof current[part] !== "object" || Array.isArray(current[part])) {
      current[part] = {}
    }
    current = current[part]
  })
}

function deleteByPath(target, path) {
  const parts = String(path).split(".")
  let current = target
  for (let index = 0; index < parts.length - 1; index += 1) {
    current = current?.[parts[index]]
    if (!current || typeof current !== "object") return
  }
  delete current?.[parts.at(-1)]
}

function normalizeFieldValue(field, rawValue) {
  if (field.type === "boolean") return rawValue === "true"
  if (field.type === "number") return rawValue === "" ? null : Number(rawValue)
  if (field.type === "list") {
    return String(rawValue || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  }
  if (field.type === "password") return String(rawValue || "").trim()
  return String(rawValue || "").trim()
}

function buildStructuredPayload(scope, fields, base) {
  const payload = deepClone(base)
  const visibleFields = fields.filter((field) => {
    if (!field.visibleKinds) return true
    const activeKind = String(payload?.kind || "")
    return field.visibleKinds.includes(activeKind)
  })
  for (const field of visibleFields) {
    if (field.type === "readonly-json") {
      continue
    }
    let value
    if (field.type === "scope") {
      const typeNode = document.querySelector(`[data-form-scope="${scope}"][data-field-key="${field.key}"][data-scope-part="type"]`)
      const valueNode = document.querySelector(`[data-form-scope="${scope}"][data-field-key="${field.key}"][data-scope-part="value"]`)
      if (!typeNode || !valueNode) continue
      value = uiScopeToChannelScope(typeNode.value, valueNode.value)
    } else {
      const node = document.querySelector(`[data-form-scope="${scope}"][data-field-key="${field.key}"]`)
      if (!node) continue
      value = normalizeFieldValue(field, node.value)
    }
    const shouldDelete =
      (field.type === "text" || field.type === "select" || field.type === "select-free" || field.type === "password" || field.type === "scope") && value === "" ||
      field.type === "number" && value == null
    if (shouldDelete) {
      deleteByPath(payload, field.key)
    } else {
      setByPath(payload, field.key, value)
    }
  }
  return payload
}

function syncModelPreview() {
  const kind = currentModelKind()
  const fields = modelFieldSpecs[kind]
  const draft = buildStructuredPayload("model", fields, state.currentModelDrafts[kind] || emptyModelEntity(kind))
  $("#model-entity-preview").textContent = pretty(draft)
}

async function loadModelEntities() {
  await ensureCatalog()
  const page = currentModelPage()
  const kind = page.kind
  const list = await api(`/api/models/${kind}`)
  state.modelEntities[kind] = list
  if (!state.selectedModelIds[kind] && list.length) {
    state.selectedModelIds[kind] = list[0][page.idKey]
  }

  renderSelectableList(
    $("#models-entity-list"),
    list,
    state.selectedModelIds[kind],
    (item) => item[page.idKey],
    (item) => escapeHtml(item[page.idKey]),
    (item) => modelListMeta(kind, item),
  )
  wireSelectableClicks($("#models-entity-list"), (id) => {
    state.selectedModelIds[kind] = id
    loadModelEntities().catch(handleError)
  })

  const selected = list.find((item) => item[page.idKey] === state.selectedModelIds[kind])
  const normalized = kind === "providers" ? normalizeProviderEntity(selected) : deepClone(selected || emptyModelEntity(kind))
  state.currentModelDrafts[kind] = normalized
  $("#model-entity-id").value = state.selectedModelIds[kind] || ""
  renderStructuredForm($("#model-dynamic-form"), modelFieldSpecs[kind], normalized, "model")
  document.querySelectorAll('[data-form-scope="model"]').forEach((node) => {
    const rerenderIfNeeded = () => {
      if (node.dataset.fieldKey === "target_type" || node.dataset.fieldKey === "kind") {
        const draft = buildStructuredPayload("model", modelFieldSpecs[kind], state.currentModelDrafts[kind] || emptyModelEntity(kind))
        state.currentModelDrafts[kind] = draft
        renderStructuredForm($("#model-dynamic-form"), modelFieldSpecs[kind], draft, "model")
        document.querySelectorAll('[data-form-scope="model"]').forEach((nextNode) => {
          nextNode.addEventListener("input", syncModelPreview)
          nextNode.addEventListener("change", syncModelPreview)
        })
      }
      syncModelPreview()
    }
    node.addEventListener("input", rerenderIfNeeded)
    node.addEventListener("change", rerenderIfNeeded)
  })
  $("#model-entity-preview").textContent = pretty(normalized)
  $("#model-entity-sidecar").textContent = selected ? pretty(selected) : ""
}

async function saveModelEntity() {
  const page = currentModelPage()
  const kind = page.kind
  let entityId = $("#model-entity-id").value.trim()
  if (!entityId && kind === "bindings") {
    entityId = generateInternalId("model-binding")
  }
  const payload = buildStructuredPayload("model", modelFieldSpecs[kind], state.currentModelDrafts[kind] || emptyModelEntity(kind))
  if (kind === "providers") {
    const existing = (state.modelEntities.providers || []).find((item) => item.provider_id === entityId)
    if (!payload.api_key && existing?.config?.api_key_env) {
      payload.api_key_env = existing.config.api_key_env
    }
  }
  await api(`/api/models/${kind}/${encodeURIComponent(entityId)}`, {
    method: "PUT",
    body: JSON.stringify({ ...payload, [page.idKey]: entityId }),
  })
  state.selectedModelIds[kind] = entityId
  await ensureCatalog(true)
  showToast(`已保存 ${page.title}: ${entityId}`)
  await loadModelEntities()
}

async function deleteModelEntity() {
  const page = currentModelPage()
  const kind = page.kind
  const entityId = $("#model-entity-id").value.trim()
  if (!entityId) return
  await api(`/api/models/${kind}/${encodeURIComponent(entityId)}`, { method: "DELETE" })
  state.selectedModelIds[kind] = ""
  state.currentModelDrafts[kind] = null
  await ensureCatalog(true)
  showToast(`已删除 ${page.title}: ${entityId}`)
  await loadModelEntities()
}

async function previewModelImpact() {
  const page = currentModelPage()
  const kind = page.kind
  const entityId = $("#model-entity-id").value.trim()
  if (!entityId) return
  const result = await api(`/api/models/${kind}/${encodeURIComponent(entityId)}/impact`)
  $("#model-entity-sidecar").textContent = pretty(result)
}

async function healthCheckPreset() {
  if (currentModelKind() !== "presets") {
    showToast("Health Check 只对 Model Presets 生效")
    return
  }
  const entityId = $("#model-entity-id").value.trim()
  if (!entityId) return
  const result = await api(`/api/models/presets/${encodeURIComponent(entityId)}/health-check`, { method: "POST" })
  $("#model-entity-sidecar").textContent = pretty(result)
}

async function reloadModelRegistry() {
  const result = await api("/api/models/reload", { method: "POST" })
  $("#model-entity-sidecar").textContent = pretty(result)
  showToast("model registry 已 reload")
  await ensureCatalog(true)
  await loadModelEntities()
}

async function loadRuntime() {
  const [threads, runs] = await Promise.all([
    api("/api/runtime/threads?limit=100"),
    api("/api/runtime/runs?limit=100"),
  ])
  state.threads = threads
  state.runs = runs
  if (!state.selectedThreadId && threads.length) state.selectedThreadId = threads[0].thread_id
  if (!state.selectedRunId && runs.length) state.selectedRunId = runs[0].run_id

  renderSelectableList(
    $("#runtime-threads-list"),
    threads,
    state.selectedThreadId,
    (item) => item.thread_id,
    (item) => `<span class="mono">${escapeHtml(item.thread_id)}</span>`,
    (item) => `${escapeHtml(item.channel_scope || "-")} · ${escapeHtml(formatTime(item.last_event_at))}`,
  )
  wireSelectableClicks($("#runtime-threads-list"), (id) => {
    state.selectedThreadId = id
    loadRuntime().catch(handleError)
  })

  renderSelectableList(
    $("#runtime-runs-list"),
    runs,
    state.selectedRunId,
    (item) => item.run_id,
    (item) => `<span class="mono">${escapeHtml(item.run_id)}</span>`,
    (item) => `agent=${escapeHtml(item.agent_id || "-")} · status=${escapeHtml(item.status || "-")}`,
  )
  wireSelectableClicks($("#runtime-runs-list"), (id) => {
    state.selectedRunId = id
    loadRuntime().catch(handleError)
  })

  await Promise.all([loadThreadDetail(), loadRunDetail()])
}

async function loadGateway() {
  const [status, config] = await Promise.all([
    api("/api/gateway/status"),
    api("/api/gateway/config"),
  ])
  $("#gateway-host").value = config.host || "0.0.0.0"
  $("#gateway-port").value = String(config.port || 8080)
  $("#gateway-token").value = config.token || ""
  $("#gateway-timeout").value = String(config.timeout || 10)
  const connected = Boolean(status.connected)
  $("#gateway-status-cards").innerHTML = `
    <div class="info-card">
      <div class="list-item-title">gateway_type</div>
      <div class="list-item-meta">${escapeHtml(status.gateway_type || "-")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">listen_url</div>
      <div class="list-item-meta mono">${escapeHtml(status.listen_url || "-")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">server_running</div>
      <div class="list-item-meta">${escapeHtml(status.server_running ? "是" : "否")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">connected</div>
      <div class="list-item-meta">${escapeHtml(connected ? "已连接" : "未连接")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">self_id</div>
      <div class="list-item-meta mono">${escapeHtml(status.self_id || "-")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">call_api</div>
      <div class="list-item-meta">${escapeHtml(status.supports_call_api ? "可用" : "不可用")}</div>
    </div>
    <div class="info-card">
      <div class="list-item-title">token</div>
      <div class="list-item-meta">${escapeHtml(status.token_configured ? "已配置" : "未配置")}</div>
    </div>
  `

  const snippet = {
    network: {
      httpServers: [],
      httpClients: [],
      websocketServers: [],
      websocketClients: [
        {
          name: "AcaBot",
          enable: true,
          url: `ws://${config.host || "127.0.0.1"}:${config.port || 8080}`,
          messagePostFormat: "array",
          reportSelfMessage: false,
          reconnectInterval: 5000,
          token: config.token || "",
          debug: false,
          heartInterval: 30000,
        },
      ],
    },
  }
  $("#gateway-napcat-snippet").textContent = pretty(snippet)

  const guide = connected
    ? `
      <div class="info-card">
        <div class="list-item-title">Gateway 已连上</div>
        <div class="list-item-meta">NapCat 已经连到 AcaBot。现在如果还不回消息，就不是 WS 连通性问题，而应该去看 routing、Bot 配置或模型调用日志。</div>
      </div>
    `
    : `
      <div class="info-card">
        <div class="list-item-title">Gateway 还没连上</div>
        <div class="list-item-meta">AcaBot 现在只是正在监听 ${escapeHtml(status.listen_url || "ws://...")}，但 NapCat 还没有建立反向 WebSocket。</div>
      </div>
      <div class="info-card">
        <div class="list-item-title">检查项</div>
        <div class="list-item-meta">如果 AcaBot 在宿主机运行、NapCat 在 Docker 里，不要继续把 NapCat 指到 <span class="mono">ws://acabot:8080</span>。这个地址只适合两边都跑在 compose 里的情况。</div>
      </div>
      <div class="info-card">
        <div class="list-item-title">成功标志</div>
        <div class="list-item-meta">日志里应该出现 <span class="mono">NapCat connected, self_id=...</span>。在这之前，Bot 不可能正常收发消息。</div>
      </div>
    `
  $("#gateway-status-guide").innerHTML = guide
}

async function saveGatewayConfig() {
  const payload = {
    host: $("#gateway-host").value.trim() || "0.0.0.0",
    port: Number($("#gateway-port").value || 8080),
    token: $("#gateway-token").value,
    timeout: Number($("#gateway-timeout").value || 10),
  }
  await api("/api/gateway/config", {
    method: "PUT",
    body: JSON.stringify(payload),
  })
  showToast("已保存 gateway 配置，监听地址或 token 变更后建议重启 AcaBot")
  await loadGateway()
}

function renderTimeline(container, items, formatter) {
  if (!items.length) {
    container.innerHTML = emptyState("暂无记录")
    return
  }
  container.innerHTML = items
    .map(
      (item) => `
        <div class="info-card">
          <div class="list-item-title">${escapeHtml(formatter(item))}</div>
          <div class="list-item-meta">${escapeHtml(formatTime(item.created_at || item.timestamp || item.updated_at || 0))}</div>
        </div>
      `,
    )
    .join("")
}

async function loadThreadDetail() {
  const threadId = state.selectedThreadId
  if (!threadId) {
    $("#runtime-thread-summary").innerHTML = emptyState("未选择 thread")
    $("#runtime-thread-steps").innerHTML = emptyState("未选择 thread")
    $("#runtime-thread-events").innerHTML = emptyState("未选择 thread")
    $("#runtime-thread-messages").innerHTML = emptyState("未选择 thread")
    return
  }
  const [thread, steps, events, messages, sandbox] = await Promise.all([
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/steps?limit=50`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/events?limit=30`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/messages?limit=30`),
    api(`/api/workspaces/${encodeURIComponent(threadId)}/sandbox`),
  ])
  $("#thread-agent-override-input").value = thread.metadata?.thread_agent_override || ""
  $("#runtime-thread-summary").innerHTML = `
    <div class="info-card"><div class="list-item-title">thread_id</div><div class="list-item-meta mono">${escapeHtml(thread.thread_id)}</div></div>
    <div class="info-card"><div class="list-item-title">channel_scope</div><div class="list-item-meta">${escapeHtml(thread.channel_scope || "-")}</div></div>
    <div class="info-card"><div class="list-item-title">last_event_at</div><div class="list-item-meta">${escapeHtml(formatTime(thread.last_event_at))}</div></div>
    <div class="info-card"><div class="list-item-title">sandbox</div><div class="list-item-meta">${escapeHtml(sandbox.backend_kind || "-")} · active=${escapeHtml(String(Boolean(sandbox.active)))}</div></div>
  `
  renderTimeline($("#runtime-thread-steps"), steps, (item) => `${item.step_type} · ${item.status}`)
  renderTimeline($("#runtime-thread-events"), events, (item) => `${item.event_type} · ${previewText(item.content_text || "-")}`)
  renderTimeline($("#runtime-thread-messages"), messages, (item) => `${item.role || item.message_type || "message"} · ${previewText(item.content_text || "-")}`)
}

async function saveThreadAgentOverride() {
  const threadId = state.selectedThreadId
  const agentId = $("#thread-agent-override-input").value.trim()
  if (!threadId || !agentId) return
  await api(`/api/runtime/threads/${encodeURIComponent(threadId)}/agent-override`, {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId }),
  })
  showToast(`thread override 已切到 ${agentId}`)
  await loadRuntime()
}

async function clearThreadAgentOverride() {
  const threadId = state.selectedThreadId
  if (!threadId) return
  await api(`/api/runtime/threads/${encodeURIComponent(threadId)}/agent-override`, { method: "DELETE" })
  showToast("thread override 已清除")
  await loadRuntime()
}

async function loadRunDetail() {
  const runId = state.selectedRunId
  if (!runId) {
    $("#runtime-run-detail").innerHTML = emptyState("未选择 run")
    $("#runtime-run-steps").innerHTML = emptyState("未选择 run")
    return
  }
  const [run, steps] = await Promise.all([
    api(`/api/runtime/runs/${encodeURIComponent(runId)}`),
    api(`/api/runtime/runs/${encodeURIComponent(runId)}/steps?limit=80`),
  ])
  $("#runtime-run-detail").innerHTML = `
    <div class="info-card"><div class="list-item-title">run_id</div><div class="list-item-meta mono">${escapeHtml(run.run_id)}</div></div>
    <div class="info-card"><div class="list-item-title">agent</div><div class="list-item-meta">${escapeHtml(run.agent_id || "-")}</div></div>
    <div class="info-card"><div class="list-item-title">status</div><div class="list-item-meta">${escapeHtml(run.status || "-")}</div></div>
    <div class="info-card"><div class="list-item-title">thread</div><div class="list-item-meta mono">${escapeHtml(run.thread_id || "-")}</div></div>
  `
  renderTimeline($("#runtime-run-steps"), steps, (item) => `${item.step_type} · ${item.status}`)
}

async function loadPlugins() {
  const [pluginsData, status, executors] = await Promise.all([
    api("/api/plugins"),
    api("/api/status"),
    api("/api/subagents/executors"),
  ])
  state.plugins = pluginsData.loaded_plugins || []
  renderSelectableList(
    $("#plugins-list"),
    state.plugins.map((name) => ({ name })),
    "",
    (item) => item.name,
    (item) => escapeHtml(item.name),
    () => "loaded",
  )
  $("#plugins-skills").innerHTML = (status.loaded_skills || []).length
    ? (status.loaded_skills || []).map((name) => `<div class="info-card">${escapeHtml(name)}</div>`).join("")
    : emptyState("没有 loaded skill")
  $("#plugins-executors").innerHTML = executors.length
    ? executors
        .map(
          (item) => `
            <div class="info-card">
              <div class="list-item-title">${escapeHtml(item.agent_id)}</div>
              <div class="list-item-meta">${escapeHtml(item.source || "-")}</div>
            </div>
          `,
        )
        .join("")
    : emptyState("没有 subagent executor")
}

async function reloadPlugins() {
  const pluginNames = $("#reload-plugins-input").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
  await api("/api/plugins/reload", {
    method: "POST",
    body: JSON.stringify({ plugin_names: pluginNames }),
  })
  showToast("plugins 已 reload")
  await Promise.all([loadMetaAndStatus(), loadPlugins()])
}

async function loadWorkspaces() {
  state.workspaces = await api("/api/workspaces")
  if (!state.selectedWorkspaceId && state.workspaces.length) {
    state.selectedWorkspaceId = state.workspaces[0].thread_id
  }
  renderSelectableList(
    $("#workspaces-list"),
    state.workspaces,
    state.selectedWorkspaceId,
    (item) => item.thread_id,
    (item) => escapeHtml(item.workspace_visible_root || item.thread_id),
    (item) => `thread=${escapeHtml(item.thread_id)} · backend=${escapeHtml(item.backend_kind)} · agent=${escapeHtml(item.agent_id || "-")}`,
  )
  wireSelectableClicks($("#workspaces-list"), (id) => {
    state.selectedWorkspaceId = id
    loadWorkspaces().catch(handleError)
  })
  await loadWorkspaceDetail()
}

async function loadWorkspaceDetail() {
  const threadId = state.selectedWorkspaceId
  if (!threadId) {
    $("#workspace-summary").innerHTML = emptyState("未选择 workspace")
    $("#workspace-entries").innerHTML = emptyState("未选择 workspace")
    $("#workspace-sessions").innerHTML = emptyState("未选择 workspace")
    $("#workspace-attachments").innerHTML = emptyState("未选择 workspace")
    return
  }
  const workspace = state.workspaces.find((item) => item.thread_id === threadId)
  const [sandbox, entries, sessions, attachments] = await Promise.all([
    api(`/api/workspaces/${encodeURIComponent(threadId)}/sandbox`),
    api(`/api/workspaces/${encodeURIComponent(threadId)}/entries?path=/`),
    api(`/api/workspaces/${encodeURIComponent(threadId)}/sessions`),
    api(`/api/workspaces/${encodeURIComponent(threadId)}/attachments`),
  ])
  $("#workspace-summary").innerHTML = `
    <div class="info-card"><div class="list-item-title">workspace_host_path</div><div class="list-item-meta mono">${escapeHtml(workspace?.workspace_host_path || "-")}</div></div>
    <div class="info-card"><div class="list-item-title">workspace_visible_root</div><div class="list-item-meta mono">${escapeHtml(workspace?.workspace_visible_root || "-")}</div></div>
    <div class="info-card"><div class="list-item-title">backend</div><div class="list-item-meta">${escapeHtml(sandbox.backend_kind || "-")} · active=${escapeHtml(String(Boolean(sandbox.active)))}</div></div>
    <div class="info-card"><div class="list-item-title">available_tools</div><div class="list-item-meta">${escapeHtml((workspace?.available_tools || []).join(", ") || "-")}</div></div>
  `
  $("#workspace-entries").innerHTML = entries.length
    ? entries
        .map(
          (item) => `
            <div class="info-card">
              <div class="list-item-title mono">${escapeHtml(item.path)}</div>
              <div class="list-item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.size_bytes || 0)} bytes</div>
            </div>
          `,
        )
        .join("")
    : emptyState("目录为空")
  $("#workspace-sessions").innerHTML = sessions.length
    ? sessions.map((item) => `<div class="info-card mono">${escapeHtml(item)}</div>`).join("")
    : emptyState("无活跃 session")
  $("#workspace-attachments").innerHTML = attachments.length
    ? attachments
        .map(
          (item) => `
            <div class="info-card">
              <div class="list-item-title mono">${escapeHtml(item.path)}</div>
              <div class="list-item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.size_bytes || 0)} bytes</div>
            </div>
          `,
        )
        .join("")
    : emptyState("无 staged attachment")
}

async function stopWorkspaceSandbox() {
  const threadId = state.selectedWorkspaceId
  if (!threadId) return
  await api(`/api/workspaces/${encodeURIComponent(threadId)}/stop-sandbox`, {
    method: "POST",
    body: JSON.stringify({ force: true }),
  })
  showToast("sandbox 已停止")
  await loadWorkspaces()
}

async function pruneWorkspace() {
  const threadId = state.selectedWorkspaceId
  if (!threadId) return
  await api(`/api/workspaces/${encodeURIComponent(threadId)}/prune`, {
    method: "POST",
    body: JSON.stringify({ force: true }),
  })
  showToast("workspace 已清理")
  await loadWorkspaces()
}

function spaceKey(space) {
  return `${space.tenant_id}::${space.space_id}`
}

function selectedReferenceSpace() {
  return state.referenceSpaces.find((item) => spaceKey(item) === state.selectedReferenceSpaceKey) || null
}

async function loadReferences() {
  state.referenceSpaces = await api("/api/references/spaces")
  if (!state.selectedReferenceSpaceKey && state.referenceSpaces.length) {
    state.selectedReferenceSpaceKey = spaceKey(state.referenceSpaces[0])
  }
  renderSelectableList(
    $("#reference-spaces-list"),
    state.referenceSpaces,
    state.selectedReferenceSpaceKey,
    (item) => spaceKey(item),
    (item) => escapeHtml(item.space_id),
    (item) => `tenant=${escapeHtml(item.tenant_id)} · mode=${escapeHtml(item.mode)} · docs=${escapeHtml(item.document_count)}`,
  )
  wireSelectableClicks($("#reference-spaces-list"), (id) => {
    state.selectedReferenceSpaceKey = id
    state.selectedReferenceDocument = null
    renderReferenceDetail()
  })
  renderReferenceDetail()
}

function renderReferenceDetail() {
  const space = selectedReferenceSpace()
  if (!space) {
    $("#reference-detail-content").innerHTML = emptyState("当前没有可用 Reference Space")
    return
  }
  if (state.selectedReferenceDocument) {
    const doc = state.selectedReferenceDocument
    $("#reference-detail-content").innerHTML = `
      <div class="info-card">
        <div class="list-item-title">${escapeHtml(doc.title || doc.uri || doc.ref_id)}</div>
        <div class="list-item-meta">ref_id=${escapeHtml(doc.ref_id)} · tenant=${escapeHtml(doc.tenant_id)} · space=${escapeHtml(doc.space_id)}</div>
      </div>
      <div class="info-card"><div class="list-item-title">Abstract</div><div class="list-item-meta">${escapeHtml(doc.abstract || "-")}</div></div>
      <div class="info-card"><div class="list-item-title">Content</div><div class="list-item-meta">${escapeHtml(previewText(doc.content || doc.overview || "", 800))}</div></div>
    `
    return
  }
  $("#reference-detail-content").innerHTML = `
    <div class="info-card">
      <div class="list-item-title">${escapeHtml(space.space_id)}</div>
      <div class="list-item-meta">tenant=${escapeHtml(space.tenant_id)} · mode=${escapeHtml(space.mode)} · documents=${escapeHtml(space.document_count)} · updated=${escapeHtml(formatTime(space.updated_at))}</div>
    </div>
    <div class="callout">先在左边 Search，点中命中文档后，这里会展示详情。</div>
  `
}

async function searchReferences() {
  const space = selectedReferenceSpace()
  const query = $("#reference-search-input").value.trim()
  if (!space || !query) return
  const params = new URLSearchParams({
    query,
    tenant_id: space.tenant_id,
    space_id: space.space_id,
    limit: "10",
    body: "full",
  })
  const hits = await api(`/api/references/search?${params.toString()}`)
  const box = $("#reference-search-results")
  if (!hits.length) {
    box.innerHTML = emptyState("无搜索结果")
    return
  }
  box.innerHTML = hits
    .map(
      (hit) => `
        <div class="list-item" data-ref-id="${escapeHtml(hit.ref_id)}" data-tenant-id="${escapeHtml(hit.tenant_id)}">
          <div class="list-item-title">${escapeHtml(hit.title || hit.uri || hit.ref_id)}</div>
          <div class="list-item-meta">score=${escapeHtml(Number(hit.score || 0).toFixed(3))} · ${escapeHtml(previewText(hit.body || hit.abstract || "", 140))}</div>
        </div>
      `,
    )
    .join("")
  box.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", async () => {
      const refId = node.dataset.refId
      const tenantId = node.dataset.tenantId
      state.selectedReferenceDocument = await api(
        `/api/references/document?ref_id=${encodeURIComponent(refId)}&tenant_id=${encodeURIComponent(tenantId)}&body=full`,
      )
      renderReferenceDetail()
    })
  })
}

async function addReferenceDocument() {
  const space = selectedReferenceSpace()
  if (!space) {
    showToast("请先选择一个 Reference Space")
    return
  }
  await api("/api/references/documents", {
    method: "POST",
    body: JSON.stringify({
      tenant_id: space.tenant_id,
      space_id: space.space_id,
      mode: space.mode,
      documents: [
        {
          title: $("#reference-add-title").value.trim(),
          body: $("#reference-add-body").value,
          source_uri: $("#reference-add-source-uri").value.trim(),
          tags: $("#reference-add-tags").value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
        },
      ],
    }),
  })
  $("#reference-add-title").value = ""
  $("#reference-add-body").value = ""
  $("#reference-add-source-uri").value = ""
  $("#reference-add-tags").value = ""
  showToast("Reference document 已写入")
  await loadReferences()
}

async function reloadRuntimeConfig() {
  await api("/api/runtime/reload-config", { method: "POST" })
  showToast("runtime 配置已 reload")
  await refreshCurrentView(true)
}

async function refreshCurrentView(forceHeader = false) {
  if (forceHeader || !state.status || !state.meta) {
    await loadMetaAndStatus()
  }
  if (state.view === "dashboard") return loadDashboard()
  if (state.view === "approvals") return loadApprovals()
  if (state.view === "agents") return loadProfiles()
  if (state.view === "subagents") return loadSubagents()
  if (state.view === "sessions") return loadSessions()
  if (state.view === "prompts") return loadPrompts()
  if (isModelView(state.view)) return loadModelEntities()
  if (state.view === "gateway") return loadGateway()
  if (state.view === "runtime") return loadRuntime()
  if (state.view === "plugins") return loadPlugins()
  if (state.view === "workspaces") return loadWorkspaces()
  if (state.view === "references") return loadReferences()
  return null
}

function wireEvents() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.section))
  })
  $$("[data-session-section-tab]").forEach((button) => {
    button.addEventListener("click", () => setSessionSection(button.dataset.sessionSectionTab))
  })
  $$("[data-bot-section-tab]").forEach((button) => {
    button.addEventListener("click", () => setBotSection(button.dataset.botSectionTab))
  })

  $("#toggle-theme-btn").addEventListener("click", () => {
    setTheme(state.theme === "light" ? "dark" : "light")
  })

  $("#refresh-all-btn").addEventListener("click", () => refreshCurrentView(true).catch(handleError))
  $("#reload-config-btn").addEventListener("click", () => reloadRuntimeConfig().catch(handleError))
  $("#dashboard-open-approvals-btn").addEventListener("click", () => setView("approvals"))
  $("#refresh-approvals-btn").addEventListener("click", () => refreshCurrentView(true).catch(handleError))

  $("#reset-bot-btn").addEventListener("click", () => {
    setBotSection("ai")
    renderProfileForm("profile", profileDraftFromSource(getBotProfile()), { withComputer: true })
    loadEffectiveModelInto("profile-effective-model", getBotAgentId()).catch(handleError)
  })
  $("#save-profile-btn").addEventListener("click", () => saveProfile().catch(handleError))
  $("#new-subagent-btn").addEventListener("click", () => {
    state.selectedSubagentId = ""
    renderProfileForm("subagent", createEmptyProfile(), { withComputer: false })
    loadEffectiveModelInto("subagent-effective-model", "").catch(handleError)
  })
  $("#save-subagent-btn").addEventListener("click", () => saveSubagent().catch(handleError))
  $("#delete-subagent-btn").addEventListener("click", () => deleteSubagent().catch(handleError))

  $("#new-prompt-btn").addEventListener("click", () => {
    state.selectedPromptRef = ""
    $("#prompt-name-input").value = "default"
    $("#prompt-content-input").value = ""
  })
  $("#save-prompt-btn").addEventListener("click", () => savePrompt().catch(handleError))
  $("#delete-prompt-btn").addEventListener("click", () => deletePrompt().catch(handleError))

  $("#new-session-btn").addEventListener("click", () => {
    state.selectedSessionKey = ""
    setSessionSection("ai")
    fillSessionForm(createEmptySessionConfig())
  })
  $("#save-session-btn").addEventListener("click", () => saveSessionConfig().catch(handleError))
  $("#delete-session-btn").addEventListener("click", () => deleteSessionConfig().catch(handleError))
  $("#session-ai-override-enabled").addEventListener("change", () => {
    setSessionAiOverrideEnabled($("#session-ai-override-enabled").checked)
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-scope-type").addEventListener("change", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-scope-value").addEventListener("input", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-name").addEventListener("input", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-persist-event").addEventListener("change", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-extract-memory").addEventListener("change", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })
  $("#session-tags").addEventListener("input", () => {
    $("#session-preview").innerHTML = renderSessionPreview(readSessionForm())
  })

  $("#new-model-entity-btn").addEventListener("click", () => {
    const kind = currentModelKind()
    state.selectedModelIds[kind] = ""
    state.currentModelDrafts[kind] = emptyModelEntity(kind)
    $("#model-entity-id").value = ""
    renderStructuredForm($("#model-dynamic-form"), modelFieldSpecs[kind], state.currentModelDrafts[kind], "model")
    document.querySelectorAll('[data-form-scope="model"]').forEach((node) => {
      node.addEventListener("input", syncModelPreview)
      node.addEventListener("change", syncModelPreview)
    })
    $("#model-entity-preview").textContent = pretty(state.currentModelDrafts[kind])
    $("#model-entity-sidecar").textContent = ""
  })
  $("#save-model-entity-btn").addEventListener("click", () => saveModelEntity().catch(handleError))
  $("#delete-model-entity-btn").addEventListener("click", () => deleteModelEntity().catch(handleError))
  $("#preview-model-impact-btn").addEventListener("click", () => previewModelImpact().catch(handleError))
  $("#health-check-preset-btn").addEventListener("click", () => healthCheckPreset().catch(handleError))
  $("#reload-model-registry-btn").addEventListener("click", () => reloadModelRegistry().catch(handleError))

  $("#refresh-gateway-btn").addEventListener("click", () => loadGateway().catch(handleError))
  $("#save-gateway-btn").addEventListener("click", () => saveGatewayConfig().catch(handleError))
  $("#refresh-runtime-btn").addEventListener("click", () => loadRuntime().catch(handleError))
  $("#save-thread-agent-override-btn").addEventListener("click", () => saveThreadAgentOverride().catch(handleError))
  $("#clear-thread-agent-override-btn").addEventListener("click", () => clearThreadAgentOverride().catch(handleError))

  $("#refresh-plugins-btn").addEventListener("click", () => loadPlugins().catch(handleError))
  $("#reload-plugins-btn").addEventListener("click", () => reloadPlugins().catch(handleError))

  $("#refresh-workspaces-btn").addEventListener("click", () => loadWorkspaces().catch(handleError))
  $("#stop-sandbox-btn").addEventListener("click", () => stopWorkspaceSandbox().catch(handleError))
  $("#prune-workspace-btn").addEventListener("click", () => pruneWorkspace().catch(handleError))

  $("#refresh-references-btn").addEventListener("click", () => loadReferences().catch(handleError))
  $("#search-references-btn").addEventListener("click", () => searchReferences().catch(handleError))
  $("#reference-search-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault()
      searchReferences().catch(handleError)
    }
  })
  $("#add-reference-btn").addEventListener("click", () => addReferenceDocument().catch(handleError))
}

async function bootstrap() {
  setTheme(state.theme)
  wireEvents()
  const initialView = location.hash.replace("#", "")
  if (legacyRoutingViews.has(initialView)) {
    state.view = "sessions"
  } else if (initialView === "model-bindings") {
    state.view = "model-presets"
  } else if (pageMeta[initialView]) {
    state.view = initialView
  }
  updatePageChrome()
  setView(state.view)
}

bootstrap().catch(handleError)
