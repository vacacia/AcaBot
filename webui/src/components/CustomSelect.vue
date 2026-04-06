<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"

type SelectOption = {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  placeholder?: string
  readonly?: boolean
}>()

const emit = defineEmits<{
  "update:modelValue": [value: string]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const selectedLabel = computed(() => {
  const found = props.options.find((o) => o.value === props.modelValue)
  return found?.label || props.placeholder || "—"
})

function toggle() {
  if (props.readonly) return
  open.value = !open.value
}

function select(value: string) {
  emit("update:modelValue", value)
  open.value = false
}

function onClickOutside(e: MouseEvent) {
  if (root.value && !root.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener("click", onClickOutside, true))
onBeforeUnmount(() => document.removeEventListener("click", onClickOutside, true))
</script>

<template>
  <div ref="root" class="cs-root" :class="{ 'is-open': open, 'is-readonly': readonly }">
    <button
      class="cs-trigger"
      type="button"
      :disabled="readonly"
      :aria-expanded="open"
      :aria-haspopup="!readonly ? 'listbox' : undefined"
      :aria-disabled="readonly"
      :aria-readonly="readonly"
      @click="toggle"
    >
      <span class="cs-value" :class="{ 'is-placeholder': !modelValue }">{{ selectedLabel }}</span>
      <svg v-if="!readonly" class="cs-arrow" width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <Transition name="cs-drop">
      <div v-if="open" class="cs-dropdown" role="listbox">
        <button
          v-for="opt in options"
          :key="opt.value"
          class="cs-option"
          :class="{ 'is-selected': opt.value === modelValue }"
          role="option"
          :aria-selected="opt.value === modelValue"
          type="button"
          @click="select(opt.value)"
        >
          {{ opt.label }}
          <svg v-if="opt.value === modelValue" class="cs-check" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 7.5L5.5 10L11 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.cs-root {
  position: relative;
  width: 100%;
}

.cs-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  box-sizing: border-box;
  padding: 9px 12px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 120ms ease, box-shadow 120ms ease;
  text-align: left;
}

.cs-trigger:hover:not(.is-readonly .cs-trigger) {
  border-color: var(--panel-line-strong);
}

.cs-root.is-open .cs-trigger {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.is-readonly .cs-trigger {
  opacity: .6;
  cursor: not-allowed;
}

.cs-trigger:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.cs-value.is-placeholder {
  color: var(--muted);
}

.cs-arrow {
  flex-shrink: 0;
  color: var(--muted);
  transition: transform 160ms ease;
}

.cs-root.is-open .cs-arrow {
  transform: rotate(180deg);
}

.cs-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  padding: 4px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--panel);
  backdrop-filter: var(--blur-card);
  -webkit-backdrop-filter: var(--blur-card);
  box-shadow: 0 12px 40px rgba(0, 0, 0, .3);
  max-height: 240px;
  overflow-y: auto;
}

.cs-dropdown::-webkit-scrollbar { width: 4px; }
.cs-dropdown::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }

.cs-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
  transition: background 120ms ease, transform 80ms ease;
}

.cs-option:hover {
  background: var(--accent-soft);
  transform: translateX(2px);
}

.cs-option:active {
  transform: translateX(1px) scale(0.98);
}

.cs-option.is-selected {
  color: var(--accent);
  font-weight: 600;
}

.cs-check {
  flex-shrink: 0;
  color: var(--accent);
}

/* 动画 */
.cs-drop-enter-active { transition: opacity 120ms ease, transform 120ms ease; }
.cs-drop-leave-active { transition: opacity 80ms ease, transform 80ms ease; }
.cs-drop-enter-from,
.cs-drop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
