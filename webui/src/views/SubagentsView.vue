<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type ExecutorItem = {
  executor_id?: string
  agent_id?: string
  display_name?: string
  description?: string
}

const items = ref<ExecutorItem[]>(peekCachedGet<ExecutorItem[]>('/api/subagents/executors') ?? [])

onMounted(() => {
  void apiGet<ExecutorItem[]>('/api/subagents/executors').then((payload) => {
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
            <h2>Executor 注册表</h2>
            <p class="ds-summary">当前先做可视化，不承诺 enable / disable 的持久配置。</p>
          </div>
        </div>
      </div>

      <div class="ds-list">
        <article v-for="item in items" :key="item.executor_id || item.agent_id" class="ds-list-item ds-list-item-padding executor-item">
          <strong>{{ item.display_name || item.executor_id || item.agent_id }}</strong>
          <p class="ds-summary compact">{{ item.description || '暂无说明' }}</p>
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
