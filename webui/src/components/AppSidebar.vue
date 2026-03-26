<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">AC</div>
      <div>
        <div class="brand-title">AcaBot</div>
        <div class="brand-subtitle">玻璃风控制台</div>
      </div>
    </div>

    <div class="switcher" data-theme-mode>
      <span class="switcher-label">主题模式</span>
      <div class="switcher-panel theme-panel" role="group" aria-label="主题模式">
        <button
          v-for="option in themeOptions"
          :key="option.value"
          class="switcher-option"
          :class="{ active: themeMode === option.value }"
          :data-theme-option="option.value"
          type="button"
          @click="emit('update:theme-mode', option.value)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>

    <div class="switcher" data-accent-theme>
      <span class="switcher-label">主题色</span>
      <div class="switcher-panel accent-panel" role="group" aria-label="主题色">
        <button
          v-for="option in accentOptions"
          :key="option.value"
          class="accent-option"
          :class="{ active: accentTheme === option.value }"
          :data-accent-option="option.value"
          type="button"
          @click="emit('update:accent-theme', option.value)"
        >
          <span class="accent-dot" :class="`is-${option.value}`" aria-hidden="true"></span>
          <span>{{ option.label }}</span>
        </button>
      </div>
    </div>

    <nav class="nav">
      <RouterLink class="nav-item" to="/">首页</RouterLink>
      <div class="group-title">配置</div>
      <RouterLink class="nav-item" to="/config/soul">Soul</RouterLink>
      <RouterLink class="nav-item" to="/config/memory">记忆</RouterLink>
      <RouterLink class="nav-item" to="/config/admins">管理员</RouterLink>
      <RouterLink class="nav-item" to="/config/providers">模型供应商</RouterLink>
      <RouterLink class="nav-item" to="/config/models">模型</RouterLink>
      <RouterLink class="nav-item" to="/config/prompts">提示词</RouterLink>
      <RouterLink class="nav-item" to="/config/plugins">插件</RouterLink>
      <RouterLink class="nav-item" to="/config/skills">技能</RouterLink>
      <RouterLink class="nav-item" to="/config/subagents">子代理</RouterLink>
      <RouterLink class="nav-item" to="/sessions">会话</RouterLink>
      <RouterLink class="nav-item" to="/system">系统</RouterLink>
      <RouterLink class="nav-item" to="/logs">日志</RouterLink>
    </nav>
  </aside>
</template>

<script setup lang="ts">
type ThemeMode = "light" | "dark" | "system"
type AccentTheme = "rose" | "violet" | "aqua" | "amber" | "graphite"

const themeOptions: Array<{ label: string; value: ThemeMode }> = [
  { label: "浅色", value: "light" },
  { label: "深色", value: "dark" },
  { label: "跟随系统", value: "system" },
]

const accentOptions: Array<{ label: string; value: AccentTheme }> = [
  { label: "蔷薇", value: "rose" },
  { label: "紫雾", value: "violet" },
  { label: "冰青", value: "aqua" },
  { label: "香槟", value: "amber" },
  { label: "石墨", value: "graphite" },
]

defineProps<{
  themeMode: ThemeMode
  accentTheme: AccentTheme
}>()

const emit = defineEmits<{
  (e: "update:theme-mode", value: ThemeMode): void
  (e: "update:accent-theme", value: AccentTheme): void
}>()
</script>

<style scoped>
.sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: calc(100vh - 36px);
  padding: 18px 16px;
  border-radius: 30px;
  overflow: auto;
  border: 1px solid var(--border-strong);
  background:
    linear-gradient(180deg, var(--glass-face-top), var(--glass-face-bottom)),
    var(--sidebar-bg);
  backdrop-filter: var(--blur-card);
  -webkit-backdrop-filter: var(--blur-card);
  box-shadow: var(--sidebar-shadow);
}

.sidebar::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background:
    linear-gradient(180deg, var(--glass-sheen-top) 0%, var(--glass-sheen-mid) 20%, rgba(255, 255, 255, 0) 40%),
    linear-gradient(120deg, rgba(255, 255, 255, 0.03) 0%, rgba(255, 255, 255, 0.012) 22%, rgba(255, 255, 255, 0) 48%);
  opacity: 0.62;
}

.sidebar > * {
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  background: linear-gradient(145deg, var(--sidebar-brand-mark-start), var(--sidebar-brand-mark-end));
  color: #fff;
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 0.08em;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.brand-title {
  font-size: 20px;
  font-weight: 800;
  color: var(--heading-strong);
}

.brand-subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
}

.switcher {
  display: grid;
  gap: 6px;
}

.switcher-label,
.group-title {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.switcher-panel {
  display: grid;
  gap: 6px;
  padding: 6px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: var(--theme-switch-bg);
}

.theme-panel {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.accent-panel {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.switcher-option,
.accent-option {
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: var(--theme-switch-text);
  cursor: pointer;
  transition:
    transform 120ms ease,
    background-color 120ms ease,
    color 120ms ease;
}

.switcher-option {
  padding: 10px 8px;
  font-size: 12px;
  font-weight: 700;
}

.accent-option {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 9px 10px;
  font-size: 12px;
  font-weight: 700;
}

.switcher-option.active,
.accent-option.active {
  background: var(--theme-switch-active-bg);
  color: var(--theme-switch-active-text);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}

.switcher-option:hover,
.accent-option:hover,
.nav-item:hover {
  transform: translateY(-1px);
}

.accent-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.32);
}

.accent-dot.is-rose {
  background: linear-gradient(145deg, #ff6479, #ff98a6);
}

.accent-dot.is-violet {
  background: linear-gradient(145deg, #8a63ff, #c0a4ff);
}

.accent-dot.is-aqua {
  background: linear-gradient(145deg, #28a8c7, #7eddf0);
}

.accent-dot.is-amber {
  background: linear-gradient(145deg, #d89a2e, #f0cb88);
}

.accent-dot.is-graphite {
  background: linear-gradient(145deg, #6f829c, #a7b4c6);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-title {
  margin-top: 6px;
  margin-bottom: 4px;
}

.nav-item {
  display: block;
  padding: 11px 12px;
  border-radius: 16px;
  color: var(--sidebar-text);
  text-decoration: none;
  transition:
    background-color 120ms ease,
    transform 120ms ease,
    color 120ms ease;
}

.nav-item:hover {
  background: color-mix(in srgb, var(--accent-soft) 90%, transparent);
}

.nav-item.router-link-active {
  background: var(--theme-switch-active-bg);
  color: var(--sidebar-active);
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
}

@media (max-width: 1100px) {
  .sidebar {
    min-height: auto;
  }
}

@media (max-width: 860px) {
  .sidebar {
    padding: 16px 14px;
  }

  .theme-panel {
    grid-template-columns: 1fr;
  }

  .accent-panel {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
