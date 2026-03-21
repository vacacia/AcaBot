<script setup lang="ts">
import { computed } from "vue"

type BaseTone = "smoke" | "slate"
type MaterialTone = "glass" | "metal"
type CoverageTone = "accent" | "full"

type BaseSpec = {
  label: string
  subtitle: string
  heroTitle: string
  heroBody: string
  vars: Record<string, string>
}

const props = defineProps<{
  base?: string
  material?: string
  coverage?: string
}>()

const currentBaseKey = computed<BaseTone>(() => (props.base === "slate" ? "slate" : "smoke"))
const currentMaterialKey = computed<MaterialTone>(() => (props.material === "metal" ? "metal" : "glass"))
const currentCoverageKey = computed<CoverageTone>(() => (props.coverage === "full" ? "full" : "accent"))

const variantLinks = [
  { base: "smoke", material: "glass", coverage: "accent" },
  { base: "smoke", material: "glass", coverage: "full" },
  { base: "smoke", material: "metal", coverage: "accent" },
  { base: "smoke", material: "metal", coverage: "full" },
  { base: "slate", material: "glass", coverage: "accent" },
  { base: "slate", material: "glass", coverage: "full" },
  { base: "slate", material: "metal", coverage: "accent" },
  { base: "slate", material: "metal", coverage: "full" },
] as const

