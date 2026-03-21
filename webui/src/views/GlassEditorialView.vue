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

const ledger = [
  { label: "System posture", value: "Stable", note: "线路稳定，无需强干预" },
  { label: "Median latency", value: "842 ms", note: "相比昨日回落 180 ms" },
  { label: "Open threads", value: "128", note: "最近 10 分钟仍在滚动的会话" },
  { label: "Intervention flags", value: "03", note: "建议 maintainer 主动复核" },
]

const signalBars = [22, 38, 64, 45, 76, 57, 82, 63, 44, 71, 53, 61]

const highlights = [
  {
    title: "Runtime notes",
    body: "当前主线路并不紧张，真正需要注意的是 sandbox timeout 和 fallback 漂移，而不是纯吞吐量。",
  },
  {
    title: "Operator posture",
    body: "把注意力集中在异常段、人工接管窗口和配置变更影响面，不要把每个卡片都做成会说话的对象。",
  },
]

const events = [
  { time: "08:42", title: "NapCat reconnect", note: "4 秒内完成重连，未形成消息积压。" },
  { time: "08:39", title: "Fallback chain", note: "summary lane 接手两次请求，当前已经恢复主线。" },
  { time: "08:33", title: "Sandbox timeout", note: "image-captioner 第三次超时，已进入 cooldown。" },
  { time: "08:28", title: "Prompt reload", note: "新版本提示词已经扩散到 6 个会话。" },
]

const queueRows = [
  ["maintainer.pi", "config.models.save -> reload.registry", "0.48s", "applied"],
  ["qq:group:114514", "summary.compact -> publish.reply", "0.91s", "running"],
  ["qq:private:1733064202", "skills.resolve -> tools.search", "1.24s", "queued"],
  ["qq:group:424242", "vision.caption -> response.render", "1.87s", "running"],
]
</script>

<template>
  <section class="editorial-page">
    <div class="ambient ambient-a"></div>
    <div class="ambient ambient-b"></div>

    <header class="masthead">
      <div class="hero-copy">
        <p class="eyebrow">Preview / Editorial Study</p>
        <h1>Editorial Graphite</h1>
        <p class="dek">
          这版不追求“有玻璃效果”，而是先把审美判断拉正。颜色收敛到石墨和纸白，强调排版、留白、硬边界和阅读秩序。
        </p>
        <div class="hero-meta">
          <span>Dense glass, but restrained.</span>
          <span>No neon, no candy gradients.</span>
        </div>
      </div>

      <aside class="study-panel">
        <p class="panel-label">Studies</p>
        <RouterLink
          v-for="item in studyLinks"
          :key="item.path"
          class="study-link"
          :class="{ active: item.path === '/preview/glass-lab/editorial-graphite' }"
          :to="item.path"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.subtitle }}</span>
        </RouterLink>
      </aside>
    </header>

    <section class="ledger-strip">
      <article v-for="item in ledger" :key="item.label" class="ledger-card">
        <span class="ledger-label">{{ item.label }}</span>
        <strong class="ledger-value">{{ item.value }}</strong>
        <p class="ledger-note">{{ item.note }}</p>
      </article>
    </section>

    <section class="editorial-grid">
      <article class="briefing-card">
        <div class="section-head">
          <div>
            <p class="section-kicker">Briefing</p>
            <h2>System rhythm</h2>
          </div>
          <span class="section-meta">Updated 08:42</span>
        </div>

        <div class="chart-shell">
          <div class="chart-copy">
            <p>
              高级感不是把每块都做得很“亮”，而是让主要信息区像一张真正可阅读的版面。
              图表退到辅助位，只承担节奏，不抢标题。
            </p>
          </div>
          <div class="chart-box">
            <div class="bars">
              <span
                v-for="(value, index) in signalBars"
                :key="index"
                class="bar"
                :style="{ height: `${value}%` }"
              ></span>
            </div>
            <div class="ticks">
              <span>02:00</span>
              <span>04:00</span>
              <span>06:00</span>
              <span>08:00</span>
            </div>
          </div>
        </div>

        <div class="highlight-grid">
          <article v-for="item in highlights" :key="item.title" class="highlight-card">
            <h3>{{ item.title }}</h3>
            <p>{{ item.body }}</p>
          </article>
        </div>
      </article>

      <aside class="side-column">
        <article class="event-card">
          <div class="section-head">
            <div>
              <p class="section-kicker">Event ledger</p>
              <h2>Recent events</h2>
            </div>
            <span class="section-meta">4 entries</span>
          </div>

          <div class="event-list">
            <article v-for="item in events" :key="`${item.time}-${item.title}`" class="event-item">
              <span class="event-time">{{ item.time }}</span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.note }}</p>
              </div>
            </article>
          </div>
        </article>

        <article class="note-card">
          <p class="section-kicker">Design stance</p>
          <p>
            这一版用的是“昂贵排版”而不是“昂贵材质”。如果这条路成立，真实控制面可以更像管理出版系统或投研后台，而不是模板化 SaaS。
          </p>
        </article>
      </aside>
    </section>

    <section class="tableau">
      <article class="queue-card">
        <div class="section-head">
          <div>
            <p class="section-kicker">Queue</p>
            <h2>Execution table</h2>
          </div>
          <span class="section-meta">Live rows</span>
        </div>

        <div class="queue-head">
          <span>Actor</span>
          <span>Pipeline</span>
          <span>Latency</span>
          <span>State</span>
        </div>
        <div v-for="row in queueRows" :key="row.join('-')" class="queue-row">
          <span>{{ row[0] }}</span>
          <span>{{ row[1] }}</span>
          <span>{{ row[2] }}</span>
          <span class="state">{{ row[3] }}</span>
        </div>
      </article>

      <article class="form-card">
        <div class="section-head">
          <div>
            <p class="section-kicker">Editor</p>
            <h2>Intervention note</h2>
          </div>
          <button type="button">Save draft</button>
        </div>

        <div class="form-grid">
          <label>
            <span>Workspace</span>
            <input type="text" value="maintainer.pi" />
          </label>
          <label>
            <span>Model lane</span>
            <select>
              <option>gpt-5.4 / primary</option>
            </select>
          </label>
          <label class="full">
            <span>Intent</span>
            <input type="text" value="优先把审美骨架做对，而不是继续堆发光和半透明" />
          </label>
          <label class="full">
            <span>Operator note</span>
            <textarea rows="5">这版把贵气放在字体关系、边界、留白和结构秩序上。真正的 glass 只退到材质提示，而不是主角。</textarea>
          </label>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.editorial-page {
  position: relative;
  display: grid;
  gap: 20px;
  min-height: calc(100vh - 48px);
  padding-bottom: 18px;
  color: #e9ecef;
  overflow: hidden;
}

