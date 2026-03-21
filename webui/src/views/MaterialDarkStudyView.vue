<script setup lang="ts">
import { computed } from "vue"
type DarkVariant =
  | "smoked-graphite"
  | "mineral-dusk"
  | "slate-flagship"
  | "monochrome-graphite"
  | "cold-black-titanium"
  | "warm-black-ore"
  | "blue-black-flagship"

type DarkVariantSpec = {
  label: string
  subtitle: string
  heroTitle: string
  heroBody: string
  vars: Record<string, string>
}

const props = withDefaults(
  defineProps<{
    variant?: DarkVariant
  }>(),
  {
    variant: "cold-black-titanium",
  },
)

const variantPaths: Array<{ key: DarkVariant; path: string }> = [
  {
    key: "smoked-graphite",
    path: "/preview/material-dark/smoked-graphite",
  },
  {
    key: "mineral-dusk",
    path: "/preview/material-dark/mineral-dusk",
  },
  {
    key: "slate-flagship",
    path: "/preview/material-dark/slate-flagship",
  },
  {
    key: "monochrome-graphite",
    path: "/preview/material-dark/monochrome-graphite",
  },
  {
    key: "cold-black-titanium",
    path: "/preview/material-dark/cold-black-titanium",
  },
  {
    key: "warm-black-ore",
    path: "/preview/material-dark/warm-black-ore",
  },
  {
    key: "blue-black-flagship",
    path: "/preview/material-dark/blue-black-flagship",
  },
]