const baseSpecs: Record<BaseTone, BaseSpec> = {
  smoke: {
    label: "Smoked Graphite",
    subtitle: "烟灰石墨",
    heroTitle: "Smoked Graphite Frost Study",
    heroBody:
      "保留已经成立的烟灰石墨亮度，只改材质。你现在看的差异主要来自磨砂玻璃和磨砂金属，以及它们是点缀还是全局。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(255, 255, 255, 0.05), transparent 24%), linear-gradient(180deg, #15181c 0%, #1b2026 100%)",
      "--surface": "#2a3037",
      "--surface-low": "#23282f",
      "--surface-high": "#343a43",
      "--surface-highest": "#3b424a",
      "--panel-border": "rgba(231, 236, 242, 0.1)",
      "--panel-hairline": "rgba(255, 255, 255, 0.05)",
      "--text": "#f0f3f6",
      "--muted": "#c9d0d8",
      "--muted-2": "#95a0ac",
      "--accent": "#eef2f6",
      "--accent-strong": "#c4ccd4",
      "--accent-container": "#3b424a",
      "--outline": "#636d78",
      "--positive": "#c1d4c7",
      "--warning": "#d8ccb7",
      "--danger": "#d9c0c0",
      "--shadow": "0 14px 34px rgba(0, 0, 0, 0.24)",
      "--hero-glow": "rgba(255, 255, 255, 0.038)",
      "--bar-top": "#eff3f6",
      "--bar-bottom": "#6a7581",
      "--chip-selected": "rgba(204, 212, 220, 0.14)",
      "--button-fill": "linear-gradient(180deg, #f1f4f7, #b2bbc4)",
      "--button-text": "#111418",
    },
  },
  slate: {
    label: "Slate Flagship",
    subtitle: "石板旗舰",
    heroTitle: "Slate Flagship Frost Study",
    heroBody:
      "保留石板旗舰那种更精密的系统感，但只在材质层做实验。这样可以看出到底是玻璃磨砂还是喷砂金属更适合这条基底。",
    vars: {
      "--page-bg": "radial-gradient(circle at top right, rgba(176, 205, 246, 0.08), transparent 24%), linear-gradient(180deg, #141920 0%, #1b212a 100%)",
      "--surface": "#27313c",
      "--surface-low": "#212a34",
      "--surface-high": "#344252",
      "--surface-highest": "#3b4b5d",
      "--panel-border": "rgba(217, 230, 247, 0.095)",
      "--panel-hairline": "rgba(255, 255, 255, 0.05)",
      "--text": "#ebf2fa",
      "--muted": "#c8d5e5",
      "--muted-2": "#98a9bc",
      "--accent": "#e6f0fc",
      "--accent-strong": "#afc4df",
      "--accent-container": "#334557",
      "--outline": "#607283",
      "--positive": "#c5dccf",
      "--warning": "#dfc896",
      "--danger": "#dcbfc0",
      "--shadow": "0 14px 34px rgba(0, 0, 0, 0.26)",
      "--hero-glow": "rgba(181, 212, 251, 0.05)",
      "--bar-top": "#e6f0fc",
      "--bar-bottom": "#637d9a",
      "--chip-selected": "rgba(183, 205, 234, 0.15)",
      "--button-fill": "linear-gradient(180deg, #ebf3fd, #9ab6d5)",
      "--button-text": "#111821",
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

const currentBase = computed(() => baseSpecs[currentBaseKey.value])
const materialLabel = computed(() => (currentMaterialKey.value === "glass" ? "Frosted Glass" : "Blasted Metal"))
const coverageLabel = computed(() => (currentCoverageKey.value === "accent" ? "Accent Frost" : "Full Frost"))
const pageClass = computed(() => ({
  "is-glass": currentMaterialKey.value === "glass",
  "is-metal": currentMaterialKey.value === "metal",
  "is-accent": currentCoverageKey.value === "accent",
  "is-full": currentCoverageKey.value === "full",
}))

function hrefFor(base: string, material: string, coverage: string): string {
  return `/preview/material-frost/${base}/${material}/${coverage}`
}

function chipTitle(base: string, material: string, coverage: string): string {
  const baseTitle = base === "smoke" ? "Smoke" : "Slate"
  const materialTitle = material === "glass" ? "Glass" : "Metal"
  const coverageTitle = coverage === "accent" ? "Accent" : "Full"
  return `${baseTitle} / ${materialTitle} / ${coverageTitle}`
}
</script>

<template>
  <section
    class="material-frost-study"
    :class="pageClass"
    :style="currentBase.vars"
  >
    <div class="app-shell">
      <aside class="nav-rail frost-target">
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
            <p class="eyebrow">Preview / Material Frost Study</p>
            <h1>{{ currentBase.heroTitle }}</h1>
            <p class="supporting">只改磨砂材质和覆盖范围，不再同时改色和结构。</p>
          </div>
          <button class="filled-button" type="button">Sync state</button>
        </header>

        <section class="hero-card frost-target">
          <div class="hero-copy">
            <p class="hero-label">Material premium material study</p>
            <div class="hero-header">
              <h2>{{ currentBase.label }}</h2>
              <span class="mode-pill">{{ materialLabel }} / {{ coverageLabel }}</span>
            </div>
            <p>{{ currentBase.heroBody }}</p>
          </div>

          <div class="variant-row">
            <RouterLink
              v-for="item in variantLinks"
              :key="hrefFor(item.base, item.material, item.coverage)"
              class="variant-chip"
              :class="{
                active:
                  item.base === currentBaseKey
                  && item.material === currentMaterialKey
                  && item.coverage === currentCoverageKey,
              }"
              :to="hrefFor(item.base, item.material, item.coverage)"
            >
              <span>{{ chipTitle(item.base, item.material, item.coverage) }}</span>
              <small>{{ item.base === "smoke" ? "Smoked Graphite" : "Slate Flagship" }}</small>
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
            class="summary-card"
            :class="{ 'frost-target': currentCoverageKey === 'full' }"
          >
            <span class="summary-label">{{ card.label }}</span>
            <strong class="summary-value">{{ card.value }}</strong>
            <p class="summary-detail">{{ card.detail }}</p>
          </article>
        </section>

        <section class="content-grid">
          <article class="surface-card chart-panel frost-target">
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
              <article class="tonal-card" :class="{ 'frost-target': currentCoverageKey === 'full' }">
                <span>Response lane</span>
                <strong>Stable</strong>
              </article>
              <article class="tonal-card" :class="{ 'frost-target': currentCoverageKey === 'full' }">
                <span>Retry pressure</span>
                <strong>Low</strong>
              </article>
              <article class="tonal-card" :class="{ 'frost-target': currentCoverageKey === 'full' }">
                <span>Operator load</span>
                <strong>76%</strong>
              </article>
            </div>
          </article>

          <article class="surface-card event-panel" :class="{ 'frost-target': currentCoverageKey === 'full' }">
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
                :class="[`tone-${item.tone}`, { 'frost-target': currentCoverageKey === 'full' }]"
              >
                <span class="event-time">{{ item.time }}</span>
                <div>
                  <strong>{{ item.title }}</strong>
                  <p>{{ item.note }}</p>
                </div>
              </article>
            </div>
          </article>

          <article class="surface-card table-panel" :class="{ 'frost-target': currentCoverageKey === 'full' }">
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
            <div
              v-for="row in queueRows"
              :key="row.join('-')"
              class="table-row"
              :class="{ 'frost-target': currentCoverageKey === 'full' }"
            >
              <span>{{ row[0] }}</span>
              <span>{{ row[1] }}</span>
              <span>{{ row[2] }}</span>
              <span class="state-pill">{{ row[3] }}</span>
            </div>
          </article>

          <article class="surface-card detail-panel" :class="{ 'frost-target': currentCoverageKey === 'full' }">
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
                <input type="text" value="比较磨砂玻璃和喷砂金属，到底哪种更像高级深色控制面" />
              </label>
              <label class="field full">
                <span>Operator note</span>
                <textarea rows="5">这次只改材质和覆盖范围。重点看它是显得更透、更贵，还是更糊、更脏。</textarea>
              </label>
            </div>
          </article>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.material-frost-study {
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
  position: relative;
  display: grid;
  gap: 16px;
  padding: 18px 10px 16px;
  border: 1px solid var(--panel-border);
  border-radius: 22px;
  background: linear-gradient(180deg, var(--surface-high), var(--surface-low));
  box-shadow: var(--shadow);
}

.brand-mark,
.rail-item,
.surface-card,
.summary-card,
.event-item,
.table-row,
.tonal-card,
.hero-card {
  box-shadow: var(--shadow);
}

.event-item,
.table-row,
.tonal-card {
  position: relative;
}

.brand-mark {
  width: 56px;
  height: 56px;
  border: 1px solid var(--panel-border);
  border-radius: 20px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, var(--accent-container), color-mix(in srgb, var(--accent-container) 82%, black));
  color: var(--accent);
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
  background: linear-gradient(180deg, color-mix(in srgb, var(--accent-container) 58%, transparent), rgba(255, 255, 255, 0.02));
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
  background: linear-gradient(180deg, color-mix(in srgb, var(--accent-container) 90%, var(--surface-high)), color-mix(in srgb, var(--accent-container) 74%, black));
  color: var(--accent);
}

