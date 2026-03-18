<template>
  <div class="shell">
    <AppSidebar />
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import AppSidebar from "./components/AppSidebar.vue"
</script>

<style>
:root {
  color-scheme: light;
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
  font-family:
    "Noto Sans SC",
    "PingFang SC",
    "Microsoft YaHei",
    sans-serif;
}

body {
  margin: 0;
  background:
    radial-gradient(circle at top left, rgba(15, 108, 184, 0.15), transparent 28%),
    radial-gradient(circle at bottom right, rgba(242, 166, 90, 0.14), transparent 24%),
    linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
  color: var(--text);
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

@media (max-width: 960px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .main {
    padding: 16px;
  }
}
</style>
