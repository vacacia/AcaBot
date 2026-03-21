<script setup lang="ts">
import { computed } from "vue"

type GlassLabPalette = "graphite" | "verdigris" | "brass" | "bordeaux"

type MetricCard = {
  label: string
  value: string
  delta: string
  detail: string
  tone: "primary" | "positive" | "warning" | "danger"
}

type EventItem = {
  title: string
  time: string
  detail: string
  tone: "primary" | "positive" | "warning" | "danger"
}

type QueueItem = {
  actor: string
  command: string
  latency: string
  state: string
}

type BindingItem = {
  name: string
  model: string
  mode: string
}

type OperatorItem = {
  name: string
  role: string
  load: number
}

type PaletteSpec = {
  label: string
  subtitle: string
  description: string
  vars: Record<string, string>
}

const props = withDefaults(
  defineProps<{
    palette?: GlassLabPalette
  }>(),
  {
    palette: "graphite",
  },
)

const palettePaths: Array<{ key: GlassLabPalette; path: string }> = [
  { key: "graphite", path: "/preview/glass-lab/graphite" },
  { key: "verdigris", path: "/preview/glass-lab/verdigris" },
  { key: "brass", path: "/preview/glass-lab/brass" },
  { key: "bordeaux", path: "/preview/glass-lab/bordeaux" },
]

