<script setup lang="ts">
import { computed, ref, watch } from "vue"

type ParamHint = {
  type: "slider" | "number" | "select" | "checkbox" | "text"
  label: string
  hint?: string
  min?: number
  max?: number
  step?: number
  options?: string[]
}

/**
 * 最小化的 fallback 定义 — 仅当后端没有返回 param_hints 时使用。
 * 真正的参数元数据（选项列表、范围、档位等）由后端根据 litellm + 模型信息动态生成。
 */
const FALLBACK_DEFS: Record<string, ParamHint> = {
  temperature:       { type: "slider", min: 0, max: 2, step: 0.05, label: "Temperature" },
  top_p:             { type: "slider", min: 0, max: 1, step: 0.05, label: "Top P" },
  max_tokens:        { type: "number", min: 1, label: "Max Tokens" },
  reasoning_effort:  { type: "select", options: ["low", "medium", "high"], label: "思考强度" },
  thinking:          { type: "checkbox", label: "深度思考" },
  frequency_penalty: { type: "slider", min: -2, max: 2, step: 0.05, label: "Frequency Penalty" },
  presence_penalty:  { type: "slider", min: -2, max: 2, step: 0.05, label: "Presence Penalty" },
  seed:              { type: "number", label: "Seed" },
  stop:              { type: "text", label: "Stop Sequences" },
}

const props = defineProps<{
  supportedParams: string[]
  modelValue: Record<string, unknown>
  /** 后端返回的 param_hints — 控件类型、范围、选项全由后端决定 */
  paramHints?: Record<string, ParamHint>
}>()

const emit = defineEmits<{
  "update:modelValue": [value: Record<string, unknown>]
}>()

const rawOpen = ref(false)
const rawJson = ref("")
const rawError = ref("")
const pulsingKey = ref("")

/**
 * 参数定义解析：如果后端提供了 paramHints，只用后端的（后端已经做了模型级过滤）。
 * 只有后端没给 paramHints 时才 fallback 到本地定义。
 */
function resolveHint(key: string): ParamHint | undefined {
  if (props.paramHints && Object.keys(props.paramHints).length > 0) {
    return props.paramHints[key]
  }
  return FALLBACK_DEFS[key]
}

const knownParams = computed(() =>
  props.supportedParams.filter((p) => resolveHint(p) != null)
)

function getVal(key: string): unknown {
  if (key in props.modelValue) return props.modelValue[key]
  return undefined
}

function update(key: string, value: unknown) {
  emit("update:modelValue", { ...props.modelValue, [key]: value })
}

function onSlider(key: string, e: Event) {
  const v = parseFloat((e.target as HTMLInputElement).value)
  update(key, v)
  pulsingKey.value = key
  setTimeout(() => { pulsingKey.value = "" }, 200)
}

function onNumber(key: string, e: Event) {
  const raw = (e.target as HTMLInputElement).value
  if (raw === "") {
    const next = { ...props.modelValue }
    delete next[key]
    emit("update:modelValue", next)
    return
  }
  const v = parseFloat(raw)
  if (!isNaN(v)) update(key, v)
}

function onText(key: string, e: Event) {
  update(key, (e.target as HTMLInputElement).value)
}

function onCheck(key: string, e: Event) {
  update(key, (e.target as HTMLInputElement).checked)
}

function onSelect(key: string, e: Event) {
  update(key, (e.target as HTMLSelectElement).value)
}

function formatSliderVal(key: string): string {
  const v = getVal(key)
  const hint = resolveHint(key)
  if (v == null) {
    return "—"
  }
  const step = hint?.step ?? 0.05
  const decimals = step < 1 ? Math.max(1, String(step).split(".")[1]?.length ?? 1) : 0
  return Number(v).toFixed(decimals)
}

function toggleRaw() {
  if (!rawOpen.value) {
    rawJson.value = JSON.stringify(props.modelValue, null, 2)
    rawError.value = ""
  }
  rawOpen.value = !rawOpen.value
}

