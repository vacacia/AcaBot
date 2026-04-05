<script setup lang="ts">
import { computed, ref, watch } from "vue"

import { apiGetFresh } from "../lib/api"

type RunRecord = {
  run_id: string
  thread_id: string
  actor_id: string
  agent_id: string
  trigger_event_id: string
  status: string
  started_at: number
  finished_at: number | null
  error: string | null
  approval_context: Record<string, unknown>
  metadata: Record<string, unknown>
}

type RunStep = {
  step_id: string
  run_id: string
  thread_id: string
  step_type: string
  status: string
  payload: Record<string, unknown>
  created_at: number
  step_seq: number
}

const props = defineProps<{
  runId: string
}>()

const emit = defineEmits<{
  close: []
}>()

const loading = ref(false)
const errorText = ref("")
const run = ref<RunRecord | null>(null)
const steps = ref<RunStep[]>([])
const expandedSteps = ref<number[]>([])
let activeRequestToken = 0

const keyMetadata = computed(() => {
  const metadata = run.value?.metadata ?? {}
  return [
    { label: "模型", value: metadata.model_used },
    { label: "Token 用量", value: metadata.token_usage },
    { label: "模型快照", value: metadata.model_snapshot },
  ].filter((item) => item.value !== undefined)
})

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value)
  }
}

function toggleStep(stepSeq: number): void {
  expandedSteps.value = expandedSteps.value.includes(stepSeq)
    ? expandedSteps.value.filter((value) => value !== stepSeq)
    : [...expandedSteps.value, stepSeq]
}

function stepSummary(step: RunStep): string {
  const payload = step.payload ?? {}
  if (step.step_type === "workspace_prepare") {
    return `workspace=${String(payload.workspace_root ?? "")}`
  }
  if (step.step_type === "exec") {
    return `exit=${String(payload.exit_code ?? "-")} cwd=${String(payload.execution_cwd ?? "")}`
  }
  if (step.step_type.startsWith("approval_")) {
    return `approval ${step.step_type}`
  }
  return step.step_type
}

async function loadRunDetails(runId: string): Promise<void> {
  const requestToken = ++activeRequestToken
  if (!runId) {
    run.value = null
    steps.value = []
    expandedSteps.value = []
    loading.value = false
    errorText.value = ""
    return
  }
  loading.value = true
  errorText.value = ""
  try {
    const [runData, stepData] = await Promise.all([
      apiGetFresh<RunRecord>(`/api/runtime/runs/${encodeURIComponent(runId)}`),
      apiGetFresh<RunStep[]>(`/api/runtime/runs/${encodeURIComponent(runId)}/steps?limit=200&latest=true`),
    ])
    if (requestToken !== activeRequestToken || runId !== props.runId) {
      return
    }
    run.value = runData
    steps.value = stepData
    expandedSteps.value = []
  } catch (error) {
    if (requestToken !== activeRequestToken || runId !== props.runId) {
      return
    }
    errorText.value = error instanceof Error ? error.message : "加载 run 详情失败"
    run.value = null
    steps.value = []
  } finally {
    if (requestToken === activeRequestToken && runId === props.runId) {
      loading.value = false
    }
  }
}

watch(
  () => props.runId,
  (value) => {
    void loadRunDetails(value)
  },
  { immediate: true },
)
</script>

