<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import { apiGet, apiPut, peekCachedGet } from "../lib/api"

type SoulFileItem = {
  name: string
  is_core: boolean
  exists: boolean
  size: number
  updated_at: number
}

type SoulFilePayload = {
  name: string
  is_core: boolean
  content: string
}

const files = ref<SoulFileItem[]>(peekCachedGet<{ items: SoulFileItem[] }>("/api/soul/files")?.items ?? [])
const selectedName = ref(files.value[0]?.name ?? "")
const content = ref(selectedName.value ? (peekCachedGet<SoulFilePayload>(`/api/soul/file?name=${encodeURIComponent(selectedName.value)}`)?.content ?? "") : "")
const draft = ref("")
const errorText = ref("")
const statusText = ref("")
const loading = ref(files.value.length === 0)
const dailyExpanded = ref(true)

let statusTimer: ReturnType<typeof setTimeout> | null = null

/** Root-level files (today.md + other non-daily) */
const rootFiles = computed(() =>
  files.value.filter((f) => !f.name.includes("/"))
)

/** Daily files grouped under daily/ */
const dailyFiles = computed(() =>
  files.value.filter((f) => f.name.startsWith("daily/"))
)

function showStatus(message: string): void {
  statusText.value = message
  if (statusTimer) clearTimeout(statusTimer)
  statusTimer = setTimeout(() => { statusText.value = "" }, 1400)
}

