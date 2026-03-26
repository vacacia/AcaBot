<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import LogStreamPanel from "../components/LogStreamPanel.vue"
import StatusCard from "../components/StatusCard.vue"
import { apiGet, peekCachedGet } from "../lib/api"

type RuntimeStatus = {
  loaded_plugins?: string[]
  active_runs?: Array<unknown>
}

type GatewayStatus = {
  connected?: boolean
}

type BackendStatus = {
  configured?: boolean
  active_modes?: string[]
}

const status = ref<RuntimeStatus>(peekCachedGet<RuntimeStatus>("/api/status") ?? {})
const gateway = ref<GatewayStatus>(peekCachedGet<GatewayStatus>("/api/gateway/status") ?? {})
const backend = ref<BackendStatus>(peekCachedGet<BackendStatus>("/api/backend/status") ?? {})
const errorText = ref("")
const loading = ref(
  !peekCachedGet<RuntimeStatus>("/api/status")
  || !peekCachedGet<GatewayStatus>("/api/gateway/status")
  || !peekCachedGet<BackendStatus>("/api/backend/status")
)

const cards = computed(() => [
  {
    title: "Runtime",
    value: "在线",
    hint: `${status.value.loaded_plugins?.length ?? 0} 个插件已装载`,
  },
  {
    title: "Gateway",
    value: gateway.value.connected ? "Connected" : "Disconnected",
    hint: "NapCat 连接状态",
  },
  {
    title: "Backend",
    value: backend.value.configured ? "Ready" : "Unavailable",
    hint: `活跃模式 ${backend.value.active_modes?.length ?? 0}`,
  },
  {
    title: "Runs",
    value: String(status.value.active_runs?.length ?? 0),
    hint: "当前活跃运行数",
  },
])

async function load(): Promise<void> {
  loading.value = true
  errorText.value = ""
  try {
    const [nextStatus, nextGateway, nextBackend] = await Promise.all([
      apiGet<RuntimeStatus>("/api/status"),
      apiGet<GatewayStatus>("/api/gateway/status"),
      apiGet<BackendStatus>("/api/backend/status"),
    ])
    status.value = nextStatus
    gateway.value = nextGateway
    backend.value = nextBackend
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : "首页加载失败"
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="page">
    <header class="hero glass-panel">
      <div class="hero-copy">
        <p class="eyebrow">AcaBot / Overview</p>
        <h1>先看 AcaBot 现在稳不稳</h1>
        <p class="summary">
          这一页先回答最核心的问题：运行态是否健康、Gateway 是否在线、Backend 是否已接线，以及最近日志里有没有异常波动。
        </p>
      </div>
      <div class="hero-actions">
        <button class="ghost" type="button">查看控制面说明</button>
        <button class="primary" type="button" @click="void load()">刷新首页</button>
      </div>
    </header>

    <div v-if="errorText" class="error-banner glass-panel">{{ errorText }}</div>

    <div class="card-grid">
      <StatusCard
        v-for="card in cards"
        :key="card.title"
        :title="card.title"
        :value="card.value"
        :hint="card.hint"
      />
    </div>

    <section class="overview-grid">
      <article class="section-card glass-panel">
        <div class="section-head">
          <div>
            <p class="eyebrow">控制面气质</p>
            <h2>首页多组件样式</h2>
            <p class="section-copy">
              先把主页的卡片、按钮、说明文字和日志视图统一到玻璃风语言，再逐步铺到其余配置页。
            </p>
          </div>
          <div class="chips">
            <span class="chip">runtime</span>
            <span class="chip">gateway</span>
            <span class="chip">backend</span>
          </div>
        </div>

        <div class="detail-grid">
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
        summary="这里只留最近一小段，方便扫一眼。要盯日志，直接去独立日志页。"
        :limit="80"
        :poll-interval-ms="1000"
        :show-controls="false"
        height="320px"
      />
    </section>
  </section>
</template>

<style scoped>
.page {
  display: grid;
  gap: 16px;
}

.glass-panel {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: 30px;
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--panel);
  backdrop-filter: var(--blur-card);
  -webkit-backdrop-filter: var(--blur-card);
  box-shadow: var(--shadow-card);
}

.glass-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background:
    linear-gradient(180deg, var(--glass-sheen-top) 0%, var(--glass-sheen-mid) 18%, rgba(255, 255, 255, 0) 40%),
    linear-gradient(120deg, rgba(255, 255, 255, 0.03) 0%, rgba(255, 255, 255, 0.012) 22%, rgba(255, 255, 255, 0) 48%);
  opacity: 0.58;
}

.glass-panel > * {
  position: relative;
  z-index: 1;
}

.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px 26px;
}

.hero-copy h1,
.section-head h2 {
  margin: 0;
  color: var(--heading-strong);
}

.hero-copy h1 {
  font-size: clamp(30px, 2.8vw, 46px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.summary,
.section-copy {
  margin: 10px 0 0;
  color: var(--muted);
  line-height: 1.65;
}

.hero-actions {
  display: flex;
  gap: 10px;
}

button {
  cursor: pointer;
}

.ghost,
.primary {
  padding: 12px 14px;
  border-radius: 16px;
}

.ghost {
  border: 1px solid var(--line);
  background: var(--panel-strong);
  color: var(--text);
}

.primary {
  border: 0;
  background: linear-gradient(135deg, var(--button-primary-start) 0%, var(--button-primary-end) 100%);
  color: #fff;
  box-shadow: 0 16px 26px var(--button-shadow-color);
}

.error-banner {
  padding: 14px 16px;
  color: var(--danger);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 1fr);
  gap: 16px;
}

.section-card {
  padding: 20px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-content: flex-start;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
  background: var(--accent-soft);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
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
  .card-grid,
  .detail-grid,
  .overview-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .hero,
  .section-head,
  .hero-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .hero {
    padding: 20px 18px;
  }
}
</style>