const paletteSpecs: Record<GlassLabPalette, PaletteSpec> = {
  graphite: {
    label: "Graphite / Ice",
    subtitle: "石墨黑 + 冰灰高光",
    description: "最克制的一版。去掉发蓝的科技味，只保留冷冽、硬朗、干净的玻璃层次。",
    vars: {
      "--ambient-a": "radial-gradient(circle, rgba(246, 248, 252, 0.14) 0%, rgba(246, 248, 252, 0) 68%)",
      "--ambient-b": "radial-gradient(circle, rgba(172, 183, 196, 0.16) 0%, rgba(172, 183, 196, 0) 70%)",
      "--ambient-c": "radial-gradient(circle, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0) 72%)",
      "--panel-border": "rgba(205, 214, 224, 0.14)",
      "--panel-base-start": "rgba(33, 37, 42, 0.84)",
      "--panel-base-end": "rgba(18, 21, 26, 0.92)",
      "--panel-tint": "rgba(240, 245, 250, 0.03)",
      "--panel-highlight": "rgba(255, 255, 255, 0.06)",
      "--panel-shadow": "0 24px 60px rgba(0, 0, 0, 0.38)",
      "--title": "#f3f5f7",
      "--text": "rgba(238, 242, 246, 0.94)",
      "--muted": "rgba(178, 186, 195, 0.82)",
      "--eyebrow": "#d8dde4",
      "--eyebrow-muted": "rgba(196, 204, 212, 0.72)",
      "--pill-border": "rgba(215, 222, 230, 0.14)",
      "--pill-bg": "rgba(255, 255, 255, 0.04)",
      "--pill-text": "rgba(236, 241, 245, 0.92)",
      "--pill-live": "#dfe6ec",
      "--primary-start": "#f1f4f6",
      "--primary-end": "#9ba8b4",
      "--primary-text": "#11161b",
      "--primary-shadow": "0 18px 32px rgba(180, 189, 199, 0.22)",
      "--ghost-bg": "rgba(255, 255, 255, 0.045)",
      "--segment-bg": "rgba(7, 11, 15, 0.44)",
      "--segment-text": "rgba(201, 208, 215, 0.84)",
      "--segment-active-bg": "linear-gradient(135deg, rgba(236, 241, 246, 0.22), rgba(156, 170, 183, 0.14))",
      "--segment-active-text": "#fafcff",
      "--chart-line": "rgba(210, 218, 226, 0.08)",
      "--chart-glow": "rgba(236, 241, 246, 0.05)",
      "--bar-top": "rgba(248, 250, 252, 0.88)",
      "--bar-bottom": "rgba(157, 169, 181, 0.16)",
      "--bar-glow": "rgba(231, 237, 243, 0.18)",
      "--track-bg": "rgba(255, 255, 255, 0.06)",
      "--load-start": "rgba(244, 247, 250, 0.94)",
      "--load-end": "rgba(142, 154, 166, 0.52)",
      "--field-border": "rgba(212, 220, 228, 0.12)",
      "--field-bg": "linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0.03)), rgba(10, 13, 17, 0.38)",
      "--tone-primary": "#f2f5f8",
      "--tone-positive": "#cfe7de",
      "--tone-warning": "#f2d5aa",
      "--tone-danger": "#f0b6c0",
    },
  },
  verdigris: {
    label: "Verdigris / Smoke",
    subtitle: "烟墨黑 + 青绿微光",
    description: "更冷、更稳的一版。主光从蓝色换成低饱和青绿，比较像设备玻璃和实验室面板。",
    vars: {
      "--ambient-a": "radial-gradient(circle, rgba(122, 214, 195, 0.2) 0%, rgba(122, 214, 195, 0) 68%)",
      "--ambient-b": "radial-gradient(circle, rgba(173, 198, 180, 0.14) 0%, rgba(173, 198, 180, 0) 70%)",
      "--ambient-c": "radial-gradient(circle, rgba(225, 250, 239, 0.08) 0%, rgba(225, 250, 239, 0) 72%)",
      "--panel-border": "rgba(163, 201, 188, 0.16)",
      "--panel-base-start": "rgba(22, 33, 31, 0.84)",
      "--panel-base-end": "rgba(11, 18, 17, 0.92)",
      "--panel-tint": "rgba(117, 176, 160, 0.04)",
      "--panel-highlight": "rgba(255, 255, 255, 0.06)",
      "--panel-shadow": "0 24px 60px rgba(1, 9, 8, 0.4)",
      "--title": "#eff8f4",
      "--text": "rgba(234, 245, 240, 0.94)",
      "--muted": "rgba(170, 196, 187, 0.82)",
      "--eyebrow": "#98e0cb",
      "--eyebrow-muted": "rgba(170, 206, 194, 0.74)",
      "--pill-border": "rgba(153, 197, 184, 0.16)",
      "--pill-bg": "rgba(255, 255, 255, 0.04)",
      "--pill-text": "rgba(233, 245, 240, 0.92)",
      "--pill-live": "#a8f0dd",
      "--primary-start": "#b6f0df",
      "--primary-end": "#4c927c",
      "--primary-text": "#081311",
      "--primary-shadow": "0 18px 32px rgba(77, 146, 126, 0.26)",
      "--ghost-bg": "rgba(255, 255, 255, 0.04)",
      "--segment-bg": "rgba(6, 14, 13, 0.46)",
      "--segment-text": "rgba(190, 218, 208, 0.84)",
      "--segment-active-bg": "linear-gradient(135deg, rgba(149, 228, 208, 0.26), rgba(88, 151, 132, 0.16))",
      "--segment-active-text": "#fbfffd",
      "--chart-line": "rgba(169, 210, 195, 0.08)",
      "--chart-glow": "rgba(124, 216, 196, 0.05)",
      "--bar-top": "rgba(182, 240, 223, 0.9)",
      "--bar-bottom": "rgba(71, 140, 121, 0.16)",
      "--bar-glow": "rgba(137, 226, 204, 0.18)",
      "--track-bg": "rgba(255, 255, 255, 0.06)",
      "--load-start": "rgba(188, 244, 228, 0.94)",
      "--load-end": "rgba(62, 126, 109, 0.54)",
      "--field-border": "rgba(160, 200, 187, 0.12)",
      "--field-bg": "linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.028)), rgba(8, 15, 14, 0.38)",
      "--tone-primary": "#c1f2e4",
      "--tone-positive": "#aef0db",
      "--tone-warning": "#e8d19d",
      "--tone-danger": "#f0b3c2",
    },
  },
  brass: {
    label: "Brass / Coal",
    subtitle: "炭黑 + 琥珀金属感",
    description: "偏设备感的一版。暖色不做金灿灿，而是压低亮度，让它更像拉丝金属和旧仪器反光。",
    vars: {
      "--ambient-a": "radial-gradient(circle, rgba(233, 188, 118, 0.22) 0%, rgba(233, 188, 118, 0) 68%)",
      "--ambient-b": "radial-gradient(circle, rgba(167, 128, 86, 0.16) 0%, rgba(167, 128, 86, 0) 70%)",
      "--ambient-c": "radial-gradient(circle, rgba(255, 230, 190, 0.09) 0%, rgba(255, 230, 190, 0) 72%)",
      "--panel-border": "rgba(198, 164, 117, 0.16)",
      "--panel-base-start": "rgba(39, 29, 22, 0.84)",
      "--panel-base-end": "rgba(19, 15, 11, 0.92)",
      "--panel-tint": "rgba(201, 164, 108, 0.04)",
      "--panel-highlight": "rgba(255, 255, 255, 0.05)",
      "--panel-shadow": "0 24px 60px rgba(8, 4, 1, 0.42)",
      "--title": "#f8f1e7",
      "--text": "rgba(244, 235, 223, 0.94)",
      "--muted": "rgba(202, 182, 158, 0.82)",
      "--eyebrow": "#ecc488",
      "--eyebrow-muted": "rgba(220, 188, 138, 0.76)",
      "--pill-border": "rgba(198, 164, 117, 0.16)",
      "--pill-bg": "rgba(255, 255, 255, 0.04)",
      "--pill-text": "rgba(245, 237, 224, 0.92)",
      "--pill-live": "#f1d2a1",
      "--primary-start": "#f0d6a5",
      "--primary-end": "#8f6037",
      "--primary-text": "#181008",
      "--primary-shadow": "0 18px 32px rgba(157, 110, 54, 0.28)",
      "--ghost-bg": "rgba(255, 255, 255, 0.04)",
      "--segment-bg": "rgba(17, 11, 8, 0.46)",
      "--segment-text": "rgba(219, 196, 164, 0.84)",
      "--segment-active-bg": "linear-gradient(135deg, rgba(240, 214, 165, 0.24), rgba(143, 96, 55, 0.16))",
      "--segment-active-text": "#fffdf8",
      "--chart-line": "rgba(216, 188, 148, 0.08)",
      "--chart-glow": "rgba(236, 196, 127, 0.05)",
      "--bar-top": "rgba(240, 214, 165, 0.9)",
      "--bar-bottom": "rgba(150, 100, 49, 0.16)",
      "--bar-glow": "rgba(229, 188, 117, 0.2)",
      "--track-bg": "rgba(255, 255, 255, 0.06)",
      "--load-start": "rgba(244, 224, 184, 0.94)",
      "--load-end": "rgba(145, 96, 47, 0.54)",
      "--field-border": "rgba(201, 168, 121, 0.12)",
      "--field-bg": "linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.028)), rgba(15, 10, 7, 0.38)",
      "--tone-primary": "#f0d9b2",
      "--tone-positive": "#d5e6bc",
      "--tone-warning": "#f2d3a0",
      "--tone-danger": "#efb0a8",
    },
  },
  bordeaux: {
    label: "Bordeaux / Cherry Glass",
    subtitle: "黑樱桃 + 酒红低光",
    description: "更有情绪的一版。不是艳红，而是偏黑的酒红玻璃，适合做更戏剧化的控制面。",
    vars: {
      "--ambient-a": "radial-gradient(circle, rgba(183, 92, 121, 0.22) 0%, rgba(183, 92, 121, 0) 68%)",
      "--ambient-b": "radial-gradient(circle, rgba(132, 68, 86, 0.16) 0%, rgba(132, 68, 86, 0) 70%)",
      "--ambient-c": "radial-gradient(circle, rgba(244, 196, 211, 0.08) 0%, rgba(244, 196, 211, 0) 72%)",
      "--panel-border": "rgba(177, 121, 143, 0.16)",
      "--panel-base-start": "rgba(41, 20, 28, 0.84)",
      "--panel-base-end": "rgba(18, 9, 13, 0.92)",
      "--panel-tint": "rgba(163, 88, 118, 0.04)",
      "--panel-highlight": "rgba(255, 255, 255, 0.05)",
      "--panel-shadow": "0 24px 60px rgba(8, 1, 4, 0.44)",
      "--title": "#f8eef3",
      "--text": "rgba(243, 232, 238, 0.94)",
      "--muted": "rgba(202, 176, 187, 0.82)",
      "--eyebrow": "#efb5c8",
      "--eyebrow-muted": "rgba(222, 181, 197, 0.74)",
      "--pill-border": "rgba(181, 124, 147, 0.15)",
      "--pill-bg": "rgba(255, 255, 255, 0.04)",
      "--pill-text": "rgba(245, 236, 241, 0.92)",
      "--pill-live": "#f2c5d3",
      "--primary-start": "#f0c8d6",
      "--primary-end": "#8c4259",
      "--primary-text": "#18090f",
      "--primary-shadow": "0 18px 32px rgba(140, 66, 89, 0.28)",
      "--ghost-bg": "rgba(255, 255, 255, 0.04)",
      "--segment-bg": "rgba(17, 7, 11, 0.46)",
      "--segment-text": "rgba(219, 193, 204, 0.84)",
      "--segment-active-bg": "linear-gradient(135deg, rgba(239, 181, 200, 0.24), rgba(140, 66, 89, 0.16))",
      "--segment-active-text": "#fffafc",
      "--chart-line": "rgba(219, 186, 198, 0.08)",
      "--chart-glow": "rgba(222, 144, 171, 0.05)",
      "--bar-top": "rgba(240, 200, 214, 0.9)",
      "--bar-bottom": "rgba(135, 63, 84, 0.16)",
      "--bar-glow": "rgba(214, 130, 159, 0.18)",
      "--track-bg": "rgba(255, 255, 255, 0.06)",
      "--load-start": "rgba(241, 204, 217, 0.94)",
      "--load-end": "rgba(134, 59, 82, 0.54)",
      "--field-border": "rgba(182, 126, 148, 0.12)",
      "--field-bg": "linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.028)), rgba(16, 7, 10, 0.38)",
      "--tone-primary": "#f1cad8",
      "--tone-positive": "#d5e3ce",
      "--tone-warning": "#efd2a4",
      "--tone-danger": "#f1b4c5",
    },
  },
}

