<script setup lang="ts">
import { computed, ref, watch } from "vue"

type ThemeMode = "light" | "dark"
type MaterialVariant = "cold-graphite" | "warm-mineral" | "deep-flagship"

type VariantSpec = {
  label: string
  subtitle: string
  heroTitle: string
  heroBody: string
  supporting: string
  defaultTheme: ThemeMode
  lightVars: Record<string, string>
  darkVars: Record<string, string>
}

const props = withDefaults(
  defineProps<{
    variant?: MaterialVariant
  }>(),
  {
    variant: "cold-graphite",
  },
)

const variantPaths: Array<{ key: MaterialVariant; path: string }> = [
  {
    key: "cold-graphite",
    path: "/preview/material-console/cold-graphite",
  },
  {
    key: "warm-mineral",
    path: "/preview/material-console/warm-mineral",
  },
  {
    key: "deep-flagship",
    path: "/preview/material-console/deep-flagship",
  },
]

const variantSpecs: Record<MaterialVariant, VariantSpec> = {
  "cold-graphite": {
    label: "Cold White Graphite",
    subtitle: "冷白石墨",
    heroTitle: "Graphite Operations",
    heroBody:
      "冷白、石墨、少量矿物蓝。把甜紫系统感抽掉，保留 Material 3 的秩序和桌面控制台的专业感。",
    supporting: "更像高端生产力工具，不像默认 Android 主题演示。",
    defaultTheme: "light",
    lightVars: {
      "--md-primary": "#4c5f7a",
      "--md-on-primary": "#ffffff",
      "--md-primary-container": "#d7e3f8",
      "--md-on-primary-container": "#071c33",
      "--md-secondary-container": "#dfe3eb",
      "--md-on-secondary-container": "#171c22",
      "--md-tertiary-container": "#dde6ef",
      "--md-on-tertiary-container": "#1a2129",
      "--md-surface": "#f6f7fa",
      "--md-surface-low": "#f0f2f5",
      "--md-surface-container": "#ebedf0",
      "--md-surface-high": "#e4e7eb",
      "--md-surface-highest": "#dde1e6",
      "--md-on-surface": "#171a1f",
      "--md-on-surface-variant": "#57606c",
      "--md-outline": "#7b8490",
      "--md-outline-variant": "#c4c9d1",
      "--md-shadow": "rgba(18, 24, 33, 0.1)",
      "--md-positive": "#1e6b3c",
      "--md-warning": "#8d5d14",
      "--md-danger": "#b13a34",
      "--page-bg": "radial-gradient(circle at top right, rgba(115, 137, 171, 0.09), transparent 28%), linear-gradient(180deg, #fbfcfd 0%, #f0f3f7 100%)",
      "--surface-border": "rgba(98, 108, 122, 0.08)",
      "--surface-glow": "rgba(255, 255, 255, 0.65)",
      "--chart-top": "#6d86ab",
      "--chart-bottom": "#cfd8e6",
      "--hero-tint": "rgba(79, 98, 126, 0.09)",
    },
    darkVars: {
      "--md-primary": "#b6cae7",
      "--md-on-primary": "#1b314d",
      "--md-primary-container": "#334863",
      "--md-on-primary-container": "#d7e3f8",
      "--md-secondary-container": "#39424d",
      "--md-on-secondary-container": "#d8dee7",
      "--md-tertiary-container": "#33424f",
      "--md-on-tertiary-container": "#dce6ef",
      "--md-surface": "#111419",
      "--md-surface-low": "#171b21",
      "--md-surface-container": "#1c2128",
      "--md-surface-high": "#242a32",
      "--md-surface-highest": "#2d343d",
      "--md-on-surface": "#e7ebf0",
      "--md-on-surface-variant": "#b5bcc6",
      "--md-outline": "#8d95a0",
      "--md-outline-variant": "#434a55",
      "--md-shadow": "rgba(0, 0, 0, 0.34)",
      "--md-positive": "#8ad6a6",
      "--md-warning": "#efc27d",
      "--md-danger": "#ffb4ab",
      "--page-bg": "radial-gradient(circle at top right, rgba(143, 169, 211, 0.14), transparent 28%), linear-gradient(180deg, #0f1216 0%, #151920 100%)",
      "--surface-border": "rgba(185, 194, 206, 0.08)",
      "--surface-glow": "rgba(255, 255, 255, 0.03)",
      "--chart-top": "#b7c8e3",
      "--chart-bottom": "#39526f",
      "--hero-tint": "rgba(145, 170, 211, 0.1)",
    },
  },
  "warm-mineral": {
    label: "Warm White Mineral",
    subtitle: "暖白矿物",
    heroTitle: "Mineral Control Deck",
    heroBody:
      "把 Material 3 做得更像矿物、陶瓷和纸感表面。暖白基底压住了系统组件味，更接近贵一点的产品后台。",
    supporting: "更柔和，也更像经过审美修整的产品，不再只是官方样板。",
    defaultTheme: "light",
    lightVars: {
      "--md-primary": "#7c5b3d",
      "--md-on-primary": "#ffffff",
      "--md-primary-container": "#f7dfc8",
      "--md-on-primary-container": "#2c1604",
      "--md-secondary-container": "#e9dfd4",
      "--md-on-secondary-container": "#241d16",
      "--md-tertiary-container": "#efe0d4",
      "--md-on-tertiary-container": "#281b12",
      "--md-surface": "#faf6f0",
      "--md-surface-low": "#f5efe8",
      "--md-surface-container": "#f0eae3",
      "--md-surface-high": "#ebe4dc",
      "--md-surface-highest": "#e4ddd5",
      "--md-on-surface": "#211b16",
      "--md-on-surface-variant": "#655d56",
      "--md-outline": "#84766c",
      "--md-outline-variant": "#d4c4b8",
      "--md-shadow": "rgba(38, 26, 17, 0.11)",
      "--md-positive": "#2f6d48",
      "--md-warning": "#8c5a19",
      "--md-danger": "#b54932",
      "--page-bg": "radial-gradient(circle at top right, rgba(201, 157, 108, 0.12), transparent 26%), linear-gradient(180deg, #fffaf3 0%, #f4ede4 100%)",
      "--surface-border": "rgba(112, 90, 65, 0.08)",
      "--surface-glow": "rgba(255, 252, 246, 0.68)",
      "--chart-top": "#b48659",
      "--chart-bottom": "#e8d7c2",
      "--hero-tint": "rgba(183, 135, 88, 0.09)",
    },
    darkVars: {
      "--md-primary": "#e8c6a3",
      "--md-on-primary": "#41290f",
      "--md-primary-container": "#604429",
      "--md-on-primary-container": "#f7dfc8",
      "--md-secondary-container": "#4d4035",
      "--md-on-secondary-container": "#efe0d2",
      "--md-tertiary-container": "#534136",
      "--md-on-tertiary-container": "#f4e1d4",
      "--md-surface": "#18130f",
      "--md-surface-low": "#211a15",
      "--md-surface-container": "#28211c",
      "--md-surface-high": "#322923",
      "--md-surface-highest": "#3c322b",
      "--md-on-surface": "#f0e5d8",
      "--md-on-surface-variant": "#d2c3b4",
      "--md-outline": "#9c8d80",
      "--md-outline-variant": "#50453d",
      "--md-shadow": "rgba(0, 0, 0, 0.36)",
      "--md-positive": "#9ad8b0",
      "--md-warning": "#f0c17f",
      "--md-danger": "#ffb4a2",
      "--page-bg": "radial-gradient(circle at top right, rgba(204, 158, 102, 0.16), transparent 26%), linear-gradient(180deg, #15100d 0%, #1b1511 100%)",
      "--surface-border": "rgba(241, 226, 207, 0.07)",
      "--surface-glow": "rgba(255, 245, 231, 0.03)",
      "--chart-top": "#e6c49f",
      "--chart-bottom": "#6d5239",
      "--hero-tint": "rgba(229, 193, 149, 0.1)",
    },
  },
  "deep-flagship": {
    label: "Deep Flagship",
    subtitle: "深色旗舰",
    heroTitle: "Flagship Runtime",
    heroBody:
      "这版保留 Material 3 的层级逻辑，但用接近旗舰 Android 控制台的深色温度。更收、更硬、更像高端设备管理系统。",
    supporting: "如果你想要旗舰感、夜间感和轻微科技气味，这条最接近。",
    defaultTheme: "dark",
    lightVars: {
      "--md-primary": "#335c8d",
      "--md-on-primary": "#ffffff",
      "--md-primary-container": "#d4e3ff",
      "--md-on-primary-container": "#001c39",
      "--md-secondary-container": "#d9e3f1",
      "--md-on-secondary-container": "#101c2b",
      "--md-tertiary-container": "#dbe4f8",
      "--md-on-tertiary-container": "#132135",
      "--md-surface": "#f7f9fc",
      "--md-surface-low": "#eff3f8",
      "--md-surface-container": "#e8edf4",
      "--md-surface-high": "#dfe6ee",
      "--md-surface-highest": "#d8e0e8",
      "--md-on-surface": "#161c23",
      "--md-on-surface-variant": "#56606b",
      "--md-outline": "#76828f",
      "--md-outline-variant": "#c2ccd7",
      "--md-shadow": "rgba(16, 27, 39, 0.12)",
      "--md-positive": "#0f7a48",
      "--md-warning": "#9a6000",
      "--md-danger": "#bf3131",
      "--page-bg": "radial-gradient(circle at top right, rgba(73, 114, 173, 0.14), transparent 26%), linear-gradient(180deg, #fafdff 0%, #edf2f9 100%)",
      "--surface-border": "rgba(84, 101, 121, 0.08)",
      "--surface-glow": "rgba(255, 255, 255, 0.63)",
      "--chart-top": "#4f79af",
      "--chart-bottom": "#d0ddf1",
      "--hero-tint": "rgba(61, 90, 140, 0.1)",
    },
    darkVars: {
      "--md-primary": "#b5ccff",
      "--md-on-primary": "#002b5d",
      "--md-primary-container": "#103e72",
      "--md-on-primary-container": "#d4e3ff",
      "--md-secondary-container": "#3a4658",
      "--md-on-secondary-container": "#d6e2f1",
      "--md-tertiary-container": "#2e405a",
      "--md-on-tertiary-container": "#d9e3ff",
      "--md-surface": "#0e141d",
      "--md-surface-low": "#131b25",
      "--md-surface-container": "#18212c",
      "--md-surface-high": "#202b36",
      "--md-surface-highest": "#2a3642",
      "--md-on-surface": "#e8eef7",
      "--md-on-surface-variant": "#bcc7d5",
      "--md-outline": "#8a95a3",
      "--md-outline-variant": "#404b59",
      "--md-shadow": "rgba(0, 0, 0, 0.42)",
      "--md-positive": "#8de0b1",
      "--md-warning": "#f0c17f",
      "--md-danger": "#ffb4ab",
      "--page-bg": "radial-gradient(circle at top right, rgba(104, 154, 230, 0.2), transparent 28%), linear-gradient(180deg, #0a1119 0%, #101824 100%)",
      "--surface-border": "rgba(201, 214, 231, 0.08)",
      "--surface-glow": "rgba(255, 255, 255, 0.025)",
      "--chart-top": "#b8d1ff",
      "--chart-bottom": "#2d4b72",
      "--hero-tint": "rgba(113, 163, 238, 0.12)",
    },
  },
}

