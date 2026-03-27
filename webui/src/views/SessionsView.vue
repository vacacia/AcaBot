<template>
  <section class="ds-page">
    <header class="ds-hero">
      <div class="ds-hero-copy">
        <p class="ds-eyebrow">Sessions</p>
        <h1>会话设置</h1>
        <p class="ds-summary">
          Session shell 正在按新的 runtime 和 session 契约重做。这里先明确收口，不再展示旧的 AI 私有模型表单。
        </p>
      </div>
    </header>

    <article class="ds-panel ds-panel-padding">
      <div class="ds-section-head">
        <div class="ds-section-title">
          <div>
            <h2>当前状态</h2>
            <p class="ds-summary">模型选择已经统一进 model target registry。Session 页会在新 shell 完成后再回到 WebUI。</p>
          </div>
        </div>
      </div>

      <div class="placeholder-grid">
        <article class="ds-surface ds-card-padding-sm">
          <h3>现在生效的入口</h3>
          <p class="ds-summary">模型供应商、模型预设、模型 target 和模型 binding 已经是唯一真源。</p>
        </article>
        <article class="ds-surface ds-card-padding-sm">
          <h3>这里为什么先下线</h3>
          <p class="ds-summary">旧 Session shell 还挂着私有模型字段，会把人重新引回已经废掉的配置路径。</p>
        </article>
        <article class="ds-surface ds-card-padding-sm">
          <h3>接下来去哪里</h3>
          <p class="ds-summary">需要调整模型时，直接去 Models 和 Providers 页面；需要改 session 行为时，等新的 session shell 上线。</p>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.placeholder-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 900px) {
  .placeholder-grid {
    grid-template-columns: 1fr;
  }
}
</style>