function formatDate(ts: number): string {
  if (!ts) return ""
  return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function displayName(name: string): string {
  const slash = name.lastIndexOf("/")
  return slash >= 0 ? name.slice(slash + 1) : name
}

const refreshSpinning = ref(false)

async function loadFiles(preferredName = ""): Promise<void> {
  refreshSpinning.value = true
  try {
    const payload = await apiGet<{ items: SoulFileItem[] }>("/api/soul/files")
    files.value = payload.items ?? []
    const nextName = preferredName || selectedName.value || files.value[0]?.name || ""
    if (nextName) {
      await loadFile(nextName)
    }
  } finally {
    // Keep spinning a bit longer so user notices
    setTimeout(() => { refreshSpinning.value = false }, 300)
  }
}

async function loadFile(name: string): Promise<void> {
  if (!name) return
  const payload = await apiGet<SoulFilePayload>(`/api/soul/file?name=${encodeURIComponent(name)}`)
  selectedName.value = payload.name
  content.value = payload.content
  draft.value = payload.content
}

async function saveFile(): Promise<void> {
  if (!selectedName.value) return
  errorText.value = ""
  try {
    const saved = await apiPut<SoulFilePayload>("/api/soul/file", {
      name: selectedName.value,
      content: draft.value,
    })
    content.value = saved.content
    draft.value = saved.content
    showStatus("已保存")
    await loadFiles(saved.name)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存失败"
  }
}

onBeforeUnmount(() => {
  if (statusTimer) {
    clearTimeout(statusTimer)
    statusTimer = null
  }
})

onMounted(() => {
  void (async () => {
    try {
      await loadFiles()
    } catch (error) {
      errorText.value = error instanceof Error ? error.message : "加载失败"
    } finally {
      loading.value = false
    }
  })()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Memory / Self</p>
        <h1>Self</h1>
      </div>
    </header>

    <div class="self-layout">
      <!-- File Tree -->
      <aside class="ds-panel ds-panel-padding tree-column soul-tree">
        <div class="tree-header">
          <h2>文件</h2>
          <button class="refresh-btn" :class="{ spinning: refreshSpinning }" type="button" @click="void loadFiles()" title="刷新">
            <svg class="refresh-icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M11.67 2.33A6.27 6.27 0 007 .5C3.41.5 .5 3.41.5 7s2.91 6.5 6.5 6.5c3.08 0 5.64-2.13 6.33-5h-1.7A4.82 4.82 0 017 11.83 4.83 4.83 0 012.17 7 4.83 4.83 0 017 2.17c1.34 0 2.54.55 3.41 1.42L8.17 5.83H13.5V.5l-1.83 1.83z" fill="currentColor"/>
            </svg>
          </button>
        </div>

        <div class="tree-list">
          <!-- Root files -->
          <button
            v-for="file in rootFiles"
            :key="file.name"
            class="tree-item"
            :class="{ active: file.name === selectedName, 'is-core': file.is_core }"
            type="button"
            @click="void loadFile(file.name)"
          >
            <svg class="tree-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M3 2h6l4 4v8H3V2z" stroke="currentColor" stroke-width="1.2" fill="none"/>
              <path d="M9 2v4h4" stroke="currentColor" stroke-width="1.2" fill="none"/>
            </svg>
            <span class="tree-name">{{ displayName(file.name) }}</span>
            <span v-if="file.is_core" class="tree-badge">core</span>
            <span class="tree-meta">{{ formatSize(file.size) }}</span>
          </button>

          <!-- daily/ folder -->
          <div v-if="dailyFiles.length > 0" class="tree-folder">
            <button class="tree-folder-toggle" type="button" @click="dailyExpanded = !dailyExpanded">
              <svg class="tree-chevron" :class="{ expanded: dailyExpanded }" width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M4.5 3L7.5 6L4.5 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <svg class="tree-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M2 4h4l1.5 2H14v8H2V4z" stroke="currentColor" stroke-width="1.2" fill="none"/>
              </svg>
              <span class="tree-name">daily</span>
              <span class="tree-meta">{{ dailyFiles.length }} 个文件</span>
            </button>
            <div v-if="dailyExpanded" class="tree-children">
              <button
                v-for="file in dailyFiles"
                :key="file.name"
                class="tree-item tree-child"
                :class="{ active: file.name === selectedName }"
                type="button"
                @click="void loadFile(file.name)"
              >
                <svg class="tree-icon" width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M3 2h6l4 4v8H3V2z" stroke="currentColor" stroke-width="1.2" fill="none"/>
                  <path d="M9 2v4h4" stroke="currentColor" stroke-width="1.2" fill="none"/>
                </svg>
                <span class="tree-name">{{ displayName(file.name) }}</span>
                <span class="tree-meta">{{ formatDate(file.updated_at) }}</span>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <!-- Editor -->
      <section class="ds-panel ds-panel-padding editor-column soul-editor">
        <Transition name="toast">
          <div v-if="statusText" class="toast-status">{{ statusText }}</div>
        </Transition>
        <p v-if="errorText" class="ds-status is-error">{{ errorText }}</p>
        <p v-else-if="loading" class="ds-empty">正在加载...</p>
        <Transition v-else-if="selectedName" name="editor-swap" mode="out-in">
          <div :key="selectedName" class="editor-stack">
            <div class="editor-head">
              <div class="editor-title">
                <span class="editor-filename">{{ selectedName }}</span>
                <Transition name="dirty">
                  <span v-if="draft !== content" class="editor-dirty">未保存</span>
                </Transition>
              </div>
              <button class="ds-primary-button editor-save-btn" type="button" @click="void saveFile()">保存</button>
            </div>
            <textarea class="ds-textarea ds-mono editor-textarea" v-model="draft" rows="24" spellcheck="false"></textarea>
          </div>
        </Transition>
        <div v-else class="ds-empty">选择一个文件开始编辑。</div>
      </section>
    </div>
  </section>
</template>

<style scoped>
/* ─── Layout entrance ─────────────────────────────── */
.self-layout {
  display: grid;
  grid-template-columns: minmax(0, 280px) minmax(0, 1fr);
  gap: 16px;
}

.soul-tree {
  opacity: 0;
  transform: translateX(-12px);
  animation: panel-in 360ms cubic-bezier(0.25, 1, 0.5, 1) 60ms forwards;
}

.soul-editor {
  opacity: 0;
  transform: translateX(12px);
  animation: panel-in 360ms cubic-bezier(0.25, 1, 0.5, 1) 120ms forwards;
}

@keyframes panel-in {
  to { opacity: 1; transform: translateX(0); }
}

/* ─── Tree items stagger ─────────────────────────── */
.tree-item {
  opacity: 0;
  transform: translateY(4px);
  animation: tree-item-in 240ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.tree-item:nth-child(1) { animation-delay: 160ms; }
.tree-item:nth-child(2) { animation-delay: 200ms; }
.tree-item:nth-child(3) { animation-delay: 240ms; }
.tree-item:nth-child(4) { animation-delay: 280ms; }
.tree-item:nth-child(n+5) { animation-delay: 320ms; }

@keyframes tree-item-in {
  to { opacity: 1; transform: translateY(0); }
}

/* ─── Tree item interactions ────────────────────── */
.tree-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 100ms, color 100ms;
  position: relative;
}

.tree-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--accent);
  opacity: 0;
  transition: opacity 120ms cubic-bezier(0.25, 1, 0.5, 1);
}

.tree-item:hover {
  background: var(--panel-strong);
}

.tree-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.tree-item.active::before {
  opacity: 1;
}

.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.tree-header h2 {
  margin: 0;
  font-size: 16px;
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

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tree-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 100ms;
}

.tree-item:hover {
  background: var(--panel-strong);
}

.tree-item.active {
  background: var(--accent-soft);
  color: var(--accent);
}

.tree-column {
  min-width: 0;
}

.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.tree-header h2 {
  margin: 0;
  font-size: 16px;
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
  transition: color 120ms cubic-bezier(0.25, 1, 0.5, 1),
    border-color 120ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 300ms cubic-bezier(0.25, 1, 0.5, 1);
}
.refresh-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.refresh-btn:active {
  transform: scale(0.92);
}
.refresh-btn.spinning .refresh-icon {
  animation: spin 500ms cubic-bezier(0.25, 1, 0.5, 1);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.tree-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tree-child {
  padding-left: 30px;
}

.tree-icon {
  flex-shrink: 0;
  opacity: 0.5;
  transition: opacity 120ms;
}

.tree-item.active .tree-icon {
  opacity: 1;
}

.tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.tree-badge {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.tree-meta {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  transition: color 120ms;
}

.tree-item.active .tree-meta {
  color: var(--accent);
  opacity: 0.6;
}

/* Folder */
.tree-folder {
  margin-top: 4px;
}

.tree-folder-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 100ms;
}

.tree-folder-toggle:hover {
  background: var(--panel-strong);
}

.tree-chevron {
  flex-shrink: 0;
  transition: transform 150ms cubic-bezier(0.25, 1, 0.5, 1);
  color: var(--muted);
}

.tree-chevron.expanded {
  transform: rotate(90deg);
}

.tree-children {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 2px;
}

/* Editor */
.editor-column {
  min-width: 0;
  position: relative;
}

.editor-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.editor-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.editor-filename {
  font-size: 14px;
  font-weight: 700;
  color: var(--heading-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.editor-dirty {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.editor-textarea {
  min-height: 480px;
  resize: vertical;
  transition: border-color 150ms cubic-bezier(0.25, 1, 0.5, 1),
    box-shadow 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.editor-textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
}

.editor-save-btn {
  transition: transform 100ms cubic-bezier(0.25, 1, 0.5, 1),
    opacity 150ms;
}
.editor-save-btn:active {
  transform: scale(0.95);
}

/* Toast */
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

/* Toast transition */
.toast-enter-active { animation: toast-in 200ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
.toast-leave-active { animation: toast-out 180ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
@keyframes toast-in {
  from { opacity: 0; transform: translateY(-6px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes toast-out {
  from { opacity: 1; transform: translateY(0) scale(1); }
  to   { opacity: 0; transform: translateY(-4px) scale(0.97); }
}

/* Editor swap transition */
.editor-swap-enter-active { animation: editor-fade-in 220ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
.editor-swap-leave-active { animation: editor-fade-out 140ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
@keyframes editor-fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes editor-fade-out {
  from { opacity: 1; transform: translateY(0); }
  to   { opacity: 0; transform: translateY(-4px); }
}

/* Dirty badge transition */
.dirty-enter-active { animation: dirty-in 200ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
.dirty-leave-active { animation: dirty-out 140ms cubic-bezier(0.25, 1, 0.5, 1) forwards; }
@keyframes dirty-in {
  from { opacity: 0; transform: scale(0.85); }
  to   { opacity: 1; transform: scale(1); }
}
@keyframes dirty-out {
  from { opacity: 1; transform: scale(1); }
  to   { opacity: 0; transform: scale(0.85); }
}

@media (max-width: 900px) {
  .self-layout {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .soul-tree,
  .soul-editor,
  .tree-item,
  .refresh-btn,
  .refresh-btn.spinning .refresh-icon,
  .tree-chevron,
  .toast-enter-active,
  .toast-leave-active,
  .editor-swap-enter-active,
  .editor-swap-leave-active,
  .dirty-enter-active,
  .dirty-leave-active {
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
  }
  .toast-status { display: inline-flex; }
}
</style>
