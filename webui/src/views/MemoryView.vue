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
const loadingText = ref("正在加载 sticky notes...")
const statusText = ref("")
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
  if (!draftScopeKey.value.trim()) {
    errorText.value = "先填写右上角的 scope key，再点击浏览。"
    statusText.value = ""
    return
  }
  errorText.value = ""
  statusText.value = ""
  try {
    await openScope(draftScope.value, draftScopeKey.value.trim())
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "读取 sticky note scope 失败"
  }
}

async function createNote(): Promise<void> {
  if (!draftScopeKey.value.trim()) {
    errorText.value = "新建 note 前，先在右上角填写 scope key 并点击浏览。"
    statusText.value = ""
    return
  }
  if (!newNoteKey.value.trim()) {
    errorText.value = "先填写 note key，再点击新建。"
    statusText.value = ""
    return
  }
  errorText.value = ""
  statusText.value = ""
  try {
    await apiPost<StickyNoteItem>("/api/memory/sticky-notes/item", {
      scope: draftScope.value,
      scope_key: draftScopeKey.value.trim(),
      key: newNoteKey.value.trim(),
    })
    newNoteKey.value = ""
    await loadScopes()
    await openScope(draftScope.value, draftScopeKey.value.trim())
    statusText.value = "已创建并打开新的 sticky note"
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "新建 sticky note 失败"
  }
}

async function saveReadonly(content: string): Promise<void> {
  if (!noteItem.value) return
  errorText.value = ""
  statusText.value = ""
  try {
    noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/readonly", {
      scope: noteItem.value.scope,
      scope_key: noteItem.value.scope_key,
      key: noteItem.value.key,
      content,
    })
    statusText.value = "只读区已保存"
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存只读区失败"
  }
}

async function saveEditable(content: string): Promise<void> {
  if (!noteItem.value) return
  errorText.value = ""
  statusText.value = ""
  try {
    noteItem.value = await apiPut<StickyNoteItem>("/api/memory/sticky-notes/item", {
      scope: noteItem.value.scope,
      scope_key: noteItem.value.scope_key,
      key: noteItem.value.key,
      content,
    })
    statusText.value = "可编辑区已保存"
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存可编辑区失败"
  }
}

onMounted(() => {
  void (async () => {
    errorText.value = ""
    try {
      await loadScopes()
      const first = scopeItems.value[0]
      if (first) {
        await openScope(first.scope, first.scope_key)
      }
    } catch (error) {
      errorText.value = error instanceof Error ? error.message : "加载 sticky notes 失败"
    } finally {
      loadingText.value = ""
    }
  })()
})
</script>

<template>
  <section class="page">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">Memory</p>
        <h1>Sticky Notes</h1>
        <p class="summary">第一版只暴露 sticky note。每条 note 都分为只读区和可编辑区，并且两块都会进入上下文。</p>
      </div>
      <div class="scope-tools">
        <select v-model="draftScope">
          <option value="user">user</option>
          <option value="channel">channel</option>
        </select>
        <input v-model="draftScopeKey" type="text" placeholder="先填 scope key，例如 qq:user:1733064202" />
        <button type="button" @click="void browseScope()">浏览</button>
      </div>
    </header>

    <div class="content">
      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>已存在 Scope</h2>
              <p>先选 scope，再继续浏览下面的 note。</p>
            </div>
          </div>
          <p v-if="scopeItems.length === 0" class="panel-empty">还没有 scope。先在右上角填 scope key，再到下面新建第一条 note。</p>
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
            <input v-model="newNoteKey" type="text" placeholder="再填 note key，例如 default" />
            <button type="button" @click="void createNote()">新建</button>
          </div>
          <p v-if="errorText" class="panel-error">{{ errorText }}</p>
          <p v-if="noteItems.length === 0" class="panel-empty">右上角先填并浏览 scope，这里再填 note key，点“新建”才会创建第一条记录。</p>
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
        <div v-else-if="loadingText" class="empty">{{ loadingText }}</div>
        <div v-else-if="noteItem === null" class="empty">
          先在右上角输入 scope key 并点击浏览。如果是第一次创建，直接在左侧 Notes 里填 note key，然后点“新建”。
        </div>
        <p v-else-if="statusText" class="status">{{ statusText }}</p>
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
  min-width: 0;
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
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 18px;
  padding: 22px 24px;
}

.hero-copy {
  min-width: 0;
  flex: 1 1 360px;
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
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.scope-tools {
  flex: 1 1 320px;
  justify-content: flex-end;
}

.scope-tools input,
.new-note input {
  min-width: 0;
  flex: 1 1 220px;
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
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  gap: 16px;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.panel,
.main-panel {
  padding: 18px;
  min-width: 0;
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

.list-item strong,
.list-item span {
  overflow-wrap: anywhere;
}

.list-item.active {
  background: var(--accent-soft);
}

.error,
.empty,
.status,
.panel-empty {
  padding: 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.64);
  color: var(--muted);
}

.status {
  margin: 0 0 16px;
  color: #166534;
}

.panel-error {
  margin: 0 0 10px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(180, 35, 24, 0.08);
  color: #b42318;
}

.panel-empty {
  margin: 0 0 10px;
  padding: 14px;
}

@media (max-width: 1100px) {
  .content {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .hero,
  .panel,
  .main-panel {
    border-radius: 20px;
  }

  .hero {
    padding: 18px;
  }

  .scope-tools {
    justify-content: stretch;
  }

  .scope-tools select,
  .scope-tools button,
  .new-note button {
    flex: 1 0 auto;
  }

  .scope-tools input,
  .new-note input {
    flex-basis: 100%;
  }
}
</style>
