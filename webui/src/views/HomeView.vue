<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import StatusCard from "../components/StatusCard.vue"
import { apiGet } from "../lib/api"

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

type LogItem = {
  timestamp: number
  level: string
  logger: string
  message: string
}

const status = ref<RuntimeStatus>({})
const gateway = ref<GatewayStatus>({})
const backend = ref<BackendStatus>({})
const logs = ref<LogItem[]>([])
const level = ref("")
const keyword = ref("")
const errorText = ref("")
const loading = ref(false)

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
    const [nextStatus, nextGateway, nextBackend, logPayload] = await Promise.all([
      apiGet<RuntimeStatus>("/api/status"),
      apiGet<GatewayStatus>("/api/gateway/status"),
      apiGet<BackendStatus>("/api/backend/status"),
      apiGet<{ items: LogItem[] }>(
        `/api/system/logs?level=${encodeURIComponent(level.value)}&keyword=${encodeURIComponent(keyword.value)}&limit=200`,
      ),
    ])
    status.value = nextStatus
    gateway.value = nextGateway
    backend.value = nextBackend
    logs.value = logPayload.items ?? []
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
    <header class="hero">
      <div>
        <p class="eyebrow">首页</p>
        <h1>先看 AcaBot 现在稳不稳</h1>
        <p class="summary">这一页只回答运行状态。上面看系统摘要，下面看实时日志。</p>
      </div>
      <button class="primary" type="button" @click="void load()">刷新首页</button>
    </header>

    <div class="card-grid">
      <StatusCard
        v-for="card in cards"
        :key="card.title"
        :title="card.title"
        :value="card.value"
        :hint="card.hint"
      />
    </div>

    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>日志流</h2>
          <p>默认全量显示，可按等级和关键词过滤。</p>
        </div>
        <div class="filters">
          <select v-model="level">
            <option value="">全部等级</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
          <input v-model="keyword" type="text" placeholder="关键词过滤" />
          <button type="button" @click="void load()">应用</button>
        </div>
      </div>

      <div v-if="errorText" class="error">{{ errorText }}</div>
      <div v-else-if="loading" class="empty">正在加载首页数据…</div>
      <div v-else-if="logs.length === 0" class="empty">暂无日志</div>
      <div v-else class="log-list">
        <article v-for="item in logs" :key="`${item.timestamp}-${item.logger}-${item.message}`" class="log-line">
          <div class="log-meta">
            <span>{{ new Date(item.timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false }) }}</span>
            <span>{{ item.level }}</span>
            <span>{{ item.logger }}</span>
          </div>
          <div class="log-message">{{ item.message }}</div>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero,
.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow);
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 26px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
}

.summary,
.panel-header p {
  margin: 8px 0 0;
  color: var(--muted);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.panel {
  padding: 18px 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.filters {
  display: flex;
  gap: 10px;
  align-items: center;
}

select,
input,
button {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
}

button {
  cursor: pointer;
}

.primary {
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  color: #fff;
  border: 0;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.log-line {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.68);
  padding: 12px 14px;
}

.log-meta {
  display: flex;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
}

.log-message {
  margin-top: 6px;
  line-height: 1.6;
}

.error,
.empty {
  padding: 18px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.64);
  color: var(--muted);
}
</style>
