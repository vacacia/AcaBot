<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { apiDelete, apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"
import ModelParamEditor from "../components/ModelParamEditor.vue"
import CustomSelect from "../components/CustomSelect.vue"

type TaskKind =
  | "chat"
  | "embedding"
  | "rerank"
  | "speech_to_text"
  | "text_to_speech"
  | "image_generation"

type Capability =
  | "tool_calling"
  | "reasoning"
  | "structured_output"
  | "image_input"
  | "image_output"
  | "document_input"
  | "audio_input"
  | "audio_output"
  | "video_input"
  | "video_output"

type ProviderKindOption = {
  value: string
  label: string
  litellm_prefix: string
  config_class: string
  default_base_url: string
}

type CatalogPayload = {
  options?: {
    model_task_kinds?: TaskKind[]
    model_capabilities?: Capability[]
    provider_kinds?: (ProviderKindOption | string)[]
  }
}

type PresetRecord = {
  preset_id: string
  provider_id: string
  model: string
  task_kind: TaskKind
  capabilities?: Capability[]
  context_window: number
  max_output_tokens?: number
  model_params?: Record<string, unknown>
}

type ProviderRecord = {
  provider_id: string
  name: string
  kind: string
}

type MutationResult = {
  ok: boolean
  applied: boolean
  message: string
}

type HealthCheckResult = {
  ok: boolean
  message: string
}

type PresetDraft = {
  preset_id: string
  provider_id: string
  model: string
  task_kind: TaskKind
  capabilities: Capability[]
  context_window: string
  max_output_tokens: string
  model_params_text: string
}

type BindingSnapshot = {
  binding: {
    binding_id: string
    target_id: string
    preset_ids: string[]
    timeout_sec?: number | null
  }
  binding_state: string
  message: string
}

type EffectiveTargetPreview = {
  request?: {
    model?: string
    preset_id?: string
  }
}

const DEFAULT_TASK_KIND_OPTIONS: TaskKind[] = [
  "chat",
  "embedding",
  "rerank",
  "speech_to_text",
  "text_to_speech",
  "image_generation",
]

const DEFAULT_CAPABILITY_OPTIONS: Capability[] = [
  "tool_calling",
  "reasoning",
  "structured_output",
  "image_input",
  "image_output",
  "document_input",
  "audio_input",
  "audio_output",
  "video_input",
  "video_output",
]

const cachedCatalog = peekCachedGet<CatalogPayload>("/api/ui/catalog")
const taskKindOptions = ref<TaskKind[]>(cachedCatalog?.options?.model_task_kinds ?? DEFAULT_TASK_KIND_OPTIONS)
const capabilityOptions = ref<Capability[]>(cachedCatalog?.options?.model_capabilities ?? DEFAULT_CAPABILITY_OPTIONS)

function parseProviderKinds(raw?: (ProviderKindOption | string)[]): ProviderKindOption[] {
  if (!raw) return []
  return raw.map((item) => {
    if (typeof item === "string") {
      return { value: item, label: item, litellm_prefix: "", config_class: "", default_base_url: "" }
    }
    return item
  })
}

const providerKindOptions = ref<ProviderKindOption[]>(parseProviderKinds(cachedCatalog?.options?.provider_kinds))

const presets = ref<PresetRecord[]>(peekCachedGet<PresetRecord[]>("/api/models/presets") ?? [])
const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>("/api/models/providers") ?? [])
const bindings = ref<BindingSnapshot[]>(peekCachedGet<BindingSnapshot[]>("/api/models/bindings") ?? [])

const selectedId = ref("")
const selectedBindingId = ref("")
const draft = ref<PresetDraft | null>(null)
const bindingDraft = ref<BindingSnapshot["binding"] | null>(null)
const showPresetEditor = ref(false)
const showBindingEditor = ref(false)
const bindingPreview = ref<EffectiveTargetPreview | null>(null)

const loading = ref(true)
const saveMessage = ref("")
const errorMessage = ref("")
const healthCheckMessage = ref("")
const healthCheckError = ref("")
const healthCheckRunning = ref(false)
const healthCheckController = ref<AbortController | null>(null)

const litellmInfo = ref<{ model_info: any; supported_params: string[]; param_hints?: Record<string, any> } | null>(null)
const litellmLoading = ref(false)
let litellmDebounceTimer: ReturnType<typeof setTimeout> | null = null

function bindingStateClass(state: string): string {
  if (!state) return "state-chip is-unknown"
  const s = state.toLowerCase()
  if (s === "active" || s === "ready" || s === "bound") return "state-chip is-active"
  if (s === "inactive" || s === "disabled" || s === "unbound") return "state-chip is-inactive"
  if (s === "error" || s === "failed" || s === "unavailable") return "state-chip is-error"
  return "state-chip is-unknown"
}

