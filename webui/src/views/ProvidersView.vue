<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import CustomSelect from "../components/CustomSelect.vue"
import { apiDelete, apiGet, apiPut, peekCachedGet } from "../lib/api"
import { buildProviderSavePayload, type HeaderEntry } from "../lib/model_config_drafts"

type ProviderRecord = {
  provider_id: string
  name: string
  kind: string
  config: {
    base_url?: string
    api_key_env?: string
    api_key?: string
    anthropic_version?: string
    api_version?: string
    project_id?: string
    location?: string
    use_vertex_ai?: boolean
    default_headers?: Record<string, string>
    default_query?: Record<string, unknown>
    default_body?: Record<string, unknown>
  }
}

type MutationResult = {
  ok: boolean
  applied: boolean
  message: string
}

type ProviderDraft = {
  provider_id: string
  name: string
  kind: string
  base_url: string
  api_key_env: string
  api_key: string
  anthropic_version: string
  api_version: string
  project_id: string
  location: string
  use_vertex_ai: boolean
  default_headers: HeaderEntry[]
  default_query: Record<string, unknown>
  default_body: Record<string, unknown>
}

type ProviderKindOption = {
  value: string
  label: string
  default_base_url: string
  config_class: string
  litellm_prefix: string
}

type Catalog = {
  options: {
    provider_kinds: ProviderKindOption[]
  }
}

const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>('/api/models/providers') ?? [])
const providerKinds = ref<ProviderKindOption[]>(peekCachedGet<Catalog>('/api/ui/catalog')?.options.provider_kinds ?? [])
const selectedId = ref('')
const draft = ref<ProviderDraft | null>(null)
const loading = ref(!(providers.value.length > 0 || providerKinds.value.length > 0))
const savingProvider = ref(false)
const deletingProvider = ref(false)
const saveMessage = ref('')
const errorMessage = ref('')
const showAdvanced = ref(false)

const kindSelectOptions = computed(() =>
  providerKinds.value.map(k => ({ value: k.value, label: k.label }))
)

const currentConfigClass = computed(() => {
  if (!draft.value) return 'openai_like'
  return providerKinds.value.find(k => k.value === draft.value!.kind)?.config_class ?? 'openai_like'
})

