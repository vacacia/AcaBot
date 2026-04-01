<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiDelete, apiGet, apiPut, peekCachedGet } from "../lib/api"

type PromptSummary = {
  prompt_ref: string
  source?: string
}

type PromptItem = {
  prompt_ref: string
  content: string
  source?: string
}

const prompts = ref<PromptSummary[]>(peekCachedGet<PromptSummary[]>('/api/prompts') ?? [])
const selectedRef = ref('')
const draftName = ref('')
const content = ref('')
const loading = ref(prompts.value.length === 0)
const saveMessage = ref('')
const errorMessage = ref('')

const cachedInitialPrompt = prompts.value[0]
if (cachedInitialPrompt) {
  selectedRef.value = cachedInitialPrompt.prompt_ref
  draftName.value = promptName(cachedInitialPrompt.prompt_ref)
}

function promptName(promptRef: string): string {
  return String(promptRef || '').replace(/^prompt\//, '')
}

function promptRefFromName(name: string): string {
  return `prompt/${name.trim()}`
}

async function loadPrompts(preferredRef = ''): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    prompts.value = await apiGet<PromptSummary[]>('/api/prompts')
    const targetRef = preferredRef || selectedRef.value || prompts.value[0]?.prompt_ref || ''
    if (targetRef) {
      await loadPrompt(targetRef)
    } else {
      createPrompt()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadPrompt(promptRef: string): Promise<void> {
  const payload = await apiGet<PromptItem>(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`)
  selectedRef.value = payload.prompt_ref
  draftName.value = promptName(payload.prompt_ref)
  content.value = payload.content
  saveMessage.value = ''
  errorMessage.value = ''
}

function createPrompt(): void {
  selectedRef.value = ''
  draftName.value = ''
  content.value = ''
  saveMessage.value = ''
  errorMessage.value = ''
}

async function savePrompt(): Promise<void> {
  const name = draftName.value.trim()
  if (!name) {
    errorMessage.value = '名字不能为空'
    return
  }
  const nextRef = promptRefFromName(name)
  if (selectedRef.value && selectedRef.value !== nextRef) {
    errorMessage.value = '当前版本不支持直接改名。请新建一个新提示词，再手动切换引用。'
    saveMessage.value = ''
    return
  }
  saveMessage.value = '保存中...'
  errorMessage.value = ''
  try {
    await apiPut<PromptItem>(`/api/prompt?prompt_ref=${encodeURIComponent(nextRef)}`, {
      content: content.value,
    })
    selectedRef.value = nextRef
    saveMessage.value = '已保存'
    await loadPrompts(nextRef)
  } catch (error) {
    saveMessage.value = ''
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function deletePrompt(): Promise<void> {
  if (!selectedRef.value) {
    return
  }
  saveMessage.value = ''
  errorMessage.value = ''
  try {
    await apiDelete<{ deleted: boolean }>(`/api/prompt?prompt_ref=${encodeURIComponent(selectedRef.value)}`)
    selectedRef.value = ''
    draftName.value = ''
    content.value = ''
    saveMessage.value = '已删除'
    await loadPrompts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '删除失败'
  }
}

onMounted(() => {
  void loadPrompts()
})
</script>

<template>
  <section class="ds-page">
    <div class="layout">
      <aside class="ds-panel ds-panel-padding sidebar-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <p class="ds-eyebrow">Prompts</p>
              <h2>提示词</h2>
            </div>
          </div>
          <button class="ds-secondary-button round-button" type="button" @click="createPrompt">+</button>
        </div>
        <div class="ds-list">
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
        </div>
      </aside>

      <article class="ds-panel ds-panel-padding editor-column">
        <div class="ds-section-head compact-head">
          <div class="ds-section-title">
            <div>
              <h2>{{ draftName || '新建提示词' }}</h2>
            </div>
          </div>
          <div class="ds-actions">
            <button class="ds-secondary-button" type="button" :disabled="!selectedRef" @click="void deletePrompt()">删除</button>
            <button class="ds-primary-button" type="button" :disabled="loading" @click="void savePrompt()">保存</button>
          </div>
        </div>

        <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
        <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
        <p v-if="loading" class="ds-empty">正在加载提示词...</p>

        <div v-else class="editor-body">
          <label class="ds-field">
            <span>名字</span>
            <input class="ds-input" v-model="draftName" type="text" />
          </label>
          <label class="ds-field">
            <span>内容</span>
            <textarea class="ds-textarea ds-mono" v-model="content" rows="20"></textarea>
          </label>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
}

.sidebar-column,
.editor-column {
  min-width: 0;
}

.compact-head {
  margin-bottom: 14px;
}

.round-button {
  min-width: 44px;
  padding-inline: 0;
}

.list-item {
  width: 100%;
  display: block;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-white);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

.editor-body {
  display: grid;
  gap: 14px;
}

.ds-textarea {
  min-height: 320px;
}

@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
