<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import StickyNotePane from "../components/StickyNotePane.vue"
import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

type StickyEntityKind = "user" | "conversation"

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

type StickyNoteSummary = {
  entity_ref: string
  updated_at: number
}

type StickyNoteItem = {
  entity_ref: string
  readonly: string
  editable: string
  updated_at: number
}

const MEMORY_KIND_STORAGE_KEY = "acabot.memory.entity_kind"
const MEMORY_ENTITY_STORAGE_KEY = "acabot.memory.entity_ref"

function noteListPath(entityKind: StickyEntityKind): string {
  return `/api/memory/sticky-notes?entity_kind=${encodeURIComponent(entityKind)}`
}

function noteItemPath(entityRef: string): string {
  return `/api/memory/sticky-notes/item?entity_ref=${encodeURIComponent(entityRef)}`
}

function readStoredKind(): StickyEntityKind {
  const raw = localStorage.getItem(MEMORY_KIND_STORAGE_KEY)
  return raw === "user" ? "user" : "conversation"
}

function readStoredEntityRef(): string {
  return localStorage.getItem(MEMORY_ENTITY_STORAGE_KEY) || ""
}

function inferEntityKind(entityRef: string): StickyEntityKind {
  const parts = entityRef.split(":")
  const segment = String(parts[1] || "").trim().toLowerCase()
  return segment === "user" ? "user" : "conversation"
}

function toLongTermMemoryDraft(value: LongTermMemoryConfig): LongTermMemoryDraft {
  return {
    enabled: Boolean(value.enabled),
    storage_dir: value.storage_dir || "long-term-memory/lancedb",
    window_size: String(value.window_size || 50),
    overlap_size: String(value.overlap_size || 10),
    max_entries: String(value.max_entries || 8),
    extractor_version: value.extractor_version || "ltm-extractor-v1",
  }
}

const storedKind = readStoredKind()
const storedEntityRef = readStoredEntityRef()
const cachedLongTermMemory = peekCachedGet<LongTermMemoryConfig>("/api/memory/long-term/config")
const cachedNotes = peekCachedGet<{ entity_kind: StickyEntityKind; items: StickyNoteSummary[] }>(
  noteListPath(storedKind),
)
const cachedNote = storedEntityRef ? peekCachedGet<StickyNoteItem>(noteItemPath(storedEntityRef)) : null

const longTermMemoryConfig = ref<LongTermMemoryConfig | null>(cachedLongTermMemory)
const longTermMemoryDraft = ref<LongTermMemoryDraft | null>(
  cachedLongTermMemory ? toLongTermMemoryDraft(cachedLongTermMemory) : null,
)
const longTermMemoryLoading = ref(!cachedLongTermMemory)
const longTermMemorySaveMessage = ref("")
const longTermMemoryErrorMessage = ref("")

const entityKind = ref<StickyEntityKind>(cachedNote ? inferEntityKind(cachedNote.entity_ref) : storedKind)
const noteItems = ref<StickyNoteSummary[]>(cachedNotes?.items ?? [])
const noteSearch = ref("")
const draftEntityRef = ref(cachedNote?.entity_ref || storedEntityRef)
const selectedEntityRef = ref(cachedNote?.entity_ref || storedEntityRef)
const noteItem = ref<StickyNoteItem | null>(cachedNote)
const loadingText = ref(cachedNote || cachedNotes ? "" : "正在加载 Sticky Notes...")
const statusText = ref("")
const errorText = ref("")

let statusTimer: ReturnType<typeof setTimeout> | null = null

const filteredNoteItems = computed(() => {
  const keyword = noteSearch.value.trim().toLowerCase()
  if (!keyword) {
    return noteItems.value
  }
  return noteItems.value.filter((item) => item.entity_ref.toLowerCase().includes(keyword))
})

function clearStatus(): void {
  statusText.value = ""
  if (statusTimer !== null) {
    clearTimeout(statusTimer)
    statusTimer = null
  }
}

function showStatus(message: string): void {
  clearStatus()
  statusText.value = message
  statusTimer = setTimeout(() => {
    statusText.value = ""
    statusTimer = null
  }, 1400)
}