function applyRaw() {
  try {
    const parsed = JSON.parse(rawJson.value)
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      rawError.value = "必须是一个 JSON 对象"
      return
    }
    rawError.value = ""
    emit("update:modelValue", parsed)
  } catch {
    rawError.value = "JSON 格式错误"
  }
}

// Sync raw textarea when modelValue changes externally while open
watch(() => props.modelValue, (v) => {
  if (rawOpen.value) {
    rawJson.value = JSON.stringify(v, null, 2)
  }
}, { deep: true })
</script>

<template>
  <div class="mpe-root">
    <div class="mpe-badge">{{ knownParams.length }} 个可调参数</div>

    <div v-if="knownParams.length === 0" class="mpe-empty">
      当前模型没有已知的可调参数
    </div>

    <div v-for="key in knownParams" :key="key" class="mpe-row">
      <div class="mpe-label-col">
        <span class="mpe-label">{{ resolveHint(key)!.label }}</span>
        <span v-if="resolveHint(key)!.hint" class="mpe-hint">{{ resolveHint(key)!.hint }}</span>
      </div>

      <div class="mpe-control-col">
        <!-- Slider -->
        <template v-if="resolveHint(key)!.type === 'slider'">
          <div class="mpe-slider-wrap">
            <input
              type="range"
              class="mpe-slider"
              :min="resolveHint(key)!.min"
              :max="resolveHint(key)!.max"
              :step="resolveHint(key)!.step"
              :value="getVal(key) ?? resolveHint(key)!.min"
              @input="onSlider(key, $event)"
            />
            <span class="mpe-slider-val" :class="{ 'mpe-val-pulse': pulsingKey === key }">{{ formatSliderVal(key) }}</span>
          </div>
        </template>

        <!-- Number -->
        <template v-else-if="resolveHint(key)!.type === 'number'">
          <input
            type="number"
            class="mpe-input"
            :min="resolveHint(key)!.min"
            :max="resolveHint(key)!.max"
            :value="getVal(key) ?? ''"
            placeholder="—"
            @change="onNumber(key, $event)"
          />
        </template>

        <!-- Select -->
        <template v-else-if="resolveHint(key)!.type === 'select'">
          <div class="mpe-select-wrap">
            <select
              class="mpe-select"
              :value="getVal(key) ?? ''"
              @change="onSelect(key, $event)"
            >
              <option value="" disabled>选择...</option>
              <option v-for="opt in resolveHint(key)!.options" :key="opt" :value="opt">{{ opt }}</option>
            </select>
            <svg class="mpe-select-arrow" width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
        </template>

        <!-- Checkbox -->
        <template v-else-if="resolveHint(key)!.type === 'checkbox'">
          <label class="mpe-toggle">
            <input
              type="checkbox"
              :checked="!!getVal(key)"
              @change="onCheck(key, $event)"
            />
            <span class="mpe-toggle-track"><span class="mpe-toggle-thumb" /></span>
          </label>
        </template>

        <!-- Text -->
        <template v-else-if="resolveHint(key)!.type === 'text'">
          <input
            type="text"
            class="mpe-input"
            :value="getVal(key) ?? ''"
            placeholder="—"
            @change="onText(key, $event)"
          />
        </template>
      </div>
    </div>

    <!-- Raw JSON fallback -->
    <div class="mpe-raw-section">
      <button class="mpe-raw-toggle" type="button" @click="toggleRaw">
        <svg class="mpe-raw-icon" :class="{ 'is-open': rawOpen }" width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M4.5 3L7.5 6L4.5 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        Raw JSON
      </button>
      <Transition name="mpe-slide">
        <div v-if="rawOpen" class="mpe-raw-body">
          <textarea
            v-model="rawJson"
            class="mpe-raw-textarea"
            rows="8"
            spellcheck="false"
          />
          <div class="mpe-raw-footer">
            <span v-if="rawError" class="mpe-raw-error">{{ rawError }}</span>
            <button class="mpe-raw-apply" type="button" @click="applyRaw">应用</button>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.mpe-root {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mpe-badge {
  font-size: 12px;
  color: var(--muted);
  padding: 0 0 8px;
}

.mpe-empty {
  font-size: 13px;
  color: var(--muted);
  padding: 12px 0;
}

/* ── Row ── */
.mpe-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--panel-line-soft);
}

