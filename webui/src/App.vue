<template>
  <div class="shell">
    <AppSidebar
      :theme-mode="themeMode"
      :accent-theme="accentTheme"
      @update:theme-mode="setThemeMode"
      @update:accent-theme="setAccentTheme"
    />
    <main class="main">
      <RouterView v-slot="{ Component }">
        <KeepAlive>
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"

import AppSidebar from "./components/AppSidebar.vue"

type ThemeMode = "light" | "dark" | "system"
type AccentTheme = "rose" | "violet" | "aqua" | "amber" | "graphite"

const THEME_STORAGE_KEY = "acabot.theme_mode"
const ACCENT_STORAGE_KEY = "acabot.accent_theme"

// Read saved values synchronously at setup time so the initial ref matches localStorage
const savedTheme = localStorage.getItem(THEME_STORAGE_KEY)
const savedAccent = localStorage.getItem(ACCENT_STORAGE_KEY)

const themeMode = ref<ThemeMode>(
  savedTheme === "light" || savedTheme === "dark" || savedTheme === "system" ? savedTheme : "dark"
)
const accentTheme = ref<AccentTheme>(
  savedAccent === "rose" || savedAccent === "violet" || savedAccent === "aqua" || savedAccent === "amber" || savedAccent === "graphite" ? savedAccent : "rose"
)

// Initialize mediaQuery synchronously — window.matchMedia is safe in <script setup>
const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")

function systemTheme(): "light" | "dark" {
  return mediaQuery.matches ? "dark" : "light"
}

function applyTheme(mode: ThemeMode): void {
  const effectiveTheme = mode === "system" ? systemTheme() : mode
  document.documentElement.dataset.themeMode = mode
  document.documentElement.dataset.theme = effectiveTheme
  document.documentElement.style.colorScheme = effectiveTheme
}

function applyAccentTheme(theme: AccentTheme): void {
  document.documentElement.dataset.accentTheme = theme
}

// Apply theme immediately during setup — no waiting for onMounted
applyTheme(themeMode.value)
applyAccentTheme(accentTheme.value)

function setThemeMode(mode: ThemeMode): void {
  themeMode.value = mode
  localStorage.setItem(THEME_STORAGE_KEY, mode)
  applyTheme(mode)
}

function setAccentTheme(theme: AccentTheme): void {
  accentTheme.value = theme
  localStorage.setItem(ACCENT_STORAGE_KEY, theme)
  applyAccentTheme(theme)
}

function handleSystemThemeChange(): void {
  if (themeMode.value === "system") {
    applyTheme("system")
  }
}

onMounted(() => {
  mediaQuery.addEventListener("change", handleSystemThemeChange)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", handleSystemThemeChange)
})
</script>

<style>
:root {
  --font-sans:
    "Inter",
    "Noto Sans SC",
    "PingFang SC",
    "Microsoft YaHei",
    sans-serif;
  --shadow-soft: 0 8px 24px rgba(0, 0, 0, 0.06);
  --shadow-card: 0 2px 8px rgba(0, 0, 0, 0.05);
  --border-strong: #e2e5ea;
  --blur-card: none;
  --glass-face-top: transparent;
  --glass-face-bottom: transparent;
  --glass-sheen-top: transparent;
  --glass-sheen-mid: transparent;
  --glass-edge-line: #e2e5ea;
  --glass-edge-shadow: rgba(0, 0, 0, 0.04);
  --theme-bg-spot-1: transparent;
  --theme-bg-spot-2: transparent;
  --theme-bg-spot-3: transparent;
  --theme-bg-spot-4: transparent;
  --orb-a-color: transparent;
  --orb-b-color: transparent;
  --orb-c-color: transparent;
  --ambient-glow-primary: transparent;
  --ambient-glow-secondary: transparent;
  --ambient-glow-tertiary: transparent;
  --ambient-ribbon-primary: transparent;
  --ambient-ribbon-secondary: transparent;
  --ambient-ribbon-tertiary: transparent;
  --ambient-band: transparent;
  --ambient-vignette: transparent;
  --main-ribbon-soft: transparent;
  --main-ribbon-accent: transparent;
  --main-ribbon-fill: transparent;
  --bg-top: #f8f9fb;
  --bg-bottom: #f0f2f5;
  --panel: #ffffff;
  --panel-strong: #f5f6f8;
  --panel-white: #ffffff;
  --panel-blue-soft: #eef2f8;
  --panel-blue-soft-text: #3d5a80;
  --line: #e2e5ea;
  --panel-line-strong: #d4d8de;
  --panel-line-soft: #e8eaef;
  --text: #1a1d23;
  --muted: #6b7280;
  --heading-strong: #111318;
  --heading-soft: #374151;
  --sidebar-text: #1f2937;
  --sidebar-active: var(--accent);
  --accent: #6366f1;
  --accent-2: #818cf8;
  --accent-soft: rgba(99, 102, 241, 0.1);
  --success: #10b981;
  --danger: #ef4444;
  --warning: #f59e0b;
  --info: #3b82f6;
  --button-primary-start: #6366f1;
  --button-primary-end: #818cf8;
  --button-shadow-color: rgba(99, 102, 241, 0.2);
  --sidebar-bg: #ffffff;
  --sidebar-shadow: 0 1px 0 #e2e5ea;
  --sidebar-brand-mark-start: #6366f1;
  --sidebar-brand-mark-end: #818cf8;
  --theme-switch-bg: #f0f2f5;
  --theme-switch-active-bg: #ffffff;
  --theme-switch-active-text: var(--accent);
  --theme-switch-text: var(--muted);
  --log-message: #1a1d23;
  --log-seq: #9ca3af;
  --log-time: #6b7280;
  --log-logger: #9ca3af;
  --napcat-chip: #059669;
  font-family: var(--font-sans);
}

