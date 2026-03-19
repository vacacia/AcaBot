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

const providers = ref<ProviderRecord[]>(peekCachedGet<ProviderRecord[]>("/api/models/providers") ?? [])
const providerKinds = ref<string[]>(peekCachedGet<Catalog>("/api/ui/catalog")?.options.provider_kinds ?? [])
const selectedId = ref("")
const draft = ref<ProviderDraft | null>(null)
const loading = ref(!(providers.value.length > 0 || providerKinds.value.length > 0))
const saveMessage = ref("")
const errorMessage = ref("")

function jsonText(value: unknown): string {
  if (!value || (typeof value === "object" && !Array.isArray(value) && Object.keys(value as object).length === 0)) {
    return ""
  }
  return JSON.stringify(value, null, 2)
}

function blankDraft(): ProviderDraft {
  return {
    provider_id: "",
    name: "",
    kind: providerKinds.value[0] || "openai_compatible",
    base_url: "",
    api_key_env: "",
    api_key: "",
    anthropic_version: "",
    api_version: "",
    project_id: "",
    location: "",
    use_vertex_ai: false,
    default_headers_text: "",
    default_query_text: "",
    default_body_text: "",
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
    base_url: item.config?.base_url || "",
    api_key_env: item.config?.api_key_env || "",
    api_key: item.config?.api_key || "",
    anthropic_version: item.config?.anthropic_version || "",
    api_version: item.config?.api_version || "",
    project_id: item.config?.project_id || "",
    location: item.config?.location || "",
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
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed
}

async function loadProviders(preferredId = ""): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const [catalogPayload, providerList] = await Promise.all([
      apiGet<Catalog>("/api/ui/catalog"),
      apiGet<ProviderRecord[]>("/api/models/providers"),
    ])
    providerKinds.value = catalogPayload.options.provider_kinds || []
    providers.value = providerList
    const targetId = preferredId || selectedId.value || providerList[0]?.provider_id || ""
    if (targetId) {
      await selectProvider(targetId, providerList)
    } else {
      createProvider()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败"
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
  selectedId.value = ""
  draft.value = blankDraft()
  saveMessage.value = ""
  errorMessage.value = ""
}

async function saveProvider(): Promise<void> {
  if (!draft.value) {
    return
  }
  const providerId = draft.value.provider_id.trim()
  if (!providerId) {
    errorMessage.value = "Provider ID 不能为空"
    return
  }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
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
      default_headers: parseObjectText("默认 Headers", draft.value.default_headers_text),
      default_query: parseObjectText("默认 Query", draft.value.default_query_text),
      default_body: parseObjectText("默认 Body", draft.value.default_body_text),
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "保存失败")
    }
    saveMessage.value = "已保存"
    await loadProviders(providerId)
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function deleteProvider(): Promise<void> {
  if (!selectedId.value) {
    return
  }
  saveMessage.value = ""
  errorMessage.value = ""
  try {
    const result = await apiDelete<MutationResult>(`/api/models/providers/${encodeURIComponent(selectedId.value)}`)
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "删除失败")
    }
    saveMessage.value = "已删除"
    selectedId.value = ""
    await loadProviders()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "删除失败"
  }
}

onMounted(() => {
  void loadProviders()
})
</script>