const themeMode = ref<ThemeMode>(variantSpecs[props.variant].defaultTheme)

watch(
  () => props.variant,
  (nextVariant) => {
    themeMode.value = variantSpecs[nextVariant].defaultTheme
  },
)

const currentVariant = computed(() => variantSpecs[props.variant])
const themeVars = computed(() =>
  themeMode.value === "light" ? currentVariant.value.lightVars : currentVariant.value.darkVars,
)

const navItems = [
  { label: "Overview", active: true },
  { label: "Sessions", active: false },
  { label: "Models", active: false },
  { label: "Plugins", active: false },
  { label: "Logs", active: false },
]

const summaryCards = [
  {
    label: "Runtime health",
    value: "Stable",
    detail: "12 services healthy, no blocked queues",
  },
  {
    label: "Median latency",
    value: "842 ms",
    detail: "Down 180 ms compared with yesterday",
  },
  {
    label: "Open threads",
    value: "128",
    detail: "Active in the last 10 minutes",
  },
  {
    label: "Alerts",
    value: "03",
    detail: "Require maintainer review",
  },
]

const quickFilters = ["All systems", "Gateway", "Models", "Memory", "Plugins"]
const barHeights = [28, 41, 60, 52, 77, 65, 88, 69, 58, 74, 54, 66]

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