const metrics: MetricCard[] = [
  {
    label: "Active Threads",
    value: "128",
    delta: "+12%",
    detail: "最近 10 分钟内仍在滚动的会话",
    tone: "primary",
  },
  {
    label: "Tool Success",
    value: "97.8%",
    delta: "+2.1%",
    detail: "工具调用成功率，含重试后的最终结果",
    tone: "positive",
  },
  {
    label: "Median Latency",
    value: "842ms",
    delta: "-180ms",
    detail: "面向用户可感知的响应中位数",
    tone: "warning",
  },
  {
    label: "Anomaly Flags",
    value: "03",
    delta: "watch",
    detail: "需要 maintainer 主动盯一下的异常段",
    tone: "danger",
  },
]

const signalBars = [26, 58, 40, 72, 46, 84, 64, 92, 57, 74, 49, 67]

const events: EventItem[] = [
  {
    title: "NapCat reconnect",
    time: "08:42",
    detail: "网关在 4 秒内完成重连，消息没有积压。",
    tone: "positive",
  },
  {
    title: "Model fallback chain",
    time: "08:39",
    detail: "主模型退避到 summary lane，两次请求都已回收。",
    tone: "warning",
  },
  {
    title: "Plugin sandbox timeout",
    time: "08:33",
    detail: "image-captioner 第三次执行超时，已进入 cooldown。",
    tone: "danger",
  },
  {
    title: "Prompt reload",
    time: "08:28",
    detail: "提示词目录热重载完成，新版本已投放到 6 个会话。",
    tone: "primary",
  },
]

