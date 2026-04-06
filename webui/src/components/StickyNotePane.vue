<script setup lang="ts">
import { computed, ref, watch } from "vue"

const props = defineProps<{
  readonlyContent: string
  editableContent: string
}>()

const emit = defineEmits<{
  (e: "save", readonly: string, editable: string): void
}>()

const readonlyDraft = ref(props.readonlyContent)
const editableDraft = ref(props.editableContent)
const originalReadonly = ref(props.readonlyContent)
const originalEditable = ref(props.editableContent)

const isDirty = computed(
  () => readonlyDraft.value !== originalReadonly.value || editableDraft.value !== originalEditable.value,
)

watch(
  () => props.readonlyContent,
  (value) => {
    readonlyDraft.value = value
    originalReadonly.value = value
  },
)

watch(
  () => props.editableContent,
  (value) => {
    editableDraft.value = value
    originalEditable.value = value
  },
)
</script>

<template>
  <div class="pane-layout">
    <div class="note-columns">
      <section class="note-section ds-panel ds-card-padding-sm">
        <header class="section-title">只读区 <span class="section-hint">LLM 可见，人工维护</span></header>
        <textarea
          class="ds-textarea ds-mono"
          v-model="readonlyDraft"
          rows="16"
          placeholder="高可信内容，如身份设定、规则、参考信息..."
        ></textarea>
      </section>
      <section class="note-section ds-panel ds-card-padding-sm">
        <header class="section-title">可编辑区 <span class="section-hint">Bot 追加观察</span></header>
        <textarea
          class="ds-textarea ds-mono"
          v-model="editableDraft"
          rows="16"
          placeholder="Bot 持续写入的观察和笔记..."
        ></textarea>
      </section>
    </div>

    <div class="save-row">
      <button
        class="ds-primary-button save-btn"
        type="button"
        :disabled="!isDirty"
        @click="emit('save', readonlyDraft, editableDraft)"
      >
        {{ isDirty ? "保存更改" : "已保存" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.pane-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.note-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}

.note-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.section-title {
  font-weight: 800;
  font-size: 13px;
  color: var(--heading-strong);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.section-hint {
  font-weight: 400;
  font-size: 11px;
  color: var(--muted);
}

.ds-textarea {
  min-height: 320px;
  resize: vertical;
}

.save-row {
  display: flex;
  justify-content: flex-end;
}

.save-btn {
  min-width: 96px;
  transition: opacity 150ms ease, background 150ms ease;
}

.save-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

@media (max-width: 900px) {
  .note-columns {
    grid-template-columns: 1fr;
  }

  .save-row {
    justify-content: stretch;
  }

  .save-btn {
    width: 100%;
  }
}
</style>
