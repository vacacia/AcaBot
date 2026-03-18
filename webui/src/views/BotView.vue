<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet } from "../lib/api"

type ProfileItem = {
  agent_id: string
  name: string
  prompt_ref: string
  enabled_tools: string[]
  skill_assignments: Array<{ skill_name: string }>
}

type Catalog = {
  bot: {
    agent_id: string
  }
}

const profile = ref<ProfileItem | null>(null)

onMounted(() => {
  void (async () => {
    const [catalog, profiles] = await Promise.all([
      apiGet<Catalog>("/api/ui/catalog"),
      apiGet<ProfileItem[]>("/api/profiles"),
    ])
    profile.value = profiles.find((item) => item.agent_id === catalog.bot.agent_id) ?? null
  })()
})
</script>

<template>
  <section class="panel">
    <p class="eyebrow">Bot</p>
    <h1>默认 Bot</h1>
    <p class="summary">这一页先展示默认 Bot 的 AI、Tools 和 Skills。下一步再把编辑动作迁过来。</p>
    <div v-if="profile" class="grid">
      <article class="card">
        <h2>{{ profile.name }}</h2>
        <p>agent_id: {{ profile.agent_id }}</p>
        <p>prompt: {{ profile.prompt_ref || "未设置" }}</p>
      </article>
      <article class="card">
        <h2>Tools</h2>
        <p>{{ profile.enabled_tools.join(", ") || "未设置" }}</p>
      </article>
      <article class="card">
        <h2>Skills</h2>
        <p>{{ profile.skill_assignments.map((item) => item.skill_name).join(", ") || "未设置" }}</p>
      </article>
    </div>
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
.card p {
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}

.card {
  padding: 16px;
}
</style>
