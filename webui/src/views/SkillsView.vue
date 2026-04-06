<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPostFormData, peekCachedGet } from "../lib/api"

type SkillItem = {
  skill_name: string
  display_name?: string
  description?: string
}

type SkillUploadResult = {
  installed_skill: SkillItem & {
    host_skill_root_path?: string
  }
}

const items = ref<SkillItem[]>(peekCachedGet<SkillItem[]>('/api/skills') ?? [])
const loading = ref(true)
const refreshing = ref(false)
const uploading = ref(false)
const errorText = ref("")
const statusText = ref("")
const statusTone = ref<"is-ok" | "is-error">("is-ok")
const selectedFile = ref<File | null>(null)

async function loadSkills(): Promise<void> {
  refreshing.value = true
  errorText.value = ""
  try {
    items.value = await apiGet<SkillItem[]>('/api/skills')
  } catch (err: any) {
    errorText.value = err?.message || String(err)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement | null
  selectedFile.value = input?.files?.[0] ?? null
}

async function uploadSkillZip(): Promise<void> {
  if (!selectedFile.value || uploading.value) {
    return
  }
  uploading.value = true
  errorText.value = ""
  statusText.value = ""
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    const result = await apiPostFormData<SkillUploadResult>('/api/skills/upload', formData)
    statusTone.value = 'is-ok'
    statusText.value = `已安装：${result.installed_skill.display_name || result.installed_skill.skill_name}`
    selectedFile.value = null
    const input = document.querySelector<HTMLInputElement>('[data-skill-upload-input]')
    if (input) {
      input.value = ''
    }
    await loadSkills()
  } catch (err: any) {
    statusTone.value = 'is-error'
    statusText.value = err?.message || String(err)
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  await loadSkills()
})
</script>

<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Config / Skills</p>
        <h1>已安装 Skills</h1>
      </div>
    </header>

    <article class="ds-panel ds-panel-padding skills-panel">
      <section class="upload-panel">
        <div class="upload-copy">
          <h2>上传 Skill 压缩包</h2>
          <p class="ds-summary compact">支持常见 zip skill 包。上传后会自动安装到项目级 skills 目录，并立即刷新列表。</p>
        </div>
        <div class="upload-actions">
          <input
            data-skill-upload-input
            class="ds-input upload-input"
            type="file"
            accept=".zip,application/zip"
            @change="onFileChange"
          />
          <div class="upload-buttons">
            <button class="ds-secondary-button" type="button" :disabled="refreshing || uploading" @click="void loadSkills()">
              {{ refreshing ? '刷新中…' : '刷新列表' }}
            </button>
            <button class="ds-primary-button" type="button" :disabled="!selectedFile || uploading" @click="void uploadSkillZip()">
              {{ uploading ? '上传中…' : '上传并安装' }}
            </button>
          </div>
          <p v-if="selectedFile" class="selected-file">当前文件：{{ selectedFile.name }}</p>
        </div>
      </section>

      <p v-if="statusText" class="ds-status" :class="statusTone">{{ statusText }}</p>
      <p v-if="loading" class="ds-status">加载中…</p>
      <p v-else-if="errorText" class="ds-status is-error">{{ errorText }}</p>

      <div v-else class="ds-list">
        <article v-for="item in items" :key="item.skill_name" class="ds-list-item ds-list-item-padding skill-item">
          <strong>{{ item.display_name || item.skill_name }}</strong>
          <p class="skill-name">{{ item.skill_name }}</p>
          <p class="ds-summary compact">{{ item.description || '暂无说明' }}</p>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.skills-panel {
  display: grid;
  gap: 18px;
}

.upload-panel {
  display: grid;
  gap: 16px;
  padding: 18px;
  border-radius: 18px;
  background: color-mix(in oklab, var(--panel-elevated) 82%, var(--accent-soft) 18%);
  border: 1px solid var(--border-soft);
}

.upload-copy {
  display: grid;
  gap: 6px;
}

.upload-copy h2 {
  margin: 0;
  font-size: 1.05rem;
}

.upload-actions {
  display: grid;
  gap: 12px;
}

.upload-input {
  width: 100%;
}

.upload-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.selected-file,
.skill-name {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.92rem;
}

.skill-item {
  display: grid;
  gap: 6px;
  opacity: 0;
  transform: translateY(8px);
  animation: skill-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
  position: relative;
  border-left: 3px solid transparent;
  transition: border-color 150ms cubic-bezier(0.25, 1, 0.5, 1),
    background 150ms cubic-bezier(0.25, 1, 0.5, 1),
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1);
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
  border-left-color: var(--accent);
  background: var(--accent-soft);
  transform: translateX(3px);
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
