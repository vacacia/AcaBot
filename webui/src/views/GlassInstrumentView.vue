<script setup lang="ts">
const studyLinks = [
  {
    label: "Palette Compare",
    subtitle: "同布局，仅比较色系",
    path: "/preview/glass-lab/graphite",
  },
  {
    label: "Editorial Graphite",
    subtitle: "石墨编辑系统",
    path: "/preview/glass-lab/editorial-graphite",
  },
  {
    label: "Instrument Brass",
    subtitle: "精密仪器控制面",
    path: "/preview/glass-lab/instrument-brass",
  },
]

const meters = [
  { label: "Thread bus", value: "128", note: "active lanes" },
  { label: "Median latency", value: "842", note: "milliseconds" },
  { label: "Fallback drift", value: "03", note: "flagged" },
  { label: "Tool success", value: "97.8", note: "percent" },
]

const waveform = [26, 44, 58, 49, 72, 66, 84, 62, 46, 67, 54, 61]

const modules = [
  {
    tag: "A1",
    title: "Gateway bus",
    note: "NapCat link healthy, transport noise low.",
  },
  {
    tag: "B2",
    title: "Model regulator",
    note: "Primary lane stable, summary fallback warm.",
  },
  {
    tag: "C3",
    title: "Sandbox chamber",
    note: "Timeout pocket persists on image-captioner.",
  },
]

const alerts = [
  ["08:42", "NapCat reconnect", "recovered in 4s"],
  ["08:39", "Fallback chain", "summary lane intercepted"],
  ["08:33", "Sandbox timeout", "cooldown engaged"],
  ["08:28", "Prompt reload", "6 sessions updated"],
]

const controlRows = [
  ["maintainer.pi", "reload.registry", "0.48s", "applied"],
  ["qq:group:114514", "publish.reply", "0.91s", "running"],
  ["qq:private:1733064202", "tools.search", "1.24s", "queued"],
  ["qq:group:424242", "vision.caption", "1.87s", "running"],
]
</script>

