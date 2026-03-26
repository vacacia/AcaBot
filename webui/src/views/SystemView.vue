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
  <section class="ds-page">
    <article class="ds-panel ds-panel-padding">
      <div class="ds-section-head">
        <div class="ds-section-title">
          <div>
            <p class="ds-eyebrow">System</p>
            <h2>系统信息</h2>
            <p class="ds-summary">这里主要看运行环境、网关状态与 backend 会话绑定位置。</p>
          </div>
        </div>
      </div>
      <div class="ds-card-grid-3">
        <StatusCard title="Storage" :value="meta?.storage_mode || '-'" :hint="meta?.config_path || '-'" />
        <StatusCard title="Gateway" :value="gateway.connected ? 'Connected' : 'Disconnected'" hint="当前网关状态" />
        <StatusCard title="Backend" :value="backend.configured ? 'Ready' : 'Unavailable'" :hint="backend.session_path || '-'" />
      </div>
    </article>
  </section>
</template>