async function loadLongTermMemoryConfig(): Promise<void> {
  longTermMemoryLoading.value = true
  longTermMemoryErrorMessage.value = ""
  try {
    const payload = await apiGet<LongTermMemoryConfig>("/api/memory/long-term/config")
    longTermMemoryConfig.value = payload
    longTermMemoryDraft.value = toLongTermMemoryDraft(payload)
  } catch (error) {
    longTermMemoryErrorMessage.value = error instanceof Error ? error.message : "加载长期记忆配置失败"
  } finally {
    longTermMemoryLoading.value = false
  }
}

async function saveLongTermMemoryConfig(): Promise<void> {
  if (!longTermMemoryDraft.value) {
    return
  }
  longTermMemorySaveMessage.value = "保存中..."
  longTermMemoryErrorMessage.value = ""
  try {
    const payload = await apiPut<LongTermMemoryConfig>("/api/memory/long-term/config", {
      enabled: longTermMemoryDraft.value.enabled,
      storage_dir: longTermMemoryDraft.value.storage_dir,
      window_size: Number(longTermMemoryDraft.value.window_size || 50),
      overlap_size: Number(longTermMemoryDraft.value.overlap_size || 10),
      max_entries: Number(longTermMemoryDraft.value.max_entries || 8),
      extractor_version: longTermMemoryDraft.value.extractor_version,
    })
    longTermMemoryConfig.value = payload
    longTermMemoryDraft.value = toLongTermMemoryDraft(payload)
    longTermMemorySaveMessage.value = payload.restart_required ? "已保存，重启 runtime 后生效" : "已保存"
  } catch (error) {
    longTermMemorySaveMessage.value = ""
    longTermMemoryErrorMessage.value = error instanceof Error ? error.message : "保存长期记忆配置失败"
  }
}

async function loadNotes(kind: StickyEntityKind): Promise<void> {
  const payload = await apiGet<{ entity_kind: StickyEntityKind; items: StickyNoteSummary[] }>(noteListPath(kind))
  noteItems.value = payload.items ?? []
}

async function openKind(kind: StickyEntityKind, preserveCurrent = false): Promise<void> {
  entityKind.value = kind
  noteSearch.value = ""
  localStorage.setItem(MEMORY_KIND_STORAGE_KEY, kind)
  await loadNotes(kind)
  if (
    preserveCurrent
    && selectedEntityRef.value
    && noteItems.value.some((item) => item.entity_ref === selectedEntityRef.value)
  ) {
    return
  }
  if (noteItems.value[0]?.entity_ref) {
    await openNote(noteItems.value[0].entity_ref)
    return
  }
  selectedEntityRef.value = ""
  noteItem.value = null
}

async function openNote(entityRef: string): Promise<void> {
  const payload = await apiGet<StickyNoteItem>(noteItemPath(entityRef))
  selectedEntityRef.value = payload.entity_ref
  draftEntityRef.value = payload.entity_ref
  noteItem.value = payload
  localStorage.setItem(MEMORY_ENTITY_STORAGE_KEY, payload.entity_ref)
}

async function browseEntityRef(): Promise<void> {
  const entityRef = draftEntityRef.value.trim()
  if (!entityRef) {
    errorText.value = "先填写 entity_ref，再点击浏览。"
    clearStatus()
    return
  }
  errorText.value = ""
  clearStatus()
  try {
    const inferredKind = inferEntityKind(entityRef)
    await openKind(inferredKind, true)
    await openNote(entityRef)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "读取 sticky note 失败"
  }
}

async function createNote(): Promise<void> {
  const entityRef = draftEntityRef.value.trim()
  if (!entityRef) {
    errorText.value = "先填写 entity_ref，再点击新建。"
    clearStatus()
    return
  }
  errorText.value = ""
  clearStatus()
  try {
    const inferredKind = inferEntityKind(entityRef)
    await apiPost<StickyNoteItem>("/api/memory/sticky-notes/item", {
      entity_ref: entityRef,
    })
    await openKind(inferredKind, true)
    await openNote(entityRef)
    showStatus("已创建并打开新的 Sticky Note")
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "新建 sticky note 失败"
  }
}

async function saveReadonly(content: string): Promise<void> {
  if (!noteItem.value) {
    return
  }
  errorText.value = ""
  clearStatus()
  try {
    noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/item", {
      entity_ref: noteItem.value.entity_ref,
      readonly: content,
      editable: noteItem.value.editable,
    })
    showStatus("只读区已保存")
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存只读区失败"
  }
}