function metaValueStateClass(state: string): string {
  if (!state) return "meta-value is-unknown"
  const s = state.toLowerCase()
  if (s === "active" || s === "ready" || s === "bound") return "meta-value is-active"
  if (s === "inactive" || s === "disabled" || s === "unbound") return "meta-value is-inactive"
  if (s === "error" || s === "failed" || s === "unavailable") return "meta-value is-error"
  return "meta-value is-unknown"
}

function queryLitellmInfo(model: string, providerKind: string): void {
  litellmInfo.value = null
  if (litellmDebounceTimer) clearTimeout(litellmDebounceTimer)
  if (!model.trim()) return
  const capturedId = selectedId.value
  litellmDebounceTimer = setTimeout(async () => {
    if (selectedId.value !== capturedId) return
    litellmLoading.value = true
    try {
      const kindMeta = providerKindOptions.value.find((k) => k.value === providerKind)
      const prefix = kindMeta?.litellm_prefix || ""
      const fullModel = model.includes("/") ? model : `${prefix}${model}`
      if (selectedId.value !== capturedId) return
      litellmInfo.value = await apiGet(`/api/models/litellm-info?model=${encodeURIComponent(fullModel)}`)
      if (selectedId.value !== capturedId) {
        litellmInfo.value = null
        return
      }
      if (litellmInfo.value?.model_info && draft.value) {
        const info = litellmInfo.value.model_info
        // Always overwrite from litellm — it's the source of truth for the queried model
        if (info.max_input_tokens) {
          draft.value.context_window = String(info.max_input_tokens)
        }
        if (info.max_output_tokens) {
          draft.value.max_output_tokens = String(info.max_output_tokens)
        }
        // Always sync capabilities from litellm
        const caps: Capability[] = []
        if (info.supports_function_calling) caps.push("tool_calling")
        if (info.supports_vision) caps.push("image_input")
        if (info.supports_reasoning) caps.push("reasoning")
        if (info.supports_response_schema) caps.push("structured_output")
        if (info.supports_audio_input) caps.push("audio_input")
        if (info.supports_audio_output) caps.push("audio_output")
        draft.value.capabilities = caps
      }
    } catch {
      litellmInfo.value = null
    } finally {
      litellmLoading.value = false
    }
  }, 600)
}

const parsedModelParams = computed(() => {
  if (!draft.value?.model_params_text) return {}
  try {
    return JSON.parse(draft.value.model_params_text)
  } catch {
    return {}
  }
})

function onModelParamsChange(params: Record<string, unknown>): void {
  if (!draft.value) return
  const clean: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") clean[k] = v
  }
  draft.value.model_params_text = Object.keys(clean).length > 0 ? JSON.stringify(clean, null, 2) : ""
}

watch(
  showPresetEditor,
  (presetOpen) => {
    if (typeof document === "undefined") {
      return
    }
    document.body.classList.toggle("overlay-active", presetOpen)
    if (!presetOpen) {
      // Cancel any in-flight health check when closing the editor
      if (healthCheckController.value) {
        healthCheckController.value.abort()
        healthCheckController.value = null
      }
      // Clear stale health check feedback when closing the editor
      healthCheckMessage.value = ""
      healthCheckError.value = ""
      healthCheckRunning.value = false
    }
  },
  { immediate: true },
)

function jsonText(value: unknown): string {
  if (!value || (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ""
  }
  return JSON.stringify(value, null, 2)
}

function derivePresetId(providerId: string, model: string): string {
  const p = providerId.trim()
  const m = model.trim()
  if (!p || !m) return ""
  return `${p}--${m}`
}

function blankDraft(): PresetDraft {
  return {
    preset_id: "",
    provider_id: providers.value[0]?.provider_id || "",
    model: "",
    task_kind: "chat",
    capabilities: [],
    context_window: "",
    max_output_tokens: "",
    model_params_text: "",
  }
}

function providerLabel(providerId: string): string {
  const provider = providers.value.find((item) => item.provider_id === providerId)
  return provider?.name || providerId
}

function toDraft(item: PresetRecord): PresetDraft {
  const capabilities = Array.isArray(item.capabilities)
    ? [...item.capabilities]
    : (item.task_kind === "chat" ? ["tool_calling"] : [])
  return {
    preset_id: item.preset_id,
    provider_id: item.provider_id,
    model: item.model,
    task_kind: item.task_kind,
    capabilities,
    context_window: String(item.context_window || ""),
    max_output_tokens: item.max_output_tokens ? String(item.max_output_tokens) : "",
    model_params_text: jsonText(item.model_params),
  }
}

function parseObjectText(label: string, value: string): Record<string, unknown> {
  const text = value.trim()
  if (!text) {
    return {}
  }
  const parsed = JSON.parse(text) as Record<string, unknown>
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed
}

function toggleCapability(capability: Capability, enabled: boolean): void {
  if (!draft.value) {
    return
  }
  const next = new Set(draft.value.capabilities)
  if (enabled) {
    next.add(capability)
  } else {
    next.delete(capability)
  }
  draft.value.capabilities = capabilityOptions.value.filter((item) => next.has(item))
}

async function loadModels(preferredPresetId = ""): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const [catalogPayload, providerList, presetList, bindingList] = await Promise.all([
      apiGet<CatalogPayload>("/api/ui/catalog"),
      apiGet<ProviderRecord[]>("/api/models/providers"),
      apiGet<PresetRecord[]>("/api/models/presets"),
      apiGet<BindingSnapshot[]>("/api/models/bindings"),
    ])
    taskKindOptions.value = catalogPayload.options?.model_task_kinds ?? DEFAULT_TASK_KIND_OPTIONS
    capabilityOptions.value = catalogPayload.options?.model_capabilities ?? DEFAULT_CAPABILITY_OPTIONS
    providerKindOptions.value = parseProviderKinds(catalogPayload.options?.provider_kinds)
    providers.value = providerList
    presets.value = presetList
    bindings.value = bindingList

    const nextPresetId = preferredPresetId || selectedId.value || presetList[0]?.preset_id || ""
    if (nextPresetId) {
      await selectPreset(nextPresetId, presetList)
    } else {
      createPreset()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败"
  } finally {
    loading.value = false
  }
}

