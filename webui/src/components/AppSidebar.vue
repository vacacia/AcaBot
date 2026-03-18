<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">AC</div>
      <div>
        <div class="brand-title">AcaBot</div>
        <div class="brand-subtitle">控制台</div>
      </div>
    </div>
    <nav class="nav">
      <RouterLink class="nav-item" to="/">首页</RouterLink>
      <div class="group-title">配置</div>
      <RouterLink class="nav-item" to="/config/soul">Soul</RouterLink>
      <RouterLink class="nav-item" to="/config/memory">记忆</RouterLink>
      <RouterLink class="nav-item" to="/config/admins">管理员</RouterLink>
      <RouterLink class="nav-item" to="/config/providers">模型供应商</RouterLink>
      <RouterLink class="nav-item" to="/config/models">模型</RouterLink>
      <RouterLink class="nav-item" to="/config/prompts">提示词</RouterLink>
      <RouterLink class="nav-item" to="/config/plugins">插件</RouterLink>
      <RouterLink class="nav-item" to="/config/skills">技能</RouterLink>
      <RouterLink class="nav-item" to="/config/subagents">子代理</RouterLink>
      <RouterLink class="nav-item" to="/sessions">会话</RouterLink>
      <RouterLink class="nav-item" to="/system">系统</RouterLink>
      <RouterLink class="nav-item" to="/logs">日志</RouterLink>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 248px;
  border-right: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.84) 0%, rgba(245, 249, 255, 0.7) 100%);
  backdrop-filter: blur(18px);
  padding: 20px 14px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  overflow: auto;
  box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.55);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, #0f6cb8 0%, #0a4a7b 100%);
  color: #fff;
  font-weight: 800;
  letter-spacing: 0.08em;
}

.brand-title {
  font-size: 20px;
  font-weight: 800;
  color: #173257;
}

.brand-subtitle {
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.group-title {
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.nav-item {
  display: block;
  padding: 10px 12px;
  border-radius: 12px;
  color: #23334f;
  text-decoration: none;
  transition:
    background-color 120ms ease,
    transform 120ms ease,
    color 120ms ease;
}

.nav-item:hover {
  background: rgba(15, 108, 184, 0.08);
  transform: translateX(2px);
}

.nav-item.router-link-active {
  background: linear-gradient(135deg, rgba(15, 108, 184, 0.16), rgba(15, 108, 184, 0.08));
  color: #0b4f83;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px rgba(15, 108, 184, 0.12);
}

@media (max-width: 960px) {
  .sidebar {
    width: auto;
    border-right: none;
    border-bottom: 1px solid var(--line);
    padding: 16px 14px;
  }

  .brand {
    margin-bottom: 6px;
  }

  .nav {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
    gap: 8px;
  }

  .group-title {
    grid-column: 1 / -1;
    margin: 4px 0 0;
  }

  .nav-item {
    padding: 10px;
  }

  .nav-item:hover {
    transform: none;
  }
}
</style>