:root[data-theme="dark"] {
  --shadow-soft: 0 8px 24px rgba(0, 0, 0, 0.3);
  --shadow-card: 0 2px 8px rgba(0, 0, 0, 0.2);
  --border-strong: #2a2d35;
  --glass-face-top: transparent;
  --glass-face-bottom: transparent;
  --glass-sheen-top: transparent;
  --glass-sheen-mid: transparent;
  --glass-edge-line: #2a2d35;
  --glass-edge-shadow: rgba(0, 0, 0, 0.3);
  --bg-top: #111318;
  --bg-bottom: #0d0f14;
  --panel: #1a1d24;
  --panel-strong: #15171e;
  --panel-white: #1e2028;
  --panel-blue-soft: #1c2130;
  --panel-blue-soft-text: #c4d5eb;
  --line: #2a2d35;
  --panel-line-strong: #33363f;
  --panel-line-soft: #232630;
  --text: #e4e5e9;
  --muted: #8b8d97;
  --heading-strong: #f0f1f3;
  --heading-soft: #c0c2c8;
  --sidebar-text: #d0d2d7;
  --accent-soft: rgba(99, 102, 241, 0.15);
  --sidebar-bg: #15171e;
  --sidebar-shadow: 0 1px 0 #2a2d35;
  --theme-switch-bg: #1e2028;
  --theme-switch-active-bg: #252830;
  --theme-switch-active-text: #f0f1f3;
  --log-message: #e4e5e9;
  --log-seq: #6b6d77;
  --log-time: #8b8d97;
  --log-logger: #6b6d77;
  --napcat-chip: #34d399;
  --main-ribbon-soft: transparent;
  --main-ribbon-accent: transparent;
  --main-ribbon-fill: transparent;
}

:root[data-accent-theme="rose"] {
  --accent: #f43f5e;
  --accent-2: #fb7185;
  --accent-soft: rgba(244, 63, 94, 0.1);
  --button-shadow-color: rgba(244, 63, 94, 0.2);
  --sidebar-brand-mark-start: #f43f5e;
  --sidebar-brand-mark-end: #fb7185;
  --button-primary-start: #f43f5e;
  --button-primary-end: #fb7185;
}

:root[data-accent-theme="violet"] {
  --accent: #8b5cf6;
  --accent-2: #a78bfa;
  --accent-soft: rgba(139, 92, 246, 0.1);
  --button-shadow-color: rgba(139, 92, 246, 0.2);
  --sidebar-brand-mark-start: #8b5cf6;
  --sidebar-brand-mark-end: #a78bfa;
  --button-primary-start: #8b5cf6;
  --button-primary-end: #a78bfa;
}

:root[data-accent-theme="aqua"] {
  --accent: #0891b2;
  --accent-2: #22d3ee;
  --accent-soft: rgba(8, 145, 178, 0.1);
  --button-shadow-color: rgba(8, 145, 178, 0.18);
  --sidebar-brand-mark-start: #0891b2;
  --sidebar-brand-mark-end: #22d3ee;
  --button-primary-start: #0891b2;
  --button-primary-end: #22d3ee;
}