const queueItems: QueueItem[] = [
  {
    actor: "qq:group:114514",
    command: "summary.compact -> publish.reply",
    latency: "0.91s",
    state: "running",
  },
  {
    actor: "qq:private:1733064202",
    command: "skills.resolve -> tools.search",
    latency: "1.24s",
    state: "queued",
  },
  {
    actor: "maintainer.pi",
    command: "config.models.save -> reload.registry",
    latency: "0.48s",
    state: "applied",
  },
  {
    actor: "qq:group:424242",
    command: "vision.caption -> response.render",
    latency: "1.87s",
    state: "running",
  },
]

const bindings: BindingItem[] = [
  {
    name: "openai-main",
    model: "gpt-5.4 / primary",
    mode: "respond",
  },
  {
    name: "summary-lane",
    model: "gpt-5.4-mini / summarize",
    mode: "summarize",
  },
  {
    name: "vision-fallback",
    model: "gemini-2.5-flash / vision",
    mode: "fallback",
  },
]

const operators: OperatorItem[] = [
  {
    name: "Frontstage",
    role: "public dialog",
    load: 76,
  },
  {
    name: "Maintainer",
    role: "repo + runtime",
    load: 43,
  },
  {
    name: "Subagents",
    role: "bounded workers",
    load: 61,
  },
]

