<script setup lang="ts">
import { onMounted, ref } from "vue"
import StatusCard from "../components/StatusCard.vue"
import { apiGet, peekCachedGet } from "../lib/api"

type MetaPayload = {
  storage_mode: string
  config_path: string
}

type GatewayStatus = {
  connected?: boolean
}

type BackendStatus = {
  configured?: boolean
  session_path?: string
}

const meta = ref<MetaPayload | null>(peekCachedGet<MetaPayload>("/api/meta"))
const gateway = ref<GatewayStatus>(peekCachedGet<GatewayStatus>("/api/gateway/status") ?? {})
const backend = ref<BackendStatus>(peekCachedGet<BackendStatus>("/api/backend/status") ?? {})

onMounted(() => {
  void (async () => {
    const [nextMeta, nextGateway, nextBackend] = await Promise.all([
      apiGet<MetaPayload>("/api/meta"),
      apiGet<GatewayStatus>("/api/gateway/status"),
      apiGet<BackendStatus>("/api/backend/status"),
    ])
    meta.value = nextMeta
    gateway.value = nextGateway
    backend.value = nextBackend
  })()
})
</script>

<template>
  <section class="page">
    <article class="panel">
      <p class="eyebrow">System</p>
      <h1>系统信息</h1>
      <div class="grid">
        <StatusCard title="Storage" :value="meta?.storage_mode || '-'" :hint="meta?.config_path || '-'" />
        <StatusCard title="Gateway" :value="gateway.connected ? 'Connected' : 'Disconnected'" hint="当前网关状态" />
        <StatusCard title="Backend" :value="backend.configured ? 'Ready' : 'Unavailable'" :hint="backend.session_path || '-'" />
      </div>
    </article>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 22px 24px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
