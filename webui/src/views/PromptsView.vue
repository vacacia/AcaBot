<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPut } from "../lib/api"

type PromptSummary = {
  prompt_ref: string
  source?: string
}

type PromptItem = {
  prompt_ref: string
  content: string
  source?: string
}

const prompts = ref<PromptSummary[]>([])
const selectedRef = ref("")
const draftName = ref("")
const content = ref("")
const loading = ref(true)
const saveMessage = ref("")
const errorMessage = ref("")

function promptName(promptRef: string): string {
  return String(promptRef || "").replace(/^prompt\//, "")
}

function promptRefFromName(name: string): string {
  return `prompt/${name.trim()}`
}

async function loadPrompts(preferredRef = ""): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    prompts.value = await apiGet<PromptSummary[]>("/api/prompts")
    const targetRef = preferredRef || selectedRef.value || prompts.value[0]?.prompt_ref || ""
    if (targetRef) {
      await loadPrompt(targetRef)
    } else {
      createPrompt()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败"
  } finally {
    loading.value = false
  }
}

async function loadPrompt(promptRef: string): Promise<void> {
  const payload = await apiGet<PromptItem>(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`)
  selectedRef.value = payload.prompt_ref
  draftName.value = promptName(payload.prompt_ref)
  content.value = payload.content
  saveMessage.value = ""
  errorMessage.value = ""
}

function createPrompt(): void {
  selectedRef.value = ""
  draftName.value = ""
  content.value = ""
  saveMessage.value = ""
  errorMessage.value = ""
}

async function savePrompt(): Promise<void> {
  const name = draftName.value.trim()
  if (!name) {
    errorMessage.value = "名字不能为空"
    return
  }
  const nextRef = promptRefFromName(name)
  if (selectedRef.value && selectedRef.value !== nextRef) {
    errorMessage.value = "当前版本不支持直接改名。请新建一个新提示词，再手动切换引用。"
    saveMessage.value = ""
    return
  }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    await apiPut<PromptItem>(`/api/prompt?prompt_ref=${encodeURIComponent(nextRef)}`, {
      content: content.value,
    })
    selectedRef.value = nextRef
    saveMessage.value = "已保存"
    await loadPrompts(nextRef)
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function deletePrompt(): Promise<void> {
  if (!selectedRef.value) {
    return
  }
  saveMessage.value = ""
  errorMessage.value = ""
  try {
    await apiDelete<{ deleted: boolean }>(`/api/prompt?prompt_ref=${encodeURIComponent(selectedRef.value)}`)
    selectedRef.value = ""
    draftName.value = ""
    content.value = ""
    saveMessage.value = "已删除"
    await loadPrompts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "删除失败"
  }
}

onMounted(() => {
  void loadPrompts()
})
</script>

<template>
  <section class="layout">
    <aside class="panel sidebar">
      <div class="sidebar-header">
        <div>
          <p class="eyebrow">Prompts</p>
          <h1>提示词</h1>
        </div>
        <button class="ghost-button" type="button" @click="createPrompt">+</button>
      </div>
      <button
        v-for="item in prompts"
        :key="item.prompt_ref"
        class="list-item"
        :class="{ active: item.prompt_ref === selectedRef }"
        type="button"
        @click="void loadPrompt(item.prompt_ref)"
      >
        {{ promptName(item.prompt_ref) }}
      </button>
    </aside>

    <article class="panel editor">
      <div class="editor-header">
        <div>
          <h1>{{ draftName || "新建提示词" }}</h1>
          <p class="summary">用户只看名字和内容，内部再映射到 <code>prompt/&lt;name&gt;</code>。</p>
        </div>
        <div class="actions">
          <button class="ghost-button" type="button" :disabled="!selectedRef" @click="void deletePrompt()">
            删除
          </button>
          <button class="primary-button" type="button" :disabled="loading" @click="void savePrompt()">
            保存
          </button>
        </div>
      </div>

      <p v-if="saveMessage" class="status ok">{{ saveMessage }}</p>
      <p v-if="errorMessage" class="status error">{{ errorMessage }}</p>
      <p v-if="loading" class="summary">正在加载提示词...</p>

      <div v-else class="editor-body">
        <label class="field">
          <span>名字</span>
          <input v-model="draftName" type="text" />
        </label>
        <label class="field">
          <span>内容</span>
          <textarea v-model="content" rows="20"></textarea>
        </label>
      </div>
    </article>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
}

.panel,
.list-item,
input,
textarea {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
}

.panel {
  padding: 20px;
}

.sidebar-header,
.editor-header,
.actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
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
p {
  margin: 0;
}

.summary {
  margin-top: 8px;
  color: var(--muted);
}

.list-item {
  width: 100%;
  display: block;
  margin-top: 12px;
  padding: 12px 14px;
  text-align: left;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
}

.status {
  margin-top: 16px;
  padding: 10px 12px;
  border-radius: 12px;
}

.status.ok {
  background: rgba(17, 120, 74, 0.08);
  color: #11784a;
}

.status.error {
  background: rgba(186, 41, 41, 0.08);
  color: #ba2929;
}

.editor-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: #23334f;
}

input,
textarea {
  width: 100%;
  box-sizing: border-box;
  border-radius: 12px;
  background: var(--panel-strong);
  padding: 10px 12px;
  color: var(--text);
}

textarea {
  resize: vertical;
}

.ghost-button,
.primary-button {
  border-radius: 999px;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}

.ghost-button {
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--text);
}

.primary-button {
  border: none;
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  color: #fff;
}

.primary-button:disabled,
.ghost-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
