<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue"

import { apiGet } from "../lib/api"

type LogItem = {
  seq: number
  timestamp: number
  level: string
  logger: string
  message: string
  kind?: string
  extra?: Record<string, unknown>
}

type LogPayload = {
  items: LogItem[]
  next_seq: number
  reset_required: boolean
}

const props = withDefaults(
  defineProps<{
    title?: string
    summary?: string
    limit?: number
    pollIntervalMs?: number
    height?: string
    dense?: boolean
    showControls?: boolean
    showDetails?: boolean
    showRunDetails?: boolean
  }>(),
  {
    title: "日志流",
    summary: "按等级和关键词过滤，自动增量刷新。",
    limit: 200,
    pollIntervalMs: 1000,
    height: "420px",
    dense: false,
    showControls: true,
    showDetails: false,
    showRunDetails: false,
  },
)

const emit = defineEmits<{
  viewRun: [runId: string]
}>()

const logs = ref<LogItem[]>([])
const level = ref("")
const keyword = ref("")
const autoRefresh = ref(true)
const autoFollow = ref(true)
const loading = ref(false)
const errorText = ref("")
const nextSeq = ref(0)
const resetHint = ref("")
const logList = ref<HTMLElement | null>(null)
const expandedSeqs = ref<number[]>([])

let pollTimer: ReturnType<typeof setTimeout> | null = null
let disposed = false
let requestInFlight = false

const panelClass = computed(() => ({
  "is-dense": props.dense,
}))

function levelClass(levelName: string): string {
  switch (String(levelName || "").toUpperCase()) {
    case "DEBUG":
      return "is-debug"
    case "INFO":
      return "is-info"
    case "WARNING":
      return "is-warning"
    case "ERROR":
      return "is-error"
    case "CRITICAL":
      return "is-critical"
    default:
      return ""
  }
}

function kindClass(kindName?: string): string {
  switch (String(kindName || "").toLowerCase()) {
    case "napcat_message":
      return "is-napcat-message"
    case "napcat_notice":
      return "is-napcat-notice"
    default:
      return ""
  }
}

function formatExtraValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "null"
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  if (typeof value === "string") {
    return value.length > 96 ? `${value.slice(0, 93)}...` : value
  }
  try {
    const json = JSON.stringify(value)
    return json.length > 96 ? `${json.slice(0, 93)}...` : json
  } catch {
    return String(value)
  }
}

function extraChipClass(key: string): string {
  switch (key) {
    case "run_id":
    case "thread_id":
    case "agent_id":
      return "is-context"
    case "tool_name":
      return "is-tool"
    case "duration_ms":
      return "is-timing"
    case "prompt_tokens":
    case "completion_tokens":
    case "total_tokens":
      return "is-token"
    case "error":
      return "is-error-field"
    default:
      return ""
  }
}

function keywordFromExtraValue(value: unknown, key: string): string {
  if (typeof value === "string") {
    return value.trim() || key
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value)
  }
  return key
}

function applyExtraFilter(key: string, value: unknown): void {
  const nextKeyword = keywordFromExtraValue(value, key)
  const previousKeyword = keyword.value
  keyword.value = nextKeyword
  if (previousKeyword === nextKeyword) {
    void applyFilters()
  }
}

function isExpanded(seq: number): boolean {
  return expandedSeqs.value.includes(seq)
}

function toggleExpanded(seq: number): void {
  expandedSeqs.value = isExpanded(seq)
    ? expandedSeqs.value.filter((value) => value !== seq)
    : [...expandedSeqs.value, seq]
}

function openRunDetails(runId: unknown): void {
  const normalized = String(runId || "").trim()
  if (!normalized) {
    return
  }
  emit("viewRun", normalized)
}

function buildPath(afterSeq = 0): string {
  const query = new URLSearchParams()
  if (level.value) {
    query.set("level", level.value)
  }
  if (keyword.value.trim()) {
    query.set("keyword", keyword.value.trim())
  }
  query.set("limit", String(props.limit))
  if (afterSeq > 0) {
    query.set("after_seq", String(afterSeq))
  }
  return `/api/system/logs?${query.toString()}`
}