<template>
  <section class="instrument-page">
    <div class="glow glow-a"></div>
    <div class="glow glow-b"></div>

    <header class="headframe">
      <div class="titleblock">
        <p class="eyebrow">Preview / Instrument Study</p>
        <h1>Instrument Brass</h1>
        <p class="dek">
          这版把控制面当成设备，而不是网站。减少柔软的模板感，增加刻度、槽位、铭牌、数码读数和硬边分区。
        </p>
      </div>

      <div class="selector-panel">
        <p class="panel-label">Route selector</p>
        <RouterLink
          v-for="item in studyLinks"
          :key="item.path"
          class="selector-link"
          :class="{ active: item.path === '/preview/glass-lab/instrument-brass' }"
          :to="item.path"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.subtitle }}</span>
        </RouterLink>
      </div>
    </header>

    <section class="meter-rack">
      <article v-for="item in meters" :key="item.label" class="meter-card">
        <span class="meter-label">{{ item.label }}</span>
        <div class="meter-display">{{ item.value }}</div>
        <span class="meter-note">{{ item.note }}</span>
      </article>
    </section>

    <section class="console-grid">
      <article class="scope-panel">
        <div class="module-head">
          <div>
            <p class="module-tag">Primary scope</p>
            <h2>Runtime pulse</h2>
          </div>
          <div class="module-badges">
            <span>coal body</span>
            <span>brass accents</span>
          </div>
        </div>

        <div class="scope-box">
          <div class="waveform">
            <span
              v-for="(value, index) in waveform"
              :key="index"
              class="wave-bar"
              :style="{ height: `${value}%` }"
            ></span>
          </div>
          <div class="scope-ticks">
            <span>02</span>
            <span>04</span>
            <span>06</span>
            <span>08</span>
            <span>10</span>
          </div>
        </div>

        <div class="module-grid">
          <article v-for="item in modules" :key="item.tag" class="module-card">
            <span class="module-id">{{ item.tag }}</span>
            <strong>{{ item.title }}</strong>
            <p>{{ item.note }}</p>
          </article>
        </div>
      </article>

      <aside class="right-rack">
        <article class="alert-panel">
          <div class="module-head">
            <div>
              <p class="module-tag">Alert strip</p>
              <h2>Recent events</h2>
            </div>
            <span class="count">04</span>
          </div>

          <div class="alert-list">
            <article v-for="item in alerts" :key="item.join('-')" class="alert-item">
              <span class="alert-time">{{ item[0] }}</span>
              <div>
                <strong>{{ item[1] }}</strong>
                <p>{{ item[2] }}</p>
              </div>
            </article>
          </div>
        </article>

        <article class="dial-panel">
          <p class="module-tag">Operator load</p>
          <div class="dial-shell">
            <div class="dial-ring">
              <div class="dial-core">
                <strong>76%</strong>
                <span>frontstage</span>
              </div>
            </div>
          </div>
          <p class="dial-note">
            这版的“高级感”来自设备语言: 结构更硬，模块更像机箱，强调可信而不是柔软。
          </p>
        </article>
      </aside>
    </section>

    <section class="lower-console">
      <article class="table-panel">
        <div class="module-head">
          <div>
            <p class="module-tag">Bus table</p>
            <h2>Control queue</h2>
          </div>
          <span class="count">live</span>
        </div>

        <div class="table-head">
          <span>actor</span>
          <span>command</span>
          <span>latency</span>
          <span>state</span>
        </div>
        <div v-for="row in controlRows" :key="row.join('-')" class="table-row">
          <span>{{ row[0] }}</span>
          <span>{{ row[1] }}</span>
          <span>{{ row[2] }}</span>
          <span class="chip">{{ row[3] }}</span>
        </div>
      </article>

      <article class="editor-panel">
        <div class="module-head">
          <div>
            <p class="module-tag">Adjustment bay</p>
            <h2>Operator input</h2>
          </div>
          <button type="button">Commit</button>
        </div>

        <div class="form-grid">
          <label>
            <span>workspace</span>
            <input type="text" value="maintainer.pi" />
          </label>
          <label>
            <span>preset</span>
            <select>
              <option>gpt-5.4 / primary</option>
            </select>
          </label>
          <label class="full">
            <span>intent</span>
            <input type="text" value="把控制面做得像可信的设备，而不是模板卡片" />
          </label>
          <label class="full">
            <span>operator note</span>
            <textarea rows="5">控制面如果要显贵，往往不是更软、更亮，而是更硬、更准、更像一台被精心打磨过的仪器。</textarea>
          </label>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.instrument-page {
  position: relative;
  display: grid;
  gap: 18px;
  min-height: calc(100vh - 48px);
  padding-bottom: 18px;
  color: #ead7bc;
  overflow: hidden;
  font-family:
    "Avenir Next Condensed",
    "DIN Alternate",
    "Bahnschrift",
    "IBM Plex Sans",
    "Noto Sans SC",
    sans-serif;
}

.instrument-page::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at top right, rgba(230, 187, 120, 0.08), transparent 28%),
    linear-gradient(180deg, #120e0a, #0b0806);
  z-index: -3;
}

.glow {
  position: absolute;
  border-radius: 999px;
  filter: blur(28px);
  pointer-events: none;
  z-index: -2;
}

.glow-a {
  top: -120px;
  right: 10%;
  width: 300px;
  height: 300px;
  background: radial-gradient(circle, rgba(224, 175, 98, 0.18), transparent 70%);
}

.glow-b {
  left: -100px;
  bottom: 10%;
  width: 240px;
  height: 240px;
  background: radial-gradient(circle, rgba(142, 100, 58, 0.18), transparent 72%);
}