async function selectPreset(presetId: string, existingList?: PresetRecord[]): Promise<void> {
  selectedId.value = presetId
  const source = existingList || presets.value
  const found = source.find((item) => item.preset_id === presetId)
  if (found) {
    draft.value = toDraft(found)
    await syncBindingSelection()
    const provider = providers.value.find((p) => p.provider_id === found.provider_id)
    if (found.model) queryLitellmInfo(found.model, provider?.kind || "")
    return
  }
  const payload = await apiGet<PresetRecord>(`/api/models/presets/${encodeURIComponent(presetId)}`)
  draft.value = toDraft(payload)
  await syncBindingSelection()
  const provider = providers.value.find((p) => p.provider_id === payload.provider_id)
  if (payload.model) queryLitellmInfo(payload.model, provider?.kind || "")
}

function createPreset(): void {
  selectedId.value = ""
  draft.value = blankDraft()
  bindingDraft.value = null
  showBindingEditor.value = false
  selectedBindingId.value = ""
  bindingPreview.value = null
  saveMessage.value = ""
  errorMessage.value = ""
}

function openNewPresetEditor(): void {
  createPreset()
  saveMessage.value = ""
  errorMessage.value = ""
  showPresetEditor.value = true
}

function openPresetEditor(): void {
  if (!draft.value) {
    return
  }
  saveMessage.value = ""
  errorMessage.value = ""
  showPresetEditor.value = true
}

function closePresetEditor(): void {
  showPresetEditor.value = false
}

async function savePreset(): Promise<void> {
  if (!draft.value) {
    return
  }
  if (!draft.value.provider_id) {
    errorMessage.value = "请先选择一个 Provider"
    return
  }
  // Auto-derive preset_id for new presets
  if (!selectedId.value && !draft.value.preset_id.trim()) {
    const derived = derivePresetId(draft.value.provider_id, draft.value.model)
    if (!derived) {
      errorMessage.value = "请填写模型名"
      return
    }
    draft.value.preset_id = derived
  }
  const presetId = draft.value.preset_id.trim()
  if (!presetId) {
    errorMessage.value = "Preset ID 不能为空"
    return
  }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    const result = await apiPut<MutationResult>(`/api/models/presets/${encodeURIComponent(presetId)}`, {
      provider_id: draft.value.provider_id,
      model: draft.value.model,
      task_kind: draft.value.task_kind,
      capabilities: [...draft.value.capabilities],
      context_window: Number(draft.value.context_window || 0),
      max_output_tokens: draft.value.max_output_tokens ? Number(draft.value.max_output_tokens) : null,
      model_params: parseObjectText("模型参数", draft.value.model_params_text),
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "保存失败")
    }
    saveMessage.value = "已保存"
    showPresetEditor.value = false
    await loadModels(presetId)
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function deletePreset(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  saveMessage.value = ""
  errorMessage.value = ""
  try {
    const result = await apiDelete<MutationResult>(`/api/models/presets/${encodeURIComponent(selectedId.value)}`)
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "删除失败")
    }
    saveMessage.value = "已删除"
    selectedId.value = ""
    draft.value = null
    litellmInfo.value = null
    showPresetEditor.value = false
    await loadModels()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "删除失败"
  }
}

