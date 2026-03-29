<script setup lang="ts">
import { ref } from "vue"

type Props = {
  modelValue: string[]
  label: string
  helper?: string
  placeholder?: string
  addLabel?: string
  emptyTitle?: string
  emptyDescription?: string
  disabled?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  helper: "",
  placeholder: "添加新项，按回车确认添加",
  addLabel: "添加",
  emptyTitle: "还没有配置任何条目",
  emptyDescription: "先添加一项，保存后会用这一份列表作为当前正式配置。",
  disabled: false,
})

const emit = defineEmits<{
  "update:modelValue": [value: string[]]
}>()

const inputValue = ref("")
const localError = ref("")

function addItem(): void {
  if (props.disabled) {
    return
  }
  const normalized = inputValue.value.trim()
  if (!normalized) {
    localError.value = "先输入一项再添加。"
    return
  }
  if (props.modelValue.includes(normalized)) {
    localError.value = "这一项已经存在，不需要重复添加。"
    return
  }
  emit("update:modelValue", [...props.modelValue, normalized])
  inputValue.value = ""
  localError.value = ""
}

function removeItem(target: string): void {
  if (props.disabled) {
    return
  }
  emit(
    "update:modelValue",
    props.modelValue.filter((item) => item !== target),
  )
  localError.value = ""
}
</script>

<template>
  <div class="editable-list-field">
    <label class="ds-field">
      <span>{{ label }}</span>
      <p v-if="helper" class="ds-helper">{{ helper }}</p>
      <div class="ds-toolbar editable-list-toolbar">
        <input
          v-model="inputValue"
          class="ds-input ds-mono"
          type="text"
          :placeholder="placeholder"
          :disabled="disabled"
          @keydown.enter.prevent="addItem"
        />
        <button class="ds-primary-button" type="button" :disabled="disabled" @click="addItem">
          {{ addLabel }}
        </button>
      </div>
    </label>

    <p v-if="localError" class="ds-status is-error">{{ localError }}</p>

    <div v-if="modelValue.length === 0" class="ds-empty editable-list-empty">
      <strong>{{ emptyTitle }}</strong>
      <p class="ds-summary">{{ emptyDescription }}</p>
    </div>

    <ul v-else class="ds-list editable-list-items">
      <li v-for="item in modelValue" :key="item" class="ds-list-item ds-list-item-padding editable-list-item">
        <div class="editable-list-copy">
          <span class="ds-chip">已添加</span>
          <code class="ds-mono editable-list-value">{{ item }}</code>
        </div>
        <button class="ds-inline-button" type="button" :disabled="disabled" @click="removeItem(item)">移除</button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.editable-list-field {
  display: grid;
  gap: 12px;
}

.editable-list-toolbar {
  align-items: stretch;
}

.editable-list-toolbar .ds-input {
  flex: 1 1 280px;
}

.editable-list-empty strong {
  display: block;
  margin-bottom: 8px;
  color: var(--heading-soft);
}

.editable-list-items {
  margin: 0;
  padding: 0;
  list-style: none;
}

.editable-list-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.editable-list-copy {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.editable-list-value {
  color: var(--text);
  font-size: 13px;
  overflow-wrap: anywhere;
}

@media (max-width: 860px) {
  .editable-list-item {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