function jsonText(value: unknown): string {
  if (!value || (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ''
  }
  return JSON.stringify(value, null, 2)
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

function blankDraft(): ProviderDraft {
  return {
    provider_id: '',
    name: '',
    kind: providerKinds.value[0]?.value || 'openai_compatible',
    base_url: '',
    api_key_env: '',
    api_key: '',
    anthropic_version: '',
    api_version: '',
    project_id: '',
    location: '',
    use_vertex_ai: false,
    default_headers: [],
    default_query: {},
    default_body: {},
  }
}

const cachedInitialProvider = providers.value[0]
if (cachedInitialProvider) {
  draft.value = toDraft(cachedInitialProvider)
  selectedId.value = cachedInitialProvider.provider_id
}

function toDraft(item: ProviderRecord): ProviderDraft {
  return {
    provider_id: item.provider_id,
    name: item.name || item.provider_id,
    kind: item.kind,
    base_url: item.config?.base_url || '',
    api_key_env: item.config?.api_key_env || '',
    api_key: item.config?.api_key || '',
    anthropic_version: item.config?.anthropic_version || '',
    api_version: item.config?.api_version || '',
    project_id: item.config?.project_id || '',
    location: item.config?.location || '',
    use_vertex_ai: Boolean(item.config?.use_vertex_ai),
    default_headers: Object.entries(item.config?.default_headers || {}).map(
      ([key, value]) => ({ key, value: String(value) })
    ),
    default_query: { ...(item.config?.default_query || {}) },
    default_body: { ...(item.config?.default_body || {}) },
  }
}

function onKindChange(newKind: string): void {
  if (!draft.value) return
  const oldDefault = providerKinds.value.find(k => k.value === draft.value!.kind)?.default_base_url ?? ''
  draft.value.kind = newKind
  const meta = providerKinds.value.find(k => k.value === newKind)
  if (meta?.default_base_url && (!draft.value.base_url || draft.value.base_url === oldDefault)) {
    draft.value.base_url = meta.default_base_url
  }
}

function addHeader(): void {
  if (!draft.value) return
  draft.value.default_headers.push({ key: '', value: '' })
}

function removeHeader(index: number): void {
  if (!draft.value) return
  draft.value.default_headers.splice(index, 1)
}

function onProviderJsonChange(field: 'default_query' | 'default_body', label: string, value: string): void {
  if (!draft.value) {
    return
  }
  try {
    draft.value[field] = parseObjectText(label, value)
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `${label} 格式错误`
  }
}

async function loadProviders(preferredId = ''): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [catalogPayload, providerList] = await Promise.all([
      apiGet<Catalog>('/api/ui/catalog'),
      apiGet<ProviderRecord[]>('/api/models/providers'),
    ])
    providerKinds.value = catalogPayload.options.provider_kinds || []
    providers.value = providerList
    const targetId = preferredId || selectedId.value || providerList[0]?.provider_id || ''
    if (targetId) {
      await selectProvider(targetId, providerList)
    } else {
      createProvider()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function selectProvider(providerId: string, existingList?: ProviderRecord[]): Promise<void> {
  selectedId.value = providerId
  const source = existingList || providers.value
  const found = source.find((item) => item.provider_id === providerId)
  if (found) {
    draft.value = toDraft(found)
    return
  }
  try {
    const payload = await apiGet<ProviderRecord>(`/api/models/providers/${encodeURIComponent(providerId)}`)
    draft.value = toDraft(payload)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载供应商失败'
  }
}

function createProvider(): void {
  selectedId.value = ''
  draft.value = blankDraft()
  saveMessage.value = ''
  errorMessage.value = ''
}

async function saveProvider(): Promise<void> {
  if (!draft.value) {
    return
  }
  const providerId = draft.value.provider_id.trim()
  if (!providerId) {
    errorMessage.value = 'Provider ID 不能为空'
    return
  }
  savingProvider.value = true
  saveMessage.value = '保存中...'
  errorMessage.value = ''
  try {
    const result = await apiPut<MutationResult>(
      `/api/models/providers/${encodeURIComponent(providerId)}`,
      buildProviderSavePayload(draft.value),
    )
    if (!result.ok || !result.applied) {
      throw new Error(result.message || '保存失败')
    }
    saveMessage.value = '已保存'
    await loadProviders(providerId)
  } catch (error) {
    saveMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    savingProvider.value = false
  }
}

async function deleteProvider(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  deletingProvider.value = true
  saveMessage.value = ''
  errorMessage.value = ''
  try {
    const result = await apiDelete<MutationResult>(`/api/models/providers/${encodeURIComponent(selectedId.value)}`)
    if (!result.ok || !result.applied) {
      throw new Error(result.message || '删除失败')
    }
    saveMessage.value = '已删除'
    selectedId.value = ''
    await loadProviders()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  } finally {
    deletingProvider.value = false
  }
}

onMounted(() => {
  void loadProviders()
})
</script>

<template>
  <section class="ds-page">
    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Providers</p>
              <h2>模型供应商</h2>
            </div>
          </div>
          <button class="ds-secondary-button round-button" type="button" @click="createProvider">+</button>
        </div>
        <div class="ds-list">
          <button
            v-for="(item, i) in providers"
            :key="item.provider_id"
            class="list-item pv-entrance"
            :class="{ active: item.provider_id === selectedId, [`pv-entrance-${i}`]: true }"
            type="button"
            @click="void selectProvider(item.provider_id)"
          >
            <strong>{{ item.name || item.provider_id }}</strong>
            <small>{{ item.provider_id }} · {{ item.kind }}</small>
          </button>
        </div>
      </aside>

      <article class="ds-panel ds-panel-padding editor-column pv-editor-entrance">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>{{ draft?.name || draft?.provider_id || '新建模型供应商' }}</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-secondary-button" type="button" :disabled="loading || savingProvider || deletingProvider || !selectedId" @click="void deleteProvider()">
              <svg v-if="deletingProvider" class="pv-spin-icon" width="13" height="13" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
              </svg>
              {{ deletingProvider ? "删除中..." : "删除" }}
            </button>
            <button class="ds-primary-button" type="button" :disabled="loading || savingProvider || deletingProvider || !draft" @click="void saveProvider()">
              <svg v-if="savingProvider" class="pv-spin-icon" width="13" height="13" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
              </svg>
              {{ savingProvider ? "保存中..." : "保存" }}
            </button>
          </div>
        </div>

        <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
        <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
        <p v-if="loading" class="ds-empty">正在加载模型供应商...</p>

        <div v-else-if="draft" class="ds-form-grid editor-grid">
          <label class="ds-field">
            <span>名称</span>
            <input class="ds-input" v-model="draft.name" type="text" placeholder="例如 OpenAI 主线路" />
          </label>
          <label class="ds-field">
            <span>Provider ID</span>
            <input class="ds-input" v-model="draft.provider_id" type="text" :readonly="Boolean(selectedId)" />
          </label>
          <div class="ds-field">
            <span>类型</span>
            <CustomSelect
              :model-value="draft.kind"
              :options="kindSelectOptions"
              placeholder="选择供应商类型"
              @update:model-value="onKindChange"
            />
          </div>
          <label class="ds-field is-span-2">
            <span>Base URL</span>
            <input class="ds-input" v-model="draft.base_url" type="text" placeholder="https://api.openai.com/v1" />
          </label>
          <label class="ds-field is-span-2">
            <span>API Key</span>
            <input class="ds-input" v-model="draft.api_key" type="password" placeholder="sk-..." />
          </label>
          <label v-if="currentConfigClass === 'anthropic'" class="ds-field is-span-2">
            <span>Anthropic Version</span>
            <input class="ds-input" v-model="draft.anthropic_version" type="text" />
          </label>

          <template v-if="currentConfigClass === 'google_gemini'">
            <label class="ds-field">
              <span>API Version</span>
              <input class="ds-input" v-model="draft.api_version" type="text" />
            </label>
            <label class="ds-field">
              <span>Project ID</span>
              <input class="ds-input" v-model="draft.project_id" type="text" />
            </label>
            <label class="ds-field">
              <span>Location</span>
              <input class="ds-input" v-model="draft.location" type="text" />
            </label>
            <label class="toggle-field ds-surface ds-card-padding-sm">
              <input v-model="draft.use_vertex_ai" type="checkbox" />
              <span>使用 Vertex AI</span>
            </label>
          </template>

          <div class="is-span-2 advanced-toggle-row">
            <button class="advanced-toggle" type="button" @click="showAdvanced = !showAdvanced">
              <svg class="advanced-arrow" :class="{ 'is-open': showAdvanced }" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              高级设置
            </button>
          </div>

          <template v-if="showAdvanced">
            <label class="ds-field is-span-2">
              <span>API Key 环境变量</span>
              <input class="ds-input" v-model="draft.api_key_env" type="text" placeholder="留空即可，直接填 API Key 更方便" />
            </label>
            <div class="ds-field is-span-2">
              <span>Extra Headers</span>
              <div class="kv-list">
                <div v-for="(entry, idx) in draft.default_headers" :key="idx" class="kv-row">
                  <input class="ds-input kv-key" v-model="entry.key" type="text" placeholder="Header name" />
                  <input class="ds-input kv-value" v-model="entry.value" type="text" placeholder="Value" />
                  <button class="kv-remove" type="button" @click="removeHeader(idx)">×</button>
                </div>
                <button class="kv-add" type="button" @click="addHeader()">+ 添加 Header</button>
              </div>
            </div>
            <label class="ds-field is-span-2">
              <span>Default Query (JSON)</span>
              <textarea
                class="ds-textarea ds-mono"
                :value="jsonText(draft.default_query)"
                rows="6"
                @change="onProviderJsonChange('default_query', 'Default Query', ($event.target as HTMLTextAreaElement).value)"
              />
            </label>
            <label class="ds-field is-span-2">
              <span>Default Body (JSON)</span>
              <textarea
                class="ds-textarea ds-mono"
                :value="jsonText(draft.default_body)"
                rows="6"
                @change="onProviderJsonChange('default_body', 'Default Body', ($event.target as HTMLTextAreaElement).value)"
              />
            </label>
          </template>
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

.advanced-toggle-row {
  padding-top: 4px;
}

.advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 0;
  border: none;
  background: none;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: color 120ms ease;
}

.advanced-toggle:hover {
  color: var(--accent);
}

.advanced-arrow {
  transition: transform 200ms ease;
}

.advanced-arrow.is-open {
  transform: rotate(180deg);
}

.kv-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.kv-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.kv-key {
  flex: 0 0 180px;
}

.kv-value {
  flex: 1;
}

.kv-remove {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--panel-line-soft);
  border-radius: 8px;
  background: none;
  color: var(--muted);
  font-size: 16px;
  cursor: pointer;
  transition: color 120ms, border-color 120ms;
}

.kv-remove:hover {
  color: var(--danger);
  border-color: var(--danger);
}

.kv-add {
  align-self: flex-start;
  padding: 6px 12px;
  border: 1px dashed var(--panel-line-soft);
  border-radius: 8px;
  background: none;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: color 120ms, border-color 120ms;
}

.kv-add:hover {
  color: var(--accent);
  border-color: var(--accent);
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .is-span-2 {
    grid-column: span 1;
  }
}

/* ── List item stagger entrance ── */
.pv-entrance {
  opacity: 0;
  transform: translateX(-8px);
  animation: pv-item-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}
.pv-entrance-0  { animation-delay: 20ms; }
.pv-entrance-1  { animation-delay: 60ms; }
.pv-entrance-2  { animation-delay: 100ms; }
.pv-entrance-3  { animation-delay: 140ms; }
.pv-entrance-4  { animation-delay: 180ms; }
.pv-entrance-5  { animation-delay: 220ms; }
.pv-entrance-6  { animation-delay: 260ms; }
.pv-entrance-7  { animation-delay: 300ms; }

@keyframes pv-item-in {
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

/* ── Editor column entrance ── */
.pv-editor-entrance {
  opacity: 0;
  transform: translateY(10px);
  animation: pv-editor-in 340ms cubic-bezier(0.25, 1, 0.5, 1) 80ms forwards;
}

@keyframes pv-editor-in {
  to { opacity: 1; transform: translateY(0); }
}

/* ── Advanced toggle arrow ── */
.advanced-arrow {
  transition: transform 220ms cubic-bezier(0.25, 1, 0.5, 1);
}

/* ── Plus button press ── */
.round-button {
  transition: transform 120ms cubic-bezier(0.25, 1, 0.5, 1), box-shadow 120ms ease;
}

.round-button:hover {
  transform: scale(1.06);
}

.round-button:active {
  transform: scale(0.94);
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .pv-entrance {
    opacity: 1;
    transform: none;
    animation: none;
  }
  .pv-editor-entrance {
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
  .round-button:hover,
  .round-button:active {
    transform: none;
  }
}

/* ── Loading spinner ── */
.pv-spin-icon {
  flex-shrink: 0;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .pv-spin-icon {
    animation: none;
  }
}
</style>