function cancelPoll(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll(): void {
  cancelPoll()
  if (!autoRefresh.value || disposed) {
    return
  }
  pollTimer = setTimeout(async () => {
    await fetchDelta()
    schedulePoll()
  }, props.pollIntervalMs)
}

async function scrollToEnd(): Promise<void> {
  if (!autoFollow.value) {
    return
  }
  await nextTick()
  if (logList.value) {
    logList.value.scrollTop = logList.value.scrollHeight
  }
}

async function fetchSnapshot(): Promise<void> {
  if (requestInFlight) {
    return
  }
  requestInFlight = true
  loading.value = true
  errorText.value = ""
  resetHint.value = ""
  try {
    const payload = await apiGet<LogPayload>(buildPath())
    logs.value = payload.items ?? []
    nextSeq.value = payload.next_seq ?? 0
    if (payload.reset_required) {
      resetHint.value = "日志窗口已重置，当前显示的是最新可用片段。"
    }
    await scrollToEnd()
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "加载日志失败"
  } finally {
    loading.value = false
    requestInFlight = false
  }
}

async function fetchDelta(): Promise<void> {
  if (requestInFlight || !autoRefresh.value) {
    return
  }
  requestInFlight = true
  try {
    const payload = await apiGet<LogPayload>(buildPath(nextSeq.value))
    const items = payload.items ?? []
    if (payload.reset_required) {
      logs.value = items
      resetHint.value = "日志窗口已重置，当前显示的是最新可用片段。"
    } else if (items.length > 0) {
      logs.value = [...logs.value, ...items].slice(-props.limit)
      resetHint.value = ""
    }
    nextSeq.value = payload.next_seq ?? nextSeq.value
    if (items.length > 0 || payload.reset_required) {
      await scrollToEnd()
    }
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "刷新日志失败"
  } finally {
    requestInFlight = false
  }
}

async function applyFilters(): Promise<void> {
  cancelPoll()
  nextSeq.value = 0
  await fetchSnapshot()
  schedulePoll()
}

watch(autoRefresh, (enabled) => {
  if (enabled) {
    schedulePoll()
    return
  }
  cancelPoll()
})

watch([level, keyword], () => {
  void applyFilters()
})

onMounted(() => {
  void fetchSnapshot().then(() => {
    schedulePoll()
  })
})

onActivated(() => {
  schedulePoll()
})

onDeactivated(() => {
  cancelPoll()
})

onBeforeUnmount(() => {
  disposed = true
  cancelPoll()
})
</script>

<template>
  <section class="panel ds-panel ds-panel-padding panel-entrance" :class="panelClass">
    <div class="panel-header ds-section-head">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ summary }}</p>
      </div>
      <div v-if="showControls" class="filters">
        <select v-model="level">
          <option value="">全部等级</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
          <option value="CRITICAL">CRITICAL</option>
        </select>
        <input v-model="keyword" type="text" placeholder="关键词过滤" />
        <label class="toggle">
          <input v-model="autoRefresh" type="checkbox" />
          <span>自动刷新</span>
        </label>
        <label class="toggle">
          <input v-model="autoFollow" type="checkbox" />
          <span>自动跟随</span>
        </label>
        <button type="button" @click="void applyFilters()">立即刷新</button>
      </div>
    </div>

    <p v-if="resetHint" class="status warn">{{ resetHint }}</p>
    <p v-if="errorText" class="status error">{{ errorText }}</p>
    <div v-else-if="loading && logs.length === 0" class="empty">正在加载日志…</div>
    <div v-else-if="logs.length === 0" class="empty">暂无日志</div>
    <div v-else ref="logList" class="log-list" :style="{ height }">
      <article
        v-for="item in logs"
        :key="item.seq"
        class="log-line"
        :class="[levelClass(item.level), kindClass(item.kind)]"
      >
        <div class="log-meta-row">
          <div class="log-meta">
            <span class="seq-chip">#{{ item.seq }}</span>
            <span class="time-chip">{{ new Date(item.timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false }) }}</span>
            <span class="level-chip" :class="levelClass(item.level)">{{ item.level }}</span>
            <span v-if="item.kind && item.kind !== 'runtime'" class="kind-chip" :class="kindClass(item.kind)">{{ item.kind }}</span>
            <span class="logger-chip">{{ item.logger }}</span>
          </div>
          <div v-if="showDetails || showRunDetails" class="log-actions">
            <button v-if="showDetails" type="button" class="ds-inline-button" @click="toggleExpanded(item.seq)">
              {{ isExpanded(item.seq) ? "收起详情" : "展开详情" }}
            </button>
            <button
              v-if="showRunDetails && item.extra && item.extra.run_id"
              type="button"
              class="ds-inline-button"
              @click="openRunDetails(item.extra.run_id)"
            >
              查看 Run 详情
            </button>
          </div>
        </div>
        <pre class="log-message">{{ item.message }}</pre>
        <div v-if="item.extra && Object.keys(item.extra).length > 0" class="log-extra">
          <button
            v-for="(value, key) in item.extra"
            :key="String(key)"
            type="button"
            class="extra-chip"
            :class="extraChipClass(String(key))"
            :title="`${String(key)}=${formatExtraValue(value)}`"
            :aria-label="`按 ${String(key)} 过滤`"
            @click="applyExtraFilter(String(key), value)"
          >
            <span class="extra-key">{{ key }}</span>
            <span class="extra-value">{{ formatExtraValue(value) }}</span>
          </button>
        </div>
        <div v-if="showDetails && isExpanded(item.seq)" class="log-detail-block">
          <div class="detail-section">
            <p class="detail-title">完整 message</p>
            <pre class="detail-json">{{ item.message }}</pre>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow);
  padding: 16px 18px;
  min-width: 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.panel-header p {
  margin-top: 6px;
  color: var(--muted);
  font-size: 13px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  align-items: center;
}

