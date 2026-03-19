<template>
  <div class="shell">
    <AppSidebar :theme-mode="themeMode" @update:theme-mode="setThemeMode" />
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

const THEME_STORAGE_KEY = "acabot.theme_mode"

const themeMode = ref<ThemeMode>("dark")
let mediaQuery: MediaQueryList | null = null

function systemTheme(): "light" | "dark" {
  return mediaQuery?.matches ? "dark" : "light"
}

function applyTheme(mode: ThemeMode): void {
  const effectiveTheme = mode === "system" ? systemTheme() : mode
  document.documentElement.dataset.themeMode = mode
  document.documentElement.dataset.theme = effectiveTheme
  document.documentElement.style.colorScheme = effectiveTheme
}

function setThemeMode(mode: ThemeMode): void {
  themeMode.value = mode
  localStorage.setItem(THEME_STORAGE_KEY, mode)
  applyTheme(mode)
}

function handleSystemThemeChange(): void {
  if (themeMode.value === "system") {
    applyTheme("system")
  }
}

onMounted(() => {
  mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
  const saved = localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === "light" || saved === "dark" || saved === "system") {
    themeMode.value = saved
  } else {
    themeMode.value = "dark"
  }
  applyTheme(themeMode.value)
  mediaQuery.addEventListener("change", handleSystemThemeChange)
})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", handleSystemThemeChange)
})
</script>

<style>
:root {
  --bg-top: #eff6ff;
  --bg-bottom: #f7f4ec;
  --panel: rgba(255, 255, 255, 0.82);
  --panel-strong: rgba(255, 255, 255, 0.94);
  --line: rgba(28, 56, 90, 0.12);
  --text: #132944;
  --muted: #65758b;
  --accent: #0f6cb8;
  --accent-soft: rgba(15, 108, 184, 0.12);
  --warm: #f2a65a;
  --shadow: 0 18px 48px rgba(16, 42, 67, 0.08);
  --success: #166534;
  --danger: #b42318;
  --warning: #9a5a05;
  --heading-strong: #173257;
  --heading-soft: #1f2f49;
  --sidebar-text: #23334f;
  --sidebar-active: #0b4f83;
  --button-primary-start: #0f6cb8;
  --button-primary-end: #0a4a7b;
  --panel-white: #fff;
  --panel-blue-soft: #dff0ff;
  --panel-blue-soft-text: #0b4f83;
  --panel-line-strong: #d5deea;
  --panel-line-soft: #cdd8e9;
  --log-message: #19304d;
  --log-seq: #35506f;
  --log-time: #52667f;
  --log-logger: #40556f;
  --napcat-chip: #0f766e;
  --sidebar-bg: linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(245, 249, 255, 0.76) 100%);
  --sidebar-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.55);
  --sidebar-brand-mark-start: #0f6cb8;
  --sidebar-brand-mark-end: #0a4a7b;
  --theme-switch-bg: rgba(15, 108, 184, 0.08);
  --theme-switch-active-bg: linear-gradient(135deg, rgba(15, 108, 184, 0.2), rgba(15, 108, 184, 0.1));
  --theme-switch-active-text: #0b4f83;
  --theme-switch-text: #52667f;
  font-family:
    "Noto Sans SC",
    "PingFang SC",
    "Microsoft YaHei",
    sans-serif;
}

:root[data-theme="dark"] {
  --bg-top: #07111d;
  --bg-bottom: #0c1624;
  --panel: rgba(15, 25, 40, 0.9);
  --panel-strong: rgba(22, 34, 52, 0.98);
  --line: rgba(129, 165, 209, 0.16);
  --text: #e6eef8;
  --muted: #9cb2cc;
  --accent: #66b7ff;
  --accent-soft: rgba(102, 183, 255, 0.16);
  --warm: #f0b164;
  --shadow: 0 28px 60px rgba(0, 0, 0, 0.42);
  --success: #6ed49a;
  --danger: #ff8a80;
  --warning: #ffcc80;
  --heading-strong: #f3f7fc;
  --heading-soft: #d7e3f2;
  --sidebar-text: #d8e4f3;
  --sidebar-active: #9fd2ff;
  --button-primary-start: #1f7cc7;
  --button-primary-end: #16598f;
  --panel-white: rgba(20, 31, 47, 0.92);
  --panel-blue-soft: rgba(64, 122, 179, 0.16);
  --panel-blue-soft-text: #9fd2ff;
  --panel-line-strong: rgba(125, 156, 196, 0.22);
  --panel-line-soft: rgba(125, 156, 196, 0.18);
  --log-message: #edf4fb;
  --log-seq: #c1d5ea;
  --log-time: #9cb2cc;
  --log-logger: #b2c5dc;
  --napcat-chip: #7ce0d4;
  --sidebar-bg: linear-gradient(180deg, rgba(10, 18, 29, 0.98) 0%, rgba(13, 23, 37, 0.98) 100%);
  --sidebar-shadow: inset -1px 0 0 rgba(129, 165, 209, 0.12), 12px 0 40px rgba(0, 0, 0, 0.2);
  --sidebar-brand-mark-start: #2d8de0;
  --sidebar-brand-mark-end: #195e96;
  --theme-switch-bg: rgba(129, 165, 209, 0.08);
  --theme-switch-active-bg: linear-gradient(135deg, rgba(102, 183, 255, 0.28), rgba(53, 122, 191, 0.16));
  --theme-switch-active-text: #eaf6ff;
  --theme-switch-text: #aac0d8;
}

body {
  margin: 0;
  background:
    radial-gradient(circle at top left, rgba(15, 108, 184, 0.16), transparent 26%),
    radial-gradient(circle at 70% 20%, rgba(49, 98, 162, 0.1), transparent 26%),
    radial-gradient(circle at bottom right, rgba(242, 166, 90, 0.12), transparent 22%),
    linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
  color: var(--text);
  transition:
    background 180ms ease,
    color 180ms ease;
}

#app {
  min-height: 100vh;
  min-width: 0;
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
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: 100vh;
  min-width: 0;
  color: var(--text);
}

.main {
  min-width: 0;
  padding: 24px 28px;
  box-sizing: border-box;
}

:root[data-theme="dark"] .main {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.015) 0%, rgba(255, 255, 255, 0) 100%);
}

@media (max-width: 960px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .main {
    padding: 16px;
  }
}
</style>
