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

const themeMode = ref<ThemeMode>("dark")
const accentTheme = ref<AccentTheme>("rose")
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

function applyAccentTheme(theme: AccentTheme): void {
  document.documentElement.dataset.accentTheme = theme
}

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
  mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY)
  const savedAccent = localStorage.getItem(ACCENT_STORAGE_KEY)
  if (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system") {
    themeMode.value = savedTheme
  } else {
    themeMode.value = "dark"
  }
  if (savedAccent === "rose" || savedAccent === "violet" || savedAccent === "aqua" || savedAccent === "amber" || savedAccent === "graphite") {
    accentTheme.value = savedAccent
  } else {
    accentTheme.value = "rose"
  }
  applyTheme(themeMode.value)
  applyAccentTheme(accentTheme.value)
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
  --shadow-soft: 0 26px 70px rgba(190, 143, 143, 0.16), 0 8px 24px rgba(255, 255, 255, 0.42);
  --shadow-card: 0 18px 44px rgba(191, 149, 149, 0.12), 0 4px 18px rgba(255, 255, 255, 0.28);
  --border-strong: rgba(255, 255, 255, 0.7);
  --blur-card: blur(24px) saturate(210%) contrast(1.02);
  --glass-face-top: rgba(255, 255, 255, 0.12);
  --glass-face-bottom: rgba(255, 247, 249, 0.04);
  --glass-sheen-top: rgba(255, 255, 255, 0.68);
  --glass-sheen-mid: rgba(255, 255, 255, 0.18);
  --glass-edge-line: rgba(255, 255, 255, 0.5);
  --glass-edge-shadow: rgba(255, 155, 171, 0.08);
  --theme-bg-spot-1: rgba(255, 179, 188, 0.3);
  --theme-bg-spot-2: rgba(255, 219, 224, 0.22);
  --theme-bg-spot-3: rgba(255, 204, 215, 0.14);
  --theme-bg-spot-4: rgba(255, 225, 230, 0.1);
  --orb-a-color: rgba(255, 162, 177, 0.22);
  --orb-b-color: rgba(255, 207, 214, 0.18);
  --orb-c-color: rgba(255, 182, 196, 0.1);
  --ambient-glow-primary: rgba(255, 178, 191, 0.3);
  --ambient-glow-secondary: rgba(255, 222, 229, 0.24);
  --ambient-glow-tertiary: rgba(255, 197, 211, 0.18);
  --ambient-ribbon-primary: rgba(255, 212, 221, 0.24);
  --ambient-ribbon-secondary: rgba(255, 255, 255, 0.16);
  --ambient-ribbon-tertiary: rgba(255, 191, 206, 0.12);
  --ambient-band: rgba(255, 255, 255, 0.28);
  --ambient-vignette: rgba(255, 245, 247, 0.22);
  --main-ribbon-soft: rgba(255, 255, 255, 0.1);
  --main-ribbon-accent: rgba(255, 216, 224, 0.14);
  --main-ribbon-fill: rgba(255, 255, 255, 0.06);
  --bg-top: #f7f1ef;
  --bg-bottom: #fff7f8;
  --panel: rgba(255, 255, 255, 0.18);
  --panel-strong: rgba(255, 251, 252, 0.24);
  --panel-white: rgba(255, 255, 255, 0.22);
  --panel-blue-soft: rgba(255, 239, 243, 0.38);
  --panel-blue-soft-text: #aa3550;
  --line: rgba(239, 217, 221, 0.82);
  --panel-line-strong: rgba(239, 217, 221, 0.72);
  --panel-line-soft: rgba(239, 217, 221, 0.56);
  --text: #221b1f;
  --muted: #6f5c65;
  --heading-strong: #241d22;
  --heading-soft: #45363d;
  --sidebar-text: #31262d;
  --sidebar-active: var(--accent);
  --accent: #ff6479;
  --accent-2: #ff98a6;
  --accent-soft: rgba(255, 100, 121, 0.16);
  --success: #18b368;
  --danger: #ef4f62;
  --warning: #d89a2e;
  --info: #4d83ff;
  --button-primary-start: var(--accent);
  --button-primary-end: var(--accent-2);
  --button-shadow-color: rgba(255, 111, 128, 0.22);
  --sidebar-bg: rgba(255, 249, 250, 0.18);
  --sidebar-shadow: 0 22px 54px rgba(191, 149, 149, 0.12);
  --sidebar-brand-mark-start: #ff6479;
  --sidebar-brand-mark-end: #ff98a6;
  --theme-switch-bg: rgba(255, 255, 255, 0.2);
  --theme-switch-active-bg: linear-gradient(135deg, rgba(255, 206, 214, 0.34), rgba(255, 244, 246, 0.2));
  --theme-switch-active-text: var(--accent);
  --theme-switch-text: var(--muted);
  --log-message: #2b2127;
  --log-seq: #7a6670;
  --log-time: #8b7781;
  --log-logger: #6d5a64;
  --napcat-chip: #16877d;
  font-family: var(--font-sans);
}