:root[data-accent-theme="amber"] {
  --accent: #d97706;
  --accent-2: #fbbf24;
  --accent-soft: rgba(217, 119, 6, 0.1);
  --button-shadow-color: rgba(217, 119, 6, 0.18);
  --sidebar-brand-mark-start: #d97706;
  --sidebar-brand-mark-end: #fbbf24;
  --button-primary-start: #d97706;
  --button-primary-end: #fbbf24;
}

:root[data-accent-theme="graphite"] {
  --accent: #64748b;
  --accent-2: #94a3b8;
  --accent-soft: rgba(100, 116, 139, 0.1);
  --button-shadow-color: rgba(100, 116, 139, 0.16);
  --sidebar-brand-mark-start: #64748b;
  --sidebar-brand-mark-end: #94a3b8;
  --button-primary-start: #64748b;
  --button-primary-end: #94a3b8;
}

html,
body,
#app {
  min-height: 100%;
}

body {
  position: relative;
  margin: 0;
  background: var(--bg-bottom);
  color: var(--text);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  transition:
    background 180ms ease,
    color 180ms ease;
}

body::before {
  content: "";
  position: fixed;
  inset: -10%;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(circle at 8% 14%, var(--ambient-glow-primary), transparent 24%),
    radial-gradient(circle at 52% -4%, var(--ambient-glow-secondary), transparent 26%),
    radial-gradient(circle at 88% 26%, var(--ambient-glow-tertiary), transparent 22%),
    radial-gradient(circle at 68% 76%, var(--ambient-glow-primary), transparent 28%),
    linear-gradient(126deg, transparent 10%, var(--ambient-ribbon-primary) 28%, transparent 46%),
    linear-gradient(154deg, transparent 18%, var(--ambient-ribbon-secondary) 36%, transparent 58%),
    linear-gradient(96deg, transparent 24%, var(--ambient-ribbon-tertiary) 40%, transparent 64%),
    linear-gradient(115deg, transparent 12%, var(--ambient-band) 36%, transparent 56%);
  filter: blur(26px) saturate(138%);
  mix-blend-mode: screen;
  opacity: 0.72;
  transition: opacity 160ms ease, filter 160ms ease;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: radial-gradient(circle at center, transparent 52%, var(--ambient-vignette) 100%);
  opacity: 0.55;
  transition: opacity 160ms ease;
}

#app {
  position: relative;
  z-index: 1;
}

a {
  color: inherit;
}

button,
input,
select,
textarea {
  font: inherit;
}

.shell {
  display: grid;
  grid-template-columns: 282px minmax(0, 1fr);
  gap: 22px;
  min-height: 100vh;
  min-width: 0;
  padding: 18px;
  box-sizing: border-box;
  color: var(--text);
}

.main {
  position: relative;
  min-width: 0;
  padding: 6px 0 18px;
  box-sizing: border-box;
}

.main::before {
  content: "";
  position: absolute;
  inset: 12px 10px 22px 10px;
  pointer-events: none;
  z-index: 0;
  border-radius: 42px;
  background:
    linear-gradient(128deg, transparent 10%, var(--main-ribbon-accent) 24%, var(--main-ribbon-soft) 34%, transparent 50%),
    linear-gradient(96deg, transparent 18%, var(--main-ribbon-accent) 32%, transparent 54%),
    radial-gradient(circle at 18% 20%, var(--main-ribbon-soft), transparent 22%),
    radial-gradient(circle at 72% 26%, var(--main-ribbon-accent), transparent 18%),
    linear-gradient(180deg, var(--main-ribbon-fill) 0%, rgba(255, 255, 255, 0) 68%);
  background-blend-mode: screen;
  filter: blur(18px) saturate(108%);
  opacity: 0.72;
  transition: opacity 160ms ease, filter 160ms ease;
}

body.overlay-active::before {
  opacity: 0.18;
  filter: blur(14px) saturate(108%);
}

body.overlay-active::after {
  opacity: 0.18;
}

body.overlay-active .main::before {
  opacity: 0.16;
  filter: blur(10px) saturate(100%);
}

.main > * {
  position: relative;
  z-index: 1;
}

@media (max-width: 1100px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .main {
    padding: 0 0 12px;
  }
}

@media (max-width: 860px) {
  .shell {
    padding: 14px;
    gap: 14px;
  }
}
</style>
