<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">AC</div>
      <div>
        <div class="brand-title">AcaBot</div>
        <div class="brand-subtitle">控制台</div>
      </div>
    </div>
    <div class="theme-switcher" data-theme-mode>
      <span class="theme-label">主题</span>
      <div class="theme-segment" role="group" aria-label="主题模式">
        <button
          class="theme-option"
          :class="{ active: themeMode === 'light' }"
          type="button"
          @click="emit('update:theme-mode', 'light')"
        >
          浅色
        </button>
        <button
          class="theme-option"
          :class="{ active: themeMode === 'dark' }"
          type="button"
          @click="emit('update:theme-mode', 'dark')"
        >
          深色
        </button>
        <button
          class="theme-option"
          :class="{ active: themeMode === 'system' }"
          type="button"
          @click="emit('update:theme-mode', 'system')"
        >
          跟随系统
        </button>
      </div>
    </div>
    <nav class="nav">
      <RouterLink class="nav-item" to="/">首页</RouterLink>
      <div class="group-title">预览</div>
      <RouterLink class="nav-item" to="/preview/glass-lab/graphite">Glass Palettes</RouterLink>
      <RouterLink class="nav-item" to="/preview/glass-lab/editorial-graphite">Editorial Study</RouterLink>
      <RouterLink class="nav-item" to="/preview/glass-lab/instrument-brass">Instrument Study</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-console/cold-graphite">Material Cold</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-console/warm-mineral">Material Warm</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-console/deep-flagship">Material Dark</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/smoked-graphite">Dark Smoke</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/mineral-dusk">Dark Dusk</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/slate-flagship">Dark Slate</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/monochrome-graphite">Dark Mono</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/cold-black-titanium">Dark Titanium</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/warm-black-ore">Dark Ore</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-dark/blue-black-flagship">Dark Flagship</RouterLink>
      <RouterLink class="nav-item" to="/preview/material-frost/smoke/glass/accent">Frost Study</RouterLink>
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

defineProps<{
  themeMode: ThemeMode
}>()

const emit = defineEmits<{
  (e: "update:theme-mode", value: ThemeMode): void
}>()
</script>

<style scoped>
.sidebar {
  width: 248px;
  border-right: 1px solid var(--line);
  background: var(--sidebar-bg);
  backdrop-filter: blur(18px);
  padding: 20px 14px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  overflow: auto;
  box-shadow: var(--sidebar-shadow);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.theme-switcher {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}

.theme-label {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.theme-segment {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--theme-switch-bg);
}

.theme-option {
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: var(--theme-switch-text);
  padding: 10px 8px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition:
    background-color 120ms ease,
    color 120ms ease,
    transform 120ms ease;
}

.theme-option.active {
  background: var(--theme-switch-active-bg);
  color: var(--theme-switch-active-text);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

.theme-option:hover {
  transform: translateY(-1px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--sidebar-brand-mark-start) 0%, var(--sidebar-brand-mark-end) 100%);
  color: #fff;
  font-weight: 800;
  letter-spacing: 0.08em;
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
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.group-title {
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.nav-item {
  display: block;
  padding: 10px 12px;
  border-radius: 12px;
  color: var(--sidebar-text);
  text-decoration: none;
  transition:
    background-color 120ms ease,
    transform 120ms ease,
    color 120ms ease;
}

.nav-item:hover {
  background: rgba(15, 108, 184, 0.08);
  transform: translateX(2px);
}

.nav-item.router-link-active {
  background: linear-gradient(135deg, rgba(15, 108, 184, 0.16), rgba(15, 108, 184, 0.08));
  color: var(--sidebar-active);
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(15, 108, 184, 0.12);
}

:root[data-theme="dark"] .nav-item:hover {
  background: rgba(102, 183, 255, 0.1);
}

:root[data-theme="dark"] .nav-item.router-link-active {
  background: linear-gradient(135deg, rgba(102, 183, 255, 0.18), rgba(102, 183, 255, 0.08));
  box-shadow: inset 0 0 0 1px rgba(102, 183, 255, 0.16);
}

@media (max-width: 960px) {
  .sidebar {
    width: auto;
    border-right: none;
    border-bottom: 1px solid var(--line);
    padding: 16px 14px;
  }

  .brand {
    margin-bottom: 6px;
  }

  .nav {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
    gap: 8px;
  }

  .group-title {
    grid-column: 1 / -1;
    margin: 4px 0 0;
  }

  .nav-item {
    padding: 10px;
  }

  .nav-item:hover {
    transform: none;
  }
}
</style>
