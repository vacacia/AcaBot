<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute } from "vue-router"

import StickyNotePane from "../components/StickyNotePane.vue"
import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

type StickyEntityKind = "user" | "conversation"

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

type LongTermMemoryConfig = {
  enabled: boolean
  required_target_ids: string[]
  missing_target_ids: string[]
}

type BindingSnapshot = {
  binding: {
    target_id: string
    preset_ids: string[]
  }
  binding_state: string
}

const MEMORY_KIND_STORAGE_KEY = "acabot.memory.entity_kind"
const MEMORY_ENTITY_STORAGE_KEY = "acabot.memory.entity_ref"
const route = useRoute()

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

function nextEntityKind(entityKind: StickyEntityKind): StickyEntityKind {
  return entityKind === "user" ? "conversation" : "user"
}

function inferEntityKind(entityRef: string): StickyEntityKind {
  const parts = entityRef.split(":")
  const segment = String(parts[1] || "").trim().toLowerCase()
  return segment === "user" ? "user" : "conversation"
}

const storedKind = readStoredKind()
const storedEntityRef = readStoredEntityRef()
const cachedNotes = peekCachedGet<{ entity_kind: StickyEntityKind; items: StickyNoteSummary[] }>(
  noteListPath(storedKind),
)
const cachedNote = storedEntityRef ? peekCachedGet<StickyNoteItem>(noteItemPath(storedEntityRef)) : null

const entityKind = ref<StickyEntityKind>(
  cachedNote
    ? inferEntityKind(cachedNote.entity_ref)
    : storedEntityRef
      ? inferEntityKind(storedEntityRef)
      : storedKind,
)
const noteItems = ref<StickyNoteSummary[]>(cachedNotes?.items ?? [])
const noteSearch = ref("")
const draftEntityRef = ref(cachedNote?.entity_ref || storedEntityRef)
const selectedEntityRef = ref(cachedNote?.entity_ref || storedEntityRef)
const noteItem = ref<StickyNoteItem | null>(cachedNote)
const loadingText = ref(cachedNote || cachedNotes ? "" : "正在加载 Sticky Notes...")
const statusText = ref("")
const errorText = ref("")
const refreshSpinning = ref(false)

let statusTimer: ReturnType<typeof setTimeout> | null = null

const filteredNoteItems = computed(() => {
  const keyword = noteSearch.value.trim().toLowerCase()
  if (!keyword) {
    return noteItems.value
  }
  return noteItems.value.filter((item) => item.entity_ref.toLowerCase().includes(keyword))
})

const isMemoryOverview = computed(() => route.path === "/config/memory")
const pageTitle = computed(() => (isMemoryOverview.value ? "长期记忆与 Sticky Notes" : "Sticky Notes"))

const ltmConfig = ref<LongTermMemoryConfig | null>(null)
const ltmBindings = ref<BindingSnapshot[]>([])

const ltmBindingState = computed(() => {
  if (ltmConfig.value === null) return "unavailable"
  if (!ltmConfig.value.enabled) return "disabled"
  if ((ltmConfig.value.missing_target_ids || []).length > 0) return "needs setup"
  const requiredIds = new Set(ltmConfig.value.required_target_ids || [])
  const ready = ltmBindings.value.filter((item) => requiredIds.has(item.binding.target_id)).every((item) => item.binding_state === "resolved")
  return ready ? "ready" : "needs setup"
})

const ltmBindingStateLabel = computed(() => {
  switch (ltmBindingState.value) {
    case "disabled": return "未启用"
    case "needs setup": return "待配置"
    case "ready": return "就绪"
    default: return "不可用"
  }
})

const ltmTargets = computed(() => ltmConfig.value?.required_target_ids ?? [])

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

async function refreshNotes(): Promise<void> {
  refreshSpinning.value = true
  try {
    await openFirstAvailableKind(entityKind.value)
  } finally {
    setTimeout(() => { refreshSpinning.value = false }, 300)
  }
}

async function openFirstAvailableKind(preferredKind: StickyEntityKind): Promise<void> {
  if (isMemoryOverview.value) {
    await openKind("conversation", true)
    return
  }
  await openKind(preferredKind, true)
  if (noteItems.value.length > 0) {
    return
  }
  await openKind(nextEntityKind(preferredKind), true)
}

async function openNote(entityRef: string): Promise<void> {
  const payload = await apiGet<StickyNoteItem>(noteItemPath(entityRef))
  selectedEntityRef.value = payload.entity_ref
  // 不修改 draftEntityRef — 它是"新建/浏览"输入框的独立状态
  noteItem.value = payload
  localStorage.setItem(MEMORY_ENTITY_STORAGE_KEY, payload.entity_ref)
}

