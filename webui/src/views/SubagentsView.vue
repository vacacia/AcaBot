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

onMounted(() => {
  void apiGet<SubagentItem[]>("/api/subagents").then((payload) => {
    items.value = payload
  })
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
            <p class="ds-summary">这里展示当前文件系统 catalog 里可发现的子代理定义。</p>
          </div>
        </div>
      </div>

      <div class="ds-list">
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
