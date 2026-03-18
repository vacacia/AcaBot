<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet } from "../lib/api"

type PromptSummary = {
  prompt_ref: string
}

type PromptItem = {
  prompt_ref: string
  content: string
}

const prompts = ref<PromptSummary[]>([])
const selectedRef = ref("")
const content = ref("")

async function loadPrompts(): Promise<void> {
  prompts.value = await apiGet<PromptSummary[]>("/api/prompts")
  if (prompts.value[0]?.prompt_ref) {
    await loadPrompt(prompts.value[0].prompt_ref)
  }
}

async function loadPrompt(promptRef: string): Promise<void> {
  const payload = await apiGet<PromptItem>(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`)
  selectedRef.value = payload.prompt_ref
  content.value = payload.content
}

onMounted(() => {
  void loadPrompts()
})
</script>

<template>
  <section class="layout">
    <aside class="panel sidebar">
      <p class="eyebrow">Prompts</p>
      <h1>Prompt 列表</h1>
      <button
        v-for="item in prompts"
        :key="item.prompt_ref"
        class="list-item"
        :class="{ active: item.prompt_ref === selectedRef }"
        type="button"
        @click="void loadPrompt(item.prompt_ref)"
      >
        {{ item.prompt_ref }}
      </button>
    </aside>
    <article class="panel editor">
      <h1>{{ selectedRef || "请选择一个 Prompt" }}</h1>
      <textarea :value="content" readonly rows="20"></textarea>
    </article>
  </section>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
}

.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 20px;
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
  margin: 0 0 14px;
}

.list-item,
textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
}

.list-item {
  display: block;
  margin-bottom: 10px;
  text-align: left;
  cursor: pointer;
}

.list-item.active {
  background: var(--accent-soft);
}

textarea {
  box-sizing: border-box;
  resize: vertical;
}
</style>
