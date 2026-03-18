<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPost, apiPut } from "../lib/api"

type PresetRecord = {
  preset_id: string
  provider_id: string
  model: string
  context_window: number
  supports_tools: boolean
  supports_vision: boolean
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
  context_window: string
  supports_tools: boolean
  supports_vision: boolean
  max_output_tokens: string
  model_params_text: string
}

const presets = ref<PresetRecord[]>([])
const providers = ref<ProviderRecord[]>([])
const selectedId = ref("")
const draft = ref<PresetDraft | null>(null)
const loading = ref(true)
const saveMessage = ref("")
const errorMessage = ref("")

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
    context_window: "128000",
    supports_tools: true,
    supports_vision: false,
    max_output_tokens: "",
    model_params_text: "",
  }
}

function providerLabel(providerId: string): string {
  const provider = providers.value.find((item) => item.provider_id === providerId)
  return provider?.name || providerId
}

function toDraft(item: PresetRecord): PresetDraft {
  return {
    preset_id: item.preset_id,
    provider_id: item.provider_id,
    model: item.model,
    context_window: String(item.context_window || ""),
    supports_tools: Boolean(item.supports_tools),
    supports_vision: Boolean(item.supports_vision),
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

async function loadPresets(preferredId = ""): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const [providerList, presetList] = await Promise.all([
      apiGet<ProviderRecord[]>("/api/models/providers"),
      apiGet<PresetRecord[]>("/api/models/presets"),
    ])
    providers.value = providerList
    presets.value = presetList
    const targetId = preferredId || selectedId.value || presetList[0]?.preset_id || ""
    if (targetId) {
      await selectPreset(targetId, presetList)
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
    return
  }
  const payload = await apiGet<PresetRecord>(`/api/models/presets/${encodeURIComponent(presetId)}`)
  draft.value = toDraft(payload)
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
      context_window: Number(draft.value.context_window || 0),
      supports_tools: draft.value.supports_tools,
      supports_vision: draft.value.supports_vision,
      max_output_tokens: draft.value.max_output_tokens ? Number(draft.value.max_output_tokens) : null,
      model_params: parseObjectText("模型参数", draft.value.model_params_text),
    })
    if (!result.ok || !result.applied) {
      throw new Error(result.message || "保存失败")
    }
    saveMessage.value = "已保存"
    await loadPresets(presetId)
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
    await loadPresets()
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

onMounted(() => {
  void loadPresets()
})
</script>

<template>
  <section class="layout">
    <aside class="panel sidebar">
      <div class="sidebar-header">
        <div>
          <p class="eyebrow">Models</p>
          <h1>模型</h1>
        </div>
        <button class="ghost-button" type="button" @click="createPreset">+</button>
      </div>
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
    </aside>

    <article class="panel editor">
      <div class="editor-header">
        <div>
          <h1>{{ draft?.preset_id || "新建模型 Preset" }}</h1>
          <p class="summary">这一页只配置 Preset，不混入供应商连接信息。</p>
        </div>
        <div class="actions">
          <button class="ghost-button" type="button" :disabled="!selectedId" @click="void healthCheckPreset()">
            健康检查
          </button>
          <button class="ghost-button" type="button" :disabled="!selectedId" @click="void deletePreset()">
            删除
          </button>
          <button class="primary-button" type="button" :disabled="loading || !draft" @click="void savePreset()">
            保存
          </button>
        </div>
      </div>

      <p v-if="saveMessage" class="status ok">{{ saveMessage }}</p>
      <p v-if="errorMessage" class="status error">{{ errorMessage }}</p>
      <p v-if="loading" class="summary">正在加载模型 Preset...</p>

      <div v-else-if="draft" class="form-grid">
        <label class="field">
          <span>Preset ID</span>
          <input v-model="draft.preset_id" type="text" :readonly="Boolean(selectedId)" />
        </label>
        <label class="field">
          <span>Provider</span>
          <select v-model="draft.provider_id">
            <option value="">请选择</option>
            <option v-for="item in providers" :key="item.provider_id" :value="item.provider_id">
              {{ item.name || item.provider_id }}
            </option>
          </select>
        </label>
        <label class="field full">
          <span>模型名</span>
          <input v-model="draft.model" type="text" />
        </label>
        <label class="field">
          <span>上下文窗口</span>
          <input v-model="draft.context_window" type="number" min="0" />
        </label>
        <label class="field">
          <span>最大输出 Tokens</span>
          <input v-model="draft.max_output_tokens" type="number" min="0" />
        </label>
        <label class="field checkbox">
          <input v-model="draft.supports_tools" type="checkbox" />
          <span>支持工具调用</span>
        </label>
        <label class="field checkbox">
          <input v-model="draft.supports_vision" type="checkbox" />
          <span>支持视觉输入</span>
        </label>
        <label class="field full">
          <span>模型参数(JSON)</span>
          <textarea v-model="draft.model_params_text" rows="8"></textarea>
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
  color: #11784a;
}

.status.error {
  background: rgba(186, 41, 41, 0.08);
  color: #ba2929;
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
  color: #23334f;
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
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
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
