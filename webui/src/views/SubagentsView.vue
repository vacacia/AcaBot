<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, peekCachedGet } from "../lib/api"

type SubagentItem = {
  subagent_id?: string
  subagent_name?: string
  description?: string
  source?: string
  host_subagent_file_path?: string
  tools?: string[]
  effective?: boolean
}

const items = ref<SubagentItem[]>(peekCachedGet<SubagentItem[]>("/api/subagents") ?? [])
const loading = ref(true)
const errorText = ref("")

onMounted(async () => {
  try {
    items.value = await apiGet<SubagentItem[]>("/api/subagents")
  } catch (err: any) {
    errorText.value = err?.message || String(err)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Config / Subagents</p>
        <h1>子代理</h1>
      </div>
    </header>

    <article class="ds-panel ds-panel-padding">

      <p v-if="loading" class="ds-status">加载中…</p>
      <p v-else-if="errorText" class="ds-status is-error">{{ errorText }}</p>

      <div v-else class="ds-list">
        <article
          v-for="item in items"
          :key="item.subagent_id || item.subagent_name || 'unnamed-subagent'"
          class="subagent-item"
        >
          <div class="subagent-head">
            <div class="subagent-identity">
              <strong class="subagent-name">{{ item.subagent_name || "unnamed-subagent" }}</strong>
              <span class="subagent-badge" :class="item.effective ? 'is-active' : 'is-inactive'">
                {{ item.effective ? "active" : "inactive" }}
              </span>
            </div>
            <p class="subagent-desc">{{ item.description || '暂无说明' }}</p>
          </div>

          <div class="subagent-meta">
            <span v-if="item.subagent_id" class="meta-chip">
              <span class="meta-key">id</span>
              <span class="meta-val">{{ item.subagent_id }}</span>
            </span>
            <span v-if="item.source" class="meta-chip">
              <span class="meta-key">source</span>
              <span class="meta-val">{{ item.source }}</span>
            </span>
            <span v-if="item.host_subagent_file_path" class="meta-chip meta-chip-path">
              <span class="meta-key">path</span>
              <span class="meta-val">{{ item.host_subagent_file_path }}</span>
            </span>
          </div>

          <div v-if="item.tools?.length" class="subagent-tools">
            <span class="tools-label">tools</span>
            <div class="tools-list">
              <span v-for="tool in item.tools" :key="tool" class="ds-chip">{{ tool }}</span>
            </div>
          </div>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.subagent-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel);
  position: relative;
  transition: border-color 160ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 160ms cubic-bezier(0.25, 1, 0.5, 1),
    box-shadow 160ms cubic-bezier(0.25, 1, 0.5, 1);
}

.subagent-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 16px;
  bottom: 16px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
  opacity: 0;
  transition: opacity 160ms;
}

.subagent-item:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--panel-line-soft));
  transform: translateX(2px);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.subagent-item:hover::before {
  opacity: 1;
}

.subagent-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subagent-identity {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subagent-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--heading-strong);
}

.subagent-badge {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.subagent-badge.is-active {
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
}

.subagent-badge.is-inactive {
  background: var(--panel-line-soft);
  color: var(--muted);
}

.subagent-desc {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
  line-height: 1.5;
}

.subagent-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--panel-strong);
  border: 1px solid var(--panel-line-soft);
  font-size: 11px;
}

.meta-key {
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 10px;
}

.meta-val {
  color: var(--text);
  font-family: "JetBrains Mono", "SF Mono", monospace;
  font-size: 11px;
}

.meta-chip-path {
  max-width: 200px;
}

.meta-chip-path .meta-val {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subagent-tools {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.tools-label {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding-top: 3px;
}

.tools-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ds-chip {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--panel-line-soft);
  color: var(--text);
  white-space: nowrap;
}
</style>
