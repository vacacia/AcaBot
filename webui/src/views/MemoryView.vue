<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import StickyNotePane from "../components/StickyNotePane.vue"
import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

type StickyScopeItem = {
  scope: string
  scope_key: string
  note_count: number
}

type StickyNoteSummary = {
  key: string
}

type StickyNoteItem = {
  scope: string
  scope_key: string
  key: string
  readonly: { content: string }
  editable: { content: string }
}

const MEMORY_SCOPE_STORAGE_KEY = 'acabot.memory.scope'
const MEMORY_NOTE_STORAGE_KEY = 'acabot.memory.note'

function noteListPath(scope: string, scopeKey: string): string {
  return `/api/memory/sticky-notes?scope=${encodeURIComponent(scope)}&scope_key=${encodeURIComponent(scopeKey)}`
}

function noteItemPath(scope: string, scopeKey: string, key: string): string {
  return `/api/memory/sticky-notes/item?scope=${encodeURIComponent(scope)}&scope_key=${encodeURIComponent(scopeKey)}&key=${encodeURIComponent(key)}`
}

function readStoredScope() {
  const raw = localStorage.getItem(MEMORY_SCOPE_STORAGE_KEY)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as { scope: string; scope_key: string }
  } catch {
    return null
  }
}

function readStoredNote() {
  const raw = localStorage.getItem(MEMORY_NOTE_STORAGE_KEY)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as { scope: string; scope_key: string; key: string }
  } catch {
    return null
  }
}

const cachedScopes = peekCachedGet<{ items: StickyScopeItem[] }>('/api/memory/sticky-notes/scopes')
const storedScope = readStoredScope()
const storedNote = readStoredNote()
const initialScope = storedScope?.scope || 'channel'
const initialScopeKey = storedScope?.scope_key || ''
const cachedNotes = initialScopeKey
  ? peekCachedGet<{ items: StickyNoteSummary[] }>(noteListPath(initialScope, initialScopeKey))
  : null
const cachedNoteItem = storedNote
  ? peekCachedGet<StickyNoteItem>(noteItemPath(storedNote.scope, storedNote.scope_key, storedNote.key))
  : null

const scopeItems = ref<StickyScopeItem[]>(cachedScopes?.items ?? [])
const noteItems = ref<StickyNoteSummary[]>(cachedNotes?.items ?? [])
const noteSearch = ref('')
const selectedScope = ref(cachedNoteItem?.scope || initialScope)
const selectedScopeKey = ref(cachedNoteItem?.scope_key || initialScopeKey)
const selectedNoteKey = ref(cachedNoteItem?.key || storedNote?.key || '')
const noteItem = ref<StickyNoteItem | null>(cachedNoteItem)
const draftScope = ref(cachedNoteItem?.scope || initialScope)
const draftScopeKey = ref(cachedNoteItem?.scope_key || initialScopeKey)
const newNoteKey = ref('')
const loadingText = ref(cachedNoteItem || cachedNotes || cachedScopes ? '' : '正在加载 sticky notes...')
const statusText = ref('')
const errorText = ref('')

let statusTimer: ReturnType<typeof setTimeout> | null = null

const filteredNoteItems = computed(() => {
  const keyword = noteSearch.value.trim().toLowerCase()
  if (!keyword) {
    return noteItems.value
  }
  return noteItems.value.filter((item) => item.key.toLowerCase().includes(keyword))
})

function clearStatus(): void {
  statusText.value = ''
  if (statusTimer !== null) {
    clearTimeout(statusTimer)
    statusTimer = null
  }
}

function showStatus(message: string): void {
  clearStatus()
  statusText.value = message
  statusTimer = setTimeout(() => {
    statusText.value = ''
    statusTimer = null
  }, 1400)
}

async function loadScopes(): Promise<void> {
  const payload = await apiGet<{ items: StickyScopeItem[] }>('/api/memory/sticky-notes/scopes')
  scopeItems.value = payload.items ?? []
}

