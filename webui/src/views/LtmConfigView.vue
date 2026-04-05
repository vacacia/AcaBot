<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"

import CustomSelect from "../components/CustomSelect.vue"
import { apiGet, apiPut, apiDelete, apiPost, peekCachedGet } from "../lib/api"

// ─── Types ──────────────────────────────────────────────────────────
type LtmStats = {
  total_entries: number
  conversations: number
  persons: number
  entities: number
}

type LtmEntry = {
  entry_id: string
  conversation_id: string
  topic: string
  lossless_restatement: string
  keywords: string[]
  persons: string[]
  entities: string[]
  location: string | null
  time_point: string | null
  time_interval_start: string | null
  time_interval_end: string | null
  created_at: number
  updated_at: number
  extractor_version: string
  provenance: Record<string, unknown> | null
}

type EntryListResponse = {
  entries: LtmEntry[]
  total: number
  offset: number
  limit: number
}

type SearchResult = LtmEntry & { hit_source?: string; score?: number }

type SearchTestResponse = {
  results: SearchResult[]
}

type LongTermMemoryConfig = {
  enabled: boolean
  storage_dir: string
  window_size: number
  overlap_size: number
  max_entries: number
  extractor_version: string
  required_target_ids: string[]
  missing_target_ids: string[]
  restart_required: boolean
}

type LongTermMemoryDraft = {
  enabled: boolean
  storage_dir: string
  window_size: string
  overlap_size: string
  max_entries: string
  extractor_version: string
}

type PresetRecord = {
  preset_id: string
  provider_id: string
  model: string
  task_kind: string
}

type BindingSnapshot = {
  binding: { binding_id: string; target_id: string; preset_ids: string[]; timeout_sec?: number | null }
  binding_state: string
  message: string
}

type MutationResult = { ok: boolean; applied: boolean; message: string }

const LTM_TARGETS = [
  { target_id: "system:ltm_extract", label: "提取模型", task_kind: "chat", description: "从对话中提取长期记忆" },
  { target_id: "system:ltm_query_plan", label: "检索规划", task_kind: "chat", description: "规划记忆检索策略" },
  { target_id: "system:ltm_answer", label: "答案整合", task_kind: "chat", description: "整合检索结果（可选）" },
  { target_id: "system:ltm_embed", label: "Embedding", task_kind: "embedding", description: "记忆向量化" },
]

const PAGE_SIZE = 20

// ─── Stats ──────────────────────────────────────────────────────────
const stats = ref<LtmStats>({ total_entries: 0, conversations: 0, persons: 0, entities: 0 })
const statsLoading = ref(true)

// ─── Entry list ─────────────────────────────────────────────────────
const entries = ref<LtmEntry[]>([])
const entriesTotalCount = ref(0)
const entriesOffset = ref(0)
const entriesLoading = ref(false)
const entriesError = ref("")

// Filters
const filterKeyword = ref("")
const filterConversation = ref("")
const filterPerson = ref("")
const filterDateStart = ref("")
const filterDateEnd = ref("")

// Expand & edit
const expandedEntryId = ref<string | null>(null)
const editingEntryId = ref<string | null>(null)
const editDraft = ref<{
  topic: string
  lossless_restatement: string
  keywords: string
  persons: string
  entities: string
  location: string
}>({ topic: "", lossless_restatement: "", keywords: "", persons: "", entities: "", location: "" })
const editSaving = ref(false)
const editError = ref("")

// Delete
const deletingEntryId = ref<string | null>(null)
const deleteConfirmId = ref<string | null>(null)
const bulkDeleteConfirm = ref(false)

// ─── Search test ────────────────────────────────────────────────────
const searchQuery = ref("")
const searchConversation = ref("")
const searchResults = ref<SearchResult[]>([])
const searchLoading = ref(false)
const searchError = ref("")

// ─── Settings ───────────────────────────────────────────────────────
const showSettings = ref(false)
const activeTab = ref<"manage" | "search" | "settings">("manage")
const config = ref<LongTermMemoryConfig | null>(null)
const draft = ref<LongTermMemoryDraft | null>(null)
const presets = ref<PresetRecord[]>([])
const bindings = ref<BindingSnapshot[]>([])
const settingsLoading = ref(false)
const settingsSaveMsg = ref("")
const settingsError = ref("")
const bindingSaveMsg = ref("")
const bindingError = ref("")

