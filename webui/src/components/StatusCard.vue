<script setup lang="ts">
defineProps<{
  title: string
  value: string
  hint: string
  detail?: string
  variant?: "default" | "active" | "connected" | "disconnected" | "ready" | "unavailable" | "warm"
}>()
</script>

<template>
  <article class="card" :class="variant ? `card-${variant}` : undefined">
    <div class="title">{{ title }}</div>
    <div class="value">{{ value }}</div>
    <div class="hint">{{ hint }}</div>
    <div v-if="detail" class="detail">{{ detail }}</div>
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.value {
  margin: 8px 0 4px;
  font-size: clamp(20px, 1.6vw, 22px);
  font-weight: 800;
  color: var(--heading-strong);
  letter-spacing: -0.03em;
}

.hint {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.detail {
  margin-top: 6px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
  opacity: 0.8;
}

/* Semantic value colors */
.card-active .value,
.card-connected .value,
.card-ready .value {
  color: var(--success);
}

.card-disconnected .value,
.card-unavailable .value {
  color: var(--muted);
  opacity: 0.7;
}

.card-warm .value {
  color: var(--warning);
}

/* Accent left-border for active cards */
.card-active,
.card-connected,
.card-ready {
  border-left: 3px solid var(--success);
}

.card-warm {
  border-left: 3px solid var(--warning);
}

/* Hover micro-interaction */
.card {
  transition:
    transform 180ms cubic-bezier(0.25, 1, 0.5, 1),
    box-shadow 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px var(--shadow-card), 0 2px 8px rgba(0, 0, 0, 0.08);
}

@media (prefers-reduced-motion: reduce) {
  .card {
    transition: none;
  }
  .card:hover {
    transform: none;
  }
}
</style>
