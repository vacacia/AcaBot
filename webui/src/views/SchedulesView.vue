<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import {
  apiGet,
  createSchedule,
  deleteSchedule,
  disableSchedule,
  enableSchedule,
  getSchedulesList,
  type ScheduleKind,
  type ScheduleSpec,
  type ScheduleTask,
} from "../lib/api"

type SessionSummary = {
  session_id: string
  title: string
  template_id: string
}

type ConversationIdMode = "select" | "manual"

const POLL_INTERVAL_MS = 1500
const SCHEDULE_KIND_OPTIONS: Array<{ value: ScheduleKind; label: string }> = [
  { value: "interval", label: "间隔" },
  { value: "one_shot", label: "一次性" },
  { value: "cron", label: "Cron" },
]

// region 页面状态
const tasks = ref<ScheduleTask[]>([])
const sessions = ref<SessionSummary[]>([])
const loading = ref(true)
const actionMessage = ref("")
const errorMessage = ref("")
const showCreateModal = ref(false)
const busyTaskId = ref("")
const refreshTimer = ref<number | null>(null)

// region 新建表单
const createError = ref("")
const creating = ref(false)
const conversationIdMode = ref<ConversationIdMode>("select")
const sessionSearch = ref("")
const selectedSessionId = ref("")
const manualConversationId = ref("")
const scheduleKind = ref<ScheduleKind>("interval")
const intervalSeconds = ref(3600)
const cronExpr = ref("0 9 * * *")
const oneShotTimestamp = ref("")
const note = ref("")

const filteredSessions = computed(() => {
  const keyword = sessionSearch.value.trim().toLowerCase()
  if (!keyword) {
    return sessions.value
  }
  return sessions.value.filter((item) => {
    const title = String(item.title || "").toLowerCase()
    const sessionId = String(item.session_id || "").toLowerCase()
    return title.includes(keyword) || sessionId.includes(keyword)
  })
})

const effectiveConversationId = computed(() => {
  if (conversationIdMode.value === "manual") {
    return manualConversationId.value.trim()
  }
  return selectedSessionId.value.trim()
})

const scheduleSummary = computed(() => {
  if (scheduleKind.value === "interval") {
    return `每 ${intervalSeconds.value || 0} 秒触发一次`
  }
  if (scheduleKind.value === "one_shot") {
    return oneShotTimestamp.value ? `将在 ${formatLocalTime(parseDateTimeLocalToUnix(oneShotTimestamp.value))} 触发` : "请选择时间"
  }
  return cronExpr.value.trim() ? `Cron: ${cronExpr.value.trim()}` : "请输入 cron 表达式"
})