const currentPalette = computed(() => paletteSpecs[props.palette])
const themeVars = computed(() => currentPalette.value.vars)
</script>

<template>
  <section class="glass-lab" :style="themeVars">
    <div class="ambient ambient-a"></div>
    <div class="ambient ambient-b"></div>
    <div class="ambient ambient-c"></div>

    <header class="glass-panel command-deck">
      <div class="command-copy">
        <p class="eyebrow">Preview / Glass Lab</p>
        <h1>{{ currentPalette.label }}</h1>
        <p class="summary">
          {{ currentPalette.description }}
        </p>
        <p class="summary subcopy">
          这一组页面故意固定布局，只换配色语言。你现在看的路径对应的是
          <strong>{{ currentPalette.subtitle }}</strong>。
        </p>
      </div>

      <div class="command-actions">
        <nav class="palette-rail" aria-label="Glass Lab palettes">
          <RouterLink
            v-for="item in palettePaths"
            :key="item.key"
            class="palette-chip"
            :class="{ active: item.key === palette }"
            :to="item.path"
          >
            <span>{{ paletteSpecs[item.key].label }}</span>
            <small>{{ paletteSpecs[item.key].subtitle }}</small>
          </RouterLink>
        </nav>
        <div class="status-strip">
          <span class="status-pill live">Palette compare</span>
          <span class="status-pill">Same layout</span>
          <span class="status-pill">Dense glass</span>
        </div>
      </div>
    </header>

    <section class="metric-grid">
      <article
        v-for="metric in metrics"
        :key="metric.label"
        class="glass-panel metric-card"
        :class="`tone-${metric.tone}`"
      >
        <div class="metric-topline">
          <span class="metric-label">{{ metric.label }}</span>
          <span class="metric-delta">{{ metric.delta }}</span>
        </div>
        <div class="metric-value">{{ metric.value }}</div>
        <p class="metric-detail">{{ metric.detail }}</p>
      </article>
    </section>

    <section class="workspace-grid">
      <article class="glass-panel signal-panel">
        <div class="panel-topline">
          <div>
            <p class="eyebrow subtle">Primary Surface</p>
            <h2>Realtime Signal Deck</h2>
          </div>
          <div class="segmented">
            <button class="active" type="button">10 min</button>
            <button type="button">1 hour</button>
            <button type="button">1 day</button>
          </div>
        </div>

        <div class="signal-grid">
          <section class="chart-card">
            <div class="chart-meta">
              <div>
                <span class="kicker">Throughput Lane</span>
                <strong>runtime -> tools -> response</strong>
              </div>
              <span class="mini-stat">72 req/min</span>
            </div>

            <div class="signal-chart">
              <div class="signal-bars">
                <span
                  v-for="(value, index) in signalBars"
                  :key="index"
                  class="signal-bar"
                  :style="{ height: `${value}%` }"
                ></span>
              </div>
            </div>

            <div class="chart-footer">
              <span>02:00</span>
              <span>04:00</span>
              <span>06:00</span>
              <span>08:00</span>
            </div>
          </section>

          <section class="insight-card">
            <div class="insight-row">
              <span>Response lane</span>
              <strong>stable</strong>
            </div>
            <div class="insight-row">
              <span>Retry pressure</span>
              <strong>low</strong>
            </div>
            <div class="insight-row">
              <span>Plugin volatility</span>
              <strong>medium</strong>
            </div>

            <div class="binding-list">
              <div v-for="item in bindings" :key="item.name" class="binding-item">
                <div>
                  <strong>{{ item.name }}</strong>
                  <p>{{ item.model }}</p>
                </div>
                <span>{{ item.mode }}</span>
              </div>
            </div>
          </section>
        </div>
      </article>

      <aside class="side-stack">
        <article class="glass-panel activity-panel">
          <div class="panel-topline">
            <div>
              <p class="eyebrow subtle">Activity</p>
              <h2>Recent Events</h2>
            </div>
            <span class="mini-stat">4 items</span>
          </div>

          <div class="event-list">
            <article
              v-for="item in events"
              :key="`${item.time}-${item.title}`"
              class="event-item"
              :class="`tone-${item.tone}`"
            >
              <div class="event-time">{{ item.time }}</div>
              <div class="event-copy">
                <strong>{{ item.title }}</strong>
                <p>{{ item.detail }}</p>
              </div>
            </article>
          </div>
        </article>

        <article class="glass-panel operator-panel">
          <div class="panel-topline">
            <div>
              <p class="eyebrow subtle">Operators</p>
              <h2>Load Window</h2>
            </div>
            <span class="mini-stat">3 lanes</span>
          </div>

          <div class="operator-list">
            <article v-for="item in operators" :key="item.name" class="operator-item">
              <div class="operator-copy">
                <strong>{{ item.name }}</strong>
                <span>{{ item.role }}</span>
              </div>
              <div class="load-track">
                <span class="load-bar" :style="{ width: `${item.load}%` }"></span>
              </div>
              <div class="load-value">{{ item.load }}%</div>
            </article>
          </div>
        </article>
      </aside>
    </section>

    <section class="lower-grid">
      <article class="glass-panel queue-panel">
        <div class="panel-topline">
          <div>
            <p class="eyebrow subtle">Execution</p>
            <h2>Command Queue</h2>
          </div>
          <button class="ghost-button compact" type="button">Inspect queue</button>
        </div>

        <div class="queue-table">
          <div class="queue-head">
            <span>Actor</span>
            <span>Pipeline</span>
            <span>Latency</span>
            <span>State</span>
          </div>
          <div v-for="item in queueItems" :key="`${item.actor}-${item.command}`" class="queue-row">
            <span>{{ item.actor }}</span>
            <span>{{ item.command }}</span>
            <span>{{ item.latency }}</span>
            <span class="state-chip">{{ item.state }}</span>
          </div>
        </div>
      </article>

      <article class="glass-panel compose-panel">
        <div class="panel-topline">
          <div>
            <p class="eyebrow subtle">Compact Form</p>
            <h2>Control Editor</h2>
          </div>
          <button class="primary-button compact" type="button">Save draft</button>
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
            <input type="text" value="让控制面的视觉语言不再默认发蓝" />
          </label>
          <label class="field">
            <span>Risk lane</span>
            <select>
              <option>medium</option>
            </select>
          </label>
          <label class="field">
            <span>Autonomy</span>
            <select>
              <option>maintainer-gated</option>
            </select>
          </label>
          <label class="field full">
            <span>Operator note</span>
            <textarea rows="5">这次只比较 palette，不比较布局。先挑中一个色系，再把 token 迁回真实页面。</textarea>
          </label>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.glass-lab {
  position: relative;
  display: grid;
  gap: 18px;
  min-height: calc(100vh - 48px);
  padding-bottom: 12px;
  isolation: isolate;
  overflow: hidden;
  font-family:
    "IBM Plex Sans",
    "Noto Sans SC",
    "PingFang SC",
    "Microsoft YaHei",
    sans-serif;
}

