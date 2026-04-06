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
    return `间隔 · ${(seconds / 3600).toFixed(1)}h`
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
  <section class="page">
    <header class="page-header">
      <div class="page-header-main">
        <p class="page-eyebrow">Scheduler / Conversation Wakeup</p>
        <h1 class="page-title">调度任务</h1>
      </div>
      <div class="page-header-actions">
        <button
          class="btn btn-secondary"
          type="button"
          data-schedule-refresh-button
          @click="void refreshPage()"
        >
          <svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 10a6 6 0 1 1 1.5 3.9" stroke-linecap="round"/>
            <path d="M4 14V10h4" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          刷新
        </button>
        <button
          class="btn btn-primary"
          type="button"
          data-schedule-create-button
          @click="openCreateModal"
        >
          <svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 4v12M4 10h12" stroke-linecap="round"/>
          </svg>
          新建任务
        </button>
      </div>
    </header>

    <Transition name="fade">
      <div v-if="actionMessage" class="toast toast-success">
        {{ actionMessage }}
      </div>
    </Transition>
    <Transition name="fade">
      <div v-if="errorMessage" class="toast toast-error" data-schedule-error>
        {{ errorMessage }}
      </div>
    </Transition>

    <article v-if="loading" class="state-panel">
      <div class="spinner"></div>
      <p class="state-text">正在读取调度任务...</p>
    </article>

    <article v-else-if="tasks.length === 0" class="state-panel state-empty">
      <svg class="state-icon" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="24" cy="24" r="20"/>
        <path d="M24 14v10l6 4" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <strong class="state-title">还没有调度任务</strong>
      <p class="state-desc">创建后会显示在这里，并持续刷新最近执行时间与下一次执行时间。</p>
      <button class="btn btn-primary" type="button" @click="openCreateModal">
        <svg class="btn-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10 4v12M4 10h12" stroke-linecap="round"/>
        </svg>
        创建第一个任务
      </button>
    </article>

    <ul v-else class="task-list" role="list">
      <li
        v-for="task in tasks"
        :key="task.task_id"
        class="task-card"
        :data-schedule-row="task.task_id"
      >
        <div class="task-card-main">
          <div class="task-card-header">
            <div class="task-card-tags">
              <span class="tag tag-accent">{{ task.schedule.kind }}</span>
              <span class="tag" :class="task.enabled ? 'tag-success' : 'tag-muted'">
                {{ stateLabel(task) }}
              </span>
            </div>
            <code class="task-conversation">{{ task.conversation_id }}</code>
          </div>

          <p class="task-note">{{ task.note || "未填写备注" }}</p>

          <div class="task-meta">
            <div class="meta-item">
              <span class="meta-label">调度</span>
              <span class="meta-value">{{ formatSchedule(task) }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">创建</span>
              <span class="meta-value meta-mono">{{ formatLocalTime(task.created_at) }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">最近执行</span>
              <span class="meta-value meta-mono" :data-schedule-last-fired="task.task_id">
                {{ formatLocalTime(task.last_fired_at) }}
              </span>
            </div>
            <div class="meta-item">
              <span class="meta-label">下一次</span>
              <span class="meta-value meta-mono" :data-schedule-next-fire="task.task_id">
                {{ formatLocalTime(task.next_fire_at) }}
              </span>
            </div>
          </div>
        </div>

        <div class="task-card-actions">
          <div class="toggle-wrapper">
            <button
              class="toggle-switch"
              :class="{
                'is-enabled': task.enabled,
                'is-loading': busyTaskId === task.task_id && task.enabled,
              }"
              type="button"
              role="switch"
              :aria-checked="task.enabled"
              :data-schedule-toggle="task.task_id"
              :disabled="busyTaskId === task.task_id"
              @click="void handleToggle(task)"
            >
              <span class="toggle-thumb"></span>
            </button>
            <span class="toggle-label" :class="{ 'is-enabled': task.enabled }">
              {{ task.enabled ? "运行中" : "已暂停" }}
            </span>
          </div>
          <button
            class="btn btn-sm btn-ghost btn-danger"
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

    <Transition name="modal">
      <div v-if="showCreateModal" class="modal-backdrop" @click.self="closeCreateModal">
        <section class="modal" data-schedule-create-modal>
          <header class="modal-header">
            <div>
              <p class="page-eyebrow">Create schedule</p>
              <h2 class="modal-title">新建调度任务</h2>
            </div>
            <button class="btn btn-ghost btn-sm modal-close" type="button" @click="closeCreateModal">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round"/>
              </svg>
            </button>
          </header>

          <Transition name="fade">
            <p v-if="createError" class="toast toast-error" data-schedule-create-error>
              {{ createError }}
            </p>
          </Transition>

          <div class="modal-body">
            <section class="form-section">
              <header class="form-section-header">
                <h3>目标会话</h3>
                <p>可以直接选现有会话，也可以手动填写 conversation_id。</p>
              </header>

              <div class="toggle-group">
                <button
                  class="toggle-btn"
                  :class="{ active: conversationIdMode === 'select' }"
                  type="button"
                  data-schedule-mode-select
                  @click="conversationIdMode = 'select'"
                >
                  选择会话
                </button>
                <button
                  class="toggle-btn"
                  :class="{ active: conversationIdMode === 'manual' }"
                  type="button"
                  data-schedule-mode-manual
                  @click="conversationIdMode = 'manual'"
                >
                  手动输入
                </button>
              </div>

              <div v-if="conversationIdMode === 'select'" class="session-picker">
                <input
                  v-model="sessionSearch"
                  class="input"
                  type="text"
                  placeholder="搜索 session_id 或标题..."
                  data-schedule-session-search
                />
                <div class="session-list">
                  <button
                    v-for="session in filteredSessions"
                    :key="session.session_id"
                    class="session-option"
                    :class="{ active: selectedSessionId === session.session_id }"
                    type="button"
                    :data-schedule-session-option="session.session_id"
                    @click="selectedSessionId = session.session_id"
                  >
                    <span class="session-title">{{ session.title || "未命名会话" }}</span>
                    <code class="session-id">{{ session.session_id }}</code>
                  </button>
                  <p v-if="filteredSessions.length === 0" class="session-empty">没有匹配的会话，试试手动输入。</p>
                </div>
              </div>
              <input
                v-else
                v-model="manualConversationId"
                class="input input-mono"
                type="text"
                placeholder="例如 qq:user:1733064202"
                data-schedule-manual-input
              />
            </section>

            <section class="form-section">
              <header class="form-section-header">
                <h3>调度规则</h3>
                <p>{{ scheduleSummary }}</p>
              </header>

              <div class="toggle-group">
                <button
                  v-for="item in SCHEDULE_KIND_OPTIONS"
                  :key="item.value"
                  class="toggle-btn"
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
                class="input"
                type="number"
                min="1"
                step="1"
                data-schedule-interval-input
              />
              <input
                v-else-if="scheduleKind === 'cron'"
                v-model="cronExpr"
                class="input input-mono"
                type="text"
                placeholder="0 9 * * *"
                data-schedule-cron-input
              />
              <input
                v-else
                v-model="oneShotTimestamp"
                class="input"
                type="datetime-local"
                data-schedule-one-shot-input
              />
            </section>

            <section class="form-section form-section-full">
              <header class="form-section-header">
                <h3>备注</h3>
                <p>这段文字会在任务触发时作为唤醒说明交给 agent。</p>
              </header>
              <input
                v-model="note"
                class="input"
                type="text"
                maxlength="500"
                placeholder="例如：2 分钟后提醒我继续看日志"
                data-schedule-note-input
              />
            </section>
          </div>

          <footer class="modal-footer">
            <code class="effective-id">{{ effectiveConversationId || "尚未选择 conversation_id" }}</code>
            <div class="modal-footer-actions">
              <button class="btn btn-secondary" type="button" @click="closeCreateModal">取消</button>
              <button
                class="btn btn-primary"
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
/* ── Page layout ── */
.page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}

