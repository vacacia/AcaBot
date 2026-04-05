<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import LogStreamPanel from "../components/LogStreamPanel.vue"
import StatusCard from "../components/StatusCard.vue"
import { apiGet, peekCachedGet } from "../lib/api"

type RuntimeStatus = {
  loaded_plugins?: string[]
  loaded_skills?: string[]
  active_runs?: Array<unknown>
}

type GatewayStatus = {
  connected?: boolean
}

type BackendStatus = {
  configured?: boolean
  active_modes?: string[]
}

type SubagentItem = { subagent_name: string }

const status = ref<RuntimeStatus>(peekCachedGet<RuntimeStatus>("/api/status") ?? {})
const gateway = ref<GatewayStatus>(peekCachedGet<GatewayStatus>("/api/gateway/status") ?? {})
const backend = ref<BackendStatus>(peekCachedGet<BackendStatus>("/api/backend/status") ?? {})
const subagents = ref<SubagentItem[]>(peekCachedGet<SubagentItem[]>("/api/subagents") ?? [])
const errorText = ref("")

// Helper to check if we have any data to show immediately
const hasSomeData = computed(() => (
  Object.keys(status.value).length > 0 ||
  Object.keys(gateway.value).length > 0 ||
  Object.keys(backend.value).length > 0
))

// Only show loading if we have absolutely nothing to show
const loading = ref(!hasSomeData.value)

const runtimeDetail = computed(() => {
  const parts: string[] = []
  const plugins = status.value.loaded_plugins?.length ?? 0
  const skills = status.value.loaded_skills?.length ?? 0
  const subs = subagents.value.length
  if (plugins) parts.push(`${plugins} 插件`)
  if (skills) parts.push(`${skills} 技能`)
  if (subs) parts.push(`${subs} 子代理`)
  return parts.join(" · ") || undefined
})

const cards = computed(() => [
  {
    title: "Runtime",
    value: "在线",
    hint: runtimeDetail.value || "运行中",
    detail: "",
    variant: "active",
  },
  {
    title: "Gateway",
    value: gateway.value.connected ? "Connected" : "Disconnected",
    hint: "NapCat 连接状态",
    variant: gateway.value.connected ? "connected" : "disconnected",
  },
  {
    title: "Backend",
    value: backend.value.configured ? "Ready" : "Unavailable",
    hint: `活跃模式 ${backend.value.active_modes?.length ?? 0}`,
    variant: backend.value.configured ? "ready" : "unavailable",
  },
  {
    title: "Runs",
    value: String(status.value.active_runs?.length ?? 0),
    hint: "当前活跃运行数",
    variant: "warm",
  },
])

async function load(): Promise<void> {
  // If we don't have cached data, we must show loading state
  if (!hasSomeData.value) {
    loading.value = true
  }
  errorText.value = ""

  // Fetch all endpoints concurrently without blocking each other (SWR pattern)
  const reqs = [
    apiGet<RuntimeStatus>("/api/status").then(r => { status.value = r }),
    apiGet<GatewayStatus>("/api/gateway/status").then(r => { gateway.value = r }),
    apiGet<BackendStatus>("/api/backend/status").then(r => { backend.value = r }),
    apiGet<SubagentItem[]>("/api/subagents").then(r => { subagents.value = r }),
  ]

  try {
    // Wait for everything to finish, but they update individual refs as they come in
    await Promise.allSettled(reqs)
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "首页某些数据刷新失败"
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">AcaBot / Overview</p>
        <h1>运行总览</h1>
      </div>
      <div class="ds-actions">
        <button class="ds-ghost-button" type="button">控制面说明</button>
        <button class="ds-primary-button" type="button" :disabled="loading" @click="void load()">
          <svg v-if="loading" class="spin-icon" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="22" stroke-dashoffset="8" stroke-linecap="round"/>
          </svg>
          {{ loading ? "刷新中" : "刷新" }}
        </button>
      </div>
    </header>

    <p v-if="errorText" class="ds-status is-error">{{ errorText }}</p>

    <div class="ds-card-grid-4">
      <StatusCard
        v-for="(card, i) in cards"
        :key="card.title"
        :title="card.title"
        :value="card.value"
        :hint="card.hint"
        :detail="card.detail"
        :class="`card-entrance card-entrance-${i} card-${card.variant}`"
      />
    </div>

    <section class="overview-grid">
      <article class="ds-panel ds-panel-padding">
        <div class="ds-section-head">
          <div class="ds-section-title">
            <p class="ds-eyebrow">Runtime Details</p>
            <h2>运行时状态</h2>
          </div>
          <div class="ds-chip-row">
            <span class="ds-chip">runtime</span>
            <span class="ds-chip">gateway</span>
            <span class="ds-chip">backend</span>
          </div>
        </div>

        <div class="ds-detail-grid">
          <div class="detail-item">
            <span>Loaded Plugins</span>
            <strong>{{ status.loaded_plugins?.length ?? 0 }}</strong>
          </div>
          <div class="detail-item">
            <span>Active Modes</span>
            <strong>{{ backend.active_modes?.length ?? 0 }}</strong>
          </div>
          <div class="detail-item">
            <span>Loading</span>
            <strong>{{ loading ? "yes" : "no" }}</strong>
          </div>
        </div>
      </article>

      <LogStreamPanel
        title="日志预览"
        :limit="80"
        :poll-interval-ms="2500"
        :show-controls="false"
        :show-details="false"
        :show-run-details="false"
        height="320px"
      />
    </section>
  </section>
</template>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 1fr);
  gap: 16px;
}

.detail-item {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: var(--panel-strong);
}

.detail-item span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.detail-item strong {
  display: block;
  margin-top: 10px;
  font-size: 22px;
  color: var(--heading-strong);
  letter-spacing: -0.03em;
}

@media (max-width: 1180px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
}

/* ── Entrance animations ── */
.ds-hero {
  opacity: 0;
  transform: translateY(-12px);
  animation: hero-in 400ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.card-entrance {
  opacity: 0;
  transform: translateY(16px);
  animation: card-in 350ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.card-entrance-0 { animation-delay: 80ms; }
.card-entrance-1 { animation-delay: 160ms; }
.card-entrance-2 { animation-delay: 240ms; }
.card-entrance-3 { animation-delay: 320ms; }

.overview-grid > :first-child {
  opacity: 0;
  transform: translateY(12px);
  animation: card-in 380ms cubic-bezier(0.25, 1, 0.5, 1) 400ms forwards;
}

.overview-grid > :last-child {
  opacity: 0;
  transform: translateY(12px);
  animation: card-in 380ms cubic-bezier(0.25, 1, 0.5, 1) 480ms forwards;
}

@keyframes hero-in {
  to { opacity: 1; transform: translateY(0); }
}

@keyframes card-in {
  to { opacity: 1; transform: translateY(0); }
}

/* Respect reduced motion */
@media (prefers-reduced-motion: reduce) {
  .ds-hero,
  .card-entrance,
  .overview-grid > * {
    opacity: 1;
    transform: none;
    animation: none;
  }
}

/* ── Spin icon ── */
.spin-icon {
  flex-shrink: 0;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .spin-icon {
    animation: none;
  }
}

/* ── Semantic card variants ── */
.card-active .value {
  color: var(--success);
}

.card-connected .value {
  color: var(--success);
}

.card-disconnected .value {
  color: var(--muted);
}

.card-ready .value {
  color: var(--success);
}

.card-unavailable .value {
  color: var(--muted);
}

.card-warm .value {
  color: var(--warning);
}
</style>
