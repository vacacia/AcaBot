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

type PrimaryField = {
  key: string
  label: string
  value: string
  tone?: string
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

function normalizeKind(kindName?: string, item?: LogItem): string {
  const explicit = String(kindName || "").trim().toLowerCase()
  if (explicit) {
    return explicit
  }
  if (String(item?.level || "").toUpperCase() === "ERROR") {
    return "error"
  }
  return "runtime"
}

function kindClass(kindName?: string, item?: LogItem): string {
  switch (normalizeKind(kindName, item)) {
    case "message":
    case "napcat_message":
      return "is-message"
    case "napcat_notice":
      return "is-notice"
    case "tool_call":
      return "is-tool-call"
    case "tool_result":
      return "is-tool-result"
    case "token_usage":
      return "is-token-usage"
    case "outbound":
      return "is-outbound"
    case "runtime_perf":
      return "is-runtime-perf"
    case "error":
      return "is-error-kind"
    default:
      return ""
  }
}

function kindTag(kindName?: string, item?: LogItem): string {
  switch (normalizeKind(kindName, item)) {
    case "message":
    case "napcat_message":
      return "MESSAGE"
    case "napcat_notice":
      return "NOTICE"
    case "tool_call":
      return "TOOL CALL"
    case "tool_result":
      return "TOOL RESULT"
    case "token_usage":
      return "TOKEN"
    case "outbound":
      return "OUTBOUND"
    case "runtime_perf":
      return "PERF"
    case "error":
      return "ERROR"
    default:
      return "RUNTIME"
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
    case "cache_read_input_tokens":
    case "cache_creation_input_tokens":
    case "cached_prompt_tokens":
    case "prompt_cache_hit_tokens":
      return "is-token"
    case "error":
      return "is-error-field"
    case "preview":
    case "content_preview":
      return "is-preview"
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

function formatClock(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false })
}

function formatPreciseTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function normalizeSummaryText(item: LogItem): string {
  const raw = String(item.message || "").trim()
  return raw.replace(/^\[[A-Z_ ]+\]\s*/u, "").trim() || raw
}

function joinNameId(name: unknown, id: unknown): string {
  const text = String(name || "").trim()
  const normalizedId = String(id || "").trim()
  if (text && normalizedId) {
    return `${text} (${normalizedId})`
  }
  return text || normalizedId || "-"
}

function field(label: string, value: unknown, key: string, tone = ""): PrimaryField | null {
  const normalized = String(value ?? "").trim()
  if (!normalized) {
    return null
  }
  return { key, label, value: normalized, tone }
}

function summarizeToolArguments(value: unknown): string {
  if (value == null) {
    return "-"
  }
  try {
    const json = JSON.stringify(value, null, 0)
    return json.length > 120 ? `${json.slice(0, 117)}...` : json
  } catch {
    return formatExtraValue(value)
  }
}

function summaryText(item: LogItem): string {
  const kind = normalizeKind(item.kind, item)
  const extra = item.extra ?? {}
  if (kind === "tool_call") {
    return String(extra.tool_name || normalizeSummaryText(item) || "Tool call")
  }
  if (kind === "tool_result") {
    return String(extra.result_summary || extra.tool_name || normalizeSummaryText(item) || "Tool result")
  }
  if (kind === "token_usage") {
    return `模型 ${String(extra.model || "-")}`
  }
  if (kind === "outbound") {
    return String(extra.preview || normalizeSummaryText(item))
  }
  return normalizeSummaryText(item)
}

function primaryFields(item: LogItem): PrimaryField[] {
  const kind = normalizeKind(item.kind, item)
  const extra = item.extra ?? {}
  const fields: Array<PrimaryField | null> = []

  if (kind === "message" || kind === "napcat_message") {
    fields.push(field("会话", String(extra.conversation_label || joinNameId(extra.group_name, extra.group_id)), "conversation", "is-strong"))
    fields.push(field("发送者", joinNameId(extra.sender_name, extra.sender_id), "sender", "is-strong"))
    fields.push(field("消息", extra.content_preview, "content"))
    fields.push(field("策略", extra.run_mode, "run_mode", "is-emphasis"))
    fields.push(field("Prompt", extra.prompt_ref, "prompt_ref"))
    fields.push(field("模型", extra.model, "model"))
  } else if (kind === "tool_call") {
    fields.push(field("工具", extra.tool_name, "tool_name", "is-strong"))
    fields.push(field("参数", summarizeToolArguments(extra.tool_arguments), "tool_arguments"))
  } else if (kind === "tool_result") {
    fields.push(field("工具", extra.tool_name, "tool_name", "is-strong"))
    fields.push(field("结果", extra.result_summary || extra.error, "result_summary"))
    fields.push(field("耗时", extra.duration_ms != null ? `${extra.duration_ms} ms` : "", "duration_ms"))
  } else if (kind === "token_usage") {
    fields.push(field("模型", extra.model, "model", "is-strong"))
    fields.push(field("Prompt", extra.prompt_tokens, "prompt_tokens", "is-token"))
    fields.push(field("Completion", extra.completion_tokens, "completion_tokens", "is-token"))
    fields.push(field("Total", extra.total_tokens, "total_tokens", "is-token"))
    fields.push(field("Cache", [extra.cache_read_input_tokens, extra.cached_prompt_tokens, extra.prompt_cache_hit_tokens].filter(Boolean).join(" / "), "cache_tokens"))
    fields.push(field("Prompt Ref", extra.prompt_ref, "prompt_ref"))
  } else if (kind === "outbound") {
    fields.push(field("目标", extra.target, "target", "is-strong"))
    fields.push(field("动作", extra.action, "action"))
    fields.push(field("文本", extra.preview, "preview"))
  } else if (kind === "runtime_perf") {
    fields.push(field("操作", extra.operation, "operation", "is-strong"))
    fields.push(field("耗时", extra.duration_ms != null ? `${extra.duration_ms} ms` : "", "duration_ms", "is-emphasis"))
  } else if (kind === "error") {
    fields.push(field("错误", extra.error || item.message, "error", "is-emphasis"))
  }

  return fields.filter((item): item is PrimaryField => item !== null)
}

async function fetchSnapshot(): Promise<void> {
  if (requestInFlight || disposed) {
    return
  }
  requestInFlight = true
  loading.value = true
  errorText.value = ""
  resetHint.value = ""
  try {
    const payload = await apiGet<LogPayload>(buildPath())
    if (disposed) return
    logs.value = payload.items ?? []
    nextSeq.value = payload.next_seq ?? 0
    if (payload.reset_required) {
      resetHint.value = "日志窗口已重置，当前显示的是最新可用片段。"
    }
    await scrollToEnd()
  } catch (error) {
    if (disposed) return
    errorText.value = error instanceof Error ? error.message : "加载日志失败"
  } finally {
    loading.value = false
    requestInFlight = false
  }
}

async function fetchDelta(): Promise<void> {
  if (requestInFlight || !autoRefresh.value || disposed) {
    return
  }
  requestInFlight = true
  try {
    const payload = await apiGet<LogPayload>(buildPath(nextSeq.value))
    if (disposed) return
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
    if (disposed) return
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
        :class="[levelClass(item.level), kindClass(item.kind, item)]"
      >
        <div class="log-header-row">
          <div class="log-chips">
            <span class="time-chip-inline" :title="formatPreciseTime(item.timestamp)">{{ formatClock(item.timestamp) }}</span>
            <span class="level-chip" :class="levelClass(item.level)">{{ item.level }}</span>
            <span class="summary-tag" :class="kindClass(item.kind, item)">{{ kindTag(item.kind, item) }}</span>
          </div>
          <div v-if="showDetails || showRunDetails || (item.extra && Object.keys(item.extra).length > 0)" class="log-actions">
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

        <div class="log-summary">{{ summaryText(item) }}</div>

        <div v-if="primaryFields(item).length" class="primary-fields">
          <div
            v-for="entry in primaryFields(item)"
            :key="entry.key"
            class="primary-field"
            :class="entry.tone"
          >
            <span class="primary-label">{{ entry.label }}</span>
            <span class="primary-value">{{ entry.value }}</span>
          </div>
        </div>

        <div v-if="isExpanded(item.seq)" class="log-expanded">
          <div class="expanded-meta">
            <span class="seq-chip">#{{ item.seq }}</span>
            <span class="time-chip">{{ formatPreciseTime(item.timestamp) }}</span>
            <span class="logger-chip">{{ item.logger }}</span>
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
  transition:
    transform 180ms cubic-bezier(0.25, 1, 0.5, 1),
    background-color 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

button {
  cursor: pointer;
}

button:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--accent);
  box-shadow: 0 4px 12px var(--button-shadow-color);
}

button:active {
  transform: translateY(0) scale(0.98);
  box-shadow: none;
  transition-duration: 80ms;
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
  gap: 8px;
  overflow: auto;
}

.log-line {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: color-mix(in srgb, var(--panel-strong) 92%, transparent);
  padding: 12px 14px;
  border-left-width: 4px;
  transition: background 150ms ease;
}

.log-line:hover {
  background: color-mix(in srgb, var(--panel-strong) 85%, transparent);
}

.log-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.log-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.time-chip-inline,
.seq-chip,
.time-chip,
.level-chip,
.summary-tag,
.logger-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 8px;
  background: rgba(19, 41, 68, 0.12);
  font-size: 10px;
}