.ambient {
  position: absolute;
  inset: auto;
  pointer-events: none;
  filter: blur(18px);
  opacity: 0.88;
  z-index: -1;
}

.ambient-a {
  top: -80px;
  right: 6%;
  width: 340px;
  height: 340px;
  border-radius: 999px;
  background: var(--ambient-a);
}

.ambient-b {
  top: 26%;
  left: -120px;
  width: 300px;
  height: 300px;
  border-radius: 999px;
  background: var(--ambient-b);
}

.ambient-c {
  right: 12%;
  bottom: -120px;
  width: 280px;
  height: 280px;
  border-radius: 999px;
  background: var(--ambient-c);
}

.glass-panel {
  position: relative;
  border: 1px solid var(--panel-border);
  border-radius: 28px;
  background:
    linear-gradient(180deg, var(--panel-base-start) 0%, var(--panel-base-end) 100%),
    linear-gradient(135deg, var(--panel-tint) 0%, rgba(255, 255, 255, 0) 52%);
  box-shadow:
    inset 0 1px 0 var(--panel-highlight),
    inset 0 0 0 1px rgba(255, 255, 255, 0.012),
    var(--panel-shadow);
  backdrop-filter: blur(22px);
}

.glass-panel::before {
  content: "";
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.045), rgba(255, 255, 255, 0));
  pointer-events: none;
}