async function openScope(scope: string, scopeKey: string, preserveCurrent = false): Promise<void> {
  selectedScope.value = scope
  selectedScopeKey.value = scopeKey
  draftScope.value = scope
  draftScopeKey.value = scopeKey
  noteSearch.value = ''
  if (!preserveCurrent) {
    selectedNoteKey.value = ''
    noteItem.value = null
  }
  localStorage.setItem(MEMORY_SCOPE_STORAGE_KEY, JSON.stringify({ scope, scope_key: scopeKey }))
  const payload = await apiGet<{ items: StickyNoteSummary[] }>(noteListPath(scope, scopeKey))
  noteItems.value = payload.items ?? []
  if (preserveCurrent && selectedNoteKey.value && noteItems.value.some((item) => item.key === selectedNoteKey.value)) {
    return
  }
  if (noteItems.value[0]?.key) {
    await openNote(noteItems.value[0].key)
  }
}

async function openNote(key: string): Promise<void> {
  if (!selectedScope.value || !selectedScopeKey.value) return
  const payload = await apiGet<StickyNoteItem>(noteItemPath(selectedScope.value, selectedScopeKey.value, key))
  selectedNoteKey.value = key
  noteItem.value = payload
  localStorage.setItem(
    MEMORY_NOTE_STORAGE_KEY,
    JSON.stringify({
      scope: payload.scope,
      scope_key: payload.scope_key,
      key: payload.key,
    }),
  )
}

async function browseScope(): Promise<void> {
  if (!draftScopeKey.value.trim()) {
    errorText.value = '先填写右上角的 scope key，再点击浏览。'
    clearStatus()
    return
  }
  errorText.value = ''
  clearStatus()
  try {
    await openScope(draftScope.value, draftScopeKey.value.trim())
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '读取 sticky note scope 失败'
  }
}

async function createNote(): Promise<void> {
  if (!draftScopeKey.value.trim()) {
    errorText.value = '新建 note 前，先在右上角填写 scope key 并点击浏览。'
    clearStatus()
    return
  }
  if (!newNoteKey.value.trim()) {
    errorText.value = '先填写 note key，再点击新建。'
    clearStatus()
    return
  }
  errorText.value = ''
  clearStatus()
  try {
    await apiPost<StickyNoteItem>('/api/memory/sticky-notes/item', {
      scope: draftScope.value,
      scope_key: draftScopeKey.value.trim(),
      key: newNoteKey.value.trim(),
    })
    newNoteKey.value = ''
    await loadScopes()
    await openScope(draftScope.value, draftScopeKey.value.trim())
    showStatus('已创建并打开新的 sticky note')
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '新建 sticky note 失败'
  }
}

async function saveReadonly(content: string): Promise<void> {
  if (!noteItem.value) return
  errorText.value = ''
  clearStatus()
  try {
    noteItem.value = await apiPut<StickyNoteItem>('/api/memory/sticky-notes/readonly', {
      scope: noteItem.value.scope,
      scope_key: noteItem.value.scope_key,
      key: noteItem.value.key,
      content,
    })
    showStatus('只读区已保存')
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '保存只读区失败'
  }
}

async function saveEditable(content: string): Promise<void> {
  if (!noteItem.value) return
  errorText.value = ''
  clearStatus()
  try {
    noteItem.value = await apiPut<StickyNoteItem>('/api/memory/sticky-notes/item', {
      scope: noteItem.value.scope,
      scope_key: noteItem.value.scope_key,
      key: noteItem.value.key,
      content,
    })
    showStatus('可编辑区已保存')
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '保存可编辑区失败'
  }
}