.editorial-page::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at top right, rgba(255, 255, 255, 0.04), transparent 30%),
    linear-gradient(180deg, rgba(18, 20, 24, 0.98), rgba(11, 12, 15, 0.98));
  z-index: -3;
}

.ambient {
  position: absolute;
  border-radius: 999px;
  filter: blur(32px);
  opacity: 0.9;
  pointer-events: none;
  z-index: -2;
}

.ambient-a {
  top: -120px;
  left: 22%;
  width: 320px;
  height: 320px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.1), transparent 70%);
}

.ambient-b {
  right: -80px;
  bottom: 12%;
  width: 240px;
  height: 240px;
  background: radial-gradient(circle, rgba(198, 204, 210, 0.1), transparent 72%);
}

.masthead,
.briefing-card,
.event-card,
.note-card,
.queue-card,
.form-card,
.study-panel,
.ledger-card {
  position: relative;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(180deg, rgba(31, 34, 39, 0.84), rgba(17, 18, 21, 0.92));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.04),
    0 24px 60px rgba(0, 0, 0, 0.26);
  backdrop-filter: blur(20px);
}

.masthead {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) 360px;
  gap: 24px;
  padding: 28px 28px 26px;
  border-radius: 26px;
}

.hero-copy {
  max-width: 860px;
}

.eyebrow,
.panel-label,
.section-kicker,
.ledger-label,
.queue-head,
label span {
  color: rgba(198, 204, 210, 0.72);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  margin-top: 10px;
  color: #f5f3f1;
  font-size: clamp(42px, 6vw, 76px);
  line-height: 0.94;
  letter-spacing: -0.055em;
  font-family:
    "Iowan Old Style",
    "Palatino Linotype",
    "Book Antiqua",
    "Songti SC",
    serif;
  font-weight: 700;
}

h2 {
  color: #f1efed;
  font-size: 28px;
  line-height: 1;
  letter-spacing: -0.04em;
  font-family:
    "Iowan Old Style",
    "Palatino Linotype",
    "Book Antiqua",
    "Songti SC",
    serif;
  font-weight: 700;
}

