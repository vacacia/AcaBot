<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPut, peekCachedGet } from "../lib/api"

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
  default_headers_text: string
  default_query_text: string
  default_body_text: string
}

type Catalog = {
  options: {
    provider_kinds: string[]
  }
}

const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>('/api/models/providers') ?? [])
const providerKinds = ref<string[]>(peekCachedGet<Catalog>('/api/ui/catalog')?.options.provider_kinds ?? [])
const selectedId = ref('')
const draft = ref<ProviderDraft | null>(null)
const loading = ref(!(providers.value.length > 0 || providerKinds.value.length > 0))
const saveMessage = ref('')
const errorMessage = ref('')

function jsonText(value: unknown): string {
  if (!value || (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ''
  }
  return JSON.stringify(value, null, 2)
}

function blankDraft(): ProviderDraft {
  return {
    provider_id: '',
    name: '',
    kind: providerKinds.value[0] || 'openai_compatible',
    base_url: '',
    api_key_env: '',
    api_key: '',
    anthropic_version: '',
    api_version: '',
    project_id: '',
    location: '',
    use_vertex_ai: false,
    default_headers_text: '',
    default_query_text: '',
    default_body_text: '',
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
    default_headers_text: jsonText(item.config?.default_headers),
    default_query_text: jsonText(item.config?.default_query),
    default_body_text: jsonText(item.config?.default_body),
  }
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
  const payload = await apiGet<ProviderRecord>(`/api/models/providers/${encodeURIComponent(providerId)}`)
  draft.value = toDraft(payload)
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
  saveMessage.value = '保存中...'
  errorMessage.value = ''
  try {
    const result = await apiPut<MutationResult>(`/api/models/providers/${encodeURIComponent(providerId)}`, {
      name: draft.value.name.trim() || providerId,
      kind: draft.value.kind,
      base_url: draft.value.base_url,
      api_key_env: draft.value.api_key_env,
      api_key: draft.value.api_key,
      anthropic_version: draft.value.anthropic_version,
      api_version: draft.value.api_version,
      project_id: draft.value.project_id,
      location: draft.value.location,
      use_vertex_ai: draft.value.use_vertex_ai,
      default_headers: parseObjectText('默认 Headers', draft.value.default_headers_text),
      default_query: parseObjectText('默认 Query', draft.value.default_query_text),
      default_body: parseObjectText('默认 Body', draft.value.default_body_text),
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || '保存失败')
    }
    saveMessage.value = '已保存'
    await loadProviders(providerId)
  } catch (error) {
    saveMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function deleteProvider(): Promise<void> {
  if (!selectedId.value) {
    return
  }
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
            v-for="item in providers"
            :key="item.provider_id"
            class="list-item"
            :class="{ active: item.provider_id === selectedId }"
            type="button"
            @click="void selectProvider(item.provider_id)"
          >
            <strong>{{ item.name || item.provider_id }}</strong>
            <small>{{ item.provider_id }} · {{ item.kind }}</small>
          </button>
        </div>
      </aside>

      <article class="ds-panel ds-panel-padding editor-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>{{ draft?.name || draft?.provider_id || '新建模型供应商' }}</h2>
              <p class="ds-summary">这里只配置连接信息，不和模型 Preset 混在一起。</p>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-secondary-button" type="button" :disabled="!selectedId" @click="void deleteProvider()">删除</button>
            <button class="ds-primary-button" type="button" :disabled="loading || !draft" @click="void saveProvider()">保存</button>
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
          <label class="ds-field">
            <span>类型</span>
            <select class="ds-select" v-model="draft.kind">
              <option v-for="kind in providerKinds" :key="kind" :value="kind">{{ kind }}</option>
            </select>
          </label>
          <label class="ds-field is-span-2">
            <span>Base URL</span>
            <input class="ds-input" v-model="draft.base_url" type="text" />
          </label>
          <label class="ds-field">
            <span>API Key 环境变量</span>
            <input class="ds-input" v-model="draft.api_key_env" type="text" />
          </label>
          <label class="ds-field">
            <span>API Key</span>
            <input class="ds-input" v-model="draft.api_key" type="password" />
          </label>
          <label v-if="draft.kind === 'anthropic'" class="ds-field is-span-2">
            <span>Anthropic Version</span>
            <input class="ds-input" v-model="draft.anthropic_version" type="text" />
          </label>

          <template v-if="draft.kind === 'google_gemini'">
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

          <label class="ds-field is-span-2">
            <span>默认 Headers(JSON)</span>
            <textarea class="ds-textarea ds-mono" v-model="draft.default_headers_text" rows="6"></textarea>
          </label>
          <label class="ds-field is-span-2">
            <span>默认 Query(JSON)</span>
            <textarea class="ds-textarea ds-mono" v-model="draft.default_query_text" rows="6"></textarea>
          </label>
          <label class="ds-field is-span-2">
            <span>默认 Body(JSON)</span>
            <textarea class="ds-textarea ds-mono" v-model="draft.default_body_text" rows="6"></textarea>
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

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .is-span-2 {
    grid-column: span 1;
  }
}
</style>
