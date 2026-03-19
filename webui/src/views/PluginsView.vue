<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPost, apiPut, peekCachedGet } from "../lib/api"

type PluginConfig = {
  path: string
  enabled: boolean
  name?: string
  display_name?: string
}

const items = ref<PluginConfig[]>(peekCachedGet<{ items: PluginConfig[] }>("/api/system/plugins/config")?.items ?? [])
const saveMessage = ref("")
const errorMessage = ref("")

async function load(): Promise<void> {
  const payload = await apiGet<{ items: PluginConfig[] }>("/api/system/plugins/config")
  items.value = payload.items ?? []
}

async function save(): Promise<void> {
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    await apiPut<{ items: PluginConfig[] }>("/api/system/plugins/config", { items: items.value })
    await load()
    saveMessage.value = "已保存"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

async function reloadPlugins(): Promise<void> {
  saveMessage.value = "重载中..."
  errorMessage.value = ""
  try {
    await apiPost("/api/plugins/reload", { plugin_names: [] })
    await load()
    saveMessage.value = "已重载"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "重载失败"
  }
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
      <div class="actions">
        <button type="button" @click="void reloadPlugins()">重载</button>
        <button type="button" @click="void save()">保存插件配置</button>
      </div>
    </div>
    <p v-if="saveMessage" class="status ok">{{ saveMessage }}</p>
    <p v-if="errorMessage" class="status error">{{ errorMessage }}</p>
    <label v-for="item in items" :key="item.path" class="item">
      <input v-model="item.enabled" type="checkbox" />
      <div>
        <strong>{{ item.display_name || item.name || item.path }}</strong>
        <p>{{ item.name || "未命名插件" }}</p>
        <p>{{ item.path }}</p>
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

.actions {
  display: flex;
  gap: 10px;
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

.status {
  margin: 0 0 16px;
  padding: 10px 12px;
  border-radius: 12px;
}

.status.ok {
  background: rgba(17, 120, 74, 0.08);
  color: var(--success);
}

.status.error {
  background: rgba(186, 41, 41, 0.08);
  color: var(--danger);
}

.item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-white);
  margin-bottom: 12px;
}

p {
  color: var(--muted);
}
</style>