// ─── Computed ───────────────────────────────────────────────────────
const totalPages = computed(() => Math.max(1, Math.ceil(entriesTotalCount.value / PAGE_SIZE)))
const currentPage = computed(() => Math.floor(entriesOffset.value / PAGE_SIZE) + 1)

const conversationOptions = computed(() => {
  const seen = new Set<string>()
  for (const e of entries.value) {
    if (e.conversation_id) seen.add(e.conversation_id)
  }
  return [
    { value: "", label: "全部会话" },
    ...Array.from(seen).sort().map(c => ({ value: c, label: c })),
  ]
})

const personOptions = computed(() => {
  const seen = new Set<string>()
  for (const e of entries.value) {
    for (const p of e.persons) seen.add(p)
  }
  return [
    { value: "", label: "全部人物" },
    ...Array.from(seen).sort().map(p => ({ value: p, label: p })),
  ]
})

// ─── Helpers ────────────────────────────────────────────────────────
function formatDate(ts: number): string {
  if (!ts) return "—"
  const d = new Date(ts * 1000)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function truncate(s: string, len: number): string {
  if (!s) return ""
  return s.length > len ? s.slice(0, len) + "..." : s
}

function toLongTermMemoryDraft(c: LongTermMemoryConfig): LongTermMemoryDraft {
  return {
    enabled: Boolean(c.enabled),
    storage_dir: c.storage_dir || "long-term-memory/lancedb",
    window_size: String(c.window_size || 50),
    overlap_size: String(c.overlap_size || 10),
    max_entries: String(c.max_entries || 8),
    extractor_version: c.extractor_version || "ltm-extractor-v1",
  }
}

function compatiblePresets(taskKind: string): PresetRecord[] {
  return presets.value.filter(p => p.task_kind === taskKind)
}

function currentBinding(targetId: string): BindingSnapshot | null {
  return bindings.value.find(b => b.binding.target_id === targetId) ?? null
}

function currentPresetId(targetId: string): string {
  const b = currentBinding(targetId)
  return b?.binding.preset_ids[0] || ""
}

// ─── Data loading ───────────────────────────────────────────────────
async function loadStats(): Promise<void> {
  statsLoading.value = true
  try {
    stats.value = await apiGet<LtmStats>("/api/memory/long-term/stats")
  } catch { /* stats are non-critical */ }
  statsLoading.value = false
}

async function loadEntries(): Promise<void> {
  entriesLoading.value = true
  entriesError.value = ""
  try {
    const params = new URLSearchParams()
    params.set("offset", String(entriesOffset.value))
    params.set("limit", String(PAGE_SIZE))
    if (filterKeyword.value) params.set("keyword", filterKeyword.value)
    if (filterConversation.value) params.set("conversation_id", filterConversation.value)
    if (filterPerson.value) params.set("person", filterPerson.value)
    if (filterDateStart.value) params.set("date_start", filterDateStart.value)
    if (filterDateEnd.value) params.set("date_end", filterDateEnd.value)
    const resp = await apiGet<EntryListResponse>(`/api/memory/long-term/entries?${params.toString()}`)
    entries.value = resp.entries
    entriesTotalCount.value = resp.total
  } catch (err) {
    entriesError.value = err instanceof Error ? err.message : "加载失败"
  }
  entriesLoading.value = false
}

async function loadSettings(): Promise<void> {
  settingsLoading.value = true
  settingsError.value = ""
  try {
    const [ltmPayload, presetList, bindingList] = await Promise.all([
      apiGet<LongTermMemoryConfig>("/api/memory/long-term/config"),
      apiGet<PresetRecord[]>("/api/models/presets"),
      apiGet<BindingSnapshot[]>("/api/models/bindings"),
    ])
    config.value = ltmPayload
    draft.value = toLongTermMemoryDraft(ltmPayload)
    presets.value = presetList
    bindings.value = bindingList
  } catch (err) {
    settingsError.value = err instanceof Error ? err.message : "加载失败"
  }
  settingsLoading.value = false
}

// ─── Actions ────────────────────────────────────────────────────────
function doSearch(): void {
  entriesOffset.value = 0
  expandedEntryId.value = null
  editingEntryId.value = null
  void loadEntries()
}

function goToPage(page: number): void {
  if (page < 1 || page > totalPages.value) return
  entriesOffset.value = (page - 1) * PAGE_SIZE
  expandedEntryId.value = null
  editingEntryId.value = null
  void loadEntries()
}

function toggleExpand(entryId: string): void {
  if (editingEntryId.value === entryId) return
  expandedEntryId.value = expandedEntryId.value === entryId ? null : entryId
}

function startEdit(entry: LtmEntry): void {
  editingEntryId.value = entry.entry_id
  expandedEntryId.value = entry.entry_id
  editError.value = ""
  editDraft.value = {
    topic: entry.topic || "",
    lossless_restatement: entry.lossless_restatement || "",
    keywords: (entry.keywords || []).join(", "),
    persons: (entry.persons || []).join(", "),
    entities: (entry.entities || []).join(", "),
    location: entry.location || "",
  }
}

function cancelEdit(): void {
  editingEntryId.value = null
  editError.value = ""
}

async function saveEdit(entryId: string): Promise<void> {
  editSaving.value = true
  editError.value = ""
  try {
    const body: Record<string, unknown> = {
      topic: editDraft.value.topic,
      lossless_restatement: editDraft.value.lossless_restatement,
      keywords: editDraft.value.keywords.split(",").map(s => s.trim()).filter(Boolean),
      persons: editDraft.value.persons.split(",").map(s => s.trim()).filter(Boolean),
      entities: editDraft.value.entities.split(",").map(s => s.trim()).filter(Boolean),
    }
    if (editDraft.value.location) body.location = editDraft.value.location
    await apiPut(`/api/memory/long-term/entries/${encodeURIComponent(entryId)}`, body)
    editingEntryId.value = null
    void loadEntries()
    void loadStats()
  } catch (err) {
    editError.value = err instanceof Error ? err.message : "保存失败"
  }
  editSaving.value = false
}

async function deleteEntry(entryId: string): Promise<void> {
  deletingEntryId.value = entryId
  try {
    await apiDelete(`/api/memory/long-term/entries/${encodeURIComponent(entryId)}`)
    deleteConfirmId.value = null
    expandedEntryId.value = null
    editingEntryId.value = null
    void loadEntries()
    void loadStats()
  } catch { /* ignore */ }
  deletingEntryId.value = null
}

async function bulkDeleteByConversation(): Promise<void> {
  if (!filterConversation.value) return
  try {
    const resp = await fetch(`/api/memory/long-term/entries?conversation_id=${encodeURIComponent(filterConversation.value)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    })
    const payload = await resp.json()
    if (!resp.ok || payload.ok !== true) throw new Error(payload.error || "删除失败")
    bulkDeleteConfirm.value = false
    void loadEntries()
    void loadStats()
  } catch { /* ignore */ }
}

async function runSearchTest(): Promise<void> {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  searchError.value = ""
  searchResults.value = []
  try {
    const body: Record<string, string> = { query_text: searchQuery.value }
    if (searchConversation.value) body.conversation_id = searchConversation.value
    const resp = await apiPost<SearchTestResponse>("/api/memory/long-term/search-test", body)
    searchResults.value = resp.results
  } catch (err) {
    searchError.value = err instanceof Error ? err.message : "检索失败"
  }
  searchLoading.value = false
}

async function saveSettings(): Promise<void> {
  if (!draft.value) return
  settingsSaveMsg.value = ""
  settingsError.value = ""
  try {
    const payload = await apiPut<LongTermMemoryConfig>("/api/memory/long-term/config", {
      enabled: draft.value.enabled,
      storage_dir: draft.value.storage_dir,
      window_size: Number(draft.value.window_size || 50),
      overlap_size: Number(draft.value.overlap_size || 10),
      max_entries: Number(draft.value.max_entries || 8),
      extractor_version: draft.value.extractor_version,
    })
    config.value = payload
    draft.value = toLongTermMemoryDraft(payload)
    settingsSaveMsg.value = payload.restart_required ? "已保存，重启后生效" : "已保存"
  } catch (err) {
    settingsError.value = err instanceof Error ? err.message : "保存失败"
  }
}

async function bindPreset(targetId: string, presetId: string): Promise<void> {
  if (!presetId) return
  bindingSaveMsg.value = ""
  bindingError.value = ""
  try {
    const bindingId = `binding:${targetId.replace(/:/g, "_")}`
    const result = await apiPut<MutationResult>(`/api/models/bindings/${encodeURIComponent(bindingId)}`, {
      target_id: targetId,
      preset_ids: [presetId],
    })
    if (!result.ok || !result.applied) throw new Error(result.message || "绑定失败")
    bindingSaveMsg.value = "已绑定"
    bindings.value = await apiGet<BindingSnapshot[]>("/api/models/bindings")
  } catch (err) {
    bindingError.value = err instanceof Error ? err.message : "绑定失败"
  }
}

// ─── Pagination helpers ─────────────────────────────────────────────
const paginationPages = computed(() => {
  const total = totalPages.value
  const cur = currentPage.value
  const pages: (number | "...")[] = []
  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
  } else {
    pages.push(1)
    if (cur > 3) pages.push("...")
    const start = Math.max(2, cur - 1)
    const end = Math.min(total - 1, cur + 1)
    for (let i = start; i <= end; i++) pages.push(i)
    if (cur < total - 2) pages.push("...")
    pages.push(total)
  }
  return pages
})

// ─── Init ───────────────────────────────────────────────────────────
onMounted(() => {
  void loadStats()
  void loadEntries()
  void loadSettings()
})
</script>

<template>
  <section class="ds-page">
    <!-- Header -->
    <div class="ltm-header">
      <h1>Long-Term Memory</h1>
    </div>

    <!-- Stats cards -->
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-label">总记忆</span>
        <span class="stat-value">{{ statsLoading ? "..." : stats.total_entries }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">活跃会话</span>
        <span class="stat-value">{{ statsLoading ? "..." : stats.conversations }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">人物</span>
        <span class="stat-value">{{ statsLoading ? "..." : stats.persons }}</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">实体</span>
        <span class="stat-value">{{ statsLoading ? "..." : stats.entities }}</span>
      </div>
    </div>

    <!-- Tab bar -->
    <div class="tab-bar">
      <button class="tab-btn" :class="{ 'is-active': activeTab === 'manage' }" type="button" @click="activeTab = 'manage'">记忆管理</button>
      <button class="tab-btn" :class="{ 'is-active': activeTab === 'search' }" type="button" @click="activeTab = 'search'">检索测试</button>
      <button class="tab-btn" :class="{ 'is-active': activeTab === 'settings' }" type="button" @click="activeTab = 'settings'">设置</button>
    </div>

    <!-- Tab: 记忆管理 -->
    <div v-if="activeTab === 'manage'" class="section-card">

      <!-- Search / filter bar -->
      <div class="filter-bar">
        <input
          class="ds-input filter-keyword"
          type="text"
          placeholder="搜索关键词..."
          v-model="filterKeyword"
          @keydown.enter="doSearch"
        />
        <div class="filter-select">
          <CustomSelect
            :model-value="filterConversation"
            :options="conversationOptions"
            placeholder="搜索或选择..."
            @update:model-value="(v: string) => { filterConversation = v }"
          />
        </div>
        <div class="filter-select">
          <CustomSelect
            :model-value="filterPerson"
            :options="personOptions"
            placeholder="搜索或选择..."
            @update:model-value="(v: string) => { filterPerson = v }"
          />
        </div>
        <label class="filter-date-wrap">
          <input class="ds-input filter-date" type="date" v-model="filterDateStart" />
          <span v-if="!filterDateStart" class="filter-date-placeholder">开始时间</span>
        </label>
        <label class="filter-date-wrap">
          <input class="ds-input filter-date" type="date" v-model="filterDateEnd" />
          <span v-if="!filterDateEnd" class="filter-date-placeholder">结束时间</span>
        </label>
        <button class="ds-primary-button filter-search-btn" type="button" @click="doSearch">搜索</button>
        <button
          v-if="filterConversation"
          class="ds-danger-button filter-bulk-btn"
          type="button"
          @click="bulkDeleteConfirm = true"
        >按会话清空</button>
      </div>

      <!-- Bulk delete confirmation -->
      <div v-if="bulkDeleteConfirm" class="bulk-delete-bar">
        <span class="bulk-delete-text">确认清空会话 <strong>{{ filterConversation }}</strong> 的所有记忆?</span>
        <button class="ds-danger-button" type="button" @click="void bulkDeleteByConversation()">确认删除</button>
        <button class="ds-secondary-button" type="button" @click="bulkDeleteConfirm = false">取消</button>
      </div>

      <!-- Loading / Error -->
      <p v-if="entriesLoading" class="ds-empty">正在加载...</p>
      <p v-if="entriesError" class="ds-status is-error">{{ entriesError }}</p>

      <!-- Entry list -->
      <div v-if="!entriesLoading && entries.length === 0 && !entriesError" class="ds-empty">暂无记忆条目</div>

      <div v-if="!entriesLoading && entries.length > 0" class="entry-list">
        <div
          v-for="entry in entries"
          :key="entry.entry_id"
          class="entry-row"
          :class="{ 'is-expanded': expandedEntryId === entry.entry_id }"
        >
          <!-- Summary row -->
          <div class="entry-summary" @click="toggleExpand(entry.entry_id)">
            <span class="entry-topic">{{ entry.topic || "(无主题)" }}</span>
            <span class="entry-restatement">{{ truncate(entry.lossless_restatement, 60) }}</span>
            <div class="entry-meta">
              <span v-for="p in entry.persons" :key="p" class="chip chip-person">{{ p }}</span>
              <span class="entry-date">{{ formatDate(entry.updated_at) }}</span>
            </div>
            <svg class="entry-chevron" width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M4 5.5L7 8.5L10 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>

          <!-- Expanded detail -->
          <div v-if="expandedEntryId === entry.entry_id" class="entry-detail">
            <template v-if="editingEntryId !== entry.entry_id">
              <!-- View mode -->
              <div class="detail-grid">
                <div class="detail-field">
                  <span class="detail-label">Topic</span>
                  <span class="detail-value">{{ entry.topic || "—" }}</span>
                </div>
                <div class="detail-field detail-field-full">
                  <span class="detail-label">Restatement</span>
                  <span class="detail-value">{{ entry.lossless_restatement || "—" }}</span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Keywords</span>
                  <span class="detail-value">
                    <span v-if="entry.keywords.length" v-for="k in entry.keywords" :key="k" class="chip">{{ k }}</span>
                    <span v-else>—</span>
                  </span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Persons</span>
                  <span class="detail-value">
                    <span v-if="entry.persons.length" v-for="p in entry.persons" :key="p" class="chip chip-person">{{ p }}</span>
                    <span v-else>—</span>
                  </span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Entities</span>
                  <span class="detail-value">
                    <span v-if="entry.entities.length" v-for="e in entry.entities" :key="e" class="chip chip-entity">{{ e }}</span>
                    <span v-else>—</span>
                  </span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Location</span>
                  <span class="detail-value">{{ entry.location || "—" }}</span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Time</span>
                  <span class="detail-value">{{ entry.time_point || "—" }}</span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Conversation</span>
                  <span class="detail-value detail-value-mono">{{ entry.conversation_id }}</span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Created</span>
                  <span class="detail-value">{{ formatDate(entry.created_at) }}</span>
                </div>
                <div class="detail-field">
                  <span class="detail-label">Extractor</span>
                  <span class="detail-value detail-value-mono">{{ entry.extractor_version }}</span>
                </div>
              </div>
              <div class="detail-actions">
                <button class="ds-secondary-button" type="button" @click="startEdit(entry)">编辑</button>
                <button
                  v-if="deleteConfirmId !== entry.entry_id"
                  class="ds-danger-button"
                  type="button"
                  @click="deleteConfirmId = entry.entry_id"
                >删除</button>
                <template v-else>
                  <button
                    class="ds-danger-button"
                    type="button"
                    :disabled="deletingEntryId === entry.entry_id"
                    @click="void deleteEntry(entry.entry_id)"
                  >{{ deletingEntryId === entry.entry_id ? "删除中..." : "确认删除" }}</button>
                  <button class="ds-secondary-button" type="button" @click="deleteConfirmId = null">取消</button>
                </template>
              </div>
            </template>

            <template v-else>
              <!-- Edit mode -->
              <p v-if="editError" class="ds-status is-error small-status">{{ editError }}</p>
              <div class="edit-grid">
                <label class="edit-field">
                  <span class="detail-label">Topic</span>
                  <input class="ds-input" type="text" v-model="editDraft.topic" />
                </label>
                <label class="edit-field edit-field-full">
                  <span class="detail-label">Restatement</span>
                  <textarea class="ds-input edit-textarea" v-model="editDraft.lossless_restatement" rows="3"></textarea>
                </label>
                <label class="edit-field">
                  <span class="detail-label">Keywords (逗号分隔)</span>
                  <input class="ds-input" type="text" v-model="editDraft.keywords" placeholder="咖啡, 拿铁" />
                </label>
                <label class="edit-field">
                  <span class="detail-label">Persons (逗号分隔)</span>
                  <input class="ds-input" type="text" v-model="editDraft.persons" placeholder="Alice, Bob" />
                </label>
                <label class="edit-field">
                  <span class="detail-label">Entities (逗号分隔)</span>
                  <input class="ds-input" type="text" v-model="editDraft.entities" />
                </label>
                <label class="edit-field">
                  <span class="detail-label">Location</span>
                  <input class="ds-input" type="text" v-model="editDraft.location" />
                </label>
              </div>
              <div class="detail-actions">
                <button
                  class="ds-primary-button"
                  type="button"
                  :disabled="editSaving"
                  @click="void saveEdit(entry.entry_id)"
                >{{ editSaving ? "保存中..." : "保存" }}</button>
                <button class="ds-secondary-button" type="button" @click="cancelEdit">取消</button>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="!entriesLoading && entriesTotalCount > PAGE_SIZE" class="pagination">
        <button
          class="page-btn"
          type="button"
          :disabled="currentPage <= 1"
          @click="goToPage(currentPage - 1)"
        >&lt;</button>
        <template v-for="pg in paginationPages" :key="pg">
          <span v-if="pg === '...'" class="page-ellipsis">...</span>
          <button
            v-else
            class="page-btn"
            :class="{ 'is-active': pg === currentPage }"
            type="button"
            @click="goToPage(pg as number)"
          >{{ pg }}</button>
        </template>
        <button
          class="page-btn"
          type="button"
          :disabled="currentPage >= totalPages"
          @click="goToPage(currentPage + 1)"
        >&gt;</button>
      </div>
    </div>

    <!-- Tab: 检索测试 -->
    <div v-if="activeTab === 'search'" class="section-card">
      <div class="section-card-title">检索测试</div>
      <div class="filter-bar">
        <input
          class="ds-input filter-keyword"
          type="text"
          placeholder="查询文本..."
          v-model="searchQuery"
          @keydown.enter="void runSearchTest()"
        />
        <div class="filter-select">
          <CustomSelect
            :model-value="searchConversation"
            :options="conversationOptions"
            placeholder="全部会话"
            @update:model-value="(v: string) => { searchConversation = v }"
          />
        </div>
        <button
          class="ds-primary-button filter-search-btn"
          type="button"
          :disabled="searchLoading || !searchQuery.trim()"
          @click="void runSearchTest()"
        >{{ searchLoading ? "检索中..." : "测试检索" }}</button>
      </div>

      <p v-if="searchError" class="ds-status is-error">{{ searchError }}</p>

      <div v-if="searchResults.length > 0" class="search-results">
        <div v-for="(r, idx) in searchResults" :key="idx" class="search-result-row">
          <div class="search-result-header">
            <span class="entry-topic">{{ r.topic || "(无主题)" }}</span>
            <span v-if="r.hit_source" class="hit-source-badge" :class="`hit-${r.hit_source}`">{{ r.hit_source }}</span>
            <span v-if="r.score != null" class="search-score">{{ r.score.toFixed(3) }}</span>
          </div>
          <div class="search-result-body">{{ r.lossless_restatement }}</div>
          <div class="search-result-meta">
            <span v-for="p in r.persons" :key="p" class="chip chip-person">{{ p }}</span>
            <span class="entry-date">{{ r.conversation_id }}</span>
          </div>
        </div>
      </div>
      <div v-else-if="!searchLoading && searchQuery && searchResults.length === 0 && !searchError" class="ds-empty">
        无匹配结果
      </div>
    </div>

    <!-- Tab: 设置 -->
    <div v-if="activeTab === 'settings'" class="section-card">
      <div class="section-card-title">LTM 配置</div>
      <p v-if="settingsSaveMsg" class="ds-status is-ok small-status">{{ settingsSaveMsg }}</p>
      <p v-if="settingsError" class="ds-status is-error small-status">{{ settingsError }}</p>

      <template v-if="draft">
        <div class="settings-grid">
          <label class="setting-row">
            <span class="setting-label">启用 LTM</span>
            <input v-model="draft.enabled" type="checkbox" class="setting-checkbox" />
          </label>
          <div class="setting-row">
            <span class="setting-label">Storage Dir</span>
            <span class="setting-value-readonly">{{ draft.storage_dir }}</span>
          </div>
          <label class="setting-row">
            <span class="setting-label">Window Size</span>
            <input class="ds-input setting-input setting-input-sm" v-model="draft.window_size" type="number" min="1" />
          </label>
          <label class="setting-row">
            <span class="setting-label">Overlap Size</span>
            <input class="ds-input setting-input setting-input-sm" v-model="draft.overlap_size" type="number" min="0" />
          </label>
          <label class="setting-row">
            <span class="setting-label">Max Entries</span>
            <input class="ds-input setting-input setting-input-sm" v-model="draft.max_entries" type="number" min="1" />
          </label>
          <label class="setting-row">
            <span class="setting-label">Extractor Version</span>
            <input class="ds-input setting-input" v-model="draft.extractor_version" type="text" />
          </label>
        </div>
      </template>

      <div class="binding-section-title">模型绑定</div>
      <p v-if="bindingSaveMsg" class="ds-status is-ok small-status">{{ bindingSaveMsg }}</p>
      <p v-if="bindingError" class="ds-status is-error small-status">{{ bindingError }}</p>
      <div class="binding-list">
        <div v-for="target in LTM_TARGETS" :key="target.target_id" class="binding-row">
          <div class="binding-info">
            <span class="binding-label">{{ target.label }}</span>
            <span class="binding-desc">{{ target.description }}</span>
          </div>
          <div class="binding-control">
            <CustomSelect
              :model-value="currentPresetId(target.target_id)"
              :options="compatiblePresets(target.task_kind).map(p => ({ value: p.preset_id, label: `${p.preset_id} (${p.model})` }))"
              :placeholder="compatiblePresets(target.task_kind).length ? '选择 Preset' : `无 ${target.task_kind} Preset`"
              @update:model-value="(v: string) => void bindPreset(target.target_id, v)"
            />
            <span class="binding-state" :class="currentBinding(target.target_id)?.binding_state === 'resolved' ? 'is-ok' : ''">
              {{ currentBinding(target.target_id)?.binding_state || "unbound" }}
            </span>
          </div>
        </div>
      </div>

      <div class="settings-actions">
        <button class="ds-primary-button" type="button" :disabled="settingsLoading" @click="void saveSettings()">保存设置</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ─── Header ───────────────────────────────────────────── */
.ltm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.ltm-header h1 {
  margin: 0;
}

/* ─── Tab bar ──────────────────────────────────────────── */
.tab-bar {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--panel-line-soft);
}

.tab-btn {
  padding: 10px 20px;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all 120ms;
}

.tab-btn:hover {
  color: var(--text);
}

.tab-btn.is-active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}


/* ─── Stats ────────────────────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel-strong);
  display: flex;
  flex-direction: column;
  gap: 6px;
  opacity: 0;
  transform: translateY(12px);
  animation: stat-in 360ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.stat-card:nth-child(1) { animation-delay: 60ms; }
.stat-card:nth-child(2) { animation-delay: 120ms; }
.stat-card:nth-child(3) { animation-delay: 180ms; }
.stat-card:nth-child(4) { animation-delay: 240ms; }

@keyframes stat-in {
  to { opacity: 1; transform: translateY(0); }
}

.stat-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transition: border-color 200ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 200ms cubic-bezier(0.25, 1, 0.5, 1),
    box-shadow 200ms cubic-bezier(0.25, 1, 0.5, 1);
}

.stat-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stat-value {
  font-size: 22px;
  font-weight: 800;
  color: var(--heading-strong);
  transition: color 300ms cubic-bezier(0.25, 1, 0.5, 1);
}

/* ─── Section card ─────────────────────────────────────── */
.section-card {
  padding: 18px;
  border-radius: 16px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel-strong);
  margin-bottom: 16px;
}

.section-card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--heading-soft);
  margin-bottom: 14px;
}

.small-status {
  margin-bottom: 10px;
}

/* ─── Filter bar ───────────────────────────────────────── */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter-keyword {
  flex: 1;
  min-width: 160px;
}

.filter-select {
  width: 180px;
  flex-shrink: 0;
}

.filter-date-wrap {
  position: relative;
  width: 150px;
  flex-shrink: 0;
  cursor: pointer;
}

.filter-date {
  width: 100%;
  cursor: pointer;
}

.filter-date::-webkit-calendar-picker-indicator {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: pointer;
}

.filter-date-placeholder {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 13px;
  color: var(--muted);
  pointer-events: none;
}

.filter-search-btn {
  flex-shrink: 0;
}

.filter-bulk-btn {
  flex-shrink: 0;
}

.bulk-delete-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.2);
  margin-bottom: 14px;
}

.bulk-delete-text {
  flex: 1;
  font-size: 13px;
  color: var(--text);
}

/* ─── Entry list ───────────────────────────────────────── */
.entry-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.entry-row {
  border-radius: 12px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel);
  transition: border-color 120ms;
  opacity: 0;
  transform: translateY(6px);
  animation: entry-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

@keyframes entry-in {
  to { opacity: 1; transform: translateY(0); }
}

.entry-row.is-expanded {
  border-color: var(--accent);
}

.entry-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  cursor: pointer;
  transition: background 100ms;
  border-radius: 12px;
}

.entry-summary:hover {
  background: var(--accent-soft);
}

.entry-topic {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading);
  flex-shrink: 0;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-restatement {
  flex: 1;
  font-size: 13px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.entry-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.entry-date {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.entry-chevron {
  flex-shrink: 0;
  color: var(--muted);
  transition: transform 160ms;
}

.entry-row.is-expanded .entry-chevron {
  transform: rotate(180deg);
}

/* ─── Chips ────────────────────────────────────────────── */
.chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--panel-line-soft);
  color: var(--text);
  white-space: nowrap;
}

.chip-person {
  background: rgba(99, 102, 241, 0.12);
  color: var(--accent);
}

.chip-entity {
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
}

/* ─── Entry detail ─────────────────────────────────────── */
.entry-detail {
  padding: 0 14px 14px 14px;
  border-top: 1px solid var(--panel-line-soft);
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
  padding-top: 14px;
}

.detail-field-full {
  grid-column: 1 / -1;
}

.detail-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 3px;
}

.detail-value {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  word-break: break-word;
}

.detail-value-mono {
  font-family: "SF Mono", "Fira Code", monospace;
  font-size: 12px;
  color: var(--muted);
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--panel-line-soft);
}

/* ─── Edit mode ────────────────────────────────────────── */
.edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 16px;
  padding-top: 14px;
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.edit-field-full {
  grid-column: 1 / -1;
}

.edit-textarea {
  resize: vertical;
  min-height: 60px;
  font-family: inherit;
}

/* ─── Pagination ───────────────────────────────────────── */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin-top: 16px;
}

.page-btn {
  min-width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid var(--panel-line-soft);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 120ms;
  font-family: inherit;
}

.page-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.page-btn.is-active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.page-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.page-ellipsis {
  font-size: 13px;
  color: var(--muted);
  padding: 0 4px;
}

/* ─── Search test ──────────────────────────────────────── */
.search-results {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.search-result-row {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel);
}

.search-result-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.hit-source-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 5px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.hit-keyword {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}

.hit-structured {
  background: rgba(99, 102, 241, 0.12);
  color: var(--accent);
}

.hit-vector {
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
}

.search-score {
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  font-family: "SF Mono", "Fira Code", monospace;
}

.search-result-body {
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 6px;
}

.search-result-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

/* ─── Settings panel ───────────────────────────────────── */
.settings-panel {
  margin-bottom: 20px;
}

.binding-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--heading-soft);
  margin-top: 18px;
  margin-bottom: 10px;
}

.binding-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.binding-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--panel);
  border: 1px solid var(--panel-line-soft);
}

.binding-info {
  flex: 0 0 160px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.binding-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.binding-desc {
  font-size: 11px;
  color: var(--muted);
}

.binding-control {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.binding-control > :first-child {
  flex: 1;
}

.binding-state {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--panel-line-soft);
  color: var(--muted);
}

.binding-state.is-ok {
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
}

.settings-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.setting-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  flex-shrink: 0;
}

.setting-input {
  flex: 1;
  max-width: 300px;
}

.setting-input-sm {
  max-width: 120px;
}

.setting-checkbox {
  width: 18px;
  height: 18px;
  accent-color: var(--accent);
}

.setting-value-readonly {
  font-size: 13px;
  color: var(--muted);
  font-family: "SF Mono", "Fira Code", monospace;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--panel-strong);
  border: 1px solid var(--panel-line-soft);
}

.settings-actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* ─── Common ───────────────────────────────────────────── */
.ds-empty {
  text-align: center;
  color: var(--muted);
  padding: 24px 0;
  font-size: 13px;
}

/* ─── Button variants ──────────────────────────────────── */
.ds-secondary-button {
  padding: 8px 16px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 120ms;
}

.ds-secondary-button:hover {
  border-color: var(--panel-line-strong);
}

.ds-danger-button {
  padding: 8px 16px;
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.08);
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 120ms;
}

.ds-danger-button:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
}

/* ─── Responsive ───────────────────────────────────────── */
@media (max-width: 860px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-select { width: 100%; }
  .detail-grid { grid-template-columns: 1fr; }
  .edit-grid { grid-template-columns: 1fr; }
  .binding-row { flex-direction: column; align-items: stretch; }
  .binding-info { flex: none; }
  .entry-summary { flex-wrap: wrap; }
  .entry-restatement { min-width: 100%; order: 3; }
}

@media (max-width: 500px) {
  .stats-row { grid-template-columns: 1fr 1fr; }
}
</style>