h3 {
  color: #f2efec;
  font-size: 16px;
  line-height: 1.1;
  letter-spacing: -0.03em;
}

.dek,
.note-card p,
.highlight-card p,
.event-item p {
  color: rgba(217, 221, 226, 0.84);
  line-height: 1.58;
}

.dek {
  max-width: 760px;
  margin-top: 18px;
  font-size: 19px;
}

.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 22px;
  color: rgba(173, 179, 186, 0.74);
  font-size: 13px;
}

.study-panel {
  display: grid;
  gap: 10px;
  align-self: start;
  padding: 18px;
  border-radius: 22px;
}

.study-link {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 16px;
  color: inherit;
  text-decoration: none;
  background: rgba(255, 255, 255, 0.02);
  transition:
    transform 120ms ease,
    border-color 120ms ease;
}

.study-link strong {
  color: #f0efed;
  font-size: 14px;
}

.study-link span {
  color: rgba(184, 190, 197, 0.78);
  font-size: 12px;
}

.study-link:hover {
  transform: translateY(-1px);
}

.study-link.active {
  border-color: rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.04);
}

.ledger-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.ledger-card {
  display: grid;
  gap: 10px;
  padding: 16px 18px 18px;
  border-radius: 22px;
}

.ledger-value {
  color: #f4f1ee;
  font-size: 34px;
  line-height: 1;
  letter-spacing: -0.05em;
}

.ledger-note {
  color: rgba(195, 201, 207, 0.76);
  line-height: 1.45;
}

.editorial-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) 420px;
  gap: 14px;
}

.briefing-card,
.event-card,
.note-card,
.queue-card,
.form-card {
  border-radius: 24px;
  padding: 22px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.section-meta {
  color: rgba(184, 190, 197, 0.78);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.chart-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.chart-copy {
  color: rgba(213, 218, 223, 0.82);
  font-size: 16px;
  line-height: 1.68;
}

.chart-box {
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 22px;
  padding: 16px 16px 12px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0)),
    rgba(0, 0, 0, 0.16);
}

.bars {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
  height: 240px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background:
    repeating-linear-gradient(
      to top,
      rgba(255, 255, 255, 0.05) 0,
      rgba(255, 255, 255, 0.05) 1px,
      transparent 1px,
      transparent 52px
    );
}

.bar {
  border-radius: 999px 999px 10px 10px;
  background: linear-gradient(180deg, rgba(244, 241, 236, 0.86), rgba(244, 241, 236, 0.16));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
  color: rgba(181, 188, 195, 0.74);
  font-size: 12px;
}

.highlight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.highlight-card {
  padding: 16px 16px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.02);
}

.highlight-card p {
  margin-top: 10px;
}

.side-column {
  display: grid;
  gap: 14px;
}

.event-list {
  display: grid;
  gap: 10px;
}

.event-item {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 14px;
  padding: 14px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.event-item:first-child {
  border-top: 0;
  padding-top: 0;
}

.event-time {
  color: rgba(244, 240, 235, 0.92);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.event-item strong {
  color: #f1efed;
  font-size: 18px;
  line-height: 1.1;
}

.event-item p {
  margin-top: 6px;
}

.note-card p {
  max-width: 36ch;
}

.tableau {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(360px, 0.92fr);
  gap: 14px;
}

.queue-head,
.queue-row {
  display: grid;
  grid-template-columns: 1.2fr 1.8fr 0.65fr 0.65fr;
  gap: 14px;
  align-items: center;
}

.queue-head {
  padding: 0 4px 10px;
}

.queue-row {
  padding: 14px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  color: rgba(226, 230, 234, 0.92);
  font-size: 14px;
}

.state {
  color: rgba(244, 240, 235, 0.92);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 12px;
}

.form-card button,
input,
select,
textarea {
  font: inherit;
}

.form-card button {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: #f1efed;
  padding: 10px 14px;
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
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  color: #f0efed;
  padding: 12px 13px;
}

textarea {
  resize: vertical;
  line-height: 1.55;
}

@media (max-width: 1280px) {
  .masthead,
  .editorial-grid,
  .tableau,
  .chart-shell {
    grid-template-columns: 1fr;
  }

  .study-panel {
    max-width: 420px;
  }
}

@media (max-width: 900px) {
  .ledger-strip,
  .highlight-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .queue-head,
  .queue-row {
    grid-template-columns: 1fr;
  }
}
</style>
