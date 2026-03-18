<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPut } from "../lib/api"

type CatalogPrompt = {
  prompt_ref: string
  prompt_name: string
}

type CatalogPreset = {
  preset_id: string
  model: string
}

type CatalogTool = {
  name: string
  description?: string
}

type CatalogSkill = {
  skill_name: string
  display_name?: string
  description?: string
}

type UiCatalog = {
  prompts: CatalogPrompt[]
  model_presets: CatalogPreset[]
  tools: CatalogTool[]
  skills: CatalogSkill[]
  options: {
    event_types: string[]
  }
}

type SessionRule = {
  event_type: string
  enabled: boolean
  run_mode: string
  persist_event: boolean
  memory_scopes: string[]
  tags: string[]
}

type SessionRecord = {
  display_name: string
  thread_id: string
  channel_scope: string
  ai: {
    prompt_ref: string
    model_preset_id: string
    summary_model_preset_id: string
    enabled_tools: string[]
    skills: string[]
  }
  message_response: {
    rules: SessionRule[]
  }
  other: {
    tags: string[]
  }
}

const catalog = ref<UiCatalog>({
  prompts: [],
  model_presets: [],
  tools: [],
  skills: [],
  options: {
    event_types: [],
  },
})
const sessions = ref<SessionRecord[]>([])
const selectedScope = ref("")
const draft = ref<SessionRecord | null>(null)
const activeTab = ref<"base" | "ai" | "response" | "other">("base")
const searchText = ref("")
const newScope = ref("")
const newName = ref("")
const errorText = ref("")

function cloneRecord(item: SessionRecord): SessionRecord {
  return JSON.parse(JSON.stringify(item)) as SessionRecord
}

function defaultRules(): SessionRule[] {
  return catalog.value.options.event_types.map((eventType) => ({
    event_type: eventType,
    enabled: true,
    run_mode: "respond",
    persist_event: true,
    memory_scopes: [],
    tags: [],
  }))
}

function normalizeRecord(item: SessionRecord): SessionRecord {
  const ruleMap = new Map(item.message_response.rules.map((rule) => [rule.event_type, rule]))
  return {
    ...item,
    message_response: {
      rules: catalog.value.options.event_types.map((eventType) => {
        const current = ruleMap.get(eventType)
        return current
          ? {
              ...current,
              memory_scopes: [...current.memory_scopes],
              tags: [...current.tags],
            }
          : {
              event_type: eventType,
              enabled: true,
              run_mode: "respond",
              persist_event: true,
              memory_scopes: [],
              tags: [],
            }
      }),
    },
  }
}

function emptySession(scope: string, displayName = ""): SessionRecord {
  return {
    display_name: displayName || scope,
    thread_id: scope,
    channel_scope: scope,
    ai: {
      prompt_ref: "",
      model_preset_id: "",
      summary_model_preset_id: "",
      enabled_tools: [],
      skills: [],
    },
    message_response: {
      rules: defaultRules(),
    },
    other: {
      tags: [],
    },
  }
}

async function loadCatalog(): Promise<void> {
  catalog.value = await apiGet<UiCatalog>("/api/ui/catalog")
}

async function loadSessions(preferredScope = ""): Promise<void> {
  const payload = await apiGet<{ items: SessionRecord[] }>("/api/sessions")
  sessions.value = (payload.items ?? []).map(normalizeRecord)
  const nextScope = preferredScope || selectedScope.value || sessions.value[0]?.channel_scope || ""
  if (nextScope) {
    await selectSession(nextScope)
  }
}

async function selectSession(scope: string): Promise<void> {
  const payload = await apiGet<SessionRecord>(`/api/sessions/${encodeURIComponent(scope)}`)
  selectedScope.value = scope
  draft.value = normalizeRecord(payload)
}

function startNewSession(): void {
  const scope = newScope.value.trim()
  if (!scope) return
  selectedScope.value = scope
  draft.value = emptySession(scope, newName.value.trim())
  activeTab.value = "base"
}

function filteredSessions(): SessionRecord[] {
  const keyword = searchText.value.trim().toLowerCase()
  if (!keyword) return sessions.value
  return sessions.value.filter((item) => {
    const text = `${item.display_name} ${item.channel_scope}`.toLowerCase()
    return text.includes(keyword)
  })
}