<template>
  <section class="layout">
    <aside class="panel sidebar">
      <div class="sidebar-header">
        <div>
          <p class="eyebrow">Providers</p>
          <h1>模型供应商</h1>
        </div>
        <button class="ghost-button" type="button" @click="createProvider">+</button>
      </div>
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
    </aside>

    <article class="panel editor">
      <div class="editor-header">
        <div>
          <h1>{{ draft?.name || draft?.provider_id || "新建模型供应商" }}</h1>
          <p class="summary">这里只配置连接信息，不和模型 Preset 混在一起。</p>
        </div>
        <div class="actions">
          <button class="ghost-button" type="button" :disabled="!selectedId" @click="void deleteProvider()">
            删除
          </button>
          <button class="primary-button" type="button" :disabled="loading || !draft" @click="void saveProvider()">
            保存
          </button>
        </div>
      </div>

      <p v-if="saveMessage" class="status ok">{{ saveMessage }}</p>
      <p v-if="errorMessage" class="status error">{{ errorMessage }}</p>
      <p v-if="loading" class="summary">正在加载模型供应商...</p>

      <div v-else-if="draft" class="form-grid">
        <label class="field">
          <span>名称</span>
          <input v-model="draft.name" type="text" placeholder="例如 OpenAI 主线路" />
        </label>
        <label class="field">
          <span>Provider ID</span>
          <input v-model="draft.provider_id" type="text" :readonly="Boolean(selectedId)" />
        </label>
        <label class="field">
          <span>类型</span>
          <select v-model="draft.kind">
            <option v-for="kind in providerKinds" :key="kind" :value="kind">{{ kind }}</option>
          </select>
        </label>
        <label class="field full">
          <span>Base URL</span>
          <input v-model="draft.base_url" type="text" />
        </label>
        <label class="field">
          <span>API Key 环境变量</span>
          <input v-model="draft.api_key_env" type="text" />
        </label>
        <label class="field">
          <span>API Key</span>
          <input v-model="draft.api_key" type="password" />
        </label>

        <label v-if="draft.kind === 'anthropic'" class="field full">
          <span>Anthropic Version</span>
          <input v-model="draft.anthropic_version" type="text" />
        </label>

        <template v-if="draft.kind === 'google_gemini'">
          <label class="field">
            <span>API Version</span>
            <input v-model="draft.api_version" type="text" />
          </label>
          <label class="field">
            <span>Project ID</span>
            <input v-model="draft.project_id" type="text" />
          </label>
          <label class="field">
            <span>Location</span>
            <input v-model="draft.location" type="text" />
          </label>
          <label class="field checkbox">
            <input v-model="draft.use_vertex_ai" type="checkbox" />
            <span>使用 Vertex AI</span>
          </label>
        </template>

        <label class="field full">
          <span>默认 Headers(JSON)</span>
          <textarea v-model="draft.default_headers_text" rows="6"></textarea>
        </label>
        <label class="field full">
          <span>默认 Query(JSON)</span>
          <textarea v-model="draft.default_query_text" rows="6"></textarea>
        </label>
        <label class="field full">
          <span>默认 Body(JSON)</span>
          <textarea v-model="draft.default_body_text" rows="6"></textarea>
        </label>
      </div>
    </article>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
}

.panel,
.list-item,
input,
select,
textarea {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
}

.panel {
  padding: 20px;
}

.sidebar-header,
.editor-header,
.actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1,
h2,
p {
  margin: 0;
}

.summary {
  margin-top: 8px;
  color: var(--muted);
}

.list-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 12px;
  padding: 12px 14px;
  text-align: left;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
}

.list-item small {
  color: var(--muted);
}

.status {
  margin-top: 16px;
  padding: 10px 12px;
  border-radius: 12px;
}

.status.ok {
  background: rgba(17, 120, 74, 0.08);
  color: var(--success);
}

.status.error {
  background: rgba(186, 41, 41, 0.08);
  color: var(--danger);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
  margin-top: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--heading-soft);
}

.field.full {
  grid-column: 1 / -1;
}

.field.checkbox {
  flex-direction: row;
  align-items: center;
  margin-top: 28px;
}

input,
select,
textarea {
  width: 100%;
  box-sizing: border-box;
  border-radius: 12px;
  background: var(--panel-strong);
  padding: 10px 12px;
  color: var(--text);
}

input[readonly] {
  color: var(--muted);
}

.field.checkbox input {
  width: 16px;
  height: 16px;
  margin: 0;
}

textarea {
  resize: vertical;
}

.ghost-button,
.primary-button {
  border-radius: 999px;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}

.ghost-button {
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--text);
}

.primary-button {
  border: none;
  background: linear-gradient(135deg, var(--button-primary-start) 0%, var(--button-primary-end) 100%);
  color: #fff;
}

.primary-button:disabled,
.ghost-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