onMounted(() => {
  void (async () => {
    errorText.value = ''
    try {
      await loadScopes()
      const preferredScope = draftScopeKey.value.trim()
        ? { scope: draftScope.value, scope_key: draftScopeKey.value.trim() }
        : scopeItems.value[0]
          ? { scope: scopeItems.value[0].scope, scope_key: scopeItems.value[0].scope_key }
          : null
      if (preferredScope) {
        const preserveCurrent =
          Boolean(noteItem.value)
          && noteItem.value?.scope === preferredScope.scope
          && noteItem.value?.scope_key === preferredScope.scope_key
        await openScope(preferredScope.scope, preferredScope.scope_key, preserveCurrent)
        const preferredNote =
          storedNote
          && storedNote.scope === preferredScope.scope
          && storedNote.scope_key === preferredScope.scope_key
          && noteItems.value.some((item) => item.key === storedNote.key)
            ? storedNote.key
            : ''
        if (preferredNote) {
          await openNote(preferredNote)
        }
      }
    } catch (error) {
      errorText.value = error instanceof Error ? error.message : '加载 sticky notes 失败'
    } finally {
      loadingText.value = ''
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
        <h1>Sticky Notes</h1>
        <p class="ds-summary">第一版只暴露 sticky note。每条 note 都分为只读区和可编辑区，并且两块都会进入上下文。</p>
      </div>
      <div class="ds-actions scope-tools">
        <select class="ds-select" v-model="draftScope">
          <option value="user">user</option>
          <option value="channel">channel</option>
        </select>
        <input class="ds-input" v-model="draftScopeKey" type="text" placeholder="先填 scope key，例如 qq:user:1733064202" />
        <button class="ds-primary-button" type="button" @click="void browseScope()">浏览</button>
      </div>
    </header>

    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column note-panel">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>Notes</h2>
              <p class="ds-summary">{{ selectedScopeKey || '先选择 scope' }}</p>
            </div>
          </div>
        </div>

        <div class="ds-field note-search">
          <input class="ds-input" v-model="noteSearch" type="text" placeholder="搜索 note" />
        </div>

        <div class="ds-list note-list">
          <p v-if="errorText" class="ds-status is-error error">{{ errorText }}</p>
          <p v-if="noteItems.length > 0 && filteredNoteItems.length === 0" class="ds-empty empty">没有匹配的 note。</p>
          <button
            v-for="item in filteredNoteItems"
            :key="item.key"
            class="list-item"
            :class="{ active: item.key === selectedNoteKey }"
            type="button"
            @click="void openNote(item.key)"
          >
            {{ item.key }}
          </button>
        </div>

        <div class="create-bar note-create">
          <div class="new-note">
            <input class="ds-input" v-model="newNoteKey" type="text" placeholder="再填 note key，例如 default" />
            <button class="ds-secondary-button" type="button" @click="void createNote()">新建</button>
          </div>
        </div>
      </aside>

      <section class="ds-panel ds-panel-padding main-column">
        <p v-if="statusText" class="toast-status">{{ statusText }}</p>
        <div v-if="errorText" class="ds-status is-error error">{{ errorText }}</div>
        <div v-else-if="loadingText" class="ds-empty empty">{{ loadingText }}</div>
        <div v-else-if="noteItem === null" class="ds-empty empty">
          先在右上角输入 scope key 并点击浏览。如果是第一次创建，直接在左侧 Notes 里填 note key，然后点“新建”。
        </div>
        <StickyNotePane
          v-else
          :readonly-content="noteItem.readonly.content"
          :editable-content="noteItem.editable.content"
          @save-readonly="(value) => void saveReadonly(value)"
          @save-editable="(value) => void saveEditable(value)"
        />
      </section>
    </div>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.main-column {
  min-width: 0;
}

.compact-head {
  margin-bottom: 14px;
}

.scope-tools {
  flex: 1 1 360px;
}

.scope-tools .ds-input {
  min-width: 260px;
}

.note-list {
  min-height: 160px;
  max-height: 420px;
  overflow: auto;
}

.list-item {
  width: 100%;
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
  font-weight: 700;
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
  .layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .scope-tools,
  .new-note {
    justify-content: stretch;
  }

  .scope-tools .ds-select,
  .scope-tools .ds-primary-button,
  .new-note .ds-secondary-button {
    flex: 1 0 auto;
  }

  .scope-tools .ds-input,
  .new-note .ds-input {
    flex-basis: 100%;
    min-width: 0;
  }
}
</style>