const variantSpecs: Record<DarkVariant, DarkVariantSpec> = {
  "smoked-graphite": {
    label: "Soft Dark / Smoked Graphite",
    subtitle: "烟灰石墨",
    heroTitle: "Smoked Graphite Console",
    heroBody:
      "把整体亮度抬一档，让深色更像高端室内里的烟灰石墨，而不是深夜关灯后的黑盒子。主体依然近中性，不让色相乱入。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(255, 255, 255, 0.05), transparent 24%), linear-gradient(180deg, #15181c 0%, #1b2026 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(39, 44, 51, 0.98), rgba(30, 35, 41, 1))",
      "--panel-low": "linear-gradient(180deg, rgba(31, 35, 41, 0.98), rgba(24, 28, 33, 1))",
      "--panel-high": "linear-gradient(180deg, rgba(47, 53, 61, 0.98), rgba(36, 41, 48, 1))",
      "--panel-tint": "rgba(255, 255, 255, 0.02)",
      "--panel-border": "rgba(231, 236, 242, 0.1)",
      "--panel-hairline": "rgba(255, 255, 255, 0.05)",
      "--text": "#f0f3f6",
      "--muted": "#c9d0d8",
      "--muted-2": "#95a0ac",
      "--primary": "#eef2f6",
      "--primary-strong": "#c4ccd4",
      "--primary-container": "#3b424a",
      "--outline": "#636d78",
      "--positive": "#c1d4c7",
      "--warning": "#d8ccb7",
      "--danger": "#d9c0c0",
      "--surface-shadow": "0 14px 34px rgba(0, 0, 0, 0.24)",
      "--hero-glow": "rgba(255, 255, 255, 0.038)",
      "--bar-top": "#eff3f6",
      "--bar-bottom": "#6a7581",
      "--chip-selected": "rgba(204, 212, 220, 0.14)",
      "--button-fill": "linear-gradient(180deg, #f1f4f7, #b2bbc4)",
      "--button-text": "#111418",
    },
  },
  "mineral-dusk": {
    label: "Soft Dark / Mineral Dusk",
    subtitle: "矿物暮色",
    heroTitle: "Mineral Dusk Console",
    heroBody:
      "把暖黑矿从“黑褐”提到“烟暖灰”。保留矿物和陶感，但降低土气，让夜间面板更像柔和石材和高级纸面。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(233, 205, 170, 0.07), transparent 24%), linear-gradient(180deg, #1c1916 0%, #221e1a 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(49, 43, 38, 0.98), rgba(38, 33, 29, 1))",
      "--panel-low": "linear-gradient(180deg, rgba(41, 36, 32, 0.98), rgba(31, 27, 24, 1))",
      "--panel-high": "linear-gradient(180deg, rgba(59, 52, 46, 0.98), rgba(45, 39, 34, 1))",
      "--panel-tint": "rgba(244, 226, 201, 0.02)",
      "--panel-border": "rgba(243, 229, 212, 0.095)",
      "--panel-hairline": "rgba(255, 246, 236, 0.048)",
      "--text": "#f1e7dc",
      "--muted": "#d5c6b7",
      "--muted-2": "#9d9184",
      "--primary": "#f0ddd0",
      "--primary-strong": "#ccb2a0",
      "--primary-container": "#4a4038",
      "--outline": "#70665d",
      "--positive": "#c6d6ca",
      "--warning": "#dbc69c",
      "--danger": "#ddbdb5",
      "--surface-shadow": "0 14px 34px rgba(0, 0, 0, 0.25)",
      "--hero-glow": "rgba(243, 221, 191, 0.04)",
      "--bar-top": "#efddcc",
      "--bar-bottom": "#84705d",
      "--chip-selected": "rgba(213, 192, 171, 0.14)",
      "--button-fill": "linear-gradient(180deg, #f1dfd0, #c3a48a)",
      "--button-text": "#17110c",
    },
  },
  "slate-flagship": {
    label: "Soft Dark / Slate Flagship",
    subtitle: "石板旗舰",
    heroTitle: "Slate Flagship Console",
    heroBody:
      "保留旗舰 Android 那种精密、清爽、略带海军蓝的高级感，但整体抬亮成石板灰环境，不再沉到发闷。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(176, 205, 246, 0.08), transparent 24%), linear-gradient(180deg, #141920 0%, #1b212a 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(35, 45, 58, 0.98), rgba(25, 33, 43, 1))",
      "--panel-low": "linear-gradient(180deg, rgba(28, 36, 46, 0.98), rgba(21, 28, 36, 1))",
      "--panel-high": "linear-gradient(180deg, rgba(43, 55, 69, 0.98), rgba(31, 40, 50, 1))",
      "--panel-tint": "rgba(187, 214, 249, 0.024)",
      "--panel-border": "rgba(217, 230, 247, 0.095)",
      "--panel-hairline": "rgba(255, 255, 255, 0.05)",
      "--text": "#ebf2fa",
      "--muted": "#c8d5e5",
      "--muted-2": "#98a9bc",
      "--primary": "#e6f0fc",
      "--primary-strong": "#afc4df",
      "--primary-container": "#334557",
      "--outline": "#607283",
      "--positive": "#c5dccf",
      "--warning": "#dfc896",
      "--danger": "#dcbfc0",
      "--surface-shadow": "0 14px 34px rgba(0, 0, 0, 0.26)",
      "--hero-glow": "rgba(181, 212, 251, 0.05)",
      "--bar-top": "#e6f0fc",
      "--bar-bottom": "#637d9a",
      "--chip-selected": "rgba(183, 205, 234, 0.15)",
      "--button-fill": "linear-gradient(180deg, #ebf3fd, #9ab6d5)",
      "--button-text": "#111821",
    },
  },
  "monochrome-graphite": {
    label: "Monochrome Graphite",
    subtitle: "单色石墨",
    heroTitle: "Monochrome Night Console",
    heroBody:
      "主体几乎不带色相，只用近黑、近灰、近白。让高级感回到材质、比例、边界和排版，而不是依赖彩色深色。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(255, 255, 255, 0.035), transparent 22%), linear-gradient(180deg, #060708 0%, #0d1013 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(19, 22, 26, 0.98), rgba(14, 17, 20, 1))",
      "--panel-low": "linear-gradient(180deg, rgba(14, 17, 20, 0.98), rgba(10, 12, 15, 1))",
      "--panel-high": "linear-gradient(180deg, rgba(25, 29, 34, 0.98), rgba(16, 19, 23, 1))",
      "--panel-tint": "rgba(255, 255, 255, 0.018)",
      "--panel-border": "rgba(228, 234, 240, 0.072)",
      "--panel-hairline": "rgba(255, 255, 255, 0.04)",
      "--text": "#f0f3f6",
      "--muted": "#c3cad3",
      "--muted-2": "#8d97a3",
      "--primary": "#edf1f5",
      "--primary-strong": "#bcc5cf",
      "--primary-container": "#2c3238",
      "--outline": "#4e5761",
      "--positive": "#bccabe",
      "--warning": "#d1c7b4",
      "--danger": "#d0bcbc",
      "--surface-shadow": "0 18px 48px rgba(0, 0, 0, 0.34)",
      "--hero-glow": "rgba(255, 255, 255, 0.03)",
      "--bar-top": "#edf1f5",
      "--bar-bottom": "#555f69",
      "--chip-selected": "rgba(198, 206, 214, 0.12)",
      "--button-fill": "linear-gradient(180deg, #eef2f6, #a4adb7)",
      "--button-text": "#090b0d",
    },
  },
  "cold-black-titanium": {
    label: "Cold Black Titanium",
    subtitle: "冷黑钛",
    heroTitle: "Titanium Control Deck",
    heroBody:
      "冷黑、钛灰、近白高光。目标不是更亮，而是更硬、更准、更像高级硬件表面和专业生产力系统。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(186, 206, 235, 0.08), transparent 26%), radial-gradient(circle at 18% 12%, rgba(255, 255, 255, 0.04), transparent 24%), linear-gradient(180deg, #090b0e 0%, #101319 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(23, 28, 35, 0.96), rgba(16, 20, 27, 0.98))",
      "--panel-low": "linear-gradient(180deg, rgba(18, 23, 29, 0.96), rgba(13, 17, 22, 0.98))",
      "--panel-high": "linear-gradient(180deg, rgba(31, 37, 46, 0.98), rgba(21, 26, 33, 0.98))",
      "--panel-tint": "rgba(197, 214, 235, 0.05)",
      "--panel-border": "rgba(200, 212, 229, 0.09)",
      "--panel-hairline": "rgba(255, 255, 255, 0.055)",
      "--text": "#edf1f7",
      "--muted": "#b2bcc9",
      "--muted-2": "#8994a3",
      "--primary": "#dbe6f4",
      "--primary-strong": "#90a7c4",
      "--primary-container": "#273545",
      "--outline": "#495462",
      "--positive": "#8fd7ae",
      "--warning": "#efc37d",
      "--danger": "#ffb8b0",
      "--surface-shadow": "0 18px 48px rgba(0, 0, 0, 0.34)",
      "--hero-glow": "rgba(215, 226, 240, 0.06)",
      "--bar-top": "#d7e3f1",
      "--bar-bottom": "#425669",
      "--chip-selected": "rgba(149, 169, 194, 0.2)",
      "--button-fill": "linear-gradient(180deg, #dce6f2, #8ca1bb)",
      "--button-text": "#0d1218",
    },
  },
  "warm-black-ore": {
    label: "Warm Black Ore",
    subtitle: "暖黑矿",
    heroTitle: "Mineral Night Console",
    heroBody:
      "不是把暖白矿物直接压暗，而是改成更像烧制陶面、矿石切面和深色纸张的夜间材质。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(224, 181, 122, 0.1), transparent 26%), radial-gradient(circle at 10% 20%, rgba(255, 238, 215, 0.03), transparent 22%), linear-gradient(180deg, #120d0a 0%, #18120f 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(36, 28, 22, 0.96), rgba(23, 18, 14, 0.98))",
      "--panel-low": "linear-gradient(180deg, rgba(30, 23, 18, 0.96), rgba(18, 14, 11, 0.98))",
      "--panel-high": "linear-gradient(180deg, rgba(48, 38, 30, 0.98), rgba(28, 22, 17, 0.98))",
      "--panel-tint": "rgba(229, 191, 139, 0.05)",
      "--panel-border": "rgba(238, 214, 185, 0.08)",
      "--panel-hairline": "rgba(255, 247, 236, 0.05)",
      "--text": "#f1e6d8",
      "--muted": "#d0bfad",
      "--muted-2": "#9d8f82",
      "--primary": "#f0d3ad",
      "--primary-strong": "#bd9265",
      "--primary-container": "#4f3c2d",
      "--outline": "#66584d",
      "--positive": "#98d6b0",
      "--warning": "#f1c57e",
      "--danger": "#ffb49c",
      "--surface-shadow": "0 18px 48px rgba(0, 0, 0, 0.36)",
      "--hero-glow": "rgba(238, 205, 159, 0.06)",
      "--bar-top": "#eccda5",
      "--bar-bottom": "#70533a",
      "--chip-selected": "rgba(210, 168, 115, 0.18)",
      "--button-fill": "linear-gradient(180deg, #f0d7b4, #ab7e51)",
      "--button-text": "#17100a",
    },
  },
  "blue-black-flagship": {
    label: "Blue Black Flagship",
    subtitle: "旗舰蓝黑",
    heroTitle: "Flagship Night Runtime",
    heroBody:
      "保留一点高端 Android 旗舰设备的深海军蓝气质，但把俗气的科技蓝去掉，只留下干净的夜间旗舰感。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(110, 156, 226, 0.14), transparent 28%), radial-gradient(circle at 78% 14%, rgba(191, 220, 255, 0.04), transparent 20%), linear-gradient(180deg, #08111a 0%, #101926 100%)",
      "--panel-bg": "linear-gradient(180deg, rgba(19, 28, 39, 0.96), rgba(13, 20, 30, 0.98))",
      "--panel-low": "linear-gradient(180deg, rgba(15, 23, 33, 0.96), rgba(11, 17, 24, 0.98))",
      "--panel-high": "linear-gradient(180deg, rgba(26, 38, 52, 0.98), rgba(16, 24, 34, 0.98))",
      "--panel-tint": "rgba(140, 181, 237, 0.06)",
      "--panel-border": "rgba(199, 217, 242, 0.08)",
      "--panel-hairline": "rgba(255, 255, 255, 0.045)",
      "--text": "#ebf2fb",
      "--muted": "#bfd0e5",
      "--muted-2": "#8b9eb8",
      "--primary": "#c9defd",
      "--primary-strong": "#78a7df",
      "--primary-container": "#173a63",
      "--outline": "#405265",
      "--positive": "#95dfb4",
      "--warning": "#f0c57d",
      "--danger": "#ffb5ab",
      "--surface-shadow": "0 18px 48px rgba(0, 0, 0, 0.4)",
      "--hero-glow": "rgba(132, 182, 248, 0.08)",
      "--bar-top": "#bfd9ff",
      "--bar-bottom": "#33557f",
      "--chip-selected": "rgba(106, 155, 224, 0.22)",
      "--button-fill": "linear-gradient(180deg, #d3e4ff, #5f8fcb)",
      "--button-text": "#07111b",
    },
  },
}

