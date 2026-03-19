<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type SkillItem = {
  skill_name: string
  display_name?: string
  description?: string
}

const items = ref<SkillItem[]>(peekCachedGet<SkillItem[]>("/api/skills") ?? [])

onMounted(() => {
  void apiGet<SkillItem[]>("/api/skills").then((payload) => {
    items.value = payload
  })
})
</script>

<template>
  <section class="panel">
    <p class="eyebrow">Skills</p>
    <h1>已安装 Skills</h1>
    <article v-for="item in items" :key="item.skill_name" class="card">
      <h2>{{ item.display_name || item.skill_name }}</h2>
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

p {
  color: var(--muted);
}
</style>
