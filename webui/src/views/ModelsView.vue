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
          <button class="ds-secondary-button round-button" type="button" @click="createPreset">+</button>
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

      <article class="ds-panel ds-panel-padding editor-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>{{ draft?.preset_id || "新建模型 Preset" }}</h2>
              <p class="ds-summary">Preset 只表达“这是什么模型”，不表达“谁在用”。</p>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-secondary-button" type="button" :disabled="!selectedId" @click="void healthCheckPreset()">健康检查</button>
            <button class="ds-secondary-button" type="button" :disabled="!selectedId" @click="void deletePreset()">删除</button>
            <button class="ds-primary-button" type="button" :disabled="loading || !draft" @click="void savePreset()">保存</button>
          </div>
        </div>

        <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
        <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
        <p v-if="loading" class="ds-empty">正在加载模型配置...</p>

        <div v-else-if="draft" class="ds-form-grid editor-grid">
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
          <div class="ds-list">
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
        </aside>

        <section class="binding-editor">
          <div v-if="selectedTarget" class="binding-stack">
            <div class="binding-header">
              <div>
                <h3>{{ selectedTarget.target_id }}</h3>
                <p class="ds-summary">{{ selectedTarget.description || "没有额外说明" }}</p>
              </div>
              <div class="ds-chip-row">
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

            <p v-if="bindingSaveMessage" class="ds-status is-ok">{{ bindingSaveMessage }}</p>
            <p v-if="bindingErrorMessage" class="ds-status is-error">{{ bindingErrorMessage }}</p>

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

            <div v-if="bindingDraft" class="binding-stack">
              <label class="ds-field">
                <span>Binding ID</span>
                <input class="ds-input" v-model="bindingDraft.binding_id" type="text" readonly />
                <small class="ds-help">Binding ID 跟随当前 target 保存，不支持在这里改名。</small>
              </label>
              <label class="ds-field">
                <span>超时(秒，可选)</span>
                <input class="ds-input" v-model="bindingDraft.timeout_sec" type="number" min="0" step="0.1" />
              </label>

              <div class="ds-field">
                <span>绑定链</span>
                <p class="ds-summary">第一项是主模型，后面的顺序就是 fallback。</p>
                <div v-if="bindingDraft.preset_ids.length > 0" class="selected-presets">
                  <article
                    v-for="(presetId, index) in bindingDraft.preset_ids"
                    :key="`${presetId}:${index}`"
                    class="ds-surface ds-card-padding-sm selected-preset"
                  >
                    <div>
                      <strong>{{ index === 0 ? "主模型" : `Fallback ${index}` }}</strong>
                      <p class="ds-summary">{{ presetLabel(presetId) }}</p>
                    </div>
                    <div class="ds-actions">
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
              </div>

              <div class="binding-add-row">
                <select class="ds-select" v-model="bindingPresetCandidate">
                  <option value="">选择一个兼容 Preset</option>
                  <option v-for="preset in compatiblePresets" :key="preset.preset_id" :value="preset.preset_id">
                    {{ presetLabel(preset.preset_id) }}
                  </option>
                </select>
                <button class="ds-secondary-button" type="button" @click="addPresetToBinding()">加入绑定链</button>
              </div>

              <div class="ds-actions">
                <button class="ds-secondary-button" type="button" :disabled="!selectedBindingSnapshot || bindingLoading" @click="void deleteBinding()">删除 Binding</button>
                <button class="ds-primary-button" type="button" :disabled="bindingLoading" @click="void saveBinding()">保存 Binding</button>
              </div>
            </div>
          </div>

          <p v-else class="ds-empty">当前没有可用 target。</p>
        </section>
      </div>
    </article>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.editor-column,
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

.binding-panel {
  margin-top: 16px;
}

.binding-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.binding-stack {
  display: grid;
  gap: 14px;
}

.target-item {
  display: grid;
  gap: 6px;
}

.target-item-head {
  display: flex;
  align-items: center;
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
  gap: 10px;
  margin-top: 10px;
}

.selected-preset {
  display: grid;
  gap: 10px;
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
}

@media (max-width: 720px) {
  .binding-add-row {
    grid-template-columns: 1fr;
  }
}
</style>
