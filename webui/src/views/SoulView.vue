<script setup lang="ts">
import { onMounted, ref } from "vue"

import FileEditorPane, { type SoulFileItem } from "../components/FileEditorPane.vue"
import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

type SoulFilePayload = {
  name: string
  is_core: boolean
  content: string
}

const files = ref<SoulFileItem[]>(peekCachedGet<{ items: SoulFileItem[] }>("/api/soul/files")?.items ?? [])
const selectedName = ref(files.value[0]?.name ?? "")
const content = ref(selectedName.value ? (peekCachedGet<SoulFilePayload>(`/api/soul/file?name=${encodeURIComponent(selectedName.value)}`)?.content ?? "") : "")
const errorText = ref("")
const newFileName = ref("")
const loading = ref(files.value.length === 0)

async function loadFiles(preferredName = ""): Promise<void> {
  const payload = await apiGet<{ items: SoulFileItem[] }>("/api/soul/files")
  files.value = payload.items ?? []
  const nextName = preferredName || selectedName.value || files.value[0]?.name || ""
  if (nextName) {
    await loadFile(nextName)
  }
}

async function loadFile(name: string): Promise<void> {
  if (!name) return
  const payload = await apiGet<SoulFilePayload>(`/api/soul/file?name=${encodeURIComponent(name)}`)
  selectedName.value = payload.name
  content.value = payload.content
}

async function saveFile(payload: { name: string; content: string }): Promise<void> {
  errorText.value = ""
  loading.value = true
  try {
    const saved = await apiPut<SoulFilePayload>("/api/soul/file", payload)
    content.value = saved.content
    await loadFiles(saved.name)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "保存 soul 文件失败"
  } finally {
    loading.value = false
  }
}

async function createFile(): Promise<void> {
  if (!newFileName.value.trim()) return
  errorText.value = ""
  loading.value = true
  try {
    const created = await apiPost<SoulFilePayload>("/api/soul/files", {
      name: newFileName.value.trim(),
      content: "",
    })
    newFileName.value = ""
    await loadFiles(created.name)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "新建 soul 文件失败"
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadFiles()
})
</script>

<template>
  <section class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">Soul</p>
        <h1>稳定自我真源</h1>
        <p class="summary">`soul` 固定进入对外交互链路，不进入维护链路。主文件会一直保持在列表顶部。</p>
      </div>
      <div class="create-row">
        <input v-model="newFileName" type="text" placeholder="新建附加文件名，例如 persona.md" />
        <button class="primary" type="button" @click="void createFile()">新建文件</button>
      </div>
    </header>

    <div v-if="errorText" class="error">{{ errorText }}</div>
    <div v-else-if="loading && files.length === 0" class="empty">正在加载 soul 文件…</div>
    <FileEditorPane
      v-else
      :files="files"
      :selected-name="selectedName"
      :content="content"
      @select="(name) => void loadFile(name)"
      @save="(payload) => void saveFile(payload)"
    />
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow);
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
}

.summary {
  margin: 8px 0 0;
  color: var(--muted);
}

.create-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

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

.primary {
  border: 0;
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  color: #fff;
}

.error,
.empty {
  padding: 18px;
  border-radius: 16px;
  background: var(--panel-strong);
  color: var(--muted);
}
</style>
