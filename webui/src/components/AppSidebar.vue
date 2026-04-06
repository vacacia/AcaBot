<template>
  <aside class="sidebar">
    <div class="brand">
      <button class="brand-mark" ref="brandMarkRef" type="button" @click="showThemePopover = !showThemePopover">AC</button>
      <div>
        <div class="brand-title">AcaBot</div>
        <div class="brand-subtitle">控制台</div>
      </div>
    </div>

    <!-- Theme popover -->
    <Transition name="popover">
    <div v-if="showThemePopover" class="theme-popover" ref="popoverRef">
      <div class="popover-section">
        <span class="popover-label">主题模式</span>
        <div class="popover-row">
          <button
            v-for="option in themeOptions"
            :key="option.value"
            class="popover-option"
            :class="{ active: themeMode === option.value }"
            type="button"
            @click="emit('update:theme-mode', option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
      <div class="popover-section">
        <span class="popover-label">主题色</span>
        <div class="popover-row accent-row">
          <button
            v-for="option in accentOptions"
            :key="option.value"
            class="accent-btn"
            :class="{ active: accentTheme === option.value }"
            type="button"
            @click="emit('update:accent-theme', option.value)"
          >
            <span class="accent-dot" :class="`is-${option.value}`"></span>
          </button>
        </div>
      </div>
    </div>
    </Transition>

    <select
      class="theme-mode-compat"
      data-theme-mode
      :value="themeMode"
      @change="emit('update:theme-mode', ($event.target as HTMLSelectElement).value as ThemeMode)"
    >
      <option v-for="option in themeOptions" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>

    <nav class="nav" role="navigation" aria-label="主导航">
      <RouterLink class="nav-item nav-entrance nav-entrance-0" to="/">首页</RouterLink>
      <div class="group-title nav-entrance nav-entrance-1">配置</div>
      <button class="nav-group-toggle nav-entrance nav-entrance-2" :class="{ expanded: memoryExpanded }" type="button" @click="memoryExpanded = !memoryExpanded">
        <span>记忆</span>
        <svg class="nav-group-arrow" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <div v-if="memoryExpanded" class="nav-group-children">
        <RouterLink class="nav-item nav-child nav-entrance nav-entrance-3" to="/config/memory/self">Self</RouterLink>
        <RouterLink class="nav-item nav-child nav-entrance nav-entrance-4" to="/config/memory/sticky-notes">Sticky Notes</RouterLink>
        <RouterLink class="nav-item nav-child nav-entrance nav-entrance-5" to="/config/memory/ltm">Long-Term Memory</RouterLink>
      </div>
      <RouterLink class="nav-item nav-entrance nav-entrance-6" to="/config/providers">模型供应商</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-8" to="/config/models">模型</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-9" to="/config/prompts">提示词</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-10" to="/config/plugins">插件</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-11" to="/config/skills">技能</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-12" to="/config/subagents">子代理</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-13" to="/sessions">会话</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-14" to="/system">系统</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-15" to="/logs">日志</RouterLink>
      <RouterLink class="nav-item nav-entrance nav-entrance-16" to="/schedules">调度</RouterLink>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute } from "vue-router"

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

const route = useRoute()
const memoryExpanded = ref(route.path.startsWith('/config/memory'))
const showThemePopover = ref(false)
const popoverRef = ref<HTMLElement | null>(null)
const brandMarkRef = ref<HTMLElement | null>(null)

watch(() => route.path, (path) => {
  if (path.startsWith('/config/memory')) {
    memoryExpanded.value = true
  }
})

function onClickOutside(event: MouseEvent) {
  if (!showThemePopover.value) return
  const target = event.target as Node
  if (popoverRef.value?.contains(target) || brandMarkRef.value?.contains(target)) return
  showThemePopover.value = false
}

onMounted(() => document.addEventListener('click', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('click', onClickOutside))
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
  border: none;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
  transition:
    transform 180ms cubic-bezier(0.25, 1, 0.5, 1),
    box-shadow 180ms cubic-bezier(0.25, 1, 0.5, 1);
}

.brand-mark:hover {
  transform: translateY(-2px) scale(1.05);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),
    0 8px 20px rgba(0, 0, 0, 0.3);
}