.page-header-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-eyebrow {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  margin: 0;
}

.page-title {
  margin: 0;
  font-size: 26px;
  font-weight: 800;
  color: var(--heading-strong);
  letter-spacing: -0.02em;
}

.page-header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border-radius: 14px;
  border: none;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 120ms ease;
  white-space: nowrap;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.btn-primary {
  background: linear-gradient(145deg, var(--button-primary-start), var(--button-primary-end));
  color: #fff;
  box-shadow: 0 2px 8px var(--button-shadow-color);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px var(--button-shadow-color);
}

.btn-secondary {
  background: var(--panel-strong);
  color: var(--text);
  border: 1px solid var(--line);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--panel-line-soft);
}

.btn-success {
  background: color-mix(in srgb, var(--success) 15%, transparent);
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
}

.btn-success:hover:not(:disabled) {
  background: color-mix(in srgb, var(--success) 25%, transparent);
}

.btn-ghost {
  background: transparent;
  color: var(--muted);
}

.btn-ghost:hover:not(:disabled) {
  background: var(--panel-strong);
  color: var(--text);
}

.btn-danger {
  color: var(--danger);
}

.btn-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  color: var(--danger);
}

.btn-sm {
  padding: 7px 12px;
  font-size: 12px;
  border-radius: 10px;
}

/* ── Toast ── */
.toast {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  margin: 0;
}

.toast-success {
  background: color-mix(in srgb, var(--success) 15%, var(--panel));
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
}

.toast-error {
  background: color-mix(in srgb, var(--danger) 15%, var(--panel));
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
}

/* ── State panels ── */
.state-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 48px 24px;
  border-radius: 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  text-align: center;
}

.state-empty {
  min-height: 320px;
}

.spinner {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--line) 70%, transparent);
  border-top-color: var(--accent);
  animation: spin 700ms linear infinite;
}

.state-text {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
}

.state-icon {
  width: 56px;
  height: 56px;
  color: var(--muted);
  opacity: 0.5;
}