select,
input,
button {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 8px 10px;
  font-size: 13px;
}

button {
  cursor: pointer;
}

.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 13px;
}

.status,
.empty {
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: 16px;
  background: var(--panel-strong);
  color: var(--muted);
  font-size: 13px;
}

.status.warn {
  color: var(--warning);
  background: rgba(154, 103, 0, 0.12);
}

.status.error {
  color: var(--danger);
  background: rgba(180, 35, 24, 0.14);
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
}

.log-line {
  border: 1px solid var(--line);
  border-radius: 14px;
  background: color-mix(in srgb, var(--panel-strong) 92%, transparent);
  padding: 8px 10px;
  border-left-width: 4px;
}

.log-meta-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.log-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.3;
  align-items: center;
}

.log-actions {
  display: inline-flex;
  gap: 6px;
  flex-wrap: wrap;
}

.log-message {
  margin: 4px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family:
    "SFMono-Regular",
    "Menlo",
    "Monaco",
    "Consolas",
    "Liberation Mono",
    monospace;
  font-size: 12px;
  line-height: 1.45;
  color: var(--log-message);
}

.log-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}

.log-detail-block {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.detail-section {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.02);
}

.detail-title {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.detail-json {
  margin: 8px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.45;
  font-family:
    "SFMono-Regular",
    "Menlo",
    "Monaco",
    "Consolas",
    "Liberation Mono",
    monospace;
}

.seq-chip,
.time-chip,
.level-chip,
.kind-chip,
.logger-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 8px;
  background: rgba(19, 41, 68, 0.12);
}

.seq-chip {
  font-weight: 700;
  color: var(--log-seq);
}

.time-chip {
  color: var(--log-time);
}

.logger-chip {
  color: var(--log-logger);
  max-width: 100%;
  overflow-wrap: anywhere;
}

.extra-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 2px 8px;
  background: rgba(19, 41, 68, 0.12);
  color: var(--muted);
  font: inherit;
  font-size: 11px;
  line-height: 1.35;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  transition:
    background 0.15s ease,
    transform 0.15s ease,
    border-color 0.15s ease;
}

.extra-chip:hover {
  background: rgba(19, 41, 68, 0.18);
  transform: translateY(-1px);
}

.extra-chip:focus-visible {
  outline: 2px solid rgba(59, 130, 246, 0.35);
  outline-offset: 2px;
}

.extra-key {
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}

.extra-key::after {
  content: "=";
  opacity: 0.45;
}

.extra-value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.level-chip {
  font-weight: 800;
  letter-spacing: 0.03em;
}

.kind-chip {
  font-weight: 700;
  color: var(--napcat-chip);
}

