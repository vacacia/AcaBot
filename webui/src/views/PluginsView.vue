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
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Plugins</p>
        <h1>插件开关</h1>
        <p class="ds-summary">统一在这里查看插件状态、保存配置和触发重载。</p>
      </div>
      <div class="ds-actions">
        <button class="ds-secondary-button" type="button" @click="void reloadPlugins()">重载</button>
        <button class="ds-primary-button" type="button" @click="void save()">保存插件配置</button>
      </div>
    </header>

    <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
    <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>

    <section class="ds-list">
      <label v-for="item in items" :key="item.path" class="ds-list-item ds-list-item-padding item">
        <input v-model="item.enabled" type="checkbox" />
        <div>
          <strong>{{ item.display_name || item.name || item.path }}</strong>
          <p class="ds-summary compact">{{ item.name || "未命名插件" }}</p>
          <p class="ds-kicker ds-mono compact">{{ item.path }}</p>
        </div>
      </label>
    </section>
  </section>
</template>

<style scoped>
.item {
  display: grid;
  grid-template-columns: 20px 1fr;
  gap: 10px;
}

.compact {
  margin-top: 4px;
}
</style>