const modeText = computed(() => (themeMode.value === "light" ? "Light Material" : "Dark Material"))
</script>

<template>
  <section class="material-console" :data-mode="themeMode" :style="themeVars">
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
        <div class="rail-footer">
          <button class="icon-button" type="button" @click="themeMode = themeMode === 'light' ? 'dark' : 'light'">
            {{ themeMode === "light" ? "◐" : "◑" }}
          </button>
        </div>
      </aside>

      <main class="workspace">
        <header class="top-bar">
          <div>
            <p class="eyebrow">Preview / Material Premium</p>
            <h1>{{ currentVariant.heroTitle }}</h1>
            <p class="supporting">{{ currentVariant.supporting }}</p>
          </div>
          <div class="top-actions">
            <div class="segmented">
              <button
                :class="{ active: themeMode === 'light' }"
                type="button"
                @click="themeMode = 'light'"
              >
                Light
              </button>
              <button
                :class="{ active: themeMode === 'dark' }"
                type="button"
                @click="themeMode = 'dark'"
              >
                Dark
              </button>
            </div>
            <button class="filled-button" type="button">Sync state</button>
          </div>
        </header>

        <section class="hero-card surface-container-high">
          <div class="hero-copy">
            <p class="hero-label">Premium Material control panel</p>
            <div class="hero-header">
              <h2>{{ currentVariant.label }}</h2>
              <span class="mode-pill">{{ modeText }}</span>
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
          <article
            v-for="card in summaryCards"
            :key="card.label"
            class="summary-card surface-container"
          >
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

            <div class="chart-box surface-container-low">
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
                class="event-item surface-container-low"
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
            <div v-for="row in queueRows" :key="row.join('-')" class="table-row surface-container-low">
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
                <input type="text" value="把 Material 3 再往更贵、更克制、更像产品的方向推一层" />
              </label>
              <label class="field full">
                <span>Operator note</span>
                <textarea rows="5">这次不只是换色，而是把默认甜紫、默认圆润和默认演示味压掉。要的是 premium Material，不是 demo Material。</textarea>
              </label>
            </div>
          </article>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.material-console {
  background: var(--page-bg);
  color: var(--md-on-surface);
  font-family:
    "Roboto Flex",
    "Roboto",
    "Noto Sans SC",
    "PingFang SC",
    sans-serif;
  min-height: calc(100vh - 48px);
  padding-bottom: 16px;
}