async function saveEditable(content: string): Promise<void> {
  if (!noteItem.value) {
    return
  }
  errorText.value = ""
  clearStatus()
  try {
    noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/item", {
      entity_ref: noteItem.value.entity_ref,
      readonly: noteItem.value.readonly,
      editable: content,
    })
    showStatus("可编辑区已保存")
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存可编辑区失败"
  }
}

onMounted(() => {
  void (async () => {
    try {
      await Promise.all([
        loadLongTermMemoryConfig(),
        openKind(entityKind.value, true),
      ])
      if (storedEntityRef) {
        try {
          await openNote(storedEntityRef)
        } catch {
          // ignore stale local selection
        }
      }
    } catch (error) {
      errorText.value = error instanceof Error ? error.message : "加载 Sticky Notes 失败"
    } finally {
      loadingText.value = ""
    }
  })()
})

onBeforeUnmount(() => {
  clearStatus()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Memory</p>
        <h1>长期记忆与 Sticky Notes</h1>
        <p class="ds-summary">
          这一页分成两条线：前半段配置 long_term_memory 的正式 runtime 开关，后半段继续维护按 `entity_ref` 组织的 Sticky Notes。
        </p>
      </div>
    </header>

    <article class="ds-panel ds-panel-padding ltm-panel">
      <div class="ds-section-head compact-head">
        <div class="ds-section-title">
          <div>
            <h2>Long-Term Memory</h2>
            <p class="ds-summary">打开开关只会把链路装配起来，真正可用还要先在 Models 页面给三个 `system:ltm_*` target 配好 binding。</p>
          </div>
        </div>
        <div class="ds-actions">
          <RouterLink class="ds-secondary-button" to="/config/models">去配置模型 Binding</RouterLink>
          <button class="ds-primary-button" type="button" :disabled="longTermMemoryLoading || !longTermMemoryDraft" @click="void saveLongTermMemoryConfig()">保存 LTM 配置</button>
        </div>
      </div>

      <p v-if="longTermMemorySaveMessage" class="ds-status is-ok">{{ longTermMemorySaveMessage }}</p>
      <p v-if="longTermMemoryErrorMessage" class="ds-status is-error">{{ longTermMemoryErrorMessage }}</p>
      <p v-if="longTermMemoryLoading" class="ds-empty">正在加载长期记忆配置...</p>

      <div v-else-if="longTermMemoryDraft" class="ltm-stack">
        <div class="ltm-meta ds-two-column">
          <article class="ds-surface ds-card-padding-sm ltm-meta-card">
            <h3>装配状态</h3>
            <p class="meta-value">{{ longTermMemoryDraft.enabled ? "enabled" : "disabled" }}</p>
            <p class="ds-summary">切换这里会改 `runtime.long_term_memory.enabled`。保存后需要重启 runtime 才会真正生效。</p>
          </article>
          <article class="ds-surface ds-card-padding-sm ltm-meta-card">
            <h3>模型 binding</h3>
            <p class="meta-value">
              {{ longTermMemoryConfig?.missing_target_ids?.length ? `缺 ${longTermMemoryConfig.missing_target_ids.length} 个` : "ready" }}
            </p>
            <p class="ds-summary">
              {{
                longTermMemoryConfig?.missing_target_ids?.length
                  ? `还没绑好：${longTermMemoryConfig.missing_target_ids.join("、")}`
                  : "system:ltm_extract / query_plan / embed 都已经有 binding。"
              }}
            </p>
          </article>
        </div>

        <div class="ds-form-grid">
          <label class="ds-field checkbox-field">
            <span>启用 long_term_memory</span>
            <input v-model="longTermMemoryDraft.enabled" type="checkbox" />
          </label>
          <label class="ds-field">
            <span>Storage Dir</span>
            <input class="ds-input" v-model="longTermMemoryDraft.storage_dir" type="text" />
          </label>
          <label class="ds-field">
            <span>Window Size</span>
            <input class="ds-input" v-model="longTermMemoryDraft.window_size" type="number" min="1" />
          </label>
          <label class="ds-field">
            <span>Overlap Size</span>
            <input class="ds-input" v-model="longTermMemoryDraft.overlap_size" type="number" min="0" />
          </label>
          <label class="ds-field">
            <span>Max Entries</span>
            <input class="ds-input" v-model="longTermMemoryDraft.max_entries" type="number" min="1" />
          </label>
          <label class="ds-field">
            <span>Extractor Version</span>
            <input class="ds-input" v-model="longTermMemoryDraft.extractor_version" type="text" />
          </label>
        </div>

        <div class="ds-chip-row">
          <span v-for="targetId in longTermMemoryConfig?.required_target_ids || []" :key="targetId" class="ds-chip">
            {{ targetId }}
          </span>
        </div>
      </div>
    </article>

    <div class="memory-layout">
      <aside class="ds-panel ds-panel-padding sidebar-column note-panel">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>Sticky Notes</h2>
              <p class="ds-summary">按 `entity_kind` 分类，实际主键是 `entity_ref`。</p>
            </div>
          </div>
        </div>

        <div class="ds-field">
          <span>实体分类</span>
          <select class="ds-select" v-model="entityKind" @change="void openKind(entityKind)">
            <option value="conversation">conversation</option>
            <option value="user">user</option>
          </select>
        </div>

        <div class="ds-field note-search">
          <input class="ds-input" v-model="noteSearch" type="text" placeholder="搜索 entity_ref" />
        </div>

        <div class="ds-list note-list">
          <p v-if="errorText" class="ds-status is-error error">{{ errorText }}</p>
          <p v-if="noteItems.length > 0 && filteredNoteItems.length === 0" class="ds-empty empty">没有匹配的 Sticky Note。</p>
          <button
            v-for="item in filteredNoteItems"
            :key="item.entity_ref"
            class="list-item"
            :class="{ active: item.entity_ref === selectedEntityRef }"
            type="button"
            @click="void openNote(item.entity_ref)"
          >
            <strong>{{ item.entity_ref }}</strong>
            <small>{{ new Date(item.updated_at * 1000).toLocaleString("zh-CN", { hour12: false }) }}</small>
          </button>
        </div>

        <div class="create-bar note-create">
          <div class="new-note">
            <input class="ds-input" v-model="draftEntityRef" type="text" placeholder="entity_ref，例如 qq:group:42 或 qq:user:10001" />
            <button class="ds-secondary-button" type="button" @click="void browseEntityRef()">浏览</button>
            <button class="ds-primary-button" type="button" @click="void createNote()">新建</button>
          </div>
        </div>
      </aside>

      <section class="ds-panel ds-panel-padding main-column">
        <p v-if="statusText" class="toast-status">{{ statusText }}</p>
        <div v-if="errorText" class="ds-status is-error error">{{ errorText }}</div>
        <div v-else-if="loadingText" class="ds-empty empty">{{ loadingText }}</div>
        <div v-else-if="noteItem === null" class="ds-empty empty">
          先选一个实体分类，再输入 `entity_ref` 点击浏览；如果是第一次创建，直接填好 `entity_ref` 然后点“新建”。
        </div>
        <StickyNotePane
          v-else
          :readonly-content="noteItem.readonly"
          :editable-content="noteItem.editable"
          @save-readonly="(value) => void saveReadonly(value)"
          @save-editable="(value) => void saveEditable(value)"
        />
      </section>
    </div>
  </section>
</template>

<style scoped>
.ltm-panel {
  margin-bottom: 16px;
}

.compact-head {
  margin-bottom: 14px;
}

.ltm-stack {
  display: grid;
  gap: 14px;
}

.ltm-meta {
  gap: 12px;
}

.ltm-meta-card {
  display: grid;
  gap: 8px;
}

.meta-value {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--heading-strong);
}

.checkbox-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.memory-layout {
  display: grid;
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.main-column {
  min-width: 0;
}

.note-list {
  min-height: 160px;
  max-height: 420px;
  overflow: auto;
}

.list-item {
  width: 100%;
  display: grid;
  gap: 6px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-white);
  color: var(--text);
  padding: 12px 14px;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.create-bar {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.new-note {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.new-note .ds-input {
  flex: 1 1 220px;
}

.main-column {
  position: relative;
}

.toast-status {
  position: absolute;
  top: 18px;
  right: 18px;
  margin: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: max-content;
  max-width: min(320px, calc(100% - 36px));
  padding: 9px 14px;
  border-radius: 14px;
  border: 1px solid rgba(110, 212, 154, 0.22);
  background: rgba(12, 38, 24, 0.88);
  color: #dcfce7;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
  backdrop-filter: blur(12px);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.22);
  z-index: 2;
}

@media (max-width: 1100px) {
  .memory-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .new-note {
    justify-content: stretch;
  }

  .new-note .ds-input,
  .new-note .ds-secondary-button,
  .new-note .ds-primary-button {
    flex: 1 0 auto;
    min-width: 0;
  }
}
</style>