.headframe,
.meter-card,
.scope-panel,
.alert-panel,
.dial-panel,
.table-panel,
.editor-panel,
.selector-panel {
  position: relative;
  border: 1px solid rgba(195, 152, 94, 0.2);
  background:
    linear-gradient(180deg, rgba(38, 27, 19, 0.88), rgba(17, 12, 8, 0.94)),
    linear-gradient(135deg, rgba(215, 173, 109, 0.04), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgba(255, 238, 216, 0.06),
    inset 0 0 0 1px rgba(255, 255, 255, 0.01),
    0 26px 60px rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(18px);
}

.headframe {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) 360px;
  gap: 18px;
  padding: 22px;
  border-radius: 18px;
}

.eyebrow,
.panel-label,
.module-tag,
.meter-label,
.table-head,
label span {
  color: rgba(223, 191, 142, 0.72);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  margin-top: 10px;
  color: #f3e7d5;
  font-size: clamp(38px, 5vw, 64px);
  line-height: 0.94;
  letter-spacing: -0.05em;
  text-transform: uppercase;
}

h2 {
  color: #f1dfc4;
  font-size: 24px;
  line-height: 1;
  letter-spacing: -0.04em;
  text-transform: uppercase;
}

.dek,
.module-card p,
.alert-item p,
.dial-note {
  color: rgba(223, 210, 193, 0.82);
  line-height: 1.56;
}

.dek {
  max-width: 760px;
  margin-top: 14px;
  font-size: 18px;
}

.selector-panel {
  display: grid;
  gap: 8px;
  align-self: start;
  padding: 16px;
  border-radius: 16px;
}

.selector-link {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid rgba(195, 152, 94, 0.18);
  border-radius: 12px;
  color: inherit;
  text-decoration: none;
  background: rgba(255, 255, 255, 0.02);
}

.selector-link strong {
  color: #f2e5cf;
  font-size: 14px;
  text-transform: uppercase;
}

.selector-link span {
  color: rgba(220, 200, 173, 0.74);
  font-size: 12px;
}

.selector-link.active {
  border-color: rgba(230, 190, 128, 0.3);
  background: linear-gradient(135deg, rgba(231, 188, 118, 0.08), rgba(255, 255, 255, 0.02));
}

.meter-rack {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.meter-card {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 14px;
}

.meter-display {
  padding: 10px 12px;
  border: 1px solid rgba(214, 175, 110, 0.16);
  border-radius: 10px;
  background: rgba(4, 4, 4, 0.24);
  color: #f2d8a5;
  font-size: 38px;
  line-height: 1;
  letter-spacing: -0.06em;
  font-family:
    "IBM Plex Mono",
    "SFMono-Regular",
    "Consolas",
    monospace;
}

.meter-note,
.module-badges span,
.count {
  color: rgba(216, 198, 171, 0.74);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.console-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) 400px;
  gap: 14px;
}

.scope-panel,
.alert-panel,
.dial-panel,
.table-panel,
.editor-panel {
  border-radius: 16px;
  padding: 18px;
}

.module-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.module-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.module-badges span {
  padding: 6px 8px;
  border: 1px solid rgba(195, 152, 94, 0.16);
  border-radius: 999px;
}

.scope-box {
  padding: 14px;
  border: 1px solid rgba(198, 158, 98, 0.14);
  border-radius: 12px;
  background:
    linear-gradient(180deg, rgba(236, 201, 142, 0.02), rgba(236, 201, 142, 0)),
    rgba(0, 0, 0, 0.18);
}

.waveform {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  align-items: end;
  gap: 8px;
  height: 210px;
  border: 1px solid rgba(198, 158, 98, 0.14);
  padding: 14px;
  background:
    repeating-linear-gradient(
      to top,
      rgba(222, 188, 132, 0.08) 0,
      rgba(222, 188, 132, 0.08) 1px,
      transparent 1px,
      transparent 46px
    );
}

.wave-bar {
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, rgba(245, 220, 173, 0.92), rgba(171, 117, 57, 0.18));
  box-shadow:
    inset 0 1px 0 rgba(255, 238, 212, 0.12),
    0 0 20px rgba(220, 177, 108, 0.12);
}