.command-deck,
.signal-panel,
.activity-panel,
.operator-panel,
.queue-panel,
.compose-panel {
  padding: 18px 18px 16px;
}

.command-deck {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
}

.command-copy {
  max-width: 700px;
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--eyebrow);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.eyebrow.subtle {
  color: var(--eyebrow-muted);
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  font-size: clamp(30px, 4vw, 42px);
  line-height: 1.02;
  color: var(--title);
  letter-spacing: -0.04em;
}

h2 {
  font-size: 18px;
  color: var(--title);
  letter-spacing: -0.02em;
}

.summary {
  margin-top: 10px;
  max-width: 720px;
  color: var(--muted);
  line-height: 1.55;
}

.summary strong {
  color: var(--text);
}

.subcopy {
  margin-top: 6px;
}

.command-actions {
  display: grid;
  gap: 12px;
  min-width: 360px;
}

.palette-rail {
  display: grid;
  gap: 8px;
}

.palette-chip {
  display: grid;
  gap: 3px;
  padding: 11px 13px;
  border: 1px solid var(--pill-border);
  border-radius: 18px;
  background: var(--pill-bg);
  color: var(--pill-text);
  text-decoration: none;
  transition:
    transform 140ms ease,
    border-color 140ms ease,
    background-color 140ms ease;
}

.palette-chip span {
  font-size: 13px;
  font-weight: 700;
}

.palette-chip small {
  color: var(--muted);
  font-size: 12px;
}

.palette-chip:hover {
  transform: translateY(-1px);
}

.palette-chip.active {
  border-color: color-mix(in srgb, var(--tone-primary) 34%, transparent);
  background: linear-gradient(135deg, color-mix(in srgb, var(--tone-primary) 20%, transparent), rgba(255, 255, 255, 0.02));
}

.status-strip {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--pill-border);
  border-radius: 999px;
  background: var(--pill-bg);
  color: var(--pill-text);
  font-size: 12px;
  font-weight: 600;
}

.status-pill.live {
  color: var(--pill-live);
}

.metric-grid,
.lower-grid {
  display: grid;
  gap: 14px;
}

.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  padding: 14px 16px;
}

.metric-topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.metric-label,
.metric-detail,
.mini-stat,
.binding-item p,
.operator-copy span,
.chart-footer,
.event-copy p,
.queue-head,
.field span {
  color: var(--muted);
}

.metric-label,
.mini-stat,
.queue-head,
.field span {
  font-size: 12px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.metric-delta {
  font-size: 12px;
  font-weight: 700;
}

.metric-value {
  margin-top: 14px;
  color: var(--title);
  font-size: 34px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.05em;
}

.metric-detail {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.45;
}

.tone-primary .metric-delta,
.tone-primary .event-time,
.tone-primary .state-chip {
  color: var(--tone-primary);
}

.tone-positive .metric-delta,
.tone-positive .event-time {
  color: var(--tone-positive);
}

.tone-warning .metric-delta,
.tone-warning .event-time {
  color: var(--tone-warning);
}

.tone-danger .metric-delta,
.tone-danger .event-time {
  color: var(--tone-danger);
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.9fr);
  gap: 14px;
}

.side-stack {
  display: grid;
  gap: 14px;
}

.panel-topline {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.segmented {
  display: inline-grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--pill-border);
  border-radius: 18px;
  background: var(--segment-bg);
}

.segmented button,
.ghost-button,
.primary-button,
.compact,
input,
select,
textarea {
  font: inherit;
}