<template>
  <aside class="run-detail-panel ds-panel ds-panel-padding">
    <div class="ds-section-head">
      <div class="ds-section-title">
        <div>
          <h2>Run 详情</h2>
          <p class="ds-summary ds-mono">{{ runId }}</p>
        </div>
      </div>
      <div class="ds-actions">
        <button class="ds-inline-button" type="button" @click="emit('close')">关闭</button>
      </div>
    </div>

    <p v-if="loading" class="ds-summary">正在加载 run 详情…</p>
    <p v-else-if="errorText" class="ds-status is-error">{{ errorText }}</p>
    <template v-else-if="run">
      <div class="ds-card-grid-2 overview-grid">
        <article class="ds-surface ds-card-padding-sm detail-card">
          <p class="summary-label">状态</p>
          <strong>{{ run.status }}</strong>
          <p class="ds-summary ds-mono">thread={{ run.thread_id }}</p>
          <p v-if="run.error" class="ds-status is-error">{{ run.error }}</p>
        </article>
        <article class="ds-surface ds-card-padding-sm detail-card">
          <p class="summary-label">Agent</p>
          <strong class="ds-mono">{{ run.agent_id }}</strong>
          <p class="ds-summary ds-mono">event={{ run.trigger_event_id }}</p>
          <p class="ds-summary ds-mono">started_at={{ run.started_at }}</p>
          <p class="ds-summary ds-mono">finished_at={{ run.finished_at ?? '-' }}</p>
        </article>
      </div>

      <div v-if="keyMetadata.length" class="metadata-stack">
        <article v-for="item in keyMetadata" :key="item.label" class="ds-surface ds-card-padding-sm">
          <p class="summary-label">{{ item.label }}</p>
          <pre class="json-block">{{ formatJson(item.value) }}</pre>
        </article>
      </div>

      <details class="ds-surface ds-card-padding-sm detail-json" open>
        <summary>完整 metadata</summary>
        <pre class="json-block">{{ formatJson(run.metadata) }}</pre>
      </details>

      <details class="ds-surface ds-card-padding-sm detail-json">
        <summary>approval_context</summary>
        <pre class="json-block">{{ formatJson(run.approval_context) }}</pre>
      </details>

      <div class="steps-head">
        <h3>最近 200 条 Steps</h3>
        <p class="ds-summary">按真实追加顺序展示，便于直接排障。</p>
      </div>

      <div class="step-list">
        <article v-for="step in steps" :key="step.step_id" class="ds-surface ds-card-padding-sm step-card">
          <div class="step-top">
            <div>
              <p class="summary-label">#{{ step.step_seq }} · {{ step.step_type }}</p>
              <p class="ds-summary">{{ stepSummary(step) }}</p>
            </div>
            <button class="ds-inline-button" type="button" @click="toggleStep(step.step_seq)">
              {{ expandedSteps.includes(step.step_seq) ? "收起" : "展开" }}
            </button>
          </div>

          <div class="chip-row">
            <span class="ds-chip">status={{ step.status }}</span>
            <span class="ds-chip">created_at={{ step.created_at }}</span>
          </div>

          <template v-if="step.step_type === 'exec' && isObject(step.payload)">
            <div class="exec-grid">
              <article class="ds-surface ds-card-padding-sm exec-card">
                <p class="summary-label">stdout excerpt</p>
                <pre class="json-block">{{ String(step.payload.stdout_excerpt ?? '') }}</pre>
              </article>
              <article class="ds-surface ds-card-padding-sm exec-card">
                <p class="summary-label">stderr excerpt</p>
                <pre class="json-block">{{ String(step.payload.stderr_excerpt ?? '') }}</pre>
              </article>
            </div>
          </template>

          <pre v-if="expandedSteps.includes(step.step_seq)" class="json-block">{{ formatJson(step.payload) }}</pre>
        </article>
      </div>
    </template>
    <p v-else class="ds-summary">选择一条带 run_id 的日志即可查看详情。</p>
  </aside>
</template>

<style scoped>
.run-detail-panel {
  min-width: 0;
}

.overview-grid,
.metadata-stack,
.step-list {
  display: grid;
  gap: 12px;
}

.metadata-stack,
.step-list {
  margin-top: 12px;
}

.detail-card strong {
  display: block;
  margin-top: 8px;
}

.summary-label {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.detail-json,
.steps-head {
  margin-top: 12px;
}

.steps-head h3 {
  margin: 0;
}

.step-top {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.json-block {
  margin: 10px 0 0;
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

.exec-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.exec-card {
  border: 1px solid var(--line);
}

@media (max-width: 900px) {
  .exec-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
