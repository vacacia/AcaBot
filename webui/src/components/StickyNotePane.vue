<script setup lang="ts">
import { ref, watch } from "vue"

const props = defineProps<{
  readonlyContent: string
  editableContent: string
}>()

const emit = defineEmits<{
  (e: "save-editable", content: string): void
  (e: "save-readonly", content: string): void
}>()

const readonlyDraft = ref(props.readonlyContent)
const editableDraft = ref(props.editableContent)

watch(
  () => props.readonlyContent,
  (value) => {
    readonlyDraft.value = value
  },
)

watch(
  () => props.editableContent,
  (value) => {
    editableDraft.value = value
  },
)
</script>

<template>
  <div class="layout">
    <section>
      <header>Readonly</header>
      <textarea v-model="readonlyDraft" rows="16"></textarea>
      <button type="button" @click="emit('save-readonly', readonlyDraft)">保存只读区</button>
    </section>
    <section>
      <header>Editable</header>
      <textarea v-model="editableDraft" rows="16"></textarea>
      <button type="button" @click="emit('save-editable', editableDraft)">保存可编辑区</button>
    </section>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

section {
  border: 1px solid var(--panel-line-strong);
  border-radius: 10px;
  padding: 10px;
  background: var(--panel-white);
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

header {
  font-weight: 700;
  color: var(--heading-strong);
}

textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--panel-line-soft);
  border-radius: 8px;
  padding: 8px;
  font-family: monospace;
  box-sizing: border-box;
  min-height: 320px;
  background: var(--panel-strong);
  color: var(--text);
}

button {
  align-self: flex-end;
  border: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--button-primary-start) 0%, var(--button-primary-end) 100%);
  color: #fff;
  padding: 8px 14px;
  cursor: pointer;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }

  button {
    width: 100%;
    align-self: stretch;
  }
}
</style>