async function healthCheckPreset(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  // Cancel any in-flight health check request
  if (healthCheckController.value) {
    healthCheckController.value.abort()
  }
  healthCheckController.value = new AbortController()
  healthCheckRunning.value = true
  healthCheckMessage.value = ""
  healthCheckError.value = ""
  try {
    const result = await apiPost<HealthCheckResult>(
      `/api/models/presets/${encodeURIComponent(selectedId.value)}/health-check`,
      {},
      healthCheckController.value.signal,
    )
    if (!result.ok) {
      throw new Error(result.message || "健康检查失败")
    }
    healthCheckMessage.value = result.message || "健康检查通过"
  } catch (error) {
    // Ignore abort errors - they're expected when cancelling
    if (error instanceof Error && error.name === 'AbortError') {
      return
    }
    healthCheckError.value = error instanceof Error ? error.message : "健康检查失败"
  } finally {
    healthCheckRunning.value = false
    healthCheckController.value = null
  }
}

const selectedPresetHeading = computed(() => {
  if (!draft.value) {
    return "先选择一个 Preset"
  }
  if (draft.value.preset_id.trim()) {
    return draft.value.preset_id
  }
  const derived = derivePresetId(draft.value.provider_id, draft.value.model)
  return derived || "新建模型 Preset"
})

const presetEditorButtonLabel = computed(() => {
  if (!draft.value) {
    return "打开 Preset 设置"
  }
  return draft.value.preset_id.trim() ? "打开 Preset 设置" : "继续填写新 Preset"
})

const selectedPresetCapabilities = computed(() => {
  return draft.value?.capabilities ?? []
})

const relatedBindings = computed(() =>
  bindings.value.filter((item) => (selectedId.value ? item.binding.preset_ids.includes(selectedId.value) : false)),
)

const selectedBindingSnapshot = computed(() => {
  if (relatedBindings.value.length === 0) {
    return null
  }
  return (
    relatedBindings.value.find((item) => item.binding.binding_id === selectedBindingId.value)
    ?? relatedBindings.value[0]
    ?? null
  )
})

async function syncBindingSelection(preferredBindingId = ""): Promise<void> {
  const nextBinding =
    relatedBindings.value.find((item) => item.binding.binding_id === preferredBindingId)
    ?? relatedBindings.value.find((item) => item.binding.binding_id === selectedBindingId.value)
    ?? relatedBindings.value[0]
    ?? null
  selectedBindingId.value = nextBinding?.binding.binding_id || ""
  bindingDraft.value = nextBinding ? { ...nextBinding.binding, preset_ids: [...nextBinding.binding.preset_ids] } : null
  if (!nextBinding) {
    bindingPreview.value = null
    return
  }
  try {
    bindingPreview.value = await apiGet<EffectiveTargetPreview>(
      `/api/models/targets/${encodeURIComponent(nextBinding.binding.target_id)}/effective`,
    )
  } catch {
    bindingPreview.value = null
  }
}

function openBindingEditor(): void {
  if (!selectedBindingSnapshot.value) {
    return
  }
  bindingDraft.value = {
    ...selectedBindingSnapshot.value.binding,
    preset_ids: [...selectedBindingSnapshot.value.binding.preset_ids],
  }
  saveMessage.value = ""
  errorMessage.value = ""
  showBindingEditor.value = true
}

function closeBindingEditor(): void {
  showBindingEditor.value = false
}

async function saveBinding(): Promise<void> {
  if (!bindingDraft.value) {
    return
  }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    const result = await apiPut<MutationResult>(
      `/api/models/bindings/${encodeURIComponent(bindingDraft.value.binding_id)}`,
      {
        target_id: bindingDraft.value.target_id,
        preset_ids: bindingDraft.value.preset_ids,
        timeout_sec: bindingDraft.value.timeout_sec ?? null,
      },
    )
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "保存 Binding 失败")
    }
    saveMessage.value = "已保存"
    showBindingEditor.value = false
    bindings.value = await apiGet<BindingSnapshot[]>("/api/models/bindings")
    await syncBindingSelection(bindingDraft.value.binding_id)
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存 Binding 失败"
  }
}

onMounted(() => {
  void loadModels()
})

onBeforeUnmount(() => {
  if (litellmDebounceTimer) {
    clearTimeout(litellmDebounceTimer)
    litellmDebounceTimer = null
  }
  if (typeof document !== "undefined") {
    document.body.classList.remove("overlay-active")
  }
})
</script>