.brand-mark:active {
  transform: translateY(0) scale(0.97);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
  transition-duration: 80ms;
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

/* Theme popover */
.theme-popover {
  position: absolute;
  top: 72px;
  left: 16px;
  right: 16px;
  z-index: 10;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid var(--panel-line-soft);
  background: var(--panel);
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.theme-mode-compat {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.popover-section { display: flex; flex-direction: column; gap: 6px; }
.popover-label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }

.popover-row {
  display: flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: var(--theme-switch-bg);
}

.popover-option {
  flex: 1;
  padding: 7px 4px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition:
    background 150ms ease,
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1),
    color 150ms ease;
}

.popover-option:hover {
  background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
  transform: scale(1.05);
}

.popover-option:active {
  transform: scale(0.95);
  transition-duration: 60ms;
}

.popover-option.active {
  background: var(--theme-switch-active-bg);
  color: var(--theme-switch-active-text);
}

.accent-row {
  background: transparent;
  padding: 0;
  gap: 8px;
}

.accent-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid transparent;
  background: none;
  cursor: pointer;
  padding: 0;
  display: grid;
  place-items: center;
  transition:
    border-color 150ms ease,
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.accent-btn:hover {
  transform: scale(1.15);
}

.accent-btn:active {
  transform: scale(0.92);
  transition-duration: 60ms;
}

.accent-btn.active {
  border-color: var(--accent);
}

.accent-dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
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
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
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
    background-color 150ms ease,
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1),
    color 150ms ease,
    box-shadow 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.nav-item:hover {
  background: color-mix(in srgb, var(--accent-soft) 90%, transparent);
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.nav-item:active {
  transform: translateY(0) scale(0.98);
  box-shadow: none;
  transition-duration: 60ms;
}

.nav-group-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 11px 12px;
  border: none;
  border-radius: 16px;
  background: transparent;
  color: var(--sidebar-text);
  font-size: inherit;
  font-family: inherit;
  cursor: pointer;
  transition:
    background 150ms ease,
    transform 150ms cubic-bezier(0.25, 1, 0.5, 1);
}

.nav-group-toggle:hover {
  background: color-mix(in srgb, var(--accent-soft) 90%, transparent);
  transform: translateY(-2px) scale(1.02);
}

.nav-group-toggle:active {
  transform: translateY(0) scale(0.98);
  transition-duration: 60ms;
}

.nav-group-toggle.expanded {
  color: var(--accent);
  font-weight: 600;
}

.nav-group-arrow {
  transition: transform 200ms ease;
  color: var(--muted);
}

.nav-group-toggle.expanded .nav-group-arrow {
  transform: rotate(180deg);
}

.nav-group-children {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 14px;
}

.nav-child {
  font-size: 13px;
  padding: 8px 12px;
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
}

/* ── Popover transition ── */
.popover-enter-active {
  animation: popover-in 200ms cubic-bezier(0.25, 1, 0.5, 1);
}

.popover-leave-active {
  animation: popover-out 140ms cubic-bezier(0.4, 0, 1, 1);
}

@keyframes popover-in {
  from { opacity: 0; transform: scale(0.95) translateY(-6px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}

@keyframes popover-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(0.97) translateY(-4px); }
}

/* ── Nav stagger entrance ── */
.nav-entrance {
  opacity: 0;
  transform: translateX(-6px);
  animation: nav-item-in 280ms cubic-bezier(0.25, 1, 0.5, 1) forwards;
}

.nav-entrance-0  { animation-delay: 20ms; }
.nav-entrance-1  { animation-delay: 50ms; }
.nav-entrance-2  { animation-delay: 80ms; }
.nav-entrance-3  { animation-delay: 120ms; }
.nav-entrance-4  { animation-delay: 135ms; }
.nav-entrance-5  { animation-delay: 150ms; }
.nav-entrance-6  { animation-delay: 160ms; }
.nav-entrance-7  { animation-delay: 180ms; }
.nav-entrance-8  { animation-delay: 200ms; }
.nav-entrance-9  { animation-delay: 220ms; }
.nav-entrance-10 { animation-delay: 240ms; }
.nav-entrance-11 { animation-delay: 260ms; }
.nav-entrance-12 { animation-delay: 280ms; }
.nav-entrance-13 { animation-delay: 300ms; }
.nav-entrance-14 { animation-delay: 320ms; }

@keyframes nav-item-in {
  to { opacity: 1; transform: translateX(0); }
}

/* ── Active nav item indicator ── */
.nav-item.router-link-active {
  position: relative;
  overflow: hidden;
}

.nav-item.router-link-active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%) scaleY(0);
  width: 3px;
  height: 60%;
  background: var(--accent);
  border-radius: 0 3px 3px 0;
  animation: nav-active-indicator 200ms cubic-bezier(0.25, 1, 0.5, 1) 350ms forwards;
}

@keyframes nav-active-indicator {
  to { transform: translateY(-50%) scaleY(1); }
}

/* ── Nav group children slide ── */
.nav-group-children {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 14px;
  overflow: hidden;
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {
  .popover-enter-active,
  .popover-leave-active {
    animation: none;
  }
  .nav-entrance {
    opacity: 1;
    transform: none;
    animation: none;
  }
  .nav-item.router-link-active::before {
    animation: none;
    transform: translateY(-50%) scaleY(1);
  }
}
</style>
