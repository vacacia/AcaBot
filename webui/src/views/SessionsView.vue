<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPut, peekCachedGet } from "../lib/api"

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

type ChannelTemplate = {
  template_id: string
  label: string
  event_types: string[]
  message_filter_options: Array<{
    value: string
    label: string
  }>
  default_message_filter: string
}

type UiCatalog = {
  prompts: CatalogPrompt[]
  model_presets: CatalogPreset[]
  tools: CatalogTool[]
  skills: CatalogSkill[]
  options: {
    event_types: string[]
    event_type_labels: Record<string, string>
    session_channel_templates: ChannelTemplate[]
  }
}

type SessionRule = {
  event_type: string
  enabled: boolean
  run_mode: string
  persist_event: boolean
}

type SessionRecord = {
  display_name: string
  thread_id: string
  channel_scope: string
  channel_template_id: string
  ai: {
    prompt_ref: string
    model_preset_id: string
    summary_model_preset_id: string
    context_management: {
      strategy: string
    }
    enabled_tools: string[]
    skills: string[]
  }
  message_response: {
    rules: SessionRule[]
  }
  other: Record<string, never>
}

const responseModeOptions = [
  { value: 'respond', label: '直接回复' },
  { value: 'record_only', label: '只记不回' },
  { value: 'silent_drop', label: '忽略' },
]

const catalog = ref<UiCatalog>(
  peekCachedGet<UiCatalog>('/api/ui/catalog') ?? {
    prompts: [],
    model_presets: [],
    tools: [],
    skills: [],
    options: {
      event_types: [],
      event_type_labels: {},
      session_channel_templates: [],
    },
  },
)
const sessions = ref<SessionRecord[]>((peekCachedGet<{ items: SessionRecord[] }>('/api/sessions')?.items ?? []).map(normalizeRecord))
const selectedScope = ref('')
const draft = ref<SessionRecord | null>(null)
const activeTab = ref<'base' | 'ai' | 'response' | 'other'>('base')
const searchText = ref('')
const createScope = ref('')
const createName = ref('')
const showCreateDialog = ref(false)
const errorText = ref('')
const saveText = ref('')

function inferTemplateFromScope(scope: string): string {
  if (scope.startsWith('qq:group:')) return 'qq_group'
  if (scope.startsWith('qq:user:') || scope.startsWith('qq:private:')) return 'qq_private'
  return 'custom'
}

function templateById(templateId: string): ChannelTemplate {
  return (
    catalog.value.options.session_channel_templates.find((item) => item.template_id === templateId) || {
      template_id: 'custom',
      label: '自定义',
      event_types: catalog.value.options.event_types,
      message_filter_options: [
        { value: 'all', label: '全部消息' },
        { value: 'mention_only', label: '仅被艾特' },
        { value: 'reply_only', label: '仅被引用' },
        { value: 'mention_or_reply', label: '被艾特或被引用' },
      ],
      default_message_filter: 'all',
    }
  )
}

function currentTemplate(): ChannelTemplate {
  const templateId = draft.value?.channel_template_id || 'custom'
  return templateById(templateId)
}

function defaultRule(eventType: string, templateId: string): SessionRule {
  return {
    event_type: eventType,
    enabled: true,
    run_mode: 'respond',
    persist_event: true,
  }
}

function normalizeRule(rule: SessionRule | undefined, eventType: string, templateId: string): SessionRule {
  const base = defaultRule(eventType, templateId)
  return {
    ...base,
    ...rule,
    event_type: eventType,
  }
}

function normalizeRecord(item: SessionRecord): SessionRecord {
  const templateId = item.channel_template_id || inferTemplateFromScope(item.channel_scope)
  const template = templateById(templateId)
  const ruleMap = new Map(item.message_response.rules.map((rule) => [rule.event_type, rule]))
  return {
    ...item,
    channel_template_id: template.template_id,
    message_response: {
      rules: template.event_types.map((eventType) => normalizeRule(ruleMap.get(eventType), eventType, template.template_id)),
    },
  }
}

