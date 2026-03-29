<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

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

type CatalogPayload = {
  model_bindings?: ModelBindingSnapshot[]
  options?: {
    model_task_kinds?: TaskKind[]
    model_capabilities?: Capability[]
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

type ModelTargetRecord = {
  target_id: string
  task_kind: TaskKind
  source_kind: "system" | "agent" | "plugin"
  owner_id: string
  description: string
  required: boolean
  allow_fallbacks: boolean
  required_capabilities: Capability[]
  metadata?: Record<string, string>
}

type ModelBindingRecord = {
  binding_id: string
  target_id: string
  preset_ids: string[]
  timeout_sec?: number | null
}

type ModelBindingSnapshot = {
  binding: ModelBindingRecord
  binding_state: string
  target_present: boolean
  message: string
}

type EffectiveTargetModel = {
  target_type: string
  target_id: string
  source: string
  request?: {
    provider_id?: string
    preset_id?: string
    provider_kind?: string
    model?: string
  } | null
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

type BindingDraft = {
  binding_id: string
  target_id: string
  preset_ids: string[]
  timeout_sec: string
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

const presets = ref<PresetRecord[]>(peekCachedGet<PresetRecord[]>("/api/models/presets") ?? [])
const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>("/api/models/providers") ?? [])
const targets = ref<ModelTargetRecord[]>(peekCachedGet<ModelTargetRecord[]>("/api/models/targets") ?? [])
const bindingSnapshots = ref<ModelBindingSnapshot[]>(cachedCatalog?.model_bindings ?? [])

const selectedId = ref("")
const selectedTargetId = ref("")
const draft = ref<PresetDraft | null>(null)
const bindingDraft = ref<BindingDraft | null>(null)
const effectiveTarget = ref<EffectiveTargetModel | null>(null)
const bindingPresetCandidate = ref("")
const showPresetEditor = ref(false)
const showBindingEditor = ref(false)

const loading = ref(true)
const saveMessage = ref("")
const errorMessage = ref("")
const bindingLoading = ref(false)
const bindingSaveMessage = ref("")
const bindingErrorMessage = ref("")

function jsonText(value: unknown): string {
  if (!value || (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ""
  }
  return JSON.stringify(value, null, 2)
}

function blankDraft(): PresetDraft {
  return {
    preset_id: "",
    provider_id: providers.value[0]?.provider_id || "",
    model: "",
    task_kind: "chat",
    capabilities: ["tool_calling"],
    context_window: "128000",
    max_output_tokens: "",
    model_params_text: "",
  }
}

function bindingIdForTarget(targetId: string): string {
  return `binding:${targetId}`
}

function blankBindingDraft(targetId: string): BindingDraft {
  return {
    binding_id: bindingIdForTarget(targetId),
    target_id: targetId,
    preset_ids: [],
    timeout_sec: "",
  }
}

function providerLabel(providerId: string): string {
  const provider = providers.value.find((item) => item.provider_id === providerId)
  return provider?.name || providerId
}

function presetLabel(presetId: string): string {
  const preset = presets.value.find((item) => item.preset_id === presetId)
  if (!preset) {
    return presetId
  }
  return `${preset.preset_id} · ${providerLabel(preset.provider_id)} · ${preset.model}`
}

function stateChipClass(state: string): string {
  if (state === "resolved") {
    return "is-resolved"
  }
  if (state === "missing_target") {
    return "is-missing"
  }
  return "is-warning"
}

function targetLabel(target: ModelTargetRecord): string {
  return target.description || target.target_id
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

function toBindingDraft(snapshot: ModelBindingSnapshot | null, targetId: string): BindingDraft {
  if (snapshot) {
    return {
      binding_id: snapshot.binding.binding_id,
      target_id: snapshot.binding.target_id,
      preset_ids: [...snapshot.binding.preset_ids],
      timeout_sec: snapshot.binding.timeout_sec != null ? String(snapshot.binding.timeout_sec) : "",
    }
  }
  return blankBindingDraft(targetId)
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

function onCapabilityToggle(capability: Capability, event: Event): void {
  const input = event.target as HTMLInputElement | null
  toggleCapability(capability, Boolean(input?.checked))
}

async function loadModels(preferredPresetId = "", preferredTargetId = ""): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  bindingErrorMessage.value = ""
  try {
    const [catalogPayload, providerList, presetList, targetList, bindingList] = await Promise.all([
      apiGet<CatalogPayload>("/api/ui/catalog"),
      apiGet<ProviderRecord[]>("/api/models/providers"),
      apiGet<PresetRecord[]>("/api/models/presets"),
      apiGet<ModelTargetRecord[]>("/api/models/targets"),
      apiGet<ModelBindingSnapshot[]>("/api/models/bindings"),
    ])
    taskKindOptions.value = catalogPayload.options?.model_task_kinds ?? DEFAULT_TASK_KIND_OPTIONS
    capabilityOptions.value = catalogPayload.options?.model_capabilities ?? DEFAULT_CAPABILITY_OPTIONS
    providers.value = providerList
    presets.value = presetList
    targets.value = targetList
    bindingSnapshots.value = bindingList

    const nextPresetId = preferredPresetId || selectedId.value || presetList[0]?.preset_id || ""
    if (nextPresetId) {
      await selectPreset(nextPresetId, presetList)
    } else {
      createPreset()
    }

    const nextTargetId = preferredTargetId || selectedTargetId.value || targetList[0]?.target_id || ""
    if (nextTargetId) {
      await selectTarget(nextTargetId, targetList, bindingList)
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
    return
  }
  const payload = await apiGet<PresetRecord>(`/api/models/presets/${encodeURIComponent(presetId)}`)
  draft.value = toDraft(payload)
}

async function selectTarget(
  targetId: string,
  existingTargets?: ModelTargetRecord[],
  existingBindings?: ModelBindingSnapshot[],
): Promise<void> {
  selectedTargetId.value = targetId
  const targetList = existingTargets || targets.value
  const bindingList = existingBindings || bindingSnapshots.value
  const foundTarget = targetList.find((item) => item.target_id === targetId)
  if (!foundTarget) {
    bindingDraft.value = null
    effectiveTarget.value = null
    return
  }
  const snapshot = bindingList.find((item) => item.binding.target_id === targetId) ?? null
  bindingDraft.value = toBindingDraft(snapshot, targetId)
  bindingPresetCandidate.value = compatiblePresets.value[0]?.preset_id || ""
  bindingSaveMessage.value = ""
  bindingErrorMessage.value = ""
  try {
    effectiveTarget.value = await apiGet<EffectiveTargetModel>(
      `/api/models/targets/${encodeURIComponent(targetId)}/effective`,
    )
  } catch {
    effectiveTarget.value = null
  }
}

function createPreset(): void {
  selectedId.value = ""
  draft.value = blankDraft()
  saveMessage.value = ""
  errorMessage.value = ""
}

function openNewPresetEditor(): void {
  createPreset()
  showPresetEditor.value = true
}

function openPresetEditor(): void {
  if (!draft.value) {
    return
  }
  showPresetEditor.value = true
}

function closePresetEditor(): void {
  showPresetEditor.value = false
}

function openBindingEditor(): void {
  if (!selectedTarget.value || !bindingDraft.value) {
    return
  }
  showBindingEditor.value = true
}

function closeBindingEditor(): void {
  showBindingEditor.value = false
}

async function savePreset(): Promise<void> {
  if (!draft.value) {
    return
  }
  const presetId = draft.value.preset_id.trim()
  if (!presetId) {
    errorMessage.value = "Preset ID 不能为空"
    return
  }
  if (!draft.value.provider_id) {
    errorMessage.value = "请先选择一个 Provider"
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
    await loadModels(presetId, selectedTargetId.value)
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
    showPresetEditor.value = false
    await loadModels("", selectedTargetId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "删除失败"
  }
}

async function healthCheckPreset(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  saveMessage.value = "检查中..."
  errorMessage.value = ""
  try {
    const result = await apiPost<HealthCheckResult>(
      `/api/models/presets/${encodeURIComponent(selectedId.value)}/health-check`,
      {},
    )
    if (!result.ok) {
      throw new Error(result.message || "健康检查失败")
    }
    saveMessage.value = result.message || "健康检查通过"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "健康检查失败"
  }
}

const selectedTarget = computed(() => {
  return targets.value.find((item) => item.target_id === selectedTargetId.value) ?? null
})

const selectedPresetCapabilities = computed(() => {
  return draft.value?.capabilities ?? []
})

const selectedBindingSnapshot = computed(() => {
  return bindingSnapshots.value.find((item) => item.binding.target_id === selectedTargetId.value) ?? null
})

const compatiblePresets = computed(() => {
  const target = selectedTarget.value
  if (!target) {
    return []
  }
  return presets.value.filter((preset) => {
    if (preset.task_kind !== target.task_kind) {
      return false
    }
    const capabilities = new Set(preset.capabilities || [])
    return target.required_capabilities.every((capability) => capabilities.has(capability))
  })
})

function addPresetToBinding(): void {
  if (!bindingDraft.value || !bindingPresetCandidate.value) {
    return
  }
  if (bindingDraft.value.preset_ids.includes(bindingPresetCandidate.value)) {
    return
  }
  bindingDraft.value.preset_ids = [...bindingDraft.value.preset_ids, bindingPresetCandidate.value]
}

function removeBindingPreset(presetId: string): void {
  if (!bindingDraft.value) {
    return
  }
  bindingDraft.value.preset_ids = bindingDraft.value.preset_ids.filter((item) => item !== presetId)
}

function moveBindingPreset(index: number, direction: number): void {
  if (!bindingDraft.value) {
    return
  }
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= bindingDraft.value.preset_ids.length) {
    return
  }
  const ordered = [...bindingDraft.value.preset_ids]
  const [moved] = ordered.splice(index, 1)
  ordered.splice(nextIndex, 0, moved)
  bindingDraft.value.preset_ids = ordered
}

async function saveBinding(): Promise<void> {
  const target = selectedTarget.value
  if (!target || !bindingDraft.value) {
    return
  }
  if (bindingDraft.value.preset_ids.length === 0) {
    bindingErrorMessage.value = "至少绑定一个 Preset，第一项就是主模型。"
    return
  }
  bindingLoading.value = true
  bindingSaveMessage.value = "保存中..."
  bindingErrorMessage.value = ""
  try {
    const bindingId = selectedBindingSnapshot.value?.binding.binding_id || bindingIdForTarget(target.target_id)
    const result = await apiPut<MutationResult>(`/api/models/bindings/${encodeURIComponent(bindingId)}`, {
      target_id: target.target_id,
      preset_ids: [...bindingDraft.value.preset_ids],
      timeout_sec: bindingDraft.value.timeout_sec ? Number(bindingDraft.value.timeout_sec) : null,
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "保存 Binding 失败")
    }
    bindingSaveMessage.value = "Binding 已保存"
    showBindingEditor.value = false
    await loadModels(selectedId.value, target.target_id)
  } catch (error) {
    bindingSaveMessage.value = ""
    bindingErrorMessage.value = error instanceof Error ? error.message : "保存 Binding 失败"
  } finally {
    bindingLoading.value = false
  }
}

async function deleteBinding(): Promise<void> {
  const snapshot = selectedBindingSnapshot.value
  if (!snapshot) {
    return
  }
  bindingLoading.value = true
  bindingSaveMessage.value = ""
  bindingErrorMessage.value = ""
  try {
    const result = await apiDelete<MutationResult>(`/api/models/bindings/${encodeURIComponent(snapshot.binding.binding_id)}`)
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "删除 Binding 失败")
    }
    bindingSaveMessage.value = "Binding 已删除"
    showBindingEditor.value = false
    await loadModels(selectedId.value, selectedTargetId.value)
  } catch (error) {
    bindingErrorMessage.value = error instanceof Error ? error.message : "删除 Binding 失败"
  } finally {
    bindingLoading.value = false
  }
}

onMounted(() => {
  void loadModels()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Models</p>
        <h1>模型真源</h1>
        <p class="ds-summary">
          Provider 负责连接，Preset 负责具体模型，Target 和 Binding 负责“系统里谁在用模型”。这一页把三层关系收在一起，不再让模块各自藏私有模型配置。
        </p>
      </div>
    </header>

    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Presets</p>
              <h2>模型预设</h2>
            </div>
          </div>
          <button class="ds-secondary-button round-button" type="button" @click="openNewPresetEditor">+</button>
        </div>
        <div class="ds-list">
          <button
            v-for="item in presets"
            :key="item.preset_id"
            class="list-item"
            :class="{ active: item.preset_id === selectedId }"
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
              <h2>{{ draft?.preset_id || "先选择一个 Preset" }}</h2>
              <p class="ds-summary">主页面只看摘要。冗长字段、能力集合和 JSON 参数都放到单独的设置弹层里编辑。</p>
            </div>
          </div>
          <button class="ds-primary-button" type="button" :disabled="!draft" @click="openPresetEditor()">打开 Preset 设置</button>
        </div>

        <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
        <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
        <p v-if="loading" class="ds-empty">正在加载模型配置...</p>

        <div v-else-if="draft" class="summary-stack">
          <div class="preset-summary-grid">
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">Provider</p>
              <strong>{{ providerLabel(draft.provider_id) }}</strong>
              <small>{{ draft.provider_id || "未选择" }}</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">模型</p>
              <strong>{{ draft.model || "未填写模型名" }}</strong>
              <small>{{ draft.preset_id || "新建 Preset" }}</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">任务类型</p>
              <strong>{{ draft.task_kind }}</strong>
              <small>{{ selectedPresetCapabilities.length }} 个能力标签</small>
            </article>
            <article class="ds-surface ds-card-padding-sm summary-card">
              <p class="summary-label">上下文窗口</p>
              <strong>{{ draft.context_window || "0" }}</strong>
              <small>max output {{ draft.max_output_tokens || "未设置" }}</small>
            </article>
          </div>

          <div class="ds-surface ds-card-padding-sm capability-preview">
            <div class="capability-preview-head">
              <div>
                <h3>能力摘要</h3>
                <p class="ds-summary">这里只展示简版标签，详细能力和参数都放进设置弹层。</p>
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
        </div>
        <p v-else class="ds-empty">当前没有可展示的 Preset。</p>
      </article>
    </div>

    <article class="ds-panel ds-panel-padding binding-panel">
      <div class="ds-section-head compact-head">
        <div class="ds-section-title">
          <div>
            <p class="ds-eyebrow">Targets</p>
            <h2>模型位点与 Binding</h2>
            <p class="ds-summary">每个 target 只管职责位点，第一项是主模型，后面的顺序就是 fallback 链。</p>
          </div>
        </div>
      </div>

      <div class="binding-layout">
        <aside class="binding-sidebar">
          <div class="ds-surface ds-card-padding-sm catalog-shell">
            <div class="catalog-head">
              <div>
                <h3>Target Catalog</h3>
                <p class="ds-summary">点击左侧职责位点，右边只显示当前选中的绑定细节。</p>
              </div>
              <div class="catalog-count">{{ targets.length }}</div>
            </div>
            <div class="ds-list target-list">
              <button
                v-for="target in targets"
                :key="target.target_id"
                class="list-item target-item"
                :class="{ active: target.target_id === selectedTargetId }"
                type="button"
                @click="void selectTarget(target.target_id)"
              >
                <div class="target-item-head">
                  <strong>{{ target.target_id }}</strong>
                  <span
                    class="state-chip"
                    :class="stateChipClass(bindingSnapshots.find((item) => item.binding.target_id === target.target_id)?.binding_state || 'unbound')"
                  >
                    {{ bindingSnapshots.find((item) => item.binding.target_id === target.target_id)?.binding_state || "unbound" }}
                  </span>
                </div>
                <small>{{ targetLabel(target) }}</small>
              </button>
            </div>
          </div>
        </aside>

        <section class="binding-editor">
          <div v-if="selectedTarget" class="binding-stack">
            <div class="ds-surface ds-card-padding-sm overview-shell">
              <div class="binding-header">
                <div class="binding-title-block">
                  <p class="ds-eyebrow">Selected Target</p>
                  <h3>{{ selectedTarget.target_id }}</h3>
                  <p class="ds-summary">{{ selectedTarget.description || "没有额外说明" }}</p>
                </div>
                <div class="ds-chip-row binding-chip-row">
                  <span class="ds-chip">{{ selectedTarget.source_kind }}</span>
                  <span class="ds-chip">{{ selectedTarget.task_kind }}</span>
                  <span v-if="selectedTarget.required" class="ds-chip">required</span>
                  <span v-if="!selectedTarget.allow_fallbacks" class="ds-chip">single-shot</span>
                  <span
                    v-for="capability in selectedTarget.required_capabilities"
                    :key="capability"
                    class="ds-chip"
                  >
                    {{ capability }}
                  </span>
                </div>
              </div>

              <div class="binding-meta ds-two-column">
                <article class="ds-surface ds-card-padding-sm binding-meta-card">
                  <h4>当前解析状态</h4>
                  <p class="meta-value">{{ selectedBindingSnapshot?.binding_state || "unbound" }}</p>
                  <p class="ds-summary">{{ selectedBindingSnapshot?.message || "这个 target 还没有 binding。" }}</p>
                </article>
                <article class="ds-surface ds-card-padding-sm binding-meta-card">
                  <h4>当前会落到</h4>
                  <p class="meta-value">{{ effectiveTarget?.request?.model || "未解析到模型" }}</p>
                  <p class="ds-summary">
                    {{ effectiveTarget?.request?.preset_id || "先绑定 Preset 才会有实际模型请求" }}
                  </p>
                </article>
              </div>
            </div>

            <p v-if="bindingSaveMessage" class="ds-status is-ok">{{ bindingSaveMessage }}</p>
            <p v-if="bindingErrorMessage" class="ds-status is-error">{{ bindingErrorMessage }}</p>

            <div v-if="bindingDraft" class="binding-stack">
              <div class="ds-surface ds-card-padding-sm chain-shell">
                <div class="chain-head">
                  <div>
                    <h4>绑定链</h4>
                    <p class="ds-summary">主页面只看当前链和解析状态；实际增删、调序、超时参数都放到单独的 Binding 设置里。</p>
                  </div>
                  <div class="chain-actions">
                    <button class="ds-secondary-button" type="button" :disabled="!selectedBindingSnapshot" @click="openBindingEditor()">打开 Binding 设置</button>
                  </div>
                </div>

                <div v-if="bindingDraft.preset_ids.length > 0" class="selected-presets">
                  <article
                    v-for="(presetId, index) in bindingDraft.preset_ids"
                    :key="`${presetId}:${index}`"
                    class="ds-surface ds-card-padding-sm selected-preset"
                  >
                    <div class="preset-rank">
                      <span class="preset-rank-label">{{ index === 0 ? "主模型" : `Fallback ${index}` }}</span>
                      <strong>{{ presetLabel(presetId) }}</strong>
                    </div>
                    <div class="preset-inline-meta">
                      <span class="ds-chip">{{ index === 0 ? "active" : "fallback" }}</span>
                    </div>
                  </article>
                </div>
                <p v-else class="ds-empty inline-empty">这个 target 还没有绑定模型。</p>
              </div>
            </div>
          </div>

          <p v-else class="ds-empty">当前没有可用 target。</p>
        </section>
      </div>
    </article>

    <Teleport to="body">
      <div v-if="showPresetEditor && draft" class="modal-backdrop" @click.self="closePresetEditor()">
        <article class="modal-shell">
          <div class="modal-head">
            <div>
              <p class="ds-eyebrow">Preset Settings</p>
              <h2>{{ draft.preset_id || "新建模型 Preset" }}</h2>
              <p class="ds-summary">长字段、能力集合和模型参数只在这里编辑，主页面保持摘要视图。</p>
            </div>
            <button class="ds-ghost-button" type="button" @click="closePresetEditor()">关闭</button>
          </div>

          <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
          <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>

          <div class="ds-form-grid editor-grid">
            <label class="ds-field">
              <span>Preset ID</span>
              <input class="ds-input" v-model="draft.preset_id" type="text" :readonly="Boolean(selectedId)" />
            </label>
            <label class="ds-field">
              <span>Provider</span>
              <select class="ds-select" v-model="draft.provider_id">
                <option value="">请选择</option>
                <option v-for="item in providers" :key="item.provider_id" :value="item.provider_id">
                  {{ item.name || item.provider_id }}
                </option>
              </select>
            </label>
            <label class="ds-field is-span-2">
              <span>模型名</span>
              <input class="ds-input" v-model="draft.model" type="text" />
            </label>
            <label class="ds-field">
              <span>任务类型</span>
              <select class="ds-select" v-model="draft.task_kind">
                <option v-for="taskKind in taskKindOptions" :key="taskKind" :value="taskKind">
                  {{ taskKind }}
                </option>
              </select>
            </label>
            <label class="ds-field">
              <span>上下文窗口</span>
              <input class="ds-input" v-model="draft.context_window" type="number" min="0" />
            </label>
            <label class="ds-field">
              <span>最大输出 Tokens</span>
              <input class="ds-input" v-model="draft.max_output_tokens" type="number" min="0" />
            </label>
            <fieldset class="ds-field is-span-2 capability-grid">
              <legend>能力集合</legend>
              <label
                v-for="capability in capabilityOptions"
                :key="capability"
                class="toggle-field ds-surface ds-card-padding-sm"
              >
                <input
                  :checked="draft.capabilities.includes(capability)"
                  type="checkbox"
                  @change="onCapabilityToggle(capability, $event)"
                />
                <span>{{ capability }}</span>
              </label>
            </fieldset>
            <label class="ds-field is-span-2">
              <span>模型参数(JSON)</span>
              <textarea class="ds-textarea ds-mono" v-model="draft.model_params_text" rows="8"></textarea>
            </label>
          </div>

          <div class="modal-actions">
            <button class="ds-secondary-button" type="button" :disabled="!selectedId" @click="void healthCheckPreset()">健康检查</button>
            <button class="ds-secondary-button" type="button" :disabled="!selectedId" @click="void deletePreset()">删除</button>
            <button class="ds-primary-button" type="button" :disabled="loading || !draft" @click="void savePreset()">保存</button>
          </div>
        </article>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="showBindingEditor && selectedTarget && bindingDraft" class="modal-backdrop" @click.self="closeBindingEditor()">
        <article class="modal-shell">
          <div class="modal-head">
            <div>
              <p class="ds-eyebrow">Binding Settings</p>
              <h2>{{ selectedTarget.target_id }}</h2>
              <p class="ds-summary">把 Binding 的长表单收在这里，主页面只保留解析状态和当前链摘要。</p>
            </div>
            <button class="ds-ghost-button" type="button" @click="closeBindingEditor()">关闭</button>
          </div>

          <p v-if="bindingSaveMessage" class="ds-status is-ok">{{ bindingSaveMessage }}</p>
          <p v-if="bindingErrorMessage" class="ds-status is-error">{{ bindingErrorMessage }}</p>

          <div class="binding-config-grid">
            <label class="ds-field">
              <span>Binding ID</span>
              <input class="ds-input" v-model="bindingDraft.binding_id" type="text" readonly />
              <small class="ds-help">Binding ID 跟随当前 target 保存，不支持在这里改名。</small>
            </label>
            <label class="ds-field">
              <span>超时(秒，可选)</span>
              <input class="ds-input" v-model="bindingDraft.timeout_sec" type="number" min="0" step="0.1" />
            </label>
          </div>

          <div class="ds-surface ds-card-padding-sm modal-chain-shell">
            <div v-if="bindingDraft.preset_ids.length > 0" class="selected-presets">
              <article
                v-for="(presetId, index) in bindingDraft.preset_ids"
                :key="`${presetId}:${index}`"
                class="ds-surface ds-card-padding-sm selected-preset"
              >
                <div class="preset-rank">
                  <span class="preset-rank-label">{{ index === 0 ? "主模型" : `Fallback ${index}` }}</span>
                  <strong>{{ presetLabel(presetId) }}</strong>
                </div>
                <div class="preset-inline-actions">
                  <button class="ds-ghost-button" type="button" :disabled="index === 0" @click="moveBindingPreset(index, -1)">上移</button>
                  <button
                    class="ds-ghost-button"
                    type="button"
                    :disabled="index === bindingDraft.preset_ids.length - 1"
                    @click="moveBindingPreset(index, 1)"
                  >
                    下移
                  </button>
                  <button class="ds-ghost-button" type="button" @click="removeBindingPreset(presetId)">移除</button>
                </div>
              </article>
            </div>
            <p v-else class="ds-empty inline-empty">这个 target 还没有绑定模型。</p>

            <div class="binding-add-row">
              <select class="ds-select" v-model="bindingPresetCandidate">
                <option value="">选择一个兼容 Preset</option>
                <option v-for="preset in compatiblePresets" :key="preset.preset_id" :value="preset.preset_id">
                  {{ presetLabel(preset.preset_id) }}
                </option>
              </select>
              <button class="ds-secondary-button" type="button" @click="addPresetToBinding()">加入绑定链</button>
            </div>
          </div>

          <div class="modal-actions">
            <button class="ds-secondary-button" type="button" :disabled="!selectedBindingSnapshot || bindingLoading" @click="void deleteBinding()">删除 Binding</button>
            <button class="ds-primary-button" type="button" :disabled="bindingLoading" @click="void saveBinding()">保存 Binding</button>
          </div>
        </article>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.summary-column,
.binding-sidebar,
.binding-editor {
  min-width: 0;
}

.compact-head {
  margin-bottom: 14px;
}

.round-button {
  min-width: 44px;
  padding-inline: 0;
}

.summary-stack {
  display: grid;
  gap: 14px;
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

.binding-panel {
  margin-top: 16px;
}

.binding-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.binding-stack {
  display: grid;
  gap: 16px;
}

.catalog-shell,
.overview-shell,
.chain-shell {
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02)),
    rgba(12, 18, 42, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.07);
}

.catalog-head,
.chain-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.catalog-head h3,
.chain-head h4,
.binding-header h3 {
  margin: 0;
}

.catalog-count {
  min-width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  font-size: 18px;
  font-weight: 800;
  color: var(--heading-strong);
  background: rgba(255, 255, 255, 0.08);
}

.target-list {
  max-height: 620px;
  overflow: auto;
}

.target-item {
  display: grid;
  gap: 6px;
  align-items: start;
}

.target-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.state-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: rgba(240, 194, 71, 0.14);
  color: #9a6700;
}

.state-chip.is-resolved {
  background: rgba(59, 130, 246, 0.12);
  color: #1d4ed8;
}

.state-chip.is-missing {
  background: rgba(220, 38, 38, 0.12);
  color: #b91c1c;
}

.binding-meta {
  gap: 12px;
}

.binding-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.binding-title-block {
  display: grid;
  gap: 6px;
}

.binding-chip-row {
  justify-content: flex-end;
}

.binding-meta-card {
  display: grid;
  gap: 8px;
}

.meta-value {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--heading-strong);
}

.selected-presets {
  display: grid;
  gap: 12px;
  margin-top: 10px;
}

.selected-preset {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.preset-rank {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.preset-rank-label {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: var(--accent);
}

.preset-inline-actions {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.preset-inline-meta {
  display: inline-flex;
  justify-content: flex-end;
}

.binding-config-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1.2fr) minmax(180px, 0.8fr);
  gap: 12px;
}

.chain-actions {
  display: inline-flex;
  gap: 10px;
  flex-wrap: wrap;
}

.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(7, 10, 24, 0.7);
  backdrop-filter: blur(18px);
}

.modal-shell {
  width: min(980px, 100%);
  max-height: min(90vh, 960px);
  overflow: auto;
  border-radius: 28px;
  padding: 24px;
  background:
    linear-gradient(180deg, rgba(26, 34, 68, 0.95), rgba(11, 16, 37, 0.96)),
    rgba(10, 14, 30, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 30px 120px rgba(0, 0, 0, 0.42);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.modal-head h2 {
  margin: 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
  flex-wrap: wrap;
}

.modal-chain-shell {
  display: grid;
  gap: 14px;
  margin-top: 14px;
}

.binding-add-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.inline-empty {
  margin-top: 10px;
}

@media (max-width: 1100px) {
  .layout,
  .binding-layout {
    grid-template-columns: 1fr;
  }

  .preset-summary-grid,
  .binding-config-grid,
  .selected-preset {
    grid-template-columns: 1fr;
  }

  .binding-header,
  .catalog-head,
  .chain-head {
    grid-template-columns: 1fr;
    display: grid;
  }

  .binding-chip-row,
  .preset-inline-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 720px) {
  .binding-add-row {
    grid-template-columns: 1fr;
  }

  .capability-preview-head,
  .modal-head {
    display: grid;
  }

  .chain-actions {
    width: 100%;
  }

  .modal-shell {
    padding: 18px;
  }
}
</style>
