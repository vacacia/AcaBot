<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type SkillItem = {
  skill_name: string
  display_name?: string
  description?: string
}

const items = ref<SkillItem[]>(peekCachedGet<SkillItem[]>('/api/skills') ?? [])

onMounted(() => {
  void apiGet<SkillItem[]>('/api/skills').then((payload) => {
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
            <p class="ds-eyebrow">Skills</p>
            <h2>已安装 Skills</h2>
            <p class="ds-summary">统一展示技能名称、说明和当前安装状态，先把目录页和设计系统对齐。</p>
          </div>
        </div>
      </div>

      <div class="ds-list">
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
}
</style>