// region helpers
function formatLocalTime(unixSeconds: number | null): string {
  if (unixSeconds === null || unixSeconds === undefined) {
    return "—"
  }
  return new Date(unixSeconds * 1000).toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

function formatSchedule(task: ScheduleTask): string {
  if (task.schedule.kind === "cron") {
    return `Cron · ${task.schedule.spec.expr}`
  }
  if (task.schedule.kind === "interval") {
    const seconds = Number(task.schedule.spec.seconds || 0)
    if (seconds < 60) {
      return `间隔 · ${seconds}s`
    }
    if (seconds < 3600) {
      return `间隔 · ${Math.round(seconds / 60)}m`
    }
    return `间隔 · ${Math.round(seconds / 3600)}h`
  }
  return `一次性 · ${formatLocalTime(task.schedule.spec.fire_at)}`
}

function isCompletedOneShot(task: ScheduleTask): boolean {
  return task.schedule.kind === "one_shot" && task.enabled === false && task.last_fired_at !== null
}

function stateLabel(task: ScheduleTask): string {
  if (isCompletedOneShot(task)) {
    return "已完成"
  }
  return task.enabled ? "启用中" : "已暂停"
}

function canResumeTask(task: ScheduleTask): boolean {
  return !isCompletedOneShot(task)
}

function parseDateTimeLocalToUnix(dateTimeLocal: string): number {
  return Math.floor(new Date(dateTimeLocal).getTime() / 1000)
}

function buildCreateSchedulePayload(): ScheduleSpec {
  if (scheduleKind.value === "cron") {
    const expr = cronExpr.value.trim()
    if (!expr) {
      throw new Error("请输入 cron 表达式")
    }
    return { kind: "cron", spec: { expr } }
  }
  if (scheduleKind.value === "interval") {
    const seconds = Number(intervalSeconds.value || 0)
    if (!Number.isFinite(seconds) || seconds <= 0) {
      throw new Error("请输入有效的间隔秒数")
    }
    return { kind: "interval", spec: { seconds } }
  }
  if (!oneShotTimestamp.value) {
    throw new Error("请选择一次性触发时间")
  }
  const fireAt = parseDateTimeLocalToUnix(oneShotTimestamp.value)
  if (!Number.isFinite(fireAt) || fireAt <= Math.floor(Date.now() / 1000)) {
    throw new Error("一次性触发时间必须晚于当前时间")
  }
  return {
    kind: "one_shot",
    spec: { fire_at: fireAt },
  }
}

function resetCreateForm(): void {
  createError.value = ""
  creating.value = false
  conversationIdMode.value = sessions.value.length > 0 ? "select" : "manual"
  sessionSearch.value = ""
  selectedSessionId.value = sessions.value[0]?.session_id ?? ""
  manualConversationId.value = ""
  scheduleKind.value = "interval"
  intervalSeconds.value = 3600
  cronExpr.value = "0 9 * * *"
  oneShotTimestamp.value = ""
  note.value = ""
}

function openCreateModal(): void {
  resetCreateForm()
  showCreateModal.value = true
}

function closeCreateModal(): void {
  showCreateModal.value = false
  createError.value = ""
}

function showTransientMessage(message: string): void {
  actionMessage.value = message
  window.setTimeout(() => {
    if (actionMessage.value === message) {
      actionMessage.value = ""
    }
  }, 2200)
}

// region data loading
async function loadTasks({ silent = false }: { silent?: boolean } = {}): Promise<void> {
  if (!silent) {
    loading.value = true
  }
  if (!silent) {
    errorMessage.value = ""
  }
  try {
    const data = await getSchedulesList(undefined, undefined, 200)
    tasks.value = data.items
  } catch (error) {
    if (!silent) {
      errorMessage.value = error instanceof Error ? error.message : "加载调度任务失败"
    }
  } finally {
    if (!silent) {
      loading.value = false
    }
  }
}

async function loadSessions(): Promise<void> {
  try {
    sessions.value = await apiGet<SessionSummary[]>("/api/sessions")
  } catch {
    sessions.value = []
  }
}

async function refreshPage(): Promise<void> {
  await Promise.all([loadTasks(), loadSessions()])
}

function startPolling(): void {
  stopPolling()
  refreshTimer.value = window.setInterval(() => {
    void loadTasks({ silent: true })
  }, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (refreshTimer.value !== null) {
    window.clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

// region actions
async function handleCreate(): Promise<void> {
  createError.value = ""
  const conversationId = effectiveConversationId.value
  if (!conversationId) {
    createError.value = "请选择会话，或手动输入 conversation_id"
    return
  }

  let schedule: ScheduleSpec
  try {
    schedule = buildCreateSchedulePayload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : "创建参数无效"
    return
  }

  creating.value = true
  try {
    await createSchedule(conversationId, schedule, note.value.trim() || undefined)
    showTransientMessage("调度任务已创建")
    closeCreateModal()
    await loadTasks()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : "创建任务失败"
  } finally {
    creating.value = false
  }
}

async function handleToggle(task: ScheduleTask): Promise<void> {
  busyTaskId.value = task.task_id
  errorMessage.value = ""
  try {
    if (task.enabled) {
      await disableSchedule(task.task_id)
      showTransientMessage("任务已暂停")
    } else {
      await enableSchedule(task.task_id)
      showTransientMessage("任务已恢复")
    }
    await loadTasks({ silent: true })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "切换任务状态失败"
  } finally {
    busyTaskId.value = ""
  }
}

async function handleDelete(task: ScheduleTask): Promise<void> {
  if (!window.confirm(`确认删除这条调度任务？\n\n${task.note || task.task_id}`)) {
    return
  }
  busyTaskId.value = task.task_id
  errorMessage.value = ""
  try {
    await deleteSchedule(task.task_id)
    showTransientMessage("任务已删除")
    await loadTasks({ silent: true })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "删除任务失败"
  } finally {
    busyTaskId.value = ""
  }
}

onMounted(async () => {
  await refreshPage()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="ds-page schedule-page">
    <header class="ds-hero schedule-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Scheduler / Conversation Wakeup</p>
        <h1>调度任务</h1>
      </div>
      <div class="schedule-actions">
        <button
          class="ds-secondary-button"
          type="button"
          data-schedule-refresh-button
          @click="void refreshPage()"
        >
          刷新
        </button>
        <button
          class="ds-primary-button"
          type="button"
          data-schedule-create-button
          @click="openCreateModal"
        >
          新建任务
        </button>
      </div>
    </header>

    <div v-if="actionMessage" class="ds-status is-ok schedule-status">
      {{ actionMessage }}
    </div>
    <div v-if="errorMessage" class="ds-status is-error schedule-status" data-schedule-error>
      {{ errorMessage }}
    </div>

    <article v-if="loading" class="ds-panel ds-panel-padding schedule-loading">
      <div class="schedule-spinner"></div>
      <p>正在读取调度任务...</p>
    </article>

    <article v-else-if="tasks.length === 0" class="ds-panel ds-panel-padding ds-empty schedule-empty">
      <strong>还没有调度任务</strong>
      <p>创建后会显示在这里，并持续刷新最近执行时间与下一次执行时间。</p>
    </article>

    <ul v-else class="schedule-list" role="list">
      <li
        v-for="task in tasks"
        :key="task.task_id"
        class="ds-panel ds-panel-padding schedule-row"
        :data-schedule-row="task.task_id"
      >
        <div class="schedule-row-main">
          <div class="schedule-row-top">
            <div class="schedule-row-heading">
              <strong class="schedule-note">{{ task.note || "未填写备注" }}</strong>
              <span class="schedule-kind-chip">{{ task.schedule.kind }}</span>
              <span class="schedule-state-chip" :class="task.enabled ? 'is-enabled' : 'is-disabled'">
                {{ stateLabel(task) }}
              </span>
            </div>
            <code class="schedule-conversation ds-mono">{{ task.conversation_id }}</code>
          </div>

          <div class="schedule-row-summary">
            <span class="schedule-summary-item">
              <span class="schedule-summary-label">调度</span>
              <span class="schedule-summary-value">{{ formatSchedule(task) }}</span>
            </span>
            <span class="schedule-summary-item">
              <span class="schedule-summary-label">创建</span>
              <span class="schedule-summary-value ds-mono">{{ formatLocalTime(task.created_at) }}</span>
            </span>
            <span class="schedule-summary-item">
              <span class="schedule-summary-label">最近执行</span>
              <span class="schedule-summary-value ds-mono" :data-schedule-last-fired="task.task_id">
                {{ formatLocalTime(task.last_fired_at) }}
              </span>
            </span>
            <span class="schedule-summary-item">
              <span class="schedule-summary-label">下一次</span>
              <span class="schedule-summary-value ds-mono" :data-schedule-next-fire="task.task_id">
                {{ formatLocalTime(task.next_fire_at) }}
              </span>
            </span>
          </div>
        </div>

        <div class="schedule-row-actions">
          <button
            v-if="task.enabled || canResumeTask(task)"
            class="ds-secondary-button"
            type="button"
            :data-schedule-toggle="task.task_id"
            :disabled="busyTaskId === task.task_id"
            @click="void handleToggle(task)"
          >
            {{ task.enabled ? "暂停" : "恢复" }}
          </button>
          <button
            class="ds-ghost-button"
            type="button"
            :data-schedule-delete="task.task_id"
            :disabled="busyTaskId === task.task_id"
            @click="void handleDelete(task)"
          >
            删除
          </button>
        </div>
      </li>
    </ul>

    <Transition name="schedule-modal">
      <div v-if="showCreateModal" class="schedule-modal-backdrop" @click.self="closeCreateModal">
        <section class="ds-panel ds-panel-padding schedule-modal" data-schedule-create-modal>
          <header class="schedule-modal-header">
            <div>
              <p class="ds-eyebrow">Create schedule</p>
              <h2>新建调度任务</h2>
            </div>
            <button class="ds-ghost-button schedule-modal-close" type="button" @click="closeCreateModal">
              关闭
            </button>
          </header>

          <p v-if="createError" class="ds-status is-error schedule-status" data-schedule-create-error>
            {{ createError }}
          </p>

          <div class="schedule-modal-grid">
            <section class="schedule-form-section">
              <header class="schedule-form-head">
                <h3>目标会话</h3>
                <p>可以直接选现有会话，也可以手动填写 conversation_id。</p>
              </header>

              <div class="schedule-mode-row">
                <button
                  class="schedule-mode-button"
                  :class="{ active: conversationIdMode === 'select' }"
                  type="button"
                  data-schedule-mode-select
                  @click="conversationIdMode = 'select'"
                >
                  选择会话
                </button>
                <button
                  class="schedule-mode-button"
                  :class="{ active: conversationIdMode === 'manual' }"
                  type="button"
                  data-schedule-mode-manual
                  @click="conversationIdMode = 'manual'"
                >
                  手动输入
                </button>
              </div>

              <div v-if="conversationIdMode === 'select'" class="schedule-session-picker">
                <input
                  v-model="sessionSearch"
                  class="ds-input"
                  type="text"
                  placeholder="搜索 session_id 或标题..."
                  data-schedule-session-search
                />
                <div class="schedule-session-list">
                  <button
                    v-for="session in filteredSessions"
                    :key="session.session_id"
                    class="schedule-session-option"
                    :class="{ active: selectedSessionId === session.session_id }"
                    type="button"
                    :data-schedule-session-option="session.session_id"
                    @click="selectedSessionId = session.session_id"
                  >
                    <span class="schedule-session-title">{{ session.title || "未命名会话" }}</span>
                    <code class="ds-mono">{{ session.session_id }}</code>
                  </button>
                  <p v-if="filteredSessions.length === 0" class="schedule-session-empty">没有匹配的会话，试试手动输入。</p>
                </div>
              </div>
              <input
                v-else
                v-model="manualConversationId"
                class="ds-input ds-mono"
                type="text"
                placeholder="例如 qq:user:1733064202"
                data-schedule-manual-input
              />
            </section>

            <section class="schedule-form-section">
              <header class="schedule-form-head">
                <h3>调度规则</h3>
                <p>{{ scheduleSummary }}</p>
              </header>

              <div class="schedule-kind-row">
                <button
                  v-for="item in SCHEDULE_KIND_OPTIONS"
                  :key="item.value"
                  class="schedule-kind-button"
                  :class="{ active: scheduleKind === item.value }"
                  type="button"
                  :data-schedule-kind="item.value"
                  @click="scheduleKind = item.value"
                >
                  {{ item.label }}
                </button>
              </div>

              <input
                v-if="scheduleKind === 'interval'"
                v-model.number="intervalSeconds"
                class="ds-input"
                type="number"
                min="1"
                step="1"
                data-schedule-interval-input
              />
              <input
                v-else-if="scheduleKind === 'cron'"
                v-model="cronExpr"
                class="ds-input ds-mono"
                type="text"
                placeholder="0 9 * * *"
                data-schedule-cron-input
              />
              <input
                v-else
                v-model="oneShotTimestamp"
                class="ds-input"
                type="datetime-local"
                data-schedule-one-shot-input
              />
            </section>

            <section class="schedule-form-section schedule-form-section-full">
              <header class="schedule-form-head">
                <h3>备注</h3>
                <p>这段文字会在任务触发时作为唤醒说明交给 agent。</p>
              </header>
              <input
                v-model="note"
                class="ds-input"
                type="text"
                maxlength="500"
                placeholder="例如：2 分钟后提醒我继续看日志"
                data-schedule-note-input
              />
            </section>
          </div>

          <footer class="schedule-modal-footer">
            <code class="ds-mono schedule-effective-id">{{ effectiveConversationId || "尚未选择 conversation_id" }}</code>
            <div class="schedule-modal-actions">
              <button class="ds-secondary-button" type="button" @click="closeCreateModal">取消</button>
              <button
                class="ds-primary-button"
                type="button"
                :disabled="creating"
                data-schedule-create-submit
                @click="void handleCreate()"
              >
                {{ creating ? "创建中..." : "创建任务" }}
              </button>
            </div>
          </footer>
        </section>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.schedule-page {
  gap: 16px;
}

.schedule-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
}

.schedule-actions {
  display: inline-flex;
  gap: 10px;
  flex-wrap: wrap;
}

.schedule-status {
  margin: 0;
}

.schedule-loading,
.schedule-empty {
  display: grid;
  place-items: center;
  gap: 12px;
  text-align: center;
  min-height: 220px;
}

.schedule-spinner {
  width: 20px;
  height: 20px;
  border-radius: 999px;
  border: 2px solid color-mix(in srgb, var(--line) 78%, transparent);
  border-top-color: var(--accent);
  animation: schedule-spin 700ms linear infinite;
}

.schedule-list {
  display: grid;
  gap: 12px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.schedule-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
}

.schedule-row-main {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.schedule-row-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.schedule-row-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.schedule-note {
  font-size: 16px;
  color: var(--heading-strong);
}

.schedule-kind-chip,
.schedule-state-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.schedule-kind-chip {
  background: color-mix(in srgb, var(--accent) 11%, transparent);
  color: var(--accent);
}

.schedule-state-chip.is-enabled {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}

.schedule-state-chip.is-disabled {
  background: color-mix(in srgb, var(--muted) 16%, transparent);
  color: var(--muted);
}

.schedule-conversation {
  padding: 6px 10px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--panel) 72%, transparent);
  border: 1px solid var(--line);
  font-size: 12px;
}

.schedule-row-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.schedule-summary-item {
  display: grid;
  gap: 4px;
}

.schedule-summary-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}

.schedule-summary-value {
  color: var(--text);
  line-height: 1.5;
}

.schedule-row-actions {
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
}

.schedule-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(12, 12, 16, 0.36);
  backdrop-filter: blur(4px);
}

.schedule-modal {
  width: min(980px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  overflow: auto;
  display: grid;
  gap: 20px;
}

.schedule-modal-header,
.schedule-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.schedule-modal-header h2 {
  margin: 4px 0 0;
}

.schedule-modal-close {
  white-space: nowrap;
}

.schedule-modal-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.schedule-form-section {
  display: grid;
  gap: 12px;
}

.schedule-form-section-full {
  grid-column: 1 / -1;
}

.schedule-form-head {
  display: grid;
  gap: 4px;
}

.schedule-form-head h3 {
  margin: 0;
  font-size: 15px;
}

.schedule-form-head p {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
}

.schedule-mode-row,
.schedule-kind-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.schedule-mode-button,
.schedule-kind-button {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 72%, transparent);
  color: var(--muted);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, color 120ms ease;
}

.schedule-mode-button.active,
.schedule-kind-button.active {
  border-color: color-mix(in srgb, var(--accent) 66%, var(--line));
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
}

.schedule-session-picker {
  display: grid;
  gap: 10px;
}

.schedule-session-list {
  display: grid;
  gap: 6px;
  max-height: 220px;
  overflow: auto;
  padding: 8px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 70%, transparent);
}

.schedule-session-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.schedule-session-option:hover,
.schedule-session-option.active {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.schedule-session-title {
  font-weight: 600;
}

.schedule-session-empty {
  margin: 0;
  color: var(--muted);
  padding: 10px 12px;
}

.schedule-effective-id {
  padding: 6px 10px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--panel) 72%, transparent);
}