.app-shell {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 18px;
}

.nav-rail {
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 16px;
  padding: 18px 10px 16px;
}

.brand-mark,
.icon-button,
.rail-item,
.surface-card,
.hero-card,
.summary-card,
.tonal-card,
.event-item,
.table-row {
  box-shadow:
    0 1px 2px var(--md-shadow),
    0 8px 24px rgba(0, 0, 0, 0.04);
}

.brand-mark,
.icon-button {
  width: 56px;
  height: 56px;
  border: 1px solid var(--surface-border);
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, var(--md-primary-container), color-mix(in srgb, var(--md-primary-container) 72%, var(--md-surface-highest)));
  color: var(--md-on-primary-container);
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
  color: var(--md-on-surface-variant);
  cursor: pointer;
  font-size: 12px;
}

.rail-item.active {
  border-color: var(--surface-border);
  background: color-mix(in srgb, var(--md-secondary-container) 72%, var(--md-surface-low));
  color: var(--md-on-surface);
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
  color: var(--md-on-surface-variant);
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
  font-size: clamp(34px, 4vw, 48px);
  line-height: 1.04;
  letter-spacing: -0.04em;
  color: var(--md-on-surface);
  font-weight: 420;
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
  color: var(--md-on-surface-variant);
  line-height: 1.54;
}

.supporting {
  margin-top: 8px;
}

.top-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.segmented {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding: 4px;
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  background: var(--md-surface-high);
}

.segmented button,
.filled-button,
.filled-tonal-button,
.outlined-button,
.text-button,
input,
select,
textarea {
  font: inherit;
}

.segmented button,
.filled-button,
.filled-tonal-button,
.outlined-button,
.text-button {
  border-radius: 999px;
  padding: 10px 14px;
  cursor: pointer;
}

.segmented button {
  border: 0;
  background: transparent;
  color: var(--md-on-surface-variant);
}

.segmented button.active {
  background: color-mix(in srgb, var(--md-secondary-container) 72%, var(--md-surface-highest));
  color: var(--md-on-secondary-container);
}

.filled-button {
  border: 0;
  background: linear-gradient(180deg, var(--md-primary), color-mix(in srgb, var(--md-primary) 82%, black));
  color: var(--md-on-primary);
}

.filled-tonal-button {
  border: 0;
  background: linear-gradient(180deg, var(--md-secondary-container), color-mix(in srgb, var(--md-secondary-container) 78%, var(--md-surface-low)));
  color: var(--md-on-secondary-container);
}

.outlined-button {
  border: 1px solid var(--md-outline);
  background: transparent;
  color: var(--md-on-surface);
}

.text-button {
  border: 0;
  background: transparent;
  color: var(--md-primary);
}

.surface-container-low {
  background: linear-gradient(180deg, var(--md-surface-low), color-mix(in srgb, var(--md-surface-low) 84%, var(--surface-glow)));
}