const navItems = [
  { label: "Overview", active: true },
  { label: "Sessions", active: false },
  { label: "Models", active: false },
  { label: "Plugins", active: false },
  { label: "Logs", active: false },
]

const summaryCards = [
  { label: "Runtime health", value: "Stable", detail: "12 services healthy, no blocked queues" },
  { label: "Median latency", value: "842 ms", detail: "Down 180 ms compared with yesterday" },
  { label: "Open threads", value: "128", detail: "Active in the last 10 minutes" },
  { label: "Alerts", value: "03", detail: "Require maintainer review" },
]

const quickFilters = ["All systems", "Gateway", "Models", "Memory", "Plugins"]
const barHeights = [24, 39, 62, 48, 74, 66, 88, 70, 53, 75, 56, 68]

const eventRows = [
  {
    time: "08:42",
    title: "NapCat reconnect",
    note: "Recovered in 4 seconds without message backlog.",
    tone: "positive",
  },
  {
    time: "08:39",
    title: "Fallback chain activated",
    note: "Summary lane intercepted two requests and then returned to normal.",
    tone: "warning",
  },
  {
    time: "08:33",
    title: "Plugin timeout pocket",
    note: "image-captioner entered cooldown after the third timeout.",
    tone: "danger",
  },
]

const queueRows = [
  ["maintainer.pi", "config.models.save -> reload.registry", "0.48s", "Applied"],
  ["qq:group:114514", "summary.compact -> publish.reply", "0.91s", "Running"],
  ["qq:private:1733064202", "skills.resolve -> tools.search", "1.24s", "Queued"],
  ["qq:group:424242", "vision.caption -> response.render", "1.87s", "Running"],
]