<template>
  <section class="ds-page">
    <h1>模型真源</h1>
    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Presets</p>
              <h2>模型预设</h2>
            </div>
          </div>
          <button class="ds-secondary-button" type="button" title="新建 Preset" @click="openNewPresetEditor">+</button>
        </div>
        <div class="ds-list">
          <button
            v-for="(item, i) in presets"
            :key="item.preset_id"
            class="list-item mv-preset-entrance"
            :class="{ active: item.preset_id === selectedId, [`mv-preset-${i}`]: true }"
            type="button"
            @click="void selectPreset(item.preset_id)"
          >
            <strong>{{ item.preset_id }}</strong>
            <small>{{ providerLabel(item.provider_id) }} · {{ item.model }}</small>
          </button>
        </div>
      </aside>

      <article class="ds-panel ds-panel-padding summary-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>{{ selectedPresetHeading }}</h2>
            </div>
          </div>
          <button class="ds-primary-button" type="button" :disabled="!draft" @click="openPresetEditor()">{{ presetEditorButtonLabel }}</button>
        </div>

        <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
        <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
        <p v-if="loading" class="ds-empty">正在加载模型配置...</p>

        <div v-else-if="draft && draft.provider_id" class="summary-stack">
          <div class="preset-summary-grid">
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">Provider</p>
              <strong>{{ providerLabel(draft.provider_id) }}</strong>
              <small>{{ draft.provider_id }}</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">模型</p>
              <strong>{{ draft.model || "未填写" }}</strong>
              <small>{{ draft.preset_id || "新建 Preset" }}</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">任务类型</p>
              <strong>{{ draft.task_kind }}</strong>
              <small>{{ selectedPresetCapabilities.length }} 个能力标签</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">上下文窗口</p>
              <strong>{{ draft.context_window || "—" }}</strong>
              <small>max output {{ draft.max_output_tokens || "—" }}</small>
            </article>
          </div>

          <div class="ds-surface ds-card-padding-sm capability-preview">
            <div class="capability-preview-head">
              <div>
                <h3>能力摘要</h3>
              </div>
              <button class="ds-secondary-button" type="button" @click="openPresetEditor()">编辑详情</button>
            </div>
            <div v-if="selectedPresetCapabilities.length > 0" class="ds-chip-row">
              <span v-for="capability in selectedPresetCapabilities" :key="capability" class="ds-chip">
                {{ capability }}
              </span>
            </div>
            <p v-else class="ds-empty inline-empty">这个 Preset 还没有声明附加能力。</p>
          </div>

          <div v-if="selectedBindingSnapshot" class="binding-editor">
            <div class="capability-preview-head">
              <div>
                <h3>Binding 预览</h3>
              </div>
              <button class="ds-secondary-button" type="button" @click="openBindingEditor()">打开 Binding 设置</button>
            </div>
            <div class="binding-meta-grid">
              <article class="ds-surface ds-card-padding-sm binding-meta-card">
                <p class="summary-label">State</p>
                <strong class="meta-value" :class="metaValueStateClass(selectedBindingSnapshot.binding_state)">{{ selectedBindingSnapshot.binding_state }}</strong>
              </article>
              <article class="ds-surface ds-card-padding-sm binding-meta-card">
                <p class="summary-label">Effective model</p>
                <strong class="meta-value">{{ bindingPreview?.request?.model || draft.model || "—" }}</strong>
              </article>
              <article class="ds-surface ds-card-padding-sm binding-meta-card">
                <p class="summary-label">Preset</p>
                <strong class="meta-value">{{ bindingPreview?.request?.preset_id || selectedBindingSnapshot.binding.preset_ids[0] || "—" }}</strong>
              </article>
            </div>
            <p class="binding-fallback-text">fallback: {{ selectedBindingSnapshot.binding.preset_ids.join(" -> ") }}</p>
          </div>
        </div>
        <div v-else-if="draft" class="ds-empty">
          <p>点击「+ 新建」或「继续填写新 Preset」开始配置。</p>
        </div>
        <p v-else class="ds-empty">当前没有可展示的 Preset。</p>
      </article>

      <aside class="ds-panel ds-panel-padding binding-sidebar">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Bindings</p>
              <h2>目标绑定</h2>
            </div>
          </div>
        </div>
        <div class="ds-list">
          <button
            v-for="(item, i) in relatedBindings"
            :key="item.binding.binding_id"
            class="list-item mv-binding-entrance"
            :class="{ active: item.binding.binding_id === selectedBindingId, [`mv-binding-${i}`]: true }"
            type="button"
            @click="void syncBindingSelection(item.binding.binding_id)"
          >
            <strong>{{ item.binding.target_id }}</strong>
            <small>{{ item.binding.binding_id }}</small>
            <span :class="bindingStateClass(item.binding_state)">{{ item.binding_state }}</span>
          </button>
        </div>
      </aside>
    </div>

    <Teleport to="body">
      <Transition name="mv-sidesheet">
      <div v-if="showPresetEditor && draft" class="modal-backdrop side-sheet-backdrop" @click.self="closePresetEditor()" role="dialog" aria-modal="true">
        <article class="modal-shell side-sheet-shell">
          <div class="modal-head">
            <div>
              <p class="ds-eyebrow">Preset Settings</p>
              <h2>{{ draft.preset_id || "新建模型 Preset" }}</h2>
            </div>
            <button class="ds-ghost-button" type="button" @click="closePresetEditor()">关闭</button>
          </div>

          <div class="side-sheet-body">
            <p v-if="healthCheckMessage" class="ds-status is-ok">{{ healthCheckMessage }}</p>
            <p v-if="healthCheckError" class="ds-status is-error">{{ healthCheckError }}</p>
            <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
            <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>

            <!-- Basic fields -->
            <div class="ds-form-grid preset-fields-grid">
              <label v-if="selectedId" class="ds-field">
                <span>Preset ID</span>
                <input class="ds-input" :value="draft.preset_id" type="text" readonly />
              </label>
              <label v-else class="ds-field">
                <span>Preset ID</span>
                <input
                  class="ds-input"
                  v-model="draft.preset_id"
                  type="text"
                  :placeholder="derivePresetId(draft.provider_id, draft.model) || '留空时自动生成'"
                />
              </label>
              <label class="ds-field">
                <span>Provider</span>
                <CustomSelect
                  :model-value="draft.provider_id"
                  :options="[{ value: '', label: '请选择' }, ...providers.map(p => ({ value: p.provider_id, label: p.name || p.provider_id }))]"
                  placeholder="请选择"
                  @update:model-value="(v: string) => { if (draft) draft.provider_id = v }"
                />
              </label>
              <label class="ds-field">
                <span>模型名</span>
                <input class="ds-input" v-model="draft.model" type="text" @input="draft && queryLitellmInfo(draft.model, providers.find(p => p.provider_id === draft!.provider_id)?.kind || '')" />
              </label>
              <label class="ds-field">
                <span>任务类型</span>
                <CustomSelect
                  :model-value="draft.task_kind"
                  :options="taskKindOptions.map(k => ({ value: k, label: k }))"
                  @update:model-value="(v: string) => { if (draft) draft.task_kind = v as any }"
                />
              </label>
            </div>

            <!-- Model info (auto-detected) -->
            <div class="sheet-section">
              <div class="sheet-section-title">模型信息</div>
              <div v-if="litellmInfo?.model_info" class="sheet-info-row">
                <div class="sheet-info-item">
                  <span class="sheet-info-label">上下文窗口</span>
                  <span class="sheet-info-value">{{ draft.context_window || '—' }}</span>
                </div>
                <div class="sheet-info-item">
                  <span class="sheet-info-label">最大输出</span>
                  <span class="sheet-info-value">{{ draft.max_output_tokens || '—' }}</span>
                </div>
              </div>
              <div v-else class="ds-form-grid preset-fields-grid">
                <label class="ds-field">
                  <span>上下文窗口</span>
                  <input class="ds-input" v-model="draft.context_window" type="number" min="0" />
                </label>
                <label class="ds-field">
                  <span>最大输出 Tokens</span>
                  <input class="ds-input" v-model="draft.max_output_tokens" type="number" min="0" />
                </label>
              </div>
            </div>

            <!-- Capabilities -->
            <div class="sheet-section">
              <div class="sheet-section-title">能力</div>
              <div class="cap-chips">
                <button
                  v-for="cap in capabilityOptions"
                  :key="cap"
                  type="button"
                  class="cap-chip"
                  :class="{ 'is-active': draft.capabilities.includes(cap) }"
                  @click="toggleCapability(cap, !draft.capabilities.includes(cap))"
                >{{ cap }}</button>
              </div>
            </div>

            <!-- Model params -->
            <div class="sheet-section">
              <div class="sheet-section-title">模型参数{{ litellmInfo?.supported_params?.length ? ` (${litellmInfo.supported_params.length} 个可调参数)` : '' }}</div>
              <div v-if="litellmInfo?.supported_params?.length">
                <ModelParamEditor
                  :supported-params="litellmInfo.supported_params"
                  :model-value="parsedModelParams"
                  :param-hints="litellmInfo.param_hints"
                  @update:model-value="onModelParamsChange"
                />
              </div>
              <label v-else class="ds-field">
                <span>模型参数(JSON)</span>
                <textarea class="ds-textarea ds-mono" v-model="draft.model_params_text" rows="8"></textarea>
              </label>
            </div>
          </div>

          <div class="modal-actions">
            <button class="ds-secondary-button" type="button" :disabled="healthCheckRunning || loading || !selectedId" @click="void healthCheckPreset()">
              <svg v-if="healthCheckRunning" class="mv-spin-icon" width="13" height="13" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
              </svg>
              {{ healthCheckRunning ? "检查中..." : "健康检查" }}
            </button>
            <button class="ds-secondary-button" type="button" :disabled="loading" @click="void deletePreset()">
              {{ loading ? "删除中..." : "删除" }}
            </button>
            <button class="ds-primary-button" type="button" :disabled="loading || !draft" @click="void savePreset()">
              <svg v-if="loading" class="mv-spin-icon" width="13" height="13" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
              </svg>
              {{ loading ? "保存中..." : "保存" }}
            </button>
          </div>
        </article>
      </div>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="mv-modal">
      <div v-if="showBindingEditor && bindingDraft" class="modal-backdrop" @click.self="closeBindingEditor()" role="dialog" aria-modal="true">
        <article class="modal-shell">
          <div class="modal-head">
            <div>
              <p class="ds-eyebrow">Binding Settings</p>
              <h2>{{ bindingDraft.target_id }}</h2>
            </div>
            <button class="ds-ghost-button" type="button" @click="closeBindingEditor()">关闭</button>
          </div>
          <div class="side-sheet-body">
            <label class="ds-field">
              <span>Binding ID</span>
              <input class="ds-input" :value="bindingDraft.binding_id" type="text" readonly />
            </label>
            <label class="ds-field">
              <span>Target ID</span>
              <input class="ds-input" :value="bindingDraft.target_id" type="text" readonly />
            </label>
          </div>
          <div class="modal-actions">
            <button class="ds-primary-button" type="button" @click="void saveBinding()">保存 Binding</button>
          </div>
        </article>
      </div>
      </Transition>
    </Teleport>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 320px;
  gap: 16px;
}