function emptySession(scope: string, displayName = ''): SessionRecord {
  const templateId = inferTemplateFromScope(scope)
  const template = templateById(templateId)
  return {
    display_name: displayName || scope,
    thread_id: scope,
    channel_scope: scope,
    channel_template_id: template.template_id,
    ai: {
      prompt_ref: '',
      model_preset_id: '',
      summary_model_preset_id: '',
      context_management: {
        strategy: '',
      },
      enabled_tools: [],
      skills: [],
    },
    message_response: {
      rules: template.event_types.map((eventType) => defaultRule(eventType, template.template_id)),
    },
    other: {},
  }
}

async function loadCatalog(): Promise<void> {
  catalog.value = await apiGet<UiCatalog>('/api/ui/catalog')
}

async function loadSessions(preferredScope = ''): Promise<void> {
  const payload = await apiGet<{ items: SessionRecord[] }>('/api/sessions')
  sessions.value = (payload.items ?? []).map(normalizeRecord)
  const nextScope = preferredScope || selectedScope.value || sessions.value[0]?.channel_scope || ''
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
  const scope = createScope.value.trim()
  const displayName = createName.value.trim()
  if (!scope || !displayName) return
  selectedScope.value = scope
  draft.value = emptySession(scope, displayName)
  activeTab.value = 'base'
  showCreateDialog.value = false
}

function filteredSessions(): SessionRecord[] {
  const keyword = searchText.value.trim().toLowerCase()
  if (!keyword) return sessions.value
  return sessions.value.filter((item) => {
    const text = `${item.display_name} ${item.channel_scope}`.toLowerCase()
    return text.includes(keyword)
  })
}

function sessionLabel(item: SessionRecord): string {
  return `${item.display_name}(${item.channel_scope})`
}

function ruleLabel(eventType: string): string {
  return catalog.value.options.event_type_labels[eventType] || eventType
}

function responseModeLabel(runMode: string): string {
  return responseModeOptions.find((item) => item.value === runMode)?.label || runMode
}

function ruleSummary(rule: SessionRule): string {
  return rule.enabled ? responseModeLabel(rule.run_mode) : '未启用'
}

function toggleAiItem(kind: 'enabled_tools' | 'skills', value: string, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  if (!draft.value) return
  const next = new Set(draft.value.ai[kind])
  if (checked) next.add(value)
  else next.delete(value)
  draft.value.ai[kind] = Array.from(next)
}

function changeSessionTemplate(templateId: string): void {
  if (!draft.value) return
  const template = templateById(templateId)
  const currentRules = new Map(draft.value.message_response.rules.map((rule) => [rule.event_type, rule]))
  draft.value.channel_template_id = template.template_id
  draft.value.message_response.rules = template.event_types.map((eventType) =>
    normalizeRule(currentRules.get(eventType), eventType, template.template_id),
  )
}

async function saveSession(): Promise<void> {
  if (!draft.value) return
  errorText.value = ''
  saveText.value = '保存中...'
  try {
    const saved = await apiPut<SessionRecord>(
      `/api/sessions/${encodeURIComponent(draft.value.channel_scope)}`,
      draft.value,
    )
    createScope.value = ''
    createName.value = ''
    await loadSessions(saved.channel_scope)
    saveText.value = '保存成功'
  } catch (error) {
    saveText.value = ''
    errorText.value = error instanceof Error ? error.message : '保存 Session 失败'
  }
}

