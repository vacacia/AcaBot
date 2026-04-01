<script setup lang="ts">
import { ref } from "vue"

import CustomSelect from "../components/CustomSelect.vue"
import LogStreamPanel from "../components/LogStreamPanel.vue"

const denseMode = ref(false)
const displayLimit = ref("600")

const limitOptions = [
  { value: "200", label: "200" },
  { value: "400", label: "400" },
  { value: "600", label: "600" },
  { value: "1000", label: "1000" },
]
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Logs</p>
        <h1>日志台</h1>
      </div>
      <div class="ds-actions actions-wrap">
        <label class="toggle-row ds-surface ds-card-padding-sm">
          <input v-model="denseMode" type="checkbox" />
          <span>{{ denseMode ? "紧凑模式" : "面板模式" }}</span>
        </label>
        <label class="limit-row ds-surface ds-card-padding-sm">
          <span>显示条数</span>
          <CustomSelect v-model="displayLimit" :options="limitOptions" />
        </label>
      </div>
    </header>

    <LogStreamPanel
      title="运行时日志"
      summary="支持过滤、自动刷新和自动跟随。紧凑模式更接近 tail，面板模式更适合运维查看。"
      :limit="Number(displayLimit)"
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

@media (max-width: 900px) {
  .actions-wrap {
    justify-content: stretch;
  }
}
</style>