.outlined-button {
  border: 1px solid var(--outline);
  background: transparent;
  color: var(--text);
}

.text-button {
  border: 0;
  background: transparent;
  color: var(--accent);
}

.hero-card,
.summary-card,
.surface-card {
  position: relative;
  border: 1px solid var(--panel-border);
  background:
    linear-gradient(180deg, var(--surface), var(--surface-low)),
    linear-gradient(135deg, rgba(255, 255, 255, 0.015), transparent 46%);
}

.hero-card::before,
.summary-card::before,
.surface-card::before,
.nav-rail::before {
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
  background: radial-gradient(circle, rgba(255, 255, 255, 0.04), transparent 68%);
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
  background: color-mix(in srgb, var(--accent-container) 72%, transparent);
  color: var(--accent);
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
  background: color-mix(in srgb, var(--accent-container) 58%, transparent);
  color: var(--accent);
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
    linear-gradient(180deg, var(--surface-high), rgba(255, 255, 255, 0.01)),
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
  background: var(--surface-high);
  color: var(--accent);
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
  background: var(--surface-high);
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
  background: var(--surface-high);
}

.state-pill,
.count-pill {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 28px;
  border-radius: 999px;
  padding: 0 10px;
  background: color-mix(in srgb, var(--accent-container) 66%, transparent);
  color: var(--accent);
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
  background: var(--surface-high);
  color: var(--text);
  padding: 12px 14px;
}

textarea {
  resize: vertical;
  line-height: 1.55;
}

.material-frost-study.is-glass .frost-target,
.material-frost-study.is-glass.is-full .summary-card,
.material-frost-study.is-glass.is-full .surface-card,
.material-frost-study.is-glass.is-full .event-item,
.material-frost-study.is-glass.is-full .table-row,
.material-frost-study.is-glass.is-full .tonal-card {
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--surface-high) 58%, transparent), color-mix(in srgb, var(--surface-low) 46%, transparent)),
    linear-gradient(135deg, rgba(255, 255, 255, 0.05), transparent 48%);
  backdrop-filter: blur(18px) saturate(120%);
  border-color: rgba(255, 255, 255, 0.12);
}

.material-frost-study.is-glass .frost-target::after,
.material-frost-study.is-glass.is-full .summary-card::after,
.material-frost-study.is-glass.is-full .surface-card::after,
.material-frost-study.is-glass.is-full .event-item::after,
.material-frost-study.is-glass.is-full .table-row::after,
.material-frost-study.is-glass.is-full .tonal-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.05), transparent 36%);
  pointer-events: none;
}

.material-frost-study.is-metal .frost-target,
.material-frost-study.is-metal.is-full .summary-card,
.material-frost-study.is-metal.is-full .surface-card,
.material-frost-study.is-metal.is-full .event-item,
.material-frost-study.is-metal.is-full .table-row,
.material-frost-study.is-metal.is-full .tonal-card {
  backdrop-filter: blur(2px);
  border-color: rgba(255, 255, 255, 0.09);
  background-image:
    linear-gradient(180deg, color-mix(in srgb, var(--surface) 96%, black), color-mix(in srgb, var(--surface-low) 98%, black)),
    repeating-linear-gradient(135deg, rgba(255, 255, 255, 0.018) 0 2px, rgba(255, 255, 255, 0) 2px 6px);
}

.material-frost-study.is-metal .frost-target::after,
.material-frost-study.is-metal.is-full .summary-card::after,
.material-frost-study.is-metal.is-full .surface-card::after,
.material-frost-study.is-metal.is-full .event-item::after,
.material-frost-study.is-metal.is-full .table-row::after,
.material-frost-study.is-metal.is-full .tonal-card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.024), transparent 42%);
  pointer-events: none;
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
