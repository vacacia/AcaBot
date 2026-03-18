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
  border: 1px solid #d5deea;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.title {
  color: #4d5d75;
  font-size: 12px;
}

.value {
  font-size: 20px;
  font-weight: 700;
  color: #173257;
  margin: 4px 0;
}

.hint {
  color: #6d7686;
  font-size: 12px;
}
</style>

