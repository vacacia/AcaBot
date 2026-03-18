<script setup lang="ts">
import { onMounted, ref } from "vue"

import { apiGet, apiPut } from "../lib/api"

type AdminsPayload = {
  admin_actor_ids: string[]
}

const draft = ref<AdminsPayload | null>(null)
const adminActorIdsText = ref("")
const saveMessage = ref("")
const errorMessage = ref("")
const loading = ref(true)

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const payload = await apiGet<AdminsPayload>("/api/admins")
    draft.value = {
      admin_actor_ids: [...payload.admin_actor_ids],
    }
    adminActorIdsText.value = payload.admin_actor_ids.join("\n")
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "加载失败"
  } finally {
    loading.value = false
  }
}

async function saveAdmins(): Promise<void> {
  if (!draft.value) {
    return
  }
  saveMessage.value = "保存中..."
  errorMessage.value = ""
  try {
    const saved = await apiPut<AdminsPayload>("/api/admins", {
      admin_actor_ids: adminActorIdsText.value
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
    })
    draft.value = {
      admin_actor_ids: [...saved.admin_actor_ids],
    }
    adminActorIdsText.value = saved.admin_actor_ids.join("\n")
    saveMessage.value = "已保存"
  } catch (error) {
    saveMessage.value = ""
    errorMessage.value = error instanceof Error ? error.message : "保存失败"
  }
}

onMounted(() => {
  void loadPage()
})
</script>

<template>
  <section class="panel">
    <div class="header">
      <div>
        <p class="eyebrow">Admins</p>
        <h1>管理员</h1>
        <p class="summary">这里只维护一份共享管理员列表。每行一个标识，例如 <code>qq:private:123456</code>。</p>
      </div>
      <div class="actions">
        <button class="primary-button" type="button" :disabled="loading || !draft" @click="void saveAdmins()">
          保存
        </button>
      </div>
    </div>

    <p v-if="saveMessage" class="status ok">{{ saveMessage }}</p>
    <p v-if="errorMessage" class="status error">{{ errorMessage }}</p>
    <p v-if="loading" class="summary">正在加载管理员设置...</p>

    <article v-else-if="draft" class="card">
      <h2>共享管理员列表</h2>
      <p class="card-summary">系统权限判断也读这一份列表。</p>
      <label class="field">
        <span>管理员</span>
        <textarea v-model="adminActorIdsText" rows="10"></textarea>
      </label>
    </article>
  </section>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 20px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.eyebrow {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--muted);
}

h1 {
  margin: 0;
  font-size: 36px;
  color: #173257;
}

.summary {
  margin: 10px 0 0;
  max-width: 720px;
  color: var(--muted);
  line-height: 1.6;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.primary-button {
  border: none;
  border-radius: 999px;
  padding: 10px 18px;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  cursor: pointer;
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  box-shadow: 0 14px 30px rgba(10, 74, 123, 0.18);
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
  box-shadow: none;
}

.status {
  margin: 0;
  font-size: 14px;
}

.status.ok {
  color: #166534;
}

.status.error {
  color: #b42318;
}

.card {
  border: 1px solid rgba(15, 108, 184, 0.12);
  border-radius: 24px;
  padding: 24px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 40px rgba(25, 58, 103, 0.08);
  display: grid;
  gap: 14px;
}

.card h2 {
  margin: 0;
  font-size: 22px;
  color: #173257;
}

.card-summary {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}

.field {
  display: grid;
  gap: 8px;
}

.field span {
  font-size: 14px;
  font-weight: 600;
  color: #1f2f49;
}

.field textarea {
  width: 100%;
  border: 1px solid rgba(15, 108, 184, 0.2);
  border-radius: 18px;
  padding: 14px 16px;
  font: inherit;
  resize: vertical;
  min-height: 220px;
  background: rgba(247, 250, 255, 0.86);
  box-sizing: border-box;
}
</style>
