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
  <div class="layout ds-two-column">
    <aside class="list ds-panel ds-card-padding-sm">
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
    <section class="editor ds-panel ds-card-padding-sm">
      <textarea class="ds-textarea ds-mono" v-model="draft" rows="24"></textarea>
      <button class="ds-primary-button save" type="button" @click="emit('save', { name: selectedName, content: draft })">
        保存
      </button>
    </section>
  </div>
</template>

<style scoped>
.layout {
  align-items: start;
}

.list {
  max-height: 70vh;
  overflow: auto;
}

.file-item {
  width: 100%;
  text-align: left;
  border: 0;
  border-radius: 12px;
  background: transparent;
  padding: 10px 12px;
  cursor: pointer;
  color: var(--text);
}

.file-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

.editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ds-textarea {
  min-height: 420px;
}

.save {
  align-self: flex-end;
}

@media (max-width: 900px) {
  .save {
    width: 100%;
    align-self: stretch;
  }
}
</style>
