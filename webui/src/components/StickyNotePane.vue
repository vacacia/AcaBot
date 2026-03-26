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
  <div class="layout ds-two-column">
    <section class="note-section ds-panel ds-card-padding-sm">
      <header class="section-title">Readonly</header>
      <textarea class="ds-textarea ds-mono" v-model="readonlyDraft" rows="16"></textarea>
      <button class="ds-primary-button note-save" type="button" @click="emit('save-readonly', readonlyDraft)">保存只读区</button>
    </section>
    <section class="note-section ds-panel ds-card-padding-sm">
      <header class="section-title">Editable</header>
      <textarea class="ds-textarea ds-mono" v-model="editableDraft" rows="16"></textarea>
      <button class="ds-primary-button note-save" type="button" @click="emit('save-editable', editableDraft)">保存可编辑区</button>
    </section>
  </div>
</template>

<style scoped>
.note-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.section-title {
  font-weight: 800;
  color: var(--heading-strong);
}

.ds-textarea {
  min-height: 320px;
}

.note-save {
  align-self: flex-end;
}

@media (max-width: 900px) {
  .note-save {
    width: 100%;
    align-self: stretch;
  }
}
</style>
