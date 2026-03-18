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
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

section {
  border: 1px solid #d5deea;
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

header {
  font-weight: 700;
  color: #163459;
}

textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid #cdd8e9;
  border-radius: 8px;
  padding: 8px;
  font-family: monospace;
}

button {
  align-self: flex-end;
  border: 0;
  border-radius: 8px;
  background: #0b77c5;
  color: #fff;
  padding: 8px 14px;
  cursor: pointer;
}
</style>

