<script setup lang="ts">
import { ref, watch } from "vue"

export type SoulFileItem = {
  name: string
  is_core: boolean
}

const props = defineProps<{
  files: SoulFileItem[]
  selectedName: string
  content: string
}>()

const emit = defineEmits<{
  (e: "select", name: string): void
  (e: "save", payload: { name: string; content: string }): void
}>()

const draft = ref(props.content)
watch(
  () => props.content,
  (value) => {
    draft.value = value
  },
)
</script>

<template>
  <div class="layout">
    <aside class="list">
      <button
        v-for="file in files"
        :key="file.name"
        class="file-item"
        :class="{ active: file.name === selectedName }"
        type="button"
        @click="emit('select', file.name)"
      >
        {{ file.name }}<span v-if="file.is_core"> (core)</span>
      </button>
    </aside>
    <section class="editor">
      <textarea v-model="draft" rows="24"></textarea>
      <button class="save" type="button" @click="emit('save', { name: selectedName, content: draft })">
        保存
      </button>
    </section>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 12px;
}

.list {
  border: 1px solid var(--panel-line-strong);
  border-radius: 10px;
  padding: 8px;
  background: var(--panel-white);
  max-height: 70vh;
  overflow: auto;
}

.file-item {
  width: 100%;
  text-align: left;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 8px;
  cursor: pointer;
}

.file-item.active {
  background: var(--panel-blue-soft);
  color: var(--panel-blue-soft-text);
  font-weight: 600;
}

.editor {
  border: 1px solid var(--panel-line-strong);
  border-radius: 10px;
  padding: 10px;
  background: var(--panel-white);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

textarea {
  width: 100%;
  resize: vertical;
  min-height: 400px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 8px;
  padding: 8px;
  font-family: monospace;
  background: var(--panel-strong);
  color: var(--text);
}

.save {
  align-self: flex-end;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--button-primary-start) 0%, var(--button-primary-end) 100%);
  color: #fff;
  padding: 8px 14px;
  cursor: pointer;
}
</style>
