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

    <LogStreamPanel
      title="日志预览"
      summary="这里只留最近一小段，方便扫一眼。要盯日志，直接去独立日志页。"
      :limit="80"
      :poll-interval-ms="1000"
      :show-controls="false"
      height="260px"
    />
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero {
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
</style>