const currentVariant = computed(() => variantSpecs[props.variant])
</script>

<template>
  <section class="material-dark-study" :style="currentVariant.vars">
    <div class="app-shell">
      <aside class="nav-rail">
        <div class="brand-mark">AC</div>
        <nav class="rail-nav">
          <button
            v-for="item in navItems"
            :key="item.label"
            class="rail-item"
            :class="{ active: item.active }"
            type="button"
          >
            <span class="rail-icon"></span>
            <span>{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <main class="workspace">
        <header class="top-bar">
          <div>
            <p class="eyebrow">Preview / Material Dark Study</p>
            <h1>{{ currentVariant.heroTitle }}</h1>
            <p class="supporting">只看深色，不再拿抽象描述说服你。</p>
          </div>
          <button class="filled-button" type="button">Sync state</button>
        </header>

        <section class="hero-card">
          <div class="hero-copy">
            <p class="hero-label">Premium dark Material</p>
            <div class="hero-header">
              <h2>{{ currentVariant.label }}</h2>
              <span class="mode-pill">{{ currentVariant.subtitle }}</span>
            </div>
            <p>{{ currentVariant.heroBody }}</p>
          </div>

          <div class="variant-row">
            <RouterLink
              v-for="item in variantPaths"
              :key="item.path"
              class="variant-chip"
              :class="{ active: item.key === variant }"
              :to="item.path"
            >
              <span>{{ variantSpecs[item.key].label }}</span>
              <small>{{ variantSpecs[item.key].subtitle }}</small>
            </RouterLink>
          </div>

          <div class="chip-row">
            <button
              v-for="(filter, index) in quickFilters"
              :key="filter"
              class="filter-chip"
              :class="{ selected: index === 0 }"
              type="button"
            >
              {{ filter }}
            </button>
          </div>
        </section>

        <section class="summary-grid">
          <article v-for="card in summaryCards" :key="card.label" class="summary-card">
            <span class="summary-label">{{ card.label }}</span>
            <strong class="summary-value">{{ card.value }}</strong>
            <p class="summary-detail">{{ card.detail }}</p>
          </article>
        </section>

        <section class="content-grid">
          <article class="surface-card chart-panel">
            <div class="panel-header">
              <div>
                <p class="panel-label">Realtime throughput</p>
                <h3>Primary lane</h3>
              </div>
              <button class="text-button" type="button">Last 10 min</button>
            </div>

            <div class="chart-box">
              <div class="bars">
                <span
                  v-for="(height, index) in barHeights"
                  :key="index"
                  class="bar"
                  :style="{ height: `${height}%` }"
                ></span>
              </div>
              <div class="ticks">
                <span>02:00</span>
                <span>04:00</span>
                <span>06:00</span>
                <span>08:00</span>
              </div>
            </div>

            <div class="insight-row">
              <article class="tonal-card">
                <span>Response lane</span>
                <strong>Stable</strong>
              </article>
              <article class="tonal-card">
                <span>Retry pressure</span>
                <strong>Low</strong>
              </article>
              <article class="tonal-card">
                <span>Operator load</span>
                <strong>76%</strong>
              </article>
            </div>
          </article>

          <article class="surface-card event-panel">
            <div class="panel-header">
              <div>
                <p class="panel-label">Recent events</p>
                <h3>Activity feed</h3>
              </div>
              <span class="count-pill">3 active</span>
            </div>

            <div class="event-list">
              <article
                v-for="item in eventRows"
                :key="`${item.time}-${item.title}`"
                class="event-item"
                :class="`tone-${item.tone}`"
              >
                <span class="event-time">{{ item.time }}</span>
                <div>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.note }}</p>
                </div>
              </article>
            </div>
          </article>

          <article class="surface-card table-panel">
            <div class="panel-header">
              <div>
                <p class="panel-label">Execution queue</p>
                <h3>Live commands</h3>
              </div>
              <button class="outlined-button" type="button">Inspect queue</button>
            </div>

            <div class="table-head">
              <span>Actor</span>
              <span>Pipeline</span>
              <span>Latency</span>
              <span>State</span>
            </div>
            <div v-for="row in queueRows" :key="row.join('-')" class="table-row">
              <span>{{ row[0] }}</span>
              <span>{{ row[1] }}</span>
              <span>{{ row[2] }}</span>
              <span class="state-pill">{{ row[3] }}</span>
            </div>
          </article>

          <article class="surface-card detail-panel">
            <div class="panel-header">
              <div>
                <p class="panel-label">Detail editor</p>
                <h3>Maintainer draft</h3>
              </div>
              <button class="filled-tonal-button" type="button">Save draft</button>
            </div>

            <div class="form-grid">
              <label class="field">
                <span>Workspace</span>
                <input type="text" value="maintainer.pi" />
              </label>
              <label class="field">
                <span>Preset</span>
                <select>
                  <option>gpt-5.4 / primary</option>
                </select>
              </label>
              <label class="field full">
                <span>Intent</span>
                <input type="text" value="看深色到底是发糊、发闷，还是已经开始有贵感" />
              </label>
              <label class="field full">
                <span>Operator note</span>
                <textarea rows="5">这页只讲深色。哪个看着最像旗舰产品，哪个最像夜间设备控制面，一眼就能分出来。</textarea>
              </label>
            </div>
          </article>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.material-dark-study {
  background: var(--page-bg);
  color: var(--text);
  min-height: calc(100vh - 48px);
  padding-bottom: 16px;
  font-family:
    "Roboto Flex",
    "Roboto",
    "Noto Sans SC",
    "PingFang SC",
    sans-serif;
}

