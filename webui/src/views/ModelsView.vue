<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet } from "../lib/api"

type ProviderItem = {
  provider_id: string
  kind: string
  base_url?: string
}

type PresetItem = {
  preset_id: string
  provider_id: string
  model: string
  context_window?: number
}

const providers = ref<ProviderItem[]>([])
const presets = ref<PresetItem[]>([])

onMounted(() => {
  void (async () => {
    const [nextProviders, nextPresets] = await Promise.all([
      apiGet<ProviderItem[]>("/api/models/providers"),
      apiGet<PresetItem[]>("/api/models/presets"),
    ])
    providers.value = nextProviders
    presets.value = nextPresets
  })()
})
</script>

<template>
  <section class="page">
    <article class="panel">
      <p class="eyebrow">Models</p>
      <h1>Providers</h1>
      <div class="grid">
        <article v-for="item in providers" :key="item.provider_id" class="card">
          <h2>{{ item.provider_id }}</h2>
          <p>{{ item.kind }}</p>
          <p>{{ item.base_url || "未设置 base_url" }}</p>
        </article>
      </div>
    </article>

    <article class="panel">
      <h1>Presets</h1>
      <div class="grid">
        <article v-for="item in presets" :key="item.preset_id" class="card">
          <h2>{{ item.preset_id }}</h2>
          <p>{{ item.model }}</p>
          <p>provider: {{ item.provider_id }}</p>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

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

.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.card {
  padding: 16px;
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