async function browseEntityRef(): Promise<void> {
  const entityRef = draftEntityRef.value.trim()
  if (!entityRef) {
    showStatus("先填写 entity_ref，再点击浏览。")
    return
  }
  errorText.value = ""
  clearStatus()
  // 浏览失败时清理选中状态，避免列表高亮与内容区不一致
  selectedEntityRef.value = ""
  noteItem.value = null
  try {
    const inferredKind = inferEntityKind(entityRef)
    await openKind(inferredKind, true)
    await openNote(entityRef)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "读取 sticky note 失败"
    // 列表中也不会高亮任何项，因为 entity 不存在
    selectedEntityRef.value = ""
    noteItem.value = null
  }
}

async function createNote(): Promise<void> {
  const entityRef = draftEntityRef.value.trim()
  if (!entityRef) {
    showStatus("先填写 entity_ref，再点击新建。")
    return
  }
  if (isMemoryOverview.value && !entityRef.startsWith("qq:group:")) {
    errorText.value = "当前记忆总览页只允许创建 conversation sticky note, 请输入 qq:group:<id>"
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

async function saveNote(readonly: string, editable: string): Promise<void> {
  if (!noteItem.value) {
    return
  }
  errorText.value = ""
  clearStatus()
  try {
    noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/item", {
      entity_ref: noteItem.value.entity_ref,
      readonly,
      editable,
    })
    showStatus("已保存")
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function loadLtmSummary(): Promise<void> {
  if (!isMemoryOverview.value) {
    return
  }
  try {
    const [configPayload, bindingPayload] = await Promise.all([
      apiGet<LongTermMemoryConfig>("/api/memory/long-term/config"),
      apiGet<BindingSnapshot[]>("/api/models/bindings"),
    ])
    ltmConfig.value = configPayload
    ltmBindings.value = bindingPayload
  } catch {
    ltmConfig.value = null
    ltmBindings.value = []
  }
}

onMounted(() => {
  void (async () => {
    try {
      await loadLtmSummary()
      await openFirstAvailableKind(entityKind.value)
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
        <p class="ds-eyebrow">Memory / Sticky Notes</p>
        <h1>{{ pageTitle }}</h1>
      </div>
    </header>

    <div class="memory-layout">
      <aside class="ds-panel ds-panel-padding sidebar-column note-panel sn-sidebar">
        <div v-if="isMemoryOverview" class="ltm-summary-grid">
          <article class="ds-surface ds-card-padding-sm ltm-meta-card">
            <p class="summary-label">LTM</p>
            <strong class="meta-value">{{ ltmConfig?.enabled ? "已启用" : "未启用" }}</strong>
          </article>
          <article class="ds-surface ds-card-padding-sm ltm-meta-card">
            <p class="summary-label">Binding</p>
            <strong class="meta-value">{{ ltmBindingStateLabel }}</strong>
          </article>
        </div>

        <div class="sidebar-header">
          <h2>Sticky Notes</h2>
          <button class="refresh-btn" :class="{ spinning: refreshSpinning }" type="button" @click="void refreshNotes()" title="刷新">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M11.67 2.33A6.27 6.27 0 007 .5C3.41.5 .5 3.41.5 7s2.91 6.5 6.5 6.5c3.08 0 5.64-2.13 6.33-5h-1.7A4.82 4.82 0 017 11.83 4.83 4.83 0 012.17 7 4.83 4.83 0 017 2.17c1.34 0 2.54.55 3.41 1.42L8.17 5.83H13.5V.5l-1.83 1.83z" fill="currentColor"/>
            </svg>
          </button>
        </div>

        <div class="action-row note-search">
          <input class="ds-input action-input" v-model="noteSearch" type="text" placeholder="搜索..." />
        </div>

        <div class="ds-list note-list">
          <p v-if="noteItems.length > 0 && filteredNoteItems.length === 0" class="ds-empty empty">没有匹配的 Sticky Note，试试换个关键词。</p>
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

        <div class="action-row create-bar note-create new-note">
          <input class="ds-input action-input" v-model="draftEntityRef" type="text" placeholder="输入 ID，如 qq:group:42" @keydown.enter="void createNote()" />
          <button class="ds-primary-button action-btn" type="button" @click="void createNote()">新建</button>
        </div>
      </aside>

      <section class="ds-panel ds-panel-padding main-column sn-main">
        <Transition name="toast">
          <p v-if="statusText" class="toast-status">{{ statusText }}</p>
        </Transition>
        <div v-if="errorText" class="ds-status is-error error">{{ errorText }}</div>
        <div v-else-if="loadingText" class="ds-empty empty">{{ loadingText }}</div>
        <div v-else-if="noteItem === null" class="ds-empty empty">
          选择或新建一个 Sticky Note。
        </div>
        <Transition v-else name="editor-swap" mode="out-in">
          <StickyNotePane
            :key="noteItem.entity_ref"
            :readonly-content="noteItem.readonly"
            :editable-content="noteItem.editable"
            @save="(readonly, editable) => void saveNote(readonly, editable)"
          />
        </Transition>

        <div v-if="isMemoryOverview" class="ltm-targets">
          <h3>Long-Term Memory Targets</h3>
          <div class="ds-chip-row">
            <span v-for="target in ltmTargets" :key="target" class="ds-chip">{{ target }}</span>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
/* ─── Layout entrance ─────────────────────────────── */
.memory-layout {
  display: grid;
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  gap: 16px;
}

.sn-sidebar {
  opacity: 0;
  transform: translateX(-12px);
  animation: panel-in 360ms cubic-bezier(0.25, 1, 0.5, 1) 60ms forwards;
}

.sn-main {
  opacity: 0;
  transform: translateX(12px);
  animation: panel-in 360ms cubic-bezier(0.25, 1, 0.5, 1) 120ms forwards;
}

@keyframes panel-in {
  to { opacity: 1; transform: translateX(0); }
}

/* ─── Note list stagger ─────────────────────────── */
.list-item {
  opacity: 0;
  transform: translateY(4px);
  animation: note-item-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.list-item:nth-child(1) { animation-delay: 160ms; }
.list-item:nth-child(2) { animation-delay: 200ms; }
.list-item:nth-child(3) { animation-delay: 240ms; }
.list-item:nth-child(4) { animation-delay: 280ms; }
.list-item:nth-child(5) { animation-delay: 320ms; }
.list-item:nth-child(n+6) { animation-delay: 360ms; }

@keyframes note-item-in {
  to { opacity: 1; transform: translateY(0); }
}

.list-item.newly-created {
  animation: note-flash 400ms ease forwards;
}

@keyframes note-flash {
  0%   { background: color-mix(in srgb, var(--accent) 20%, var(--panel-white)); }
  100% { background: var(--panel-white); }
}

/* ─── Note item interactions ───────────────────── */
.list-item {
  width: 100%;
  display: grid;
  gap: 4px;
  text-align: left;
  border: 1px solid var(--panel-line-soft);
  border-radius: 12px;
  background: var(--panel-white);
  color: var(--text);
  padding: 10px 12px;
  cursor: pointer;
  font-family: inherit;
  font-size: inherit;
  transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
  position: relative;
}

.list-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 60%;
  background: var(--accent);
  opacity: 0;
  transition: opacity 150ms ease;
  border-radius: 0 2px 2px 0;
}

.list-item:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--panel-line-soft));
  transform: translateX(2px);
}

.list-item:hover::before {
  opacity: 0.4;
}

.list-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--panel-line-soft));
}

.list-item.active::before {
  opacity: 1;
}

.list-item strong {
  font-size: 13px;
  font-weight: 700;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.list-item small {
  font-size: 11px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ─── Layout ───────────────────────────────────── */
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.ltm-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.ltm-meta-card {
  display: grid;
  gap: 4px;
}

.meta-value {
  font-size: 16px;
  color: var(--heading-strong);
}

.summary-label {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}

.sidebar-header h2 {
  margin: 0;
  font-size: 16px;
}

.action-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.ltm-targets {
  margin-top: 16px;
  display: grid;
  gap: 10px;
}

.action-input {
  flex: 1;
}

.action-btn {
  flex-shrink: 0;
}

.create-bar {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  margin-bottom: 0;
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
  overflow: auto;
}

@media (max-width: 1100px) {
  .memory-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .create-row {
    flex-wrap: wrap;
  }

  .create-input,
  .create-btn {
    flex: 1 0 auto;
    min-width: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sn-sidebar,
  .sn-main,
  .list-item,
  .refresh-btn,
  .refresh-btn.spinning svg,
  .toast-enter-active,
  .toast-leave-active,
  .editor-swap-enter-active,
  .editor-swap-leave-active {
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
  }
  .toast-status { display: inline-flex; }
}
</style>
