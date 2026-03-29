<script setup lang="ts">
import { computed, onMounted, ref } from "vue"

import EditableListField from "../components/EditableListField.vue"
import { apiGet, apiPut, peekCachedGet } from "../lib/api"

type AdminsPayload = {
  admin_actor_ids: string[]
  apply_status?: string
  restart_required?: boolean
  message?: string
}

const cachedAdmins = peekCachedGet<AdminsPayload>("/api/admins")
const draft = ref<AdminsPayload | null>(
  cachedAdmins
    ? {
        admin_actor_ids: [...cachedAdmins.admin_actor_ids],
      }
    : null,
)
const saveMessage = ref("")
const errorMessage = ref("")
const loading = ref(!cachedAdmins)

const adminActorIds = computed<string[]>({
  get() {
    return draft.value?.admin_actor_ids ?? []
  },
  set(value) {
    if (!draft.value) {
      return
    }
    draft.value = {
      admin_actor_ids: [...value],
    }
  },
})

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = ""
  try {
    const payload = await apiGet<AdminsPayload>("/api/admins")
    draft.value = {
      admin_actor_ids: [...payload.admin_actor_ids],
    }
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
      admin_actor_ids: draft.value.admin_actor_ids,
    })
    draft.value = {
      admin_actor_ids: [...saved.admin_actor_ids],
    }
    saveMessage.value = saved.message || "已保存"
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
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Admins</p>
        <h1>管理员</h1>
        <p class="ds-summary">这里只维护一份共享管理员列表。每行一个标识，例如 <code>qq:private:123456</code>。</p>
      </div>
      <div class="ds-actions">
        <button class="ds-primary-button" type="button" :disabled="loading || !draft" @click="void saveAdmins()">保存</button>
      </div>
    </header>

    <p v-if="saveMessage" class="ds-status is-ok">{{ saveMessage }}</p>
    <p v-if="errorMessage" class="ds-status is-error">{{ errorMessage }}</p>
    <p v-if="loading" class="ds-empty">正在加载管理员设置...</p>

    <article v-else-if="draft" class="ds-panel ds-panel-padding">
      <div class="ds-section-head">
        <div class="ds-section-title">
          <div>
            <h2>共享管理员列表</h2>
            <p class="ds-summary">系统权限判断会直接读取这一份共享管理员列表。</p>
          </div>
        </div>
      </div>
      <EditableListField
        v-model="adminActorIds"
        label="管理员"
        helper="一次添加一个标识，例如 qq:private:123456。保存后系统权限判断会立即使用这一份列表。"
        placeholder="添加新项，按回车确认添加"
        empty-title="还没有配置任何管理员"
        empty-description="先添加一项，AcaBot 保存后会立刻把它纳入共享管理员列表。"
        :disabled="loading || !draft"
      />
    </article>
  </section>
</template>
