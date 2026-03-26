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
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  border-radius: 24px;
  padding: 18px 18px 16px;
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--panel);
  backdrop-filter: var(--blur-card);
  -webkit-backdrop-filter: var(--blur-card);
  box-shadow: var(--shadow-card);
}

.card::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background:
    linear-gradient(180deg, var(--glass-sheen-top) 0%, var(--glass-sheen-mid) 16%, rgba(255, 255, 255, 0) 36%),
    linear-gradient(140deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.014) 22%, rgba(255, 255, 255, 0) 46%);
  opacity: 0.56;
}

.card > * {
  position: relative;
  z-index: 1;
}

.title {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.value {
  margin: 10px 0 6px;
  font-size: clamp(28px, 2vw, 36px);
  font-weight: 800;
  color: var(--heading-strong);
  letter-spacing: -0.04em;
}

.hint {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.55;
}
</style>