.mpe-row:last-of-type {
  border-bottom: none;
}

.mpe-label-col {
  flex: 0 0 180px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.mpe-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--heading);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mpe-hint {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mpe-control-col {
  flex: 1;
  min-width: 0;
}

/* ── Slider ── */
.mpe-slider-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mpe-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  border-radius: 2px;
  background: var(--panel-line-soft);
  outline: none;
  cursor: pointer;
}

.mpe-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--panel-strong);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  transition: transform 100ms ease;
}

.mpe-slider::-webkit-slider-thumb:hover {
  transform: scale(1.15);
}

.mpe-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--accent);
  border: 2px solid var(--panel-strong);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  cursor: pointer;
}

.mpe-slider-val {
  flex: 0 0 44px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  transition: color 100ms ease, transform 100ms ease;
}

.mpe-val-pulse {
  animation: val-pulse 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

@keyframes val-pulse {
  0%   { transform: scale(1); color: var(--text); }
  50%  { transform: scale(1.15); color: var(--accent); }
  100% { transform: scale(1); color: var(--text); }
}

/* ── Number / Text inputs ── */
.mpe-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.mpe-input::placeholder {
  color: var(--muted);
}

.mpe-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

/* Hide number input spinners */
.mpe-input[type="number"]::-webkit-inner-spin-button,
.mpe-input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.mpe-input[type="number"] {
  -moz-appearance: textfield;
}

/* ── Select ── */
.mpe-select-wrap {
  position: relative;
}

.mpe-select {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 32px 8px 12px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  outline: none;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.mpe-select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.mpe-select-arrow {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  pointer-events: none;
}

/* ── Toggle (checkbox) ── */
.mpe-toggle {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.mpe-toggle input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.mpe-toggle-track {
  position: relative;
  width: 38px;
  height: 22px;
  border-radius: 11px;
  background: var(--panel-line-soft);
  transition: background 160ms ease;
}

.mpe-toggle input:checked + .mpe-toggle-track {
  background: var(--accent);
}

.mpe-toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transition: transform 160ms ease;
}

.mpe-toggle input:checked + .mpe-toggle-track .mpe-toggle-thumb {
  transform: translateX(16px);
}

.mpe-toggle input:focus-visible + .mpe-toggle-track {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* ── Raw JSON ── */
.mpe-raw-section {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--panel-line-soft);
}

.mpe-raw-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: color 120ms ease;
}

.mpe-raw-toggle:hover {
  color: var(--text);
}

.mpe-raw-icon {
  transition: transform 160ms ease;
}

.mpe-raw-icon.is-open {
  transform: rotate(90deg);
}

.mpe-raw-body {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mpe-raw-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid var(--panel-line-soft);
  border-radius: 10px;
  background: var(--panel-strong);
  color: var(--text);
  font-size: 12px;
  font-family: "SF Mono", "Fira Code", "Consolas", monospace;
  line-height: 1.5;
  resize: vertical;
  outline: none;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.mpe-raw-textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}

.mpe-raw-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.mpe-raw-error {
  font-size: 12px;
  color: #e55;
}

.mpe-raw-apply {
  padding: 6px 16px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: opacity 120ms ease;
}

.mpe-raw-apply:hover {
  opacity: 0.85;
}

/* ── Transition ── */
.mpe-slide-enter-active { transition: opacity 120ms ease, max-height 200ms ease; overflow: hidden; }
.mpe-slide-leave-active { transition: opacity 80ms ease, max-height 150ms ease; overflow: hidden; }
.mpe-slide-enter-from,
.mpe-slide-leave-to {
  opacity: 0;
}
</style>