.app-shell {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 18px;
}

.nav-rail {
  display: grid;
  gap: 16px;
  padding: 18px 10px 16px;
}

.brand-mark,
.rail-item,
.surface-card,
.summary-card,
.event-item,
.table-row,
.tonal-card,
.hero-card {
  box-shadow: var(--surface-shadow);
}

.brand-mark {
  width: 56px;
  height: 56px;
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, var(--primary-container), color-mix(in srgb, var(--primary-container) 80%, black));
  color: var(--primary);
  font-weight: 700;
}

.rail-nav {
  display: grid;
  gap: 10px;
}

.rail-item {
  border: 1px solid transparent;
  border-radius: 22px;
  padding: 12px 8px;
  display: grid;
  gap: 8px;
  justify-items: center;
  background: transparent;
  color: var(--muted-2);
  cursor: pointer;
  font-size: 12px;
}

.rail-item.active {
  border-color: var(--panel-border);
  background: linear-gradient(180deg, color-mix(in srgb, var(--primary-container) 58%, transparent), rgba(255, 255, 255, 0.02));
  color: var(--text);
}

.rail-icon {
  width: 24px;
  height: 24px;
  border-radius: 8px;
  background: currentColor;
  opacity: 0.18;
}

.workspace {
  display: grid;
  gap: 18px;
  padding: 18px 18px 16px 0;
}

