<script setup lang="ts">
import { ref } from "vue"

import LogStreamPanel from "../components/LogStreamPanel.vue"

const denseMode = ref(false)
const displayLimit = ref(600)
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Logs</p>
        <h1>日志台</h1>
        <p class="ds-summary">首页只留预览。这里是信息量拉满的独立日志页。</p>
      </div>
      <div class="ds-actions actions-wrap">
        <label class="toggle-row ds-surface ds-card-padding-sm">
          <input v-model="denseMode" type="checkbox" />
          <span>{{ denseMode ? "紧凑模式" : "面板模式" }}</span>
        </label>
        <label class="limit-row ds-surface ds-card-padding-sm">
          <span>显示条数</span>
          <select class="ds-select" v-model="displayLimit">
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
.actions-wrap {
  justify-content: flex-end;
}

.toggle-row,
.limit-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
}

.toggle-row {
  border-radius: 18px;
}

.limit-row {
  min-width: 220px;
  border-radius: 18px;
}

.limit-row .ds-select {
  min-width: 110px;
}

@media (max-width: 900px) {
  .actions-wrap {
    justify-content: stretch;
  }
}
</style>