.surface-container {
  background: linear-gradient(180deg, var(--md-surface-container), color-mix(in srgb, var(--md-surface-container) 84%, var(--surface-glow)));
}

.surface-container-high {
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--md-surface-high) 92%, var(--surface-glow)), var(--md-surface-high)),
    linear-gradient(135deg, var(--hero-tint), transparent 52%);
}

.surface-card,
.hero-card,
.summary-card {
  border: 1px solid var(--surface-border);
}

.surface-card {
  border-radius: 24px;
  background: linear-gradient(180deg, var(--md-surface), color-mix(in srgb, var(--md-surface) 86%, var(--surface-glow)));
  padding: 18px;
}

.hero-card {
  display: grid;
  gap: 18px;
  border-radius: 32px;
  padding: 24px;
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
  background: color-mix(in srgb, var(--md-tertiary-container) 82%, var(--md-surface-highest));
  color: var(--md-on-tertiary-container);
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
  border: 1px solid var(--md-outline-variant);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
  color: inherit;
  text-decoration: none;
  transition:
    transform 120ms ease,
    border-color 120ms ease,
    background-color 120ms ease;
}

.variant-chip span {
  color: var(--md-on-surface);
  font-size: 13px;
  font-weight: 600;
}

.variant-chip:hover {
  transform: translateY(-1px);
}

.variant-chip.active {
  border-color: transparent;
  background: linear-gradient(180deg, var(--md-primary-container), color-mix(in srgb, var(--md-primary-container) 80%, var(--md-surface-highest)));
}

.filter-chip {
  border: 1px solid var(--md-outline-variant);
  border-radius: 10px;
  background: transparent;
  color: var(--md-on-surface);
  padding: 9px 12px;
  cursor: pointer;
}

.filter-chip.selected {
  border-color: transparent;
  background: linear-gradient(180deg, var(--md-secondary-container), color-mix(in srgb, var(--md-secondary-container) 82%, var(--md-surface-highest)));
  color: var(--md-on-secondary-container);
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
  color: var(--md-on-surface);
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

.chart-panel {
  display: grid;
  gap: 18px;
}

.chart-box {
  border: 1px solid var(--surface-border);
  border-radius: 26px;
  padding: 16px;
}

.bars {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
  height: 230px;
  border-bottom: 1px solid var(--md-outline-variant);
  background:
    repeating-linear-gradient(
      to top,
      color-mix(in srgb, var(--md-outline-variant) 58%, transparent) 0,
      color-mix(in srgb, var(--md-outline-variant) 58%, transparent) 1px,
      transparent 1px,
      transparent 52px
    );
}

.bar {
  border-radius: 999px 999px 10px 10px;
  background: linear-gradient(180deg, var(--chart-top), var(--chart-bottom));
}

.ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: var(--md-on-surface-variant);
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
  border: 1px solid var(--surface-border);
  border-radius: 20px;
  padding: 14px;
  background: linear-gradient(180deg, var(--md-secondary-container), color-mix(in srgb, var(--md-secondary-container) 82%, var(--surface-glow)));
  color: var(--md-on-secondary-container);
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
  border: 1px solid var(--surface-border);
  border-radius: 20px;
  padding: 14px;
}

.event-time {
  color: var(--md-on-surface);
  font-size: 13px;
  font-weight: 620;
}

.event-item strong {
  color: var(--md-on-surface);
  font-size: 18px;
  line-height: 1.14;
  font-weight: 430;
}

.tone-positive .event-time {
  color: var(--md-positive);
}

.tone-warning .event-time {
  color: var(--md-warning);
}

.tone-danger .event-time {
  color: var(--md-danger);
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
  border: 1px solid var(--surface-border);
  border-radius: 20px;
  padding: 13px 14px;
  color: var(--md-on-surface);
}

.state-pill,
.count-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 28px;
  border-radius: 999px;
  padding: 0 10px;
  background: linear-gradient(180deg, var(--md-tertiary-container), color-mix(in srgb, var(--md-tertiary-container) 82%, var(--md-surface-highest)));
  color: var(--md-on-tertiary-container);
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
  border: 1px solid var(--md-outline);
  border-radius: 12px 12px 4px 4px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--md-surface-high) 86%, var(--surface-glow)), var(--md-surface-low));
  color: var(--md-on-surface);
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
    grid-template-rows: none;
    grid-template-columns: auto 1fr auto;
    align-items: center;
  }

  .rail-nav {
    grid-auto-flow: column;
    grid-auto-columns: minmax(88px, 1fr);
  }

  .workspace {
    padding: 0 0 16px;
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
