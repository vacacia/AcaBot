<script setup lang="ts">
import { onMounted, ref } from "vue"

import StickyNotePane from "../components/StickyNotePane.vue"
import { apiGet, apiPost, apiPut } from "../lib/api"

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

const scopeItems = ref<StickyScopeItem[]>([])
const noteItems = ref<StickyNoteSummary[]>([])
const selectedScope = ref("channel")
const selectedScopeKey = ref("")
const selectedNoteKey = ref("")
const noteItem = ref<StickyNoteItem | null>(null)
const draftScope = ref("channel")
const draftScopeKey = ref("")
const newNoteKey = ref("")
const errorText = ref("")

async function loadScopes(): Promise<void> {
  const payload = await apiGet<{ items: StickyScopeItem[] }>("/api/memory/sticky-notes/scopes")
  scopeItems.value = payload.items ?? []
}

async function openScope(scope: string, scopeKey: string): Promise<void> {
  selectedScope.value = scope
  selectedScopeKey.value = scopeKey
  draftScope.value = scope
  draftScopeKey.value = scopeKey
  selectedNoteKey.value = ""
  noteItem.value = null
  const payload = await apiGet<{ items: StickyNoteSummary[] }>(
    `/api/memory/sticky-notes?scope=${encodeURIComponent(scope)}&scope_key=${encodeURIComponent(scopeKey)}`,
  )
  noteItems.value = payload.items ?? []
  if (noteItems.value[0]?.key) {
    await openNote(noteItems.value[0].key)
  }
}

async function openNote(key: string): Promise<void> {
  if (!selectedScope.value || !selectedScopeKey.value) return
  const payload = await apiGet<StickyNoteItem>(
    `/api/memory/sticky-notes/item?scope=${encodeURIComponent(selectedScope.value)}&scope_key=${encodeURIComponent(selectedScopeKey.value)}&key=${encodeURIComponent(key)}`,
  )
  selectedNoteKey.value = key
  noteItem.value = payload
}

async function browseScope(): Promise<void> {
  if (!draftScopeKey.value.trim()) return
  errorText.value = ""
  try {
    await openScope(draftScope.value, draftScopeKey.value.trim())
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "读取 sticky note scope 失败"
  }
}

async function createNote(): Promise<void> {
  if (!draftScopeKey.value.trim() || !newNoteKey.value.trim()) return
  errorText.value = ""
  try {
    await apiPost<StickyNoteItem>("/api/memory/sticky-notes/item", {
      scope: draftScope.value,
      scope_key: draftScopeKey.value.trim(),
      key: newNoteKey.value.trim(),
    })
    newNoteKey.value = ""
    await openScope(draftScope.value, draftScopeKey.value.trim())
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "新建 sticky note 失败"
  }
}

async function saveReadonly(content: string): Promise<void> {
  if (!noteItem.value) return
  noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/readonly", {
    scope: noteItem.value.scope,
    scope_key: noteItem.value.scope_key,
    key: noteItem.value.key,
    content,
  })
}

async function saveEditable(content: string): Promise<void> {
  if (!noteItem.value) return
  noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/item", {
    scope: noteItem.value.scope,
    scope_key: noteItem.value.scope_key,
    key: noteItem.value.key,
    content,
  })
}

onMounted(() => {
  void loadScopes().then(() => {
    const first = scopeItems.value[0]
    if (first) {
      return openScope(first.scope, first.scope_key)
    }
    return Promise.resolve()
  })
})
</script>

<template>
  <section class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">Memory</p>
        <h1>Sticky Notes</h1>
        <p class="summary">第一版只暴露 sticky note。每条 note 都分为只读区和可编辑区，并且两块都会进入上下文。</p>
      </div>
      <div class="scope-tools">
        <select v-model="draftScope">
          <option value="user">user</option>
          <option value="channel">channel</option>
        </select>
        <input v-model="draftScopeKey" type="text" placeholder="scope key，例如 qq:group:42" />
        <button type="button" @click="void browseScope()">浏览</button>
      </div>
    </header>

    <div class="content">
      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>已存在 Scope</h2>
              <p>点进去以后再看 note 列表。</p>
            </div>
          </div>
          <button
            v-for="item in scopeItems"
            :key="`${item.scope}:${item.scope_key}`"
            class="list-item"
            :class="{ active: item.scope === selectedScope && item.scope_key === selectedScopeKey }"
            type="button"
            @click="void openScope(item.scope, item.scope_key)"
          >
            <strong>{{ item.scope }}</strong>
            <span>{{ item.scope_key }}</span>
          </button>
        </section>

        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Notes</h2>
              <p>{{ selectedScopeKey || "先选择 scope" }}</p>
            </div>
          </div>
          <div class="new-note">
            <input v-model="newNoteKey" type="text" placeholder="新建 note key" />
            <button type="button" @click="void createNote()">新建</button>
          </div>
          <button
            v-for="item in noteItems"
            :key="item.key"
            class="list-item"
            :class="{ active: item.key === selectedNoteKey }"
            type="button"
            @click="void openNote(item.key)"
          >
            {{ item.key }}
          </button>
        </section>
      </aside>

      <section class="main-panel">
        <div v-if="errorText" class="error">{{ errorText }}</div>
        <div v-else-if="noteItem === null" class="empty">先选择一个 sticky note，或者先新建一个。</div>
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
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero,
.panel,
.main-panel {
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
h2 {
  margin: 0;
}

.summary,
.panel-header p {
  margin: 8px 0 0;
  color: var(--muted);
}

.scope-tools,
.new-note {
  display: flex;
  gap: 10px;
}

select,
input,
button {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
}

button {
  cursor: pointer;
}

.content {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel,
.main-panel {
  padding: 18px;
}

.panel-header {
  margin-bottom: 14px;
}

.list-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  text-align: left;
}

.list-item.active {
  background: var(--accent-soft);
}

.error,
.empty {
  padding: 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.64);
  color: var(--muted);
}
</style>