.top-bar,
.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.eyebrow,
.panel-label,
.hero-label,
.summary-label,
.table-head,
.field span {
  margin: 0;
  color: var(--muted-2);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  margin-top: 4px;
  color: var(--text);
  font-size: clamp(34px, 4vw, 48px);
  line-height: 1.04;
  letter-spacing: -0.04em;
  font-weight: 430;
}

h2 {
  font-size: 28px;
  line-height: 1.08;
  font-weight: 430;
}

h3 {
  margin-top: 4px;
  font-size: 22px;
  line-height: 1.08;
  font-weight: 430;
}

.supporting,
.hero-card p,
.summary-detail,
.event-item p,
.variant-chip small {
  color: var(--muted);
  line-height: 1.54;
}

.supporting {
  margin-top: 8px;
}

.filled-button,
.filled-tonal-button,
.outlined-button,
.text-button,
input,
select,
textarea {
  font: inherit;
}

.filled-button,
.filled-tonal-button,
.outlined-button,
.text-button {
  border-radius: 999px;
  padding: 10px 14px;
  cursor: pointer;
}

.filled-button {
  border: 0;
  background: var(--button-fill);
  color: var(--button-text);
}

.filled-tonal-button {
  border: 0;
  background: linear-gradient(180deg, color-mix(in srgb, var(--primary-container) 90%, var(--panel-high)), color-mix(in srgb, var(--primary-container) 74%, black));
  color: var(--primary);
}

.outlined-button {
  border: 1px solid var(--outline);
  background: transparent;
  color: var(--text);
}

.text-button {
  border: 0;
  background: transparent;
  color: var(--primary);
}

.hero-card,
.summary-card,
.surface-card {
  position: relative;
  border: 1px solid var(--panel-border);
  background:
    linear-gradient(180deg, var(--panel-bg), var(--panel-low)),
    linear-gradient(135deg, var(--panel-tint), transparent 46%);
}

.hero-card::before,
.summary-card::before,
.surface-card::before {
  content: "";
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  border-top: 1px solid var(--panel-hairline);
  pointer-events: none;
}

.hero-card {
  display: grid;
  gap: 18px;
  border-radius: 32px;
  padding: 24px;
  overflow: hidden;
}

