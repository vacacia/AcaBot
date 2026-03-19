<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type ExecutorItem = {
  executor_id?: string
  agent_id?: string
  display_name?: string
  description?: string
}

const items = ref<ExecutorItem[]>(peekCachedGet<ExecutorItem[]>("/api/subagents/executors") ?? [])

onMounted(() => {
  void apiGet<ExecutorItem[]>("/api/subagents/executors").then((payload) => {
    items.value = payload
  })
})
</script>

<template>
  <section class="panel">
    <p class="eyebrow">Subagents</p>
    <h1>Executor 注册表</h1>
    <p class="summary">当前先做可视化，不承诺 enable / disable 的持久配置。</p>
    <article v-for="item in items" :key="item.executor_id || item.agent_id" class="card">
      <h2>{{ item.display_name || item.executor_id || item.agent_id }}</h2>
      <p>{{ item.description || "暂无说明" }}</p>
    </article>
  </section>
</template>

<style scoped>
.panel,
.card {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
}

.panel {
  padding: 22px 24px;
}

.card {
  padding: 16px;
  margin-top: 14px;
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
p {
  color: var(--muted);
}
</style>