.scope-ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: rgba(210, 191, 164, 0.72);
  font-size: 12px;
  font-family:
    "IBM Plex Mono",
    "SFMono-Regular",
    "Consolas",
    monospace;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.module-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid rgba(195, 152, 94, 0.16);
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.16);
}

.module-id {
  display: inline-flex;
  width: fit-content;
  padding: 5px 8px;
  border: 1px solid rgba(198, 158, 98, 0.2);
  border-radius: 999px;
  color: #f0d39d;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.module-card strong,
.alert-item strong {
  color: #f2dfbf;
  font-size: 18px;
}

.right-rack {
  display: grid;
  gap: 14px;
}

.alert-list {
  display: grid;
  gap: 10px;
}

.alert-item {
  display: grid;
  grid-template-columns: 62px 1fr;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(195, 152, 94, 0.14);
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.16);
}

.alert-time {
  color: #f1d39d;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  font-family:
    "IBM Plex Mono",
    "SFMono-Regular",
    "Consolas",
    monospace;
}

.dial-shell {
  display: grid;
  place-items: center;
  padding: 16px 0 18px;
}

.dial-ring {
  display: grid;
  place-items: center;
  width: 210px;
  height: 210px;
  border-radius: 999px;
  background:
    radial-gradient(circle at center, rgba(10, 7, 5, 0.92) 52%, transparent 53%),
    conic-gradient(from 210deg, rgba(112, 74, 35, 0.4), rgba(242, 205, 142, 0.96), rgba(112, 74, 35, 0.24));
  box-shadow:
    inset 0 0 0 16px rgba(32, 22, 14, 0.96),
    inset 0 0 0 18px rgba(198, 158, 98, 0.12);
}

.dial-core {
  display: grid;
  gap: 6px;
  place-items: center;
  width: 118px;
  height: 118px;
  border-radius: 999px;
  background: linear-gradient(180deg, rgba(26, 18, 12, 0.98), rgba(10, 7, 5, 0.98));
  box-shadow: inset 0 1px 0 rgba(255, 238, 212, 0.08);
}

.dial-core strong {
  color: #f1d6a6;
  font-size: 34px;
  line-height: 1;
  font-family:
    "IBM Plex Mono",
    "SFMono-Regular",
    "Consolas",
    monospace;
}

.dial-core span {
  color: rgba(217, 196, 168, 0.74);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.dial-note {
  max-width: 28ch;
}

.lower-console {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.9fr);
  gap: 14px;
}

.table-head,
.table-row {
  display: grid;
  grid-template-columns: 1.1fr 1.45fr 0.65fr 0.7fr;
  gap: 12px;
  align-items: center;
}

.table-head {
  padding: 0 2px 10px;
}

.table-row {
  padding: 12px 2px;
  border-top: 1px solid rgba(195, 152, 94, 0.14);
  color: rgba(231, 218, 196, 0.92);
  font-size: 14px;
}

.chip {
  display: inline-flex;
  width: fit-content;
  padding: 5px 8px;
  border: 1px solid rgba(198, 158, 98, 0.2);
  border-radius: 999px;
  color: #f1d39d;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.editor-panel button,
input,
select,
textarea {
  font: inherit;
}

.editor-panel button {
  border: 1px solid rgba(198, 158, 98, 0.18);
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(236, 196, 129, 0.92), rgba(137, 92, 45, 0.88));
  color: #140e09;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

label {
  display: grid;
  gap: 8px;
}

label.full {
  grid-column: 1 / -1;
}

input,
select,
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid rgba(198, 158, 98, 0.14);
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.18);
  color: #f0dfc2;
  padding: 12px 13px;
}

textarea {
  resize: vertical;
  line-height: 1.58;
}

@media (max-width: 1280px) {
  .headframe,
  .console-grid,
  .lower-console {
    grid-template-columns: 1fr;
  }

  .selector-panel {
    max-width: 420px;
  }
}

@media (max-width: 900px) {
  .meter-rack,
  .module-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .table-head,
  .table-row {
    grid-template-columns: 1fr;
  }
}
</style>