.hero-card::after {
  content: "";
  position: absolute;
  inset: auto -120px -120px auto;
  width: 280px;
  height: 280px;
  border-radius: 999px;
  background: radial-gradient(circle, var(--hero-glow), transparent 68%);
  pointer-events: none;
}

.hero-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-top: 8px;
}

.mode-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary-container) 72%, transparent);
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
}

.variant-row,
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.variant-chip {
  display: grid;
  gap: 3px;
  min-width: 180px;
  padding: 12px 14px;
  border: 1px solid var(--outline);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.02);
  color: inherit;
  text-decoration: none;
}

.variant-chip span {
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
}

.variant-chip.active {
  border-color: transparent;
  background: var(--chip-selected);
}

.filter-chip {
  border: 1px solid var(--outline);
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  padding: 9px 12px;
  cursor: pointer;
}

.filter-chip.selected {
  border-color: transparent;
  background: color-mix(in srgb, var(--primary-container) 58%, transparent);
  color: var(--primary);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.summary-card {
  display: grid;
  gap: 10px;
  border-radius: 24px;
  padding: 16px 18px;
}

.summary-value {
  color: var(--text);
  font-size: 36px;
  line-height: 1;
  letter-spacing: -0.06em;
  font-weight: 430;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.95fr);
  gap: 14px;
}

.surface-card {
  border-radius: 24px;
  padding: 18px;
}

.chart-panel {
  display: grid;
  gap: 18px;
}

.chart-box {
  border: 1px solid var(--panel-border);
  border-radius: 26px;
  padding: 16px;
  background:
    linear-gradient(180deg, var(--panel-high), rgba(255, 255, 255, 0.01)),
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent);
}

.bars {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
  height: 230px;
  border-bottom: 1px solid color-mix(in srgb, var(--outline) 72%, transparent);
  background:
    repeating-linear-gradient(
      to top,
      color-mix(in srgb, var(--outline) 40%, transparent) 0,
      color-mix(in srgb, var(--outline) 40%, transparent) 1px,
      transparent 1px,
      transparent 52px
    );
}

.bar {
  border-radius: 999px 999px 10px 10px;
  background: linear-gradient(180deg, var(--bar-top), var(--bar-bottom));
}

.ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}

.insight-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.tonal-card {
  display: grid;
  gap: 8px;
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  padding: 14px;
  background: var(--panel-high);
  color: var(--primary);
}

.event-panel,
.detail-panel {
  display: grid;
  gap: 14px;
}

.event-list {
  display: grid;
  gap: 10px;
}

.event-item {
  display: grid;
  grid-template-columns: 60px 1fr;
  gap: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  padding: 14px;
  background: var(--panel-high);
}

.event-time {
  color: var(--text);
  font-size: 13px;
  font-weight: 620;
}

.event-item strong {
  color: var(--text);
  font-size: 18px;
  line-height: 1.14;
  font-weight: 430;
}

.tone-positive .event-time {
  color: var(--positive);
}

.tone-warning .event-time {
  color: var(--warning);
}

.tone-danger .event-time {
  color: var(--danger);
}

.table-panel {
  display: grid;
  gap: 10px;
}

.table-head,
.table-row {
  display: grid;
  grid-template-columns: 1.1fr 1.5fr 0.7fr 0.7fr;
  gap: 12px;
  align-items: center;
}

.table-row {
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  padding: 13px 14px;
  color: var(--text);
  background: var(--panel-high);
}

.state-pill,
.count-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 28px;
  border-radius: 999px;
  padding: 0 10px;
  background: color-mix(in srgb, var(--primary-container) 66%, transparent);
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
}

.detail-panel .panel-header {
  align-items: center;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.field {
  display: grid;
  gap: 8px;
}

.field.full {
  grid-column: 1 / -1;
}

input,
select,
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--outline);
  border-radius: 12px 12px 4px 4px;
  background: var(--panel-high);
  color: var(--text);
  padding: 12px 14px;
}

textarea {
  resize: vertical;
  line-height: 1.55;
}

@media (max-width: 1280px) {
  .summary-grid,
  .content-grid,
  .insight-row {
    grid-template-columns: 1fr 1fr;
  }

  .content-grid > *:last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .nav-rail {
    padding-bottom: 0;
  }

  .hero-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .summary-grid,
  .content-grid,
  .insight-row,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .table-head,
  .table-row {
    grid-template-columns: 1fr;
  }
}
</style>