onMounted(() => {
  void loadCatalog().then(() => loadSessions())
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Sessions</p>
        <h1>会话设置</h1>
        <p class="ds-summary">这里只设置会话本身的备注、AI 和消息处理方式。</p>
      </div>
      <div class="ds-actions">
        <button class="ds-primary-button" type="button" @click="void saveSession()">保存当前 Session</button>
      </div>
    </header>

    <p v-if="saveText" class="ds-status is-ok">{{ saveText }}</p>

    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <input class="ds-input" v-model="searchText" type="text" placeholder="搜索会话" />
        <div class="session-list ds-list">
          <button
            v-for="item in filteredSessions()"
            :key="item.channel_scope"
            class="session-item"
            :class="{ active: item.channel_scope === selectedScope }"
            type="button"
            @click="void selectSession(item.channel_scope)"
          >
            {{ sessionLabel(item) }}
          </button>
        </div>
        <button class="ds-secondary-button plus-button" type="button" @click="showCreateDialog = true">+</button>
      </aside>

      <section class="ds-panel ds-panel-padding main-column">
        <div v-if="showCreateDialog" class="create-dialog ds-surface ds-card-padding">
          <h2>新建会话</h2>
          <label class="ds-field">
            <span>会话 ID</span>
            <input class="ds-input" v-model="createScope" type="text" placeholder="例如 qq:group:42" />
          </label>
          <label class="ds-field">
            <span>备注名</span>
            <input class="ds-input" v-model="createName" type="text" placeholder="例如 招聘群" />
          </label>
          <div class="ds-actions">
            <button class="ds-secondary-button" type="button" @click="showCreateDialog = false">取消</button>
            <button class="ds-primary-button" type="button" @click="startNewSession()">确定</button>
          </div>
        </div>

        <div v-if="draft === null" class="ds-empty">先从左侧选择一个 Session，或者新建一个草稿。</div>
        <template v-else>
          <div class="ds-section-head compact-head">
            <div class="ds-section-title">
              <div>
                <h2>{{ draft.display_name || '未命名 Session' }}</h2>
                <p class="ds-summary">Session ID: {{ draft.channel_scope }}</p>
              </div>
            </div>
            <div class="tabs">
              <button class="tab-button" :class="{ active: activeTab === 'base' }" type="button" @click="activeTab = 'base'">基础信息</button>
              <button class="tab-button" :class="{ active: activeTab === 'ai' }" type="button" @click="activeTab = 'ai'">AI</button>
              <button class="tab-button" :class="{ active: activeTab === 'response' }" type="button" @click="activeTab = 'response'">消息响应</button>
              <button class="tab-button" :class="{ active: activeTab === 'other' }" type="button" @click="activeTab = 'other'">其他</button>
            </div>
          </div>

          <div v-if="errorText" class="ds-status is-error">{{ errorText }}</div>

          <section v-if="activeTab === 'base'" class="tab-panel ds-form-grid">
            <label class="ds-field">
              <span>备注名</span>
              <input class="ds-input" v-model="draft.display_name" type="text" />
            </label>
            <label class="ds-field">
              <span>会话 ID</span>
              <input class="ds-input" :value="draft.thread_id" type="text" readonly />
            </label>
            <label class="ds-field is-span-2">
              <span>渠道模板</span>
              <select class="ds-select" :value="draft.channel_template_id" @change="changeSessionTemplate(($event.target as HTMLSelectElement).value)">
                <option v-for="item in catalog.options.session_channel_templates" :key="item.template_id" :value="item.template_id">
                  {{ item.label }}
                </option>
              </select>
            </label>
          </section>

          <section v-else-if="activeTab === 'ai'" class="tab-panel ds-form-grid">
            <label class="ds-field">
              <span>Prompt</span>
              <select class="ds-select" v-model="draft.ai.prompt_ref">
                <option value="">不指定</option>
                <option v-for="item in catalog.prompts" :key="item.prompt_ref" :value="item.prompt_ref">{{ item.prompt_name }}</option>
              </select>
            </label>
            <label class="ds-field">
              <span>主模型</span>
              <select class="ds-select" v-model="draft.ai.model_preset_id">
                <option value="">不指定</option>
                <option v-for="item in catalog.model_presets" :key="item.preset_id" :value="item.preset_id">{{ item.model || item.preset_id }}</option>
              </select>
            </label>
            <label class="ds-field">
              <span>摘要模型</span>
              <select class="ds-select" v-model="draft.ai.summary_model_preset_id">
                <option value="">不指定</option>
                <option v-for="item in catalog.model_presets" :key="`summary-${item.preset_id}`" :value="item.preset_id">{{ item.model || item.preset_id }}</option>
              </select>
            </label>
            <label class="ds-field">
              <span>上下文管理策略</span>
              <select class="ds-select" v-model="draft.ai.context_management.strategy">
                <option value="">跟随全局</option>
                <option value="truncate">直接截断</option>
                <option value="summarize">压缩总结</option>
              </select>
            </label>

            <div class="checkbox-grid is-span-2">
              <article class="checkbox-panel ds-surface ds-card-padding-sm">
                <h3>Tools</h3>
                <label v-for="item in catalog.tools" :key="item.name" class="check-item">
                  <input
                    :checked="draft.ai.enabled_tools.includes(item.name)"
                    type="checkbox"
                    @change="toggleAiItem('enabled_tools', item.name, $event)"
                  />
                  <div>
                    <strong>{{ item.name }}</strong>
                    <p class="ds-summary compact">{{ item.description || '已注册工具' }}</p>
                  </div>
                </label>
              </article>

              <article class="checkbox-panel ds-surface ds-card-padding-sm">
                <h3>Skills</h3>
                <label v-for="item in catalog.skills" :key="item.skill_name" class="check-item">
                  <input
                    :checked="draft.ai.skills.includes(item.skill_name)"
                    type="checkbox"
                    @change="toggleAiItem('skills', item.skill_name, $event)"
                  />
                  <div>
                    <strong>{{ item.display_name || item.skill_name }}</strong>
                    <p class="ds-summary compact">{{ item.description || '已安装 skill' }}</p>
                  </div>
                </label>
              </article>
            </div>
          </section>

          <section v-else-if="activeTab === 'response'" class="tab-panel rules">
            <p class="ds-summary">当前模板：{{ currentTemplate().label }}。这里只展示这个模板真正会遇到的输入类型。</p>
            <details v-for="rule in draft.message_response.rules" :key="rule.event_type" class="rule-card ds-surface ds-card-padding-sm">
              <summary>
                <span>{{ ruleLabel(rule.event_type) }}</span>
                <small>{{ ruleSummary(rule) }}</small>
              </summary>
              <div class="rule-body">
                <label class="inline-field ds-field">
                  <span>是否启用</span>
                  <input v-model="rule.enabled" type="checkbox" />
                </label>
                <label class="ds-field">
                  <span>响应方式</span>
                  <select class="ds-select" v-model="rule.run_mode">
                    <option v-for="item in responseModeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                  </select>
                </label>
                <label class="inline-field ds-field">
                  <span>保存事件</span>
                  <input v-model="rule.persist_event" type="checkbox" />
                </label>
              </div>
            </details>
          </section>

          <section v-else class="tab-panel">
            <article class="note-card ds-surface ds-card-padding-sm">
              <h3>说明</h3>
              <p class="ds-summary">这里先留给后续扩展。当前版本不再给 Session 放标签之类的杂项字段。</p>
            </article>
          </section>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.main-column {
  min-width: 0;
}

.session-list {
  flex: 1;
  overflow: auto;
  margin-top: 14px;
}

.session-item {
  width: 100%;
  display: block;
  margin-bottom: 10px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-white);
  color: var(--text);
  padding: 12px 14px;
  cursor: pointer;
}

.session-item.active,
.tab-button.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

.plus-button {
  width: 100%;
  margin-top: 8px;
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

.compact-head {
  margin-bottom: 16px;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tab-button {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
  cursor: pointer;
}

.tab-panel {
  display: grid;
  gap: 14px;
}

.is-span-2 {
  grid-column: span 2;
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.checkbox-panel,
.note-card,
.rule-card {
  border-radius: 18px;
}

.check-item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 10px;
  margin-top: 12px;
}

.compact {
  margin-top: 4px;
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

.inline-field {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
}

.create-dialog {
  margin-bottom: 16px;
  border-radius: 18px;
}

@media (max-width: 1180px) {
  .layout,
  .checkbox-grid,
  .rule-body {
    grid-template-columns: 1fr;
  }

  .is-span-2 {
    grid-column: span 1;
  }
}
</style>
