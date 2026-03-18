<script setup lang="ts">
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue"

import { apiGet } from "../lib/api"

type LogItem = {
  seq: number
  timestamp: number
  level: string
  logger: string
  message: string
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
  }>(),
  {
    title: "日志流",
    summary: "按等级和关键词过滤，自动增量刷新。",
    limit: 200,
    pollIntervalMs: 1000,
    height: "420px",
    dense: false,
    showControls: true,
  },
)

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

onBeforeUnmount(() => {
  disposed = true
  cancelPoll()
})
</script>

<template>
  <section class="panel" :class="panelClass">
    <div class="panel-header">
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
      <article v-for="item in logs" :key="item.seq" class="log-line" :class="levelClass(item.level)">
        <div class="log-meta">
          <span class="seq-chip">#{{ item.seq }}</span>
          <span class="time-chip">{{ new Date(item.timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false }) }}</span>
          <span class="level-chip" :class="levelClass(item.level)">{{ item.level }}</span>
          <span class="logger-chip">{{ item.logger }}</span>
        </div>
        <pre class="log-message">{{ item.message }}</pre>
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
  background: rgba(255, 255, 255, 0.68);
  color: var(--muted);
  font-size: 13px;
}

.status.warn {
  color: #9a6700;
  background: rgba(154, 103, 0, 0.08);
}

.status.error {
  color: #b42318;
  background: rgba(180, 35, 24, 0.08);
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
  background: rgba(255, 255, 255, 0.82);
  padding: 8px 10px;
  border-left-width: 4px;
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
  color: #19304d;
}

.seq-chip,
.time-chip,
.level-chip,
.logger-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 8px;
  background: rgba(19, 41, 68, 0.06);
}

.seq-chip {
  font-weight: 700;
  color: #35506f;
}

.time-chip {
  color: #52667f;
}

.logger-chip {
  color: #40556f;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.level-chip {
  font-weight: 800;
  letter-spacing: 0.03em;
}

.log-line.is-debug {
  border-left-color: #7c8ba1;
  background: linear-gradient(90deg, rgba(124, 139, 161, 0.08), rgba(255, 255, 255, 0.82));
}

.log-line.is-info {
  border-left-color: #0f6cb8;
  background: linear-gradient(90deg, rgba(15, 108, 184, 0.08), rgba(255, 255, 255, 0.82));
}

.log-line.is-warning {
  border-left-color: #d97706;
  background: linear-gradient(90deg, rgba(217, 119, 6, 0.1), rgba(255, 255, 255, 0.84));
}

.log-line.is-error {
  border-left-color: #dc2626;
  background: linear-gradient(90deg, rgba(220, 38, 38, 0.1), rgba(255, 255, 255, 0.84));
}

.log-line.is-critical {
  border-left-color: #7c3aed;
  background: linear-gradient(90deg, rgba(124, 58, 237, 0.12), rgba(255, 255, 255, 0.86));
}

.level-chip.is-debug {
  background: rgba(124, 139, 161, 0.16);
  color: #5a697d;
}

.level-chip.is-info {
  background: rgba(15, 108, 184, 0.14);
  color: #0b5d9d;
}

.level-chip.is-warning {
  background: rgba(217, 119, 6, 0.16);
  color: #9a5a05;
}

.level-chip.is-error {
  background: rgba(220, 38, 38, 0.15);
  color: #b42318;
}

.level-chip.is-critical {
  background: rgba(124, 58, 237, 0.16);
  color: #6d28d9;
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
.panel.is-dense .logger-chip {
  padding: 1px 6px;
}

.panel.is-dense .log-message {
  margin-top: 3px;
  font-size: 11px;
  line-height: 1.35;
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
}
</style>