:root[data-theme="dark"] {
  --shadow-soft: 0 30px 84px rgba(0, 0, 0, 0.42), 0 10px 28px rgba(255, 149, 167, 0.04);
  --shadow-card: 0 22px 54px rgba(0, 0, 0, 0.32), 0 4px 18px rgba(255, 149, 167, 0.05);
  --border-strong: rgba(255, 255, 255, 0.12);
  --glass-face-top: rgba(31, 38, 54, 0.12);
  --glass-face-bottom: rgba(21, 27, 38, 0.04);
  --glass-sheen-top: rgba(255, 255, 255, 0.14);
  --glass-sheen-mid: rgba(255, 255, 255, 0.04);
  --glass-edge-line: rgba(255, 255, 255, 0.18);
  --glass-edge-shadow: rgba(5, 8, 16, 0.22);
  --bg-top: #0e1218;
  --bg-bottom: #171c26;
  --panel: rgba(25, 31, 44, 0.16);
  --panel-strong: rgba(18, 24, 35, 0.22);
  --panel-white: rgba(30, 36, 51, 0.3);
  --panel-blue-soft: rgba(66, 90, 128, 0.18);
  --panel-blue-soft-text: #dbe7f5;
  --line: rgba(103, 111, 139, 0.46);
  --panel-line-strong: rgba(103, 111, 139, 0.34);
  --panel-line-soft: rgba(103, 111, 139, 0.24);
  --text: #f6f4f7;
  --muted: #b8adba;
  --heading-strong: #f7f5f8;
  --heading-soft: #d8cfda;
  --sidebar-text: #efeaf1;
  --accent-soft: rgba(255, 120, 135, 0.18);
  --sidebar-bg: rgba(20, 25, 37, 0.18);
  --sidebar-shadow: 0 22px 54px rgba(0, 0, 0, 0.34);
  --theme-switch-bg: rgba(255, 255, 255, 0.06);
  --theme-switch-active-bg: linear-gradient(135deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.04));
  --theme-switch-active-text: #fff8fb;
  --log-message: #f4edf6;
  --log-seq: #d3c6d5;
  --log-time: #b7a9ba;
  --log-logger: #c7b8ca;
  --napcat-chip: #7ce0d4;
  --main-ribbon-soft: rgba(255, 255, 255, 0.06);
  --main-ribbon-accent: rgba(255, 188, 201, 0.08);
  --main-ribbon-fill: rgba(255, 255, 255, 0.02);
}

:root[data-accent-theme="rose"] {
  --accent: #ff6479;
  --accent-2: #ff98a6;
  --button-shadow-color: rgba(255, 111, 128, 0.22);
  --theme-bg-spot-1: rgba(255, 179, 188, 0.3);
  --theme-bg-spot-2: rgba(255, 219, 224, 0.22);
  --theme-bg-spot-3: rgba(255, 204, 215, 0.14);
  --theme-bg-spot-4: rgba(255, 225, 230, 0.1);
  --orb-a-color: rgba(255, 162, 177, 0.22);
  --orb-b-color: rgba(255, 207, 214, 0.18);
  --orb-c-color: rgba(255, 182, 196, 0.1);
  --ambient-glow-primary: rgba(255, 178, 191, 0.3);
  --ambient-glow-secondary: rgba(255, 222, 229, 0.24);
  --ambient-glow-tertiary: rgba(255, 197, 211, 0.18);
  --ambient-ribbon-primary: rgba(255, 212, 221, 0.3);
  --ambient-ribbon-secondary: rgba(255, 255, 255, 0.22);
  --ambient-ribbon-tertiary: rgba(255, 191, 206, 0.18);
  --sidebar-brand-mark-start: #ff6479;
  --sidebar-brand-mark-end: #ff98a6;
}

:root[data-accent-theme="violet"] {
  --accent: #8a63ff;
  --accent-2: #c0a4ff;
  --button-shadow-color: rgba(138, 99, 255, 0.2);
  --theme-bg-spot-1: rgba(201, 183, 255, 0.3);
  --theme-bg-spot-2: rgba(230, 220, 255, 0.22);
  --theme-bg-spot-3: rgba(189, 207, 255, 0.14);
  --theme-bg-spot-4: rgba(221, 213, 255, 0.1);
  --orb-a-color: rgba(188, 163, 255, 0.22);
  --orb-b-color: rgba(219, 205, 255, 0.18);
  --orb-c-color: rgba(181, 202, 255, 0.1);
  --ambient-glow-primary: rgba(196, 176, 255, 0.3);
  --ambient-glow-secondary: rgba(225, 214, 255, 0.24);
  --ambient-glow-tertiary: rgba(177, 197, 255, 0.18);
  --ambient-ribbon-primary: rgba(198, 180, 255, 0.28);
  --ambient-ribbon-secondary: rgba(239, 234, 255, 0.2);
  --ambient-ribbon-tertiary: rgba(177, 202, 255, 0.16);
  --sidebar-brand-mark-start: #8a63ff;
  --sidebar-brand-mark-end: #c0a4ff;
}