.schedule-modal-actions {
  display: inline-flex;
  gap: 10px;
}

.schedule-modal-enter-active,
.schedule-modal-leave-active {
  transition: opacity 160ms ease;
}

.schedule-modal-enter-from,
.schedule-modal-leave-to {
  opacity: 0;
}

.schedule-modal-enter-active .schedule-modal {
  animation: schedule-modal-in 180ms cubic-bezier(0.22, 1, 0.36, 1);
}

.schedule-modal-leave-active .schedule-modal {
  animation: schedule-modal-out 120ms cubic-bezier(0.4, 0, 1, 1);
}

@keyframes schedule-modal-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes schedule-modal-out {
  from {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
  to {
    opacity: 0;
    transform: translateY(6px) scale(0.985);
  }
}

@keyframes schedule-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 980px) {
  .schedule-row-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .schedule-modal-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .schedule-hero,
  .schedule-modal-header,
  .schedule-modal-footer,
  .schedule-row {
    grid-template-columns: 1fr;
    display: grid;
  }

  .schedule-actions,
  .schedule-row-actions,
  .schedule-modal-actions {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .schedule-row-summary {
    grid-template-columns: 1fr;
  }

  .schedule-modal {
    width: min(100vw - 24px, 980px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .schedule-spinner,
  .schedule-modal-enter-active .schedule-modal,
  .schedule-modal-leave-active .schedule-modal {
    animation: none;
  }
}
</style>