.sidebar-column,
.summary-column {
  min-width: 0;
}

.list-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background 120ms, border-color 120ms;
  font-family: inherit;
}

.list-item:hover {
  border-color: var(--accent);
}

.list-item.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}

.list-item strong {
  font-size: 14px;
  font-weight: 700;
}

.list-item small {
  font-size: 12px;
  color: var(--muted);
}

.list-item.active small {
  color: var(--accent);
  opacity: 0.7;
}

.compact-head {
  margin-bottom: 14px;
}

.summary-stack {
  display: grid;
  gap: 14px;
}

.binding-sidebar {
  min-width: 0;
}

.binding-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.meta-value {
  font-size: 16px;
  color: var(--heading-strong);
}

.meta-value.is-active   { color: var(--binding-active-text); }
.meta-value.is-inactive { color: var(--binding-inactive-text); }
.meta-value.is-error    { color: var(--binding-error-text); }
.meta-value.is-unknown  { color: var(--binding-unknown-text); }

.state-chip {
  display: inline-flex;
  align-self: flex-start;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: var(--binding-inactive-bg);
  color: var(--binding-inactive-text);
}

.state-chip.is-active {
  background: var(--binding-active-bg);
  color: var(--binding-active-text);
}

.state-chip.is-inactive {
  background: var(--binding-inactive-bg);
  color: var(--binding-inactive-text);
}

