<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPut } from "../lib/api"

type PluginConfig = {
  path: string
  enabled: boolean
}

const items = ref<PluginConfig[]>([])

async function load(): Promise<void> {
  const payload = await apiGet<{ items: PluginConfig[] }>("/api/system/plugins/config")
  items.value = payload.items ?? []
}

async function save(): Promise<void> {
  await apiPut<{ items: PluginConfig[] }>("/api/system/plugins/config", { items: items.value })
  await load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="panel">
    <div class="header">
      <div>
        <p class="eyebrow">Plugins</p>
        <h1>插件开关</h1>
      </div>
      <button type="button" @click="void save()">保存插件配置</button>
    </div>
    <label v-for="item in items" :key="item.path" class="item">
      <input v-model="item.enabled" type="checkbox" />
      <div>
        <strong>{{ item.path }}</strong>
        <p>{{ item.enabled ? "enabled" : "disabled" }}</p>
      </div>
    </label>
  </section>
</template>

<style scoped>
.panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: var(--shadow);
  padding: 22px 24px;
}

.header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
}

button {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel-strong);
  color: var(--text);
  padding: 10px 12px;
  cursor: pointer;
}

.item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.7);
  margin-bottom: 12px;
}

p {
  color: var(--muted);
}
</style>