function toggleAiItem(kind: "enabled_tools" | "skills", value: string, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  if (!draft.value) return
  const next = new Set(draft.value.ai[kind])
  if (checked) next.add(value)
  else next.delete(value)
  draft.value.ai[kind] = Array.from(next)
}

function updateRuleList(eventType: string, field: "memory_scopes" | "tags", event: Event): void {
  if (!draft.value) return
  const target = draft.value.message_response.rules.find((item) => item.event_type === eventType)
  if (!target) return
  const raw = (event.target as HTMLInputElement).value
  target[field] = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

async function saveSession(): Promise<void> {
  if (!draft.value) return
  errorText.value = ""
  try {
    const saved = await apiPut<SessionRecord>(
      `/api/sessions/${encodeURIComponent(draft.value.channel_scope)}`,
      draft.value,
    )
    newScope.value = ""
    newName.value = ""
    await loadSessions(saved.channel_scope)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存 Session 失败"
  }
}

onMounted(() => {
  void loadCatalog().then(() => loadSessions())
})
</script>

<template>
  <section class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">Sessions</p>
        <h1>Session 只讲产品口径</h1>
        <p class="summary">这里不出现 binding rule、inbound rule、event policy。前端只维护 `基础信息 / AI / 消息响应 / 其他`。</p>
      </div>
      <button class="primary" type="button" @click="void saveSession()">保存当前 Session</button>
    </header>

    <div class="content">
      <aside class="sidebar panel">
        <div class="panel-header">
          <div>
            <h2>会话列表</h2>
            <p>用备注名和 Session ID 找目标会话。</p>
          </div>
        </div>
        <input v-model="searchText" type="text" placeholder="搜索 Session" />
        <div class="create-box">
          <input v-model="newScope" type="text" placeholder="新建 Session ID，例如 qq:group:42" />
          <input v-model="newName" type="text" placeholder="备注名，可选" />
          <button type="button" @click="startNewSession()">新建草稿</button>
        </div>
        <button
          v-for="item in filteredSessions()"
          :key="item.channel_scope"
          class="session-item"
          :class="{ active: item.channel_scope === selectedScope }"
          type="button"
          @click="void selectSession(item.channel_scope)"
        >
          <strong>{{ item.display_name }}</strong>
          <span>{{ item.channel_scope }}</span>
        </button>
      </aside>

      <section class="main panel">
        <div v-if="draft === null" class="empty">先从左侧选择一个 Session，或者新建一个草稿。</div>
        <template v-else>
          <div class="main-header">
            <div>
              <h2>{{ draft.display_name || "未命名 Session" }}</h2>
              <p>Session ID: {{ draft.channel_scope }}</p>
            </div>
            <div class="tabs">
              <button :class="{ active: activeTab === 'base' }" type="button" @click="activeTab = 'base'">基础信息</button>
              <button :class="{ active: activeTab === 'ai' }" type="button" @click="activeTab = 'ai'">AI</button>
              <button :class="{ active: activeTab === 'response' }" type="button" @click="activeTab = 'response'">消息响应</button>
              <button :class="{ active: activeTab === 'other' }" type="button" @click="activeTab = 'other'">其他</button>
            </div>
          </div>

          <div v-if="errorText" class="error">{{ errorText }}</div>

          <section v-if="activeTab === 'base'" class="tab-panel">
            <label>
              <span>备注名</span>
              <input v-model="draft.display_name" type="text" />
            </label>
            <label>
              <span>thread_id</span>
              <input :value="draft.thread_id" type="text" readonly />
            </label>
            <label>
              <span>channel_scope</span>
              <input v-model="draft.channel_scope" type="text" />
            </label>
          </section>

          <section v-else-if="activeTab === 'ai'" class="tab-panel">
            <label>
              <span>Prompt</span>
              <select v-model="draft.ai.prompt_ref">
                <option value="">不指定</option>
                <option v-for="item in catalog.prompts" :key="item.prompt_ref" :value="item.prompt_ref">
                  {{ item.prompt_name }}
                </option>
              </select>
            </label>
            <label>
              <span>主模型</span>
              <select v-model="draft.ai.model_preset_id">
                <option value="">不指定</option>
                <option v-for="item in catalog.model_presets" :key="item.preset_id" :value="item.preset_id">
                  {{ item.model || item.preset_id }}
                </option>
              </select>
            </label>
            <label>
              <span>摘要模型</span>
              <select v-model="draft.ai.summary_model_preset_id">
                <option value="">不指定</option>
                <option v-for="item in catalog.model_presets" :key="`summary-${item.preset_id}`" :value="item.preset_id">
                  {{ item.model || item.preset_id }}
                </option>
              </select>
            </label>

            <div class="checkbox-grid">
              <article class="checkbox-panel">
                <h3>Tools</h3>
                <label v-for="item in catalog.tools" :key="item.name" class="check-item">
                  <input
                    :checked="draft.ai.enabled_tools.includes(item.name)"
                    type="checkbox"
                    @change="toggleAiItem('enabled_tools', item.name, $event)"
                  />
                  <div>
                    <strong>{{ item.name }}</strong>
                    <p>{{ item.description || "已注册工具" }}</p>
                  </div>
                </label>
              </article>

              <article class="checkbox-panel">
                <h3>Skills</h3>
                <label v-for="item in catalog.skills" :key="item.skill_name" class="check-item">
                  <input
                    :checked="draft.ai.skills.includes(item.skill_name)"
                    type="checkbox"
                    @change="toggleAiItem('skills', item.skill_name, $event)"
                  />
                  <div>
                    <strong>{{ item.display_name || item.skill_name }}</strong>
                    <p>{{ item.description || "已安装 skill" }}</p>
                  </div>
                </label>
              </article>
            </div>
          </section>

          <section v-else-if="activeTab === 'response'" class="tab-panel rules">
            <details v-for="rule in draft.message_response.rules" :key="rule.event_type" class="rule-card">
              <summary>
                <span>{{ rule.event_type }}</span>
                <small>{{ rule.enabled ? rule.run_mode : "disabled" }}</small>
              </summary>
              <div class="rule-body">
                <label class="inline">
                  <span>是否启用</span>
                  <input v-model="rule.enabled" type="checkbox" />
                </label>
                <label>
                  <span>响应方式</span>
                  <select v-model="rule.run_mode">
                    <option value="respond">respond</option>
                    <option value="record_only">record_only</option>
                    <option value="silent_drop">silent_drop</option>
                  </select>
                </label>
                <label class="inline">
                  <span>是否保存</span>
                  <input v-model="rule.persist_event" type="checkbox" />
                </label>
                <label>
                  <span>memory scopes</span>
                  <input
                    :value="rule.memory_scopes.join(', ')"
                    type="text"
                    placeholder="例如 channel, user"
                    @input="updateRuleList(rule.event_type, 'memory_scopes', $event)"
                  />
                </label>
                <label>
                  <span>tags</span>
                  <input
                    :value="rule.tags.join(', ')"
                    type="text"
                    placeholder="例如 intake, qa"
                    @input="updateRuleList(rule.event_type, 'tags', $event)"
                  />
                </label>
              </div>
            </details>
          </section>

          <section v-else class="tab-panel">
            <label>
              <span>备注 tags</span>
              <input
                :value="draft.other.tags.join(', ')"
                type="text"
                placeholder="例如 campus, 2026"
                @input="
                  draft.other.tags = ( $event.target as HTMLInputElement ).value
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean)
                "
              />
            </label>
            <article class="note-card">
              <h3>说明</h3>
              <p>这块只留轻量补充字段。更复杂的临时运维动作不放进 Session 主表单。</p>
            </article>
          </section>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero,
.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow);
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 24px;
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
h3 {
  margin: 0;
}

.summary,
.panel-header p,
.main-header p,
.check-item p {
  margin: 8px 0 0;
  color: var(--muted);
}

.primary,
button,
input,
select {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
}

button {
  cursor: pointer;
}

.primary {
  border: 0;
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  color: #fff;
}

.content {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
}

.panel {
  padding: 18px;
}

.create-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 14px 0;
}

.session-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  text-align: left;
}

.session-item.active {
  background: var(--accent-soft);
}

.main-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.tabs {
  display: flex;
  gap: 8px;
}

.tabs button.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

label {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

label.inline {
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.checkbox-panel,
.note-card,
.rule-card {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.7);
  padding: 14px;
}

.check-item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 10px;
  margin-top: 12px;
}

.rules {
  gap: 10px;
}

.rule-card summary {
  display: flex;
  justify-content: space-between;
  cursor: pointer;
}

.rule-body {
  margin-top: 14px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.empty,
.error {
  padding: 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.64);
  color: var(--muted);
}
</style>
