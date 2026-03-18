<script setup lang="ts">
import { ref } from "vue"

import LogStreamPanel from "../components/LogStreamPanel.vue"

const denseMode = ref(false)
const displayLimit = ref(600)
</script>

<template>
  <section class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">Logs</p>
        <h1>日志台</h1>
        <p class="summary">首页只留预览。这里是信息量拉满的独立日志页。</p>
      </div>
      <div class="actions">
        <label class="toggle">
          <input v-model="denseMode" type="checkbox" />
          <span>{{ denseMode ? "紧凑模式" : "面板模式" }}</span>
        </label>
        <label class="limit">
          <span>显示条数</span>
          <select v-model="displayLimit">
            <option :value="200">200</option>
            <option :value="400">400</option>
            <option :value="600">600</option>
            <option :value="1000">1000</option>
          </select>
        </label>
      </div>
    </header>

    <LogStreamPanel
      title="运行时日志"
      summary="支持过滤、自动刷新和自动跟随。紧凑模式更接近 tail，面板模式更适合运维查看。"
      :limit="displayLimit"
      :poll-interval-ms="800"
      :dense="denseMode"
      height="calc(100vh - 220px)"
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
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 22px;
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
.summary {
  margin: 0;
}

.summary {
  margin-top: 8px;
  color: var(--muted);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
}

.toggle,
.limit {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 14px;
}

.limit select {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 8px 10px;
}

@media (max-width: 900px) {
  .hero {
    flex-direction: column;
  }

  .actions {
    justify-content: stretch;
  }
}
</style>