.state-title {
  font-size: 16px;
  color: var(--heading-strong);
}

.state-desc {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  max-width: 280px;
  line-height: 1.5;
}

/* ── Task list ── */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.task-card {
  display: flex;
  gap: 20px;
  padding: 20px;
  border-radius: 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  transition: border-color 120ms ease, box-shadow 120ms ease;
}

.task-card:hover {
  border-color: var(--panel-line-strong);
  box-shadow: var(--shadow-card);
}

.task-card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.task-card-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.tag-accent {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
}

.tag-success {
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}

.tag-muted {
  background: color-mix(in srgb, var(--muted) 14%, transparent);
  color: var(--muted);
}

.task-conversation {
  padding: 5px 10px;
  border-radius: 10px;
  background: var(--panel-strong);
  border: 1px solid var(--line);
  font-size: 11px;
  font-family: inherit;
  color: var(--muted);
}

.task-note {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--heading-strong);
  line-height: 1.4;
}

.task-meta {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.meta-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}

.meta-value {
  font-size: 13px;
  color: var(--text);
  line-height: 1.4;
}

.meta-mono {
  font-family: "SF Mono", "Fira Code", "Fira Mono", ui-monospace, monospace;
  font-size: 12px;
}

.task-card-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-end;
  flex-shrink: 0;
}

/* ── Toggle Switch ── */
.toggle-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toggle-switch {
  position: relative;
  width: 44px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: var(--panel-line-strong);
  cursor: pointer;
  transition: background 200ms ease;
}

.toggle-switch:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.toggle-switch.is-enabled {
  background: var(--success);
}

.toggle-switch:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  transition: transform 200ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

.toggle-switch.is-enabled .toggle-thumb {
  transform: translateX(20px);
}

.toggle-switch.is-loading .toggle-thumb {
  animation: toggle-pulse 800ms ease-in-out infinite;
}

.toggle-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  min-width: 48px;
}

.toggle-label.is-enabled {
  color: var(--success);
}

@keyframes toggle-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── Modal ── */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(12, 12, 16, 0.48);
  backdrop-filter: blur(6px);
}

.modal {
  width: min(900px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  border-radius: 24px;
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 24px 0;
}

.modal-title {
  margin: 4px 0 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--heading-strong);
}

.modal-close {
  padding: 8px;
}

.modal-close svg {
  width: 18px;
  height: 18px;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
  border-top: 1px solid var(--line);
  background: var(--panel-strong);
}

.modal-footer-actions {
  display: flex;
  gap: 10px;
}

.effective-id {
  padding: 6px 12px;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
  font-family: inherit;
}

/* ── Form ── */
.form-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-section-full {
  grid-column: 1 / -1;
}

.form-section-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-section-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--heading-strong);
}

.form-section-header p {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.toggle-group {
  display: flex;
  gap: 6px;
}

.toggle-btn {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--muted);
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 120ms ease;
}

.toggle-btn:hover {
  border-color: var(--panel-line-strong);
}

.toggle-btn.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}

.input {
  width: 100%;
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  transition: border-color 120ms ease, box-shadow 120ms ease;
  box-sizing: border-box;
}

.input::placeholder {
  color: var(--muted);
}

.input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 15%, transparent);
}

.input-mono {
  font-family: "SF Mono", "Fira Code", "Fira Mono", ui-monospace, monospace;
  font-size: 12px;
}

/* ── Session picker ── */
.session-picker {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
  padding: 8px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--panel-strong);
}

.session-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 100ms ease;
}

.session-option:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.session-option.active {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
}

.session-title {
  font-weight: 600;
  font-size: 13px;
}

.session-id {
  font-size: 11px;
  color: var(--muted);
  font-family: inherit;
}

.session-empty {
  margin: 0;
  padding: 12px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

/* ── Animations ── */
@keyframes spin {
  to { transform: rotate(360deg); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 160ms ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.modal-enter-active .modal {
  animation: modal-in 200ms cubic-bezier(0.22, 1, 0.36, 1);
}

.modal-leave-active .modal {
  animation: modal-out 140ms cubic-bezier(0.4, 0, 1, 1);
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 180ms ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

@keyframes modal-in {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@keyframes modal-out {
  from {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
  to {
    opacity: 0;
    transform: scale(0.98) translateY(4px);
  }
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .modal-body {
    grid-template-columns: 1fr;
  }

  .task-meta {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 700px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .page-header-actions {
    width: 100%;
  }

  .page-header-actions .btn {
    flex: 1;
  }

  .task-card {
    flex-direction: column;
  }

  .task-card-actions {
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
  }

  .task-meta {
    grid-template-columns: 1fr 1fr;
  }

  .modal-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .effective-id {
    text-align: center;
    margin-bottom: 8px;
  }

  .modal-footer-actions {
    justify-content: stretch;
  }

  .modal-footer-actions .btn {
    flex: 1;
  }
}

@media (max-width: 480px) {
  .task-meta {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .spinner,
  .modal-enter-active .modal,
  .modal-leave-active .modal {
    animation: none;
  }
}
</style>