:root[data-accent-theme="aqua"] {
  --accent: #28a8c7;
  --accent-2: #7eddf0;
  --button-shadow-color: rgba(40, 168, 199, 0.18);
  --theme-bg-spot-1: rgba(177, 238, 248, 0.28);
  --theme-bg-spot-2: rgba(214, 248, 255, 0.22);
  --theme-bg-spot-3: rgba(174, 218, 255, 0.14);
  --theme-bg-spot-4: rgba(201, 242, 249, 0.1);
  --orb-a-color: rgba(124, 218, 237, 0.2);
  --orb-b-color: rgba(205, 244, 250, 0.16);
  --orb-c-color: rgba(167, 221, 255, 0.1);
  --ambient-glow-primary: rgba(151, 228, 242, 0.28);
  --ambient-glow-secondary: rgba(207, 245, 251, 0.22);
  --ambient-glow-tertiary: rgba(174, 221, 255, 0.16);
  --ambient-ribbon-primary: rgba(155, 229, 242, 0.26);
  --ambient-ribbon-secondary: rgba(232, 250, 255, 0.18);
  --ambient-ribbon-tertiary: rgba(170, 220, 255, 0.14);
  --sidebar-brand-mark-start: #28a8c7;
  --sidebar-brand-mark-end: #7eddf0;
}

:root[data-accent-theme="amber"] {
  --accent: #d89a2e;
  --accent-2: #f0cb88;
  --button-shadow-color: rgba(216, 154, 46, 0.18);
  --theme-bg-spot-1: rgba(255, 220, 174, 0.28);
  --theme-bg-spot-2: rgba(255, 241, 214, 0.22);
  --theme-bg-spot-3: rgba(255, 216, 179, 0.14);
  --theme-bg-spot-4: rgba(255, 236, 203, 0.1);
  --orb-a-color: rgba(248, 209, 138, 0.2);
  --orb-b-color: rgba(255, 237, 204, 0.16);
  --orb-c-color: rgba(255, 216, 164, 0.1);
  --ambient-glow-primary: rgba(248, 214, 155, 0.28);
  --ambient-glow-secondary: rgba(255, 238, 209, 0.22);
  --ambient-glow-tertiary: rgba(255, 214, 158, 0.16);
  --ambient-ribbon-primary: rgba(248, 214, 156, 0.26);
  --ambient-ribbon-secondary: rgba(255, 247, 229, 0.18);
  --ambient-ribbon-tertiary: rgba(255, 222, 174, 0.14);
  --sidebar-brand-mark-start: #d89a2e;
  --sidebar-brand-mark-end: #f0cb88;
}

:root[data-accent-theme="graphite"] {
  --accent: #6f829c;
  --accent-2: #a7b4c6;
  --button-shadow-color: rgba(111, 130, 156, 0.16);
  --theme-bg-spot-1: rgba(210, 218, 231, 0.26);
  --theme-bg-spot-2: rgba(236, 241, 248, 0.2);
  --theme-bg-spot-3: rgba(198, 214, 232, 0.14);
  --theme-bg-spot-4: rgba(225, 232, 240, 0.1);
  --orb-a-color: rgba(184, 197, 214, 0.18);
  --orb-b-color: rgba(228, 235, 244, 0.16);
  --orb-c-color: rgba(191, 208, 229, 0.1);
  --ambient-glow-primary: rgba(199, 209, 223, 0.24);
  --ambient-glow-secondary: rgba(232, 238, 246, 0.18);
  --ambient-glow-tertiary: rgba(187, 205, 227, 0.14);
  --ambient-ribbon-primary: rgba(197, 210, 225, 0.22);
  --ambient-ribbon-secondary: rgba(239, 244, 250, 0.16);
  --ambient-ribbon-tertiary: rgba(186, 204, 227, 0.12);
  --sidebar-brand-mark-start: #6f829c;
  --sidebar-brand-mark-end: #a7b4c6;
}

html,
body,
#app {
  min-height: 100%;
}

body {
  position: relative;
  margin: 0;
  background:
    radial-gradient(circle at 12% 12%, var(--theme-bg-spot-1), transparent 0, transparent 25%),
    radial-gradient(circle at 46% 0%, var(--theme-bg-spot-2), transparent 0, transparent 26%),
    radial-gradient(circle at 88% 20%, var(--theme-bg-spot-3), transparent 0, transparent 24%),
    radial-gradient(circle at 68% 74%, var(--theme-bg-spot-4), transparent 0, transparent 30%),
    linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
  background-attachment: fixed;
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
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: radial-gradient(circle at center, transparent 52%, var(--ambient-vignette) 100%);
  opacity: 0.55;
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
