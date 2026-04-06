<script setup lang="ts">
import { ref } from "vue"

import CustomSelect from "../components/CustomSelect.vue"
import LogStreamPanel from "../components/LogStreamPanel.vue"
import RunDetailPanel from "../components/RunDetailPanel.vue"

const denseMode = ref(false)
const displayLimit = ref("600")
const selectedRunId = ref("")

function openRunDetails(runId: string): void {
  selectedRunId.value = runId
}

function closeRunDetails(): void {
  selectedRunId.value = ""
}

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

    <div class="logs-layout logs-layout-entrance">
      <LogStreamPanel
        title="运行时日志"
        summary="支持过滤、自动刷新和自动跟随。紧凑模式更接近 tail，面板模式更适合运维查看。"
        :limit="Number(displayLimit)"
        :poll-interval-ms="800"
        :dense="denseMode"
        :show-details="true"
        :show-run-details="true"
        height="calc(100vh - 220px)"
        @view-run="openRunDetails"
      />
    </div>
    <div v-if="selectedRunId" class="run-detail-backdrop" @click="closeRunDetails"></div>
    <RunDetailPanel
      v-if="selectedRunId"
      class="run-detail-drawer"
      :run-id="selectedRunId"
      @close="closeRunDetails"
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
  border-radius: 18px;
  /* 确保下拉菜单不被裁剪 */
  overflow: visible;
}

.limit-row {
  min-width: 220px;
}

.logs-layout {
  min-width: 0;
}

.run-detail-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(12, 12, 14, 0.36);
  backdrop-filter: blur(2px);
  z-index: 40;
}

:deep(.run-detail-drawer) {
  position: fixed;
  top: 24px;
  right: 24px;
  bottom: 24px;
  width: min(760px, calc(100vw - 48px));
  overflow: auto;
  z-index: 41;
  box-shadow: 0 24px 72px rgba(12, 12, 14, 0.24);
}

@media (max-width: 900px) {
  .actions-wrap {
    justify-content: stretch;
  }

  :deep(.run-detail-drawer) {
    top: 12px;
    right: 12px;
    bottom: 12px;
    left: 12px;
    width: auto;
  }
}

/* ── Entrance animation ── */
.ds-hero {
  opacity: 0;
  transform: translateY(-10px);
  animation: lv-hero-in 380ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.logs-layout-entrance {
  opacity: 0;
  transform: translateY(10px);
  animation: lv-layout-in 400ms cubic-bezier(0.25, 1, 0.5, 1) 120ms forwards;
}

@keyframes lv-hero-in {
  to { opacity: 1; transform: translateY(0); }
}

@keyframes lv-layout-in {
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .ds-hero,
  .logs-layout-entrance {
    opacity: 1;
    transform: none;
    animation: none;
  }
}
</style>
