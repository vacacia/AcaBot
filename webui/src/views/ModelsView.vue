<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

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

type TaskKind =
  | 'chat'
  | 'embedding'
  | 'rerank'
  | 'speech_to_text'
  | 'text_to_speech'
  | 'image_generation'

type Capability =
  | 'tool_calling'
  | 'reasoning'
  | 'structured_output'
  | 'image_input'
  | 'image_output'
  | 'document_input'
  | 'audio_input'
  | 'audio_output'
  | 'video_input'
  | 'video_output'

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

const TASK_KIND_OPTIONS: TaskKind[] = [
  'chat',
  'embedding',
  'rerank',
  'speech_to_text',
  'text_to_speech',
  'image_generation',
]

const CAPABILITY_OPTIONS: Capability[] = [
  'tool_calling',
  'reasoning',
  'structured_output',
  'image_input',
  'image_output',
  'document_input',
  'audio_input',
  'audio_output',
  'video_input',
  'video_output',
]

const presets = ref<PresetRecord[]>(peekCachedGet<PresetRecord[]>('/api/models/presets') ?? [])
const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>('/api/models/providers') ?? [])
const selectedId = ref('')
const draft = ref<PresetDraft | null>(null)
const loading = ref(!(presets.value.length > 0 || providers.value.length > 0))
const saveMessage = ref('')
const errorMessage = ref('')

function jsonText(value: unknown): string {
  if (!value || (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ''
  }
  return JSON.stringify(value, null, 2)
}

function blankDraft(): PresetDraft {
  return {
    preset_id: '',
    provider_id: providers.value[0]?.provider_id || '',
    model: '',
    task_kind: 'chat',
    capabilities: ['tool_calling'],
    context_window: '128000',
    max_output_tokens: '',
    model_params_text: '',
  }
}

const cachedInitialPreset = presets.value[0]
if (cachedInitialPreset) {
  draft.value = toDraft(cachedInitialPreset)
  selectedId.value = cachedInitialPreset.preset_id
}

function providerLabel(providerId: string): string {
  const provider = providers.value.find((item) => item.provider_id === providerId)
  return provider?.name || providerId
}

function toDraft(item: PresetRecord): PresetDraft {
  const capabilities = Array.isArray(item.capabilities)
    ? [...item.capabilities]
    : (item.task_kind === 'chat' ? ['tool_calling'] : [])
  return {
    preset_id: item.preset_id,
    provider_id: item.provider_id,
    model: item.model,
    task_kind: item.task_kind,
    capabilities,
    context_window: String(item.context_window || ''),
    max_output_tokens: item.max_output_tokens ? String(item.max_output_tokens) : '',
    model_params_text: jsonText(item.model_params),
  }
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
  draft.value.capabilities = CAPABILITY_OPTIONS.filter((item) => next.has(item))
}

function onCapabilityToggle(capability: Capability, event: Event): void {
  const input = event.target as HTMLInputElement | null
  toggleCapability(capability, Boolean(input?.checked))
}

function parseObjectText(label: string, value: string): Record<string, unknown> {
  const text = value.trim()
  if (!text) {
    return {}
  }
  const parsed = JSON.parse(text) as Record<string, unknown>
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed
}

async function loadPresets(preferredId = ''): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [providerList, presetList] = await Promise.all([
      apiGet<ProviderRecord[]>('/api/models/providers'),
      apiGet<PresetRecord[]>('/api/models/presets'),
    ])
    providers.value = providerList
    presets.value = presetList
    const targetId = preferredId || selectedId.value || presetList[0]?.preset_id || ''
    if (targetId) {
      await selectPreset(targetId, presetList)
    } else {
      createPreset()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载失败'
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

function createPreset(): void {
  selectedId.value = ''
  draft.value = blankDraft()
  saveMessage.value = ''
  errorMessage.value = ''
}

async function savePreset(): Promise<void> {
  if (!draft.value) {
    return
  }
  const presetId = draft.value.preset_id.trim()
  if (!presetId) {
    errorMessage.value = 'Preset ID 不能为空'
    return
  }
  if (!draft.value.provider_id) {
    errorMessage.value = '请先选择一个 Provider'
    return
  }
  saveMessage.value = '保存中...'
  errorMessage.value = ''
  try {
    const result = await apiPut<MutationResult>(`/api/models/presets/${encodeURIComponent(presetId)}`, {
      provider_id: draft.value.provider_id,
      model: draft.value.model,
      task_kind: draft.value.task_kind,
      capabilities: [...draft.value.capabilities],
      context_window: Number(draft.value.context_window || 0),
      max_output_tokens: draft.value.max_output_tokens ? Number(draft.value.max_output_tokens) : null,
      model_params: parseObjectText('模型参数', draft.value.model_params_text),
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || '保存失败')
    }
    saveMessage.value = '已保存'
    await loadPresets(presetId)
  } catch (error) {
    saveMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function deletePreset(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  saveMessage.value = ''
  errorMessage.value = ''
  try {
    const result = await apiDelete<MutationResult>(`/api/models/presets/${encodeURIComponent(selectedId.value)}`)
    if (!result.ok || !result.applied) {
      throw new Error(result.message || '删除失败')
    }
    saveMessage.value = '已删除'
    selectedId.value = ''
    await loadPresets()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  }
}

async function healthCheckPreset(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  saveMessage.value = '检查中...'
  errorMessage.value = ''
  try {
    const result = await apiPost<HealthCheckResult>(
      `/api/models/presets/${encodeURIComponent(selectedId.value)}/health-check`,
      {},
    )
    if (!result.ok) {
      throw new Error(result.message || '健康检查失败')
    }
    saveMessage.value = result.message || '健康检查通过'
  } catch (error) {
    saveMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '健康检查失败'
  }
}

onMounted(() => {
  void loadPresets()
})
</script>

<template>
  <section class="ds-page">
    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Models</p>
              <h2>模型</h2>
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
              <h2>{{ draft?.preset_id || '新建模型 Preset' }}</h2>
              <p class="ds-summary">这一页只配置 Preset，不混入供应商连接信息。</p>
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
        <p v-if="loading" class="ds-empty">正在加载模型 Preset...</p>

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
              <option v-for="taskKind in TASK_KIND_OPTIONS" :key="taskKind" :value="taskKind">
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
              v-for="capability in CAPABILITY_OPTIONS"
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
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.editor-column {
  min-width: 0;
}

.compact-head {
  margin-bottom: 14px;
}

.round-button {
  min-width: 44px;
  padding-inline: 0;
}

.list-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-white);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.list-item small {
  color: var(--muted);
}

.editor-grid {
  align-items: start;
}

.is-span-2 {
  grid-column: span 2;
}

.toggle-field {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  border-radius: 18px;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  border: 0;
}

.capability-grid legend {
  margin-bottom: 10px;
  font-weight: 600;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .is-span-2 {
    grid-column: span 1;
  }
}
</style>
