<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type SkillItem = {
  skill_name: string
  display_name?: string
  description?: string
}

const items = ref<SkillItem[]>(peekCachedGet<SkillItem[]>('/api/skills') ?? [])
const loading = ref(true)
const errorText = ref("")

onMounted(async () => {
  try {
    items.value = await apiGet<SkillItem[]>('/api/skills')
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
            <p class="ds-eyebrow">Skills</p>
            <h2>已安装 Skills</h2>
          </div>
        </div>
      </div>

      <p v-if="loading" class="ds-status">加载中…</p>
      <p v-else-if="errorText" class="ds-status is-error">{{ errorText }}</p>

      <div v-else class="ds-list">
        <article v-for="item in items" :key="item.skill_name" class="ds-list-item ds-list-item-padding skill-item">
          <strong>{{ item.display_name || item.skill_name }}</strong>
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

.skill-item {
  display: grid;
  gap: 6px;
  opacity: 0;
  transform: translateY(8px);
  animation: skill-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.skill-item:nth-child(1) { animation-delay: 40ms; }
.skill-item:nth-child(2) { animation-delay: 80ms; }
.skill-item:nth-child(3) { animation-delay: 120ms; }
.skill-item:nth-child(4) { animation-delay: 160ms; }
.skill-item:nth-child(5) { animation-delay: 200ms; }
.skill-item:nth-child(n+6) { animation-delay: 240ms; }

@keyframes skill-in {
  to { opacity: 1; transform: translateY(0); }
}

.skill-item:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
  transform: translateX(3px);
  transition: border-color 150ms cubic-bezier(0.25, 1, 0.5, 1),
    background 150ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.skill-item:active {
  transform: translateX(1px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .skill-item {
    opacity: 1;
    transform: none;
    animation: none;
  }
  .skill-item:hover {
    transform: none;
  }
}
</style>