.segmented button,
.ghost-button,
.primary-button {
  border-radius: 14px;
  padding: 10px 14px;
  cursor: pointer;
}

.segmented button {
  border: 0;
  background: transparent;
  color: var(--segment-text);
}

.segmented button.active {
  background: var(--segment-active-bg);
  color: var(--segment-active-text);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--tone-primary) 14%, transparent);
}

.signal-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(240px, 0.85fr);
  gap: 14px;
}

.chart-card,
.insight-card {
  border: 1px solid color-mix(in srgb, var(--panel-border) 82%, transparent);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.024);
  padding: 14px;
}

.chart-meta,
.insight-row,
.binding-item,
.operator-item,
.queue-head,
.queue-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.kicker {
  display: block;
  margin-bottom: 4px;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--eyebrow-muted);
}

.chart-meta strong,
.binding-item strong,
.event-copy strong,
.operator-copy strong,
.insight-row strong,
.queue-row,
.load-value {
  color: var(--text);
}

.signal-chart {
  position: relative;
  margin-top: 14px;
  height: 248px;
  border-radius: 18px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)),
    repeating-linear-gradient(
      to top,
      var(--chart-line) 0,
      var(--chart-line) 1px,
      transparent 1px,
      transparent 52px
    );
}

.signal-chart::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, var(--chart-glow), rgba(255, 255, 255, 0));
  pointer-events: none;
}

.signal-bars {
  position: absolute;
  inset: 18px 18px 14px;
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
}

.signal-bar {
  border-radius: 999px 999px 10px 10px;
  background: linear-gradient(180deg, var(--bar-top), var(--bar-bottom));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    0 0 28px var(--bar-glow);
}

.insight-card {
  display: grid;
  gap: 12px;
}

.insight-row {
  padding-bottom: 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--panel-border) 70%, transparent);
}

.binding-list,
.event-list,
.operator-list {
  display: grid;
  gap: 10px;
}

.binding-item,
.event-item,
.operator-item {
  border: 1px solid color-mix(in srgb, var(--panel-border) 82%, transparent);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.024);
  padding: 12px;
}

.event-item {
  display: grid;
  grid-template-columns: 52px 1fr;
  gap: 12px;
  align-items: flex-start;
}

.event-time {
  min-width: 46px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.load-track {
  flex: 1;
  min-width: 110px;
  height: 8px;
  border-radius: 999px;
  background: var(--track-bg);
  overflow: hidden;
}

.load-bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--load-start), var(--load-end));
}

.load-value {
  width: 44px;
  text-align: right;
  font-size: 13px;
  font-weight: 700;
}

.queue-table {
  display: grid;
  gap: 8px;
}

.queue-head,
.queue-row {
  display: grid;
  grid-template-columns: 1.25fr 1.8fr 0.7fr 0.7fr;
  gap: 12px;
  align-items: center;
}

.queue-head {
  padding: 0 4px;
}

.queue-row {
  border: 1px solid color-mix(in srgb, var(--panel-border) 82%, transparent);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.024);
  padding: 12px 14px;
  font-size: 13px;
}

.state-chip {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--tone-primary) 10%, transparent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.lower-grid {
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.95fr);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
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
  border: 1px solid var(--field-border);
  border-radius: 16px;
  background: var(--field-bg);
  color: var(--text);
  padding: 12px 13px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

textarea {
  resize: vertical;
}

.ghost-button,
.primary-button {
  border: 1px solid var(--field-border);
}

.ghost-button {
  background: var(--ghost-bg);
  color: var(--text);
}

.primary-button {
  border-color: transparent;
  background: linear-gradient(135deg, var(--primary-start), var(--primary-end));
  color: var(--primary-text);
  box-shadow: var(--primary-shadow);
}

.compact {
  padding: 9px 12px;
}

@media (max-width: 1280px) {
  .metric-grid,
  .lower-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workspace-grid,
  .signal-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .glass-lab {
    min-height: auto;
  }

  .command-deck {
    flex-direction: column;
  }

  .command-actions {
    min-width: 0;
    width: 100%;
  }

  .metric-grid,
  .lower-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .queue-head,
  .queue-row {
    grid-template-columns: 1fr;
  }
}
</style>
