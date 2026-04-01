<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type SubagentItem = {
  subagent_id?: string
  subagent_name?: string
  description?: string
  source?: string
  host_subagent_file_path?: string
  tools?: string[]
  effective?: boolean
}

const items = ref<SubagentItem[]>(peekCachedGet<SubagentItem[]>("/api/subagents") ?? [])
const loading = ref(true)
const errorText = ref("")

onMounted(async () => {
  try {
    items.value = await apiGet<SubagentItem[]>("/api/subagents")
  } catch (err: any) {
    errorText.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="ds-page">
    <article class="ds-panel ds-panel-padding">
      <div class="ds-section-head compact-head">
        <div class="ds-section-title">
          <div>
            <p class="ds-eyebrow">Subagents</p>
            <h2>Catalog 清单</h2>
          </div>
        </div>
      </div>

      <p v-if="loading" class="ds-status">加载中…</p>
      <p v-else-if="errorText" class="ds-status is-error">{{ errorText }}</p>

      <div v-else class="ds-list">
        <article
          v-for="item in items"
          :key="item.subagent_id || item.subagent_name || 'unnamed-subagent'"
          class="ds-list-item ds-list-item-padding executor-item"
        >
          <strong>{{ item.subagent_name || "unnamed-subagent" }}</strong>
          <p class="ds-summary compact">{{ item.description || '暂无说明' }}</p>
          <p class="ds-summary compact">id={{ item.subagent_id || "-" }}</p>
          <p class="ds-summary compact">
            source={{ item.source || "-" }} effective={{ item.effective ? "yes" : "no" }}
          </p>
          <p class="ds-summary compact">path={{ item.host_subagent_file_path || "-" }}</p>
          <p class="ds-summary compact">tools={{ (item.tools || []).join(", ") || "-" }}</p>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.compact-head {
  margin-bottom: 14px;
}

.executor-item {
  display: grid;
  gap: 6px;
}
</style>
