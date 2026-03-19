<script setup lang="ts">
defineProps<{
  title: string
  value: string
  hint: string
}>()
</script>

<template>
  <article class="card">
    <div class="title">{{ title }}</div>
    <div class="value">{{ value }}</div>
    <div class="hint">{{ hint }}</div>
  </article>
</template>

<style scoped>
.card {
  border: 1px solid var(--panel-line-strong);
  border-radius: 12px;
  padding: 12px;
  background: var(--panel-white);
}

.title {
  color: var(--muted);
  font-size: 12px;
}

.value {
  font-size: 20px;
  font-weight: 700;
  color: var(--heading-strong);
  margin: 4px 0;
}

.hint {
  color: var(--muted);
  font-size: 12px;
}
</style>
