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
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Soul</p>
        <h1>稳定自我真源</h1>
        <p class="ds-summary">`soul` 固定进入对外交互链路，不进入维护链路。主文件会一直保持在列表顶部。</p>
      </div>
      <div class="ds-actions create-row">
        <input class="ds-input" v-model="newFileName" type="text" placeholder="新建附加文件名，例如 persona.md" />
        <button class="ds-primary-button" type="button" @click="void createFile()">新建文件</button>
      </div>
    </header>

    <p v-if="errorText" class="ds-status is-error">{{ errorText }}</p>
    <p v-else-if="loading && files.length === 0" class="ds-empty">正在加载 soul 文件…</p>
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
.create-row {
  min-width: min(420px, 100%);
}

.create-row .ds-input {
  min-width: 240px;
}
</style>