.log-line.is-debug {
  border-left-color: var(--log-debug-border);
  background: linear-gradient(90deg, var(--log-debug-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-info {
  border-left-color: var(--log-info-border);
  background: linear-gradient(90deg, var(--log-info-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-warning {
  border-left-color: var(--log-warn-border);
  background: linear-gradient(90deg, var(--log-warn-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-error {
  border-left-color: var(--log-error-border);
  background: linear-gradient(90deg, var(--log-error-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-critical {
  border-left-color: var(--log-critical-border);
  background: linear-gradient(90deg, var(--log-critical-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-napcat-message {
  box-shadow: inset 0 0 0 1px var(--log-napcat-msg-border);
  background: linear-gradient(90deg, var(--log-napcat-msg-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-napcat-notice {
  box-shadow: inset 0 0 0 1px var(--log-napcat-notice-border);
  background: linear-gradient(90deg, var(--log-napcat-notice-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.level-chip.is-debug {
  background: var(--log-debug-chip-bg);
  color: var(--log-debug-chip-text);
}

.level-chip.is-info {
  background: var(--log-info-chip-bg);
  color: var(--log-info-chip-text);
}

.level-chip.is-warning {
  background: var(--log-warn-chip-bg);
  color: var(--log-warn-chip-text);
}

.level-chip.is-error {
  background: var(--log-error-chip-bg);
  color: var(--log-error-chip-text);
}

.level-chip.is-critical {
  background: var(--log-critical-chip-bg);
  color: var(--log-critical-chip-text);
}

.kind-chip.is-napcat-message {
  background: var(--log-napcat-msg-chip-bg);
  color: var(--log-napcat-msg-chip-text);
}

.kind-chip.is-napcat-notice {
  background: var(--log-napcat-notice-chip-bg);
  color: var(--log-napcat-notice-chip-text);
}

.extra-chip.is-context {
  background: var(--chip-context-bg);
  color: var(--chip-context-text);
}

.extra-chip.is-context .extra-key {
  color: var(--chip-context-key);
}

.extra-chip.is-tool {
  background: var(--chip-tool-bg);
  color: var(--chip-tool-text);
}

.extra-chip.is-tool .extra-key {
  color: var(--chip-tool-key);
}

.extra-chip.is-timing {
  background: var(--chip-timing-bg);
  color: var(--chip-timing-text);
}

.extra-chip.is-timing .extra-key {
  color: var(--chip-timing-key);
}

.extra-chip.is-token {
  background: var(--chip-token-bg);
  color: var(--chip-token-text);
}

.extra-chip.is-token .extra-key {
  color: var(--chip-token-key);
}

.extra-chip.is-error-field {
  background: var(--chip-errfield-bg);
  color: var(--chip-errfield-text);
}

.extra-chip.is-error-field .extra-key {
  color: var(--chip-errfield-key);
}

.panel.is-dense {
  padding: 12px 14px;
}

.panel.is-dense .panel-header {
  margin-bottom: 10px;
}

.panel.is-dense .panel-header p {
  font-size: 12px;
}

.panel.is-dense .filters {
  gap: 6px;
}

.panel.is-dense select,
.panel.is-dense input,
.panel.is-dense button {
  padding: 7px 9px;
  font-size: 12px;
}

.panel.is-dense .status,
.panel.is-dense .empty {
  margin-bottom: 10px;
  padding: 10px 12px;
}

.panel.is-dense .log-list {
  gap: 4px;
}

.panel.is-dense .log-line {
  padding: 6px 8px;
  border-radius: 10px;
}

.panel.is-dense .log-meta {
  gap: 4px;
  font-size: 10px;
}

.panel.is-dense .seq-chip,
.panel.is-dense .time-chip,
.panel.is-dense .level-chip,
.panel.is-dense .kind-chip,
.panel.is-dense .logger-chip {
  padding: 1px 6px;
}

.panel.is-dense .log-message {
  margin-top: 3px;
  font-size: 11px;
  line-height: 1.35;
}

.panel.is-dense .log-extra {
  gap: 4px;
  margin-top: 4px;
}

.panel.is-dense .extra-chip {
  padding: 1px 7px;
  font-size: 10px;
}

@media (max-width: 900px) {
  .panel-header {
    flex-direction: column;
  }

  .filters {
    justify-content: stretch;
  }

  .filters input[type="text"],
  .filters select,
  .filters button {
    width: 100%;
    box-sizing: border-box;
  }

  .log-line {
    padding: 8px 9px;
  }

  .log-message {
    font-size: 11px;
  }

  .log-extra {
    gap: 4px;
  }

  .extra-chip {
    width: 100%;
    justify-content: space-between;
  }
}

/* ── Entrance animation ── */
.panel-entrance {
  animation: panel-entrance-in 360ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

@keyframes panel-entrance-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .panel-entrance {
    animation: none;
  }
}
</style>