.state-chip.is-error {
  background: var(--binding-error-bg);
  color: var(--binding-error-text);
}

.state-chip.is-unknown {
  background: var(--binding-unknown-bg);
  color: var(--binding-unknown-text);
}

.binding-fallback-text {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.preset-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  display: grid;
  gap: 6px;
}

.summary-card strong {
  font-size: 18px;
  color: var(--heading-strong);
}

.summary-card small,
.summary-label {
  color: var(--muted);
}

.summary-label {
  margin: 0;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.capability-preview {
  display: grid;
  gap: 12px;
}

.capability-preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.capability-preview-head h3 {
  margin: 0;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.5);
}

.side-sheet-backdrop {
  display: block;
  place-items: initial;
  padding: 0;
  overflow: hidden;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  background: rgba(0, 0, 0, 0.4);
}

.modal-shell {
  width: min(980px, 100%);
  max-height: min(90vh, 960px);
  overflow: auto;
  box-sizing: border-box;
  border-radius: 28px;
  padding: 24px;
  background: var(--panel);
  border: 1px solid var(--panel-line-soft);
  box-shadow: var(--shadow-soft);
}

.side-sheet-shell {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  max-width: 680px;
  max-height: 100dvh;
  height: 100dvh;
  margin: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 1;
  border-radius: 28px 0 0 28px;
  padding: 22px 20px 18px;
  box-shadow: -18px 0 64px rgba(0, 0, 0, 0.34);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.side-sheet-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  gap: 0;
  padding-right: 4px;
  align-content: start;
}

.modal-head h2 {
  margin: 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--panel-line-soft);
  background: var(--panel);
  flex-wrap: wrap;
  flex-shrink: 0;
}

.inline-empty {
  margin-top: 10px;
}

.preset-fields-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding-bottom: 4px;
}

.sheet-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 14px;
  border-top: 1px solid var(--panel-line-soft);
}

.sheet-section-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.sheet-info-row {
  display: flex;
  gap: 24px;
}

.sheet-info-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sheet-info-label {
  font-size: 11px;
  color: var(--muted);
}

