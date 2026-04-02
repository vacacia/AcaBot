<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

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

async function openFirstAvailableKind(preferredKind: StickyEntityKind): Promise<void> {
  await openKind(preferredKind, true)
  if (noteItems.value.length > 0) {
    return
  }
  await openKind(nextEntityKind(preferredKind), true)
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
    showStatus("先填写 entity_ref，再点击浏览。")
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
    showStatus("先填写 entity_ref，再点击新建。")
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
    <h1>Sticky Notes</h1>

    <div class="memory-layout">
      <aside class="ds-panel ds-panel-padding sidebar-column note-panel">
        <div class="sidebar-header">
          <h2>Sticky Notes</h2>
          <button class="refresh-btn" type="button" @click="void openFirstAvailableKind(entityKind)" title="刷新">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M11.67 2.33A6.27 6.27 0 007 .5C3.41.5 .5 3.41.5 7s2.91 6.5 6.5 6.5c3.08 0 5.64-2.13 6.33-5h-1.7A4.82 4.82 0 017 11.83 4.83 4.83 0 012.17 7 4.83 4.83 0 017 2.17c1.34 0 2.54.55 3.41 1.42L8.17 5.83H13.5V.5l-1.83 1.83z" fill="currentColor"/>
            </svg>
          </button>
        </div>

        <div class="action-row">
          <input class="ds-input action-input" v-model="noteSearch" type="text" placeholder="搜索..." />
        </div>

        <div class="ds-list note-list">
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

        <div class="action-row create-bar">
          <input class="ds-input action-input" v-model="draftEntityRef" type="text" placeholder="输入 ID，如 qq:group:42" @keydown.enter="void createNote()" />
          <button class="ds-primary-button action-btn" type="button" @click="void createNote()">新建</button>
        </div>
      </aside>

      <section class="ds-panel ds-panel-padding main-column">
        <p v-if="statusText" class="toast-status">{{ statusText }}</p>
        <div v-if="errorText" class="ds-status is-error error">{{ errorText }}</div>
        <div v-else-if="loadingText" class="ds-empty empty">{{ loadingText }}</div>
        <div v-else-if="noteItem === null" class="ds-empty empty">
          选择或新建一个 Sticky Note。
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
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
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

.note-panel {
  overflow: visible;
}

.refresh-btn {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 1px solid var(--panel-line-soft);
  border-radius: 8px;
  background: none;
  color: var(--muted);
  cursor: pointer;
  transition: all 120ms;
}
.refresh-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
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
  border: 1px solid var(--panel-line-soft);
  background: var(--panel-strong);
  color: var(--text);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
  box-shadow: var(--shadow-soft);
  z-index: 2;
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
</style>