.time-chip-inline,
.time-chip {
  color: var(--log-time);
}

.level-chip {
  font-weight: 700;
  letter-spacing: 0.02em;
}

.summary-tag {
  font-weight: 800;
  letter-spacing: 0.04em;
}

.log-actions {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.log-summary {
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.primary-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.primary-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 6px 10px;
  border-radius: 12px;
  background: rgba(19, 41, 68, 0.08);
  border: 1px solid rgba(19, 41, 68, 0.08);
}

.primary-field.is-strong {
  background: color-mix(in srgb, var(--accent-soft) 44%, transparent);
  border-color: color-mix(in srgb, var(--accent) 18%, transparent);
}

.primary-field.is-emphasis {
  background: rgba(154, 103, 0, 0.12);
  border-color: rgba(154, 103, 0, 0.22);
}

.primary-field.is-token {
  background: color-mix(in srgb, #0f766e 16%, transparent);
  border-color: color-mix(in srgb, #0f766e 26%, transparent);
}

.primary-label {
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.primary-value {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.log-expanded {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.expanded-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--muted);
  font-size: 10px;
  align-items: center;
}

.log-message {
  margin: 0;
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
  line-height: 1.5;
  color: var(--log-message);
}

.log-extra {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
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
    background 150ms ease,
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1),
    border-color 150ms ease,
    box-shadow 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.extra-chip:hover {
  background: rgba(19, 41, 68, 0.18);
  transform: translateY(-2px) scale(1.04);
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.15);
}

.extra-chip:active {
  transform: translateY(0) scale(0.96);
  transition-duration: 60ms;
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

.log-line.is-debug {
  border-left-color: var(--log-debug-border);
}

.log-line.is-info {
  border-left-color: var(--log-info-border);
}

.log-line.is-warning {
  border-left-color: var(--log-warn-border);
}

.log-line.is-error,
.log-line.is-error-kind {
  border-left-color: var(--log-error-border);
  background: linear-gradient(90deg, var(--log-error-bg), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-critical {
  border-left-color: var(--log-critical-border);
}

.log-line.is-message {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 26%, transparent);
  background: linear-gradient(90deg, color-mix(in srgb, var(--accent-soft) 42%, transparent), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-notice {
  box-shadow: inset 0 0 0 1px var(--log-napcat-notice-border);
}

.log-line.is-tool-call {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #2563eb 26%, transparent);
  background: linear-gradient(90deg, rgba(37, 99, 235, 0.10), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-tool-result {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #7c3aed 24%, transparent);
  background: linear-gradient(90deg, rgba(124, 58, 237, 0.10), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-token-usage {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #0f766e 26%, transparent);
  background: linear-gradient(90deg, rgba(15, 118, 110, 0.10), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-outbound {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #d97706 24%, transparent);
  background: linear-gradient(90deg, rgba(217, 119, 6, 0.10), color-mix(in srgb, var(--panel-strong) 94%, transparent));
}

.log-line.is-runtime-perf {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, #64748b 22%, transparent);
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

.summary-tag.is-message {
  background: color-mix(in srgb, var(--accent-soft) 66%, transparent);
  color: var(--accent);
}

.summary-tag.is-notice {
  background: var(--log-napcat-notice-chip-bg);
  color: var(--log-napcat-notice-chip-text);
}

.summary-tag.is-tool-call {
  background: rgba(37, 99, 235, 0.16);
  color: #1d4ed8;
}

.summary-tag.is-tool-result {
  background: rgba(124, 58, 237, 0.16);
  color: #6d28d9;
}

.summary-tag.is-token-usage {
  background: rgba(15, 118, 110, 0.16);
  color: #0f766e;
}

.summary-tag.is-outbound {
  background: rgba(217, 119, 6, 0.16);
  color: #b45309;
}

.summary-tag.is-runtime-perf {
  background: rgba(100, 116, 139, 0.16);
  color: #475569;
}

.summary-tag.is-error-kind {
  background: rgba(180, 35, 24, 0.14);
  color: var(--danger);
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

.panel.is-dense .log-line {
  padding: 10px 12px;
}

.panel.is-dense .log-summary {
  font-size: 13px;
}

.panel.is-dense .primary-field {
  padding: 5px 8px;
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
    padding: 10px;
  }

  .log-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .primary-field,
  .extra-chip {
    width: 100%;
    justify-content: space-between;
  }
}

.panel-entrance {
  animation: panel-entrance-in 360ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

@keyframes panel-entrance-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .panel-entrance {
    animation: none;
  }
}
</style>