.sheet-info-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--heading-strong);
  font-variant-numeric: tabular-nums;
}

.cap-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cap-chip {
  padding: 6px 14px;
  border-radius: 10px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel-strong);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 150ms ease;
  font-family: inherit;
}

.cap-chip.is-active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}

.cap-chip:hover {
  border-color: var(--accent);
}

@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .preset-summary-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .capability-preview-head,
  .modal-head {
    display: grid;
  }

  .modal-shell {
    padding: 18px;
  }

  .side-sheet-shell {
    width: 100vw;
    border-radius: 0;
    padding: 18px 16px 16px;
  }

  .preset-fields-grid {
    grid-template-columns: 1fr;
  }
}

/* ── Preset list stagger entrance ── */
.mv-preset-entrance {
  opacity: 0;
  transform: translateX(-8px);
  animation: mv-item-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}
.mv-preset-0  { animation-delay: 20ms; }
.mv-preset-1  { animation-delay: 60ms; }
.mv-preset-2  { animation-delay: 100ms; }
.mv-preset-3  { animation-delay: 140ms; }
.mv-preset-4  { animation-delay: 180ms; }
.mv-preset-5  { animation-delay: 220ms; }
.mv-preset-6  { animation-delay: 260ms; }
.mv-preset-7  { animation-delay: 300ms; }

/* ── Binding list stagger entrance ── */
.mv-binding-entrance {
  opacity: 0;
  transform: translateX(-6px);
  animation: mv-item-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}
.mv-binding-0 { animation-delay: 40ms; }
.mv-binding-1 { animation-delay: 80ms; }
.mv-binding-2 { animation-delay: 120ms; }
.mv-binding-3 { animation-delay: 160ms; }

@keyframes mv-item-in {
  to { opacity: 1; transform: translateX(0); }
}

/* ── List item hover slide ── */
.list-item {
  transition: background 140ms ease, border-color 140ms ease, transform 140ms cubic-bezier(0.25, 1, 0.5, 1);
}

.list-item:hover {
  transform: translateX(3px);
}

.list-item.active {
  transform: translateX(2px);
}

/* ── Capability chip hover ── */
.cap-chip {
  transition: all 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.cap-chip:hover {
  transform: scale(1.06);
}

.cap-chip:active {
  transform: scale(0.97);
}

.cap-chip.is-active {
  transition: all 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

/* ── Side-sheet slide in from right ── */
.mv-sidesheet-enter-active {
  animation: mv-sheet-in 320ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.mv-sidesheet-leave-active {
  animation: mv-sheet-out 220ms cubic-bezier(0.4, 0, 1, 1) forwards;
}

@keyframes mv-sheet-in {
  from { opacity: 0; transform: translateX(40px); }
  to   { opacity: 1; transform: translateX(0); }
}

@keyframes mv-sheet-out {
  from { opacity: 1; transform: translateX(0); }
  to   { opacity: 0; transform: translateX(30px); }
}

/* ── Binding modal fade + scale ── */
.mv-modal-enter-active {
  animation: mv-modal-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.mv-modal-leave-active {
  animation: mv-modal-out 180ms cubic-bezier(0.4, 0, 1, 1) forwards;
}

.mv-modal-enter-active .modal-shell {
  animation: mv-modal-shell-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.mv-modal-leave-active .modal-shell {
  animation: mv-modal-shell-out 200ms cubic-bezier(0.4, 0, 1, 1) forwards;
}

@keyframes mv-modal-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes mv-modal-out {
  from { opacity: 1; }
  to   { opacity: 0; }
}

@keyframes mv-modal-shell-in {
  from { opacity: 0; transform: scale(0.95) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes mv-modal-shell-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(0.97) translateY(4px); }
}

/* ── Summary cards stagger ── */
.summary-card {
  opacity: 0;
  transform: translateY(8px);
  animation: mv-card-in 300ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

@keyframes mv-card-in {
  to { opacity: 1; transform: translateY(0); }
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .mv-preset-entrance,
  .mv-binding-entrance {
    opacity: 1;
    transform: none;
    animation: none;
  }
  .list-item:hover {
    transform: none;
  }
  .list-item.active {
    transform: none;
  }
  .cap-chip:hover {
    transform: none;
  }
  .mv-sidesheet-enter-active,
  .mv-sidesheet-leave-active {
    animation: none;
  }
  .mv-modal-enter-active,
  .mv-modal-leave-active,
  .mv-modal-enter-active .modal-shell,
  .mv-modal-leave-active .modal-shell {
    animation: none;
  }
  .summary-card {
    opacity: 1;
    transform: none;
    animation: none;
  }
}

/* ── Loading spinner ── */
.mv-spin-icon {
  flex-shrink: 0;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .mv-spin-icon {
    animation: none;
  }
}
</style>
