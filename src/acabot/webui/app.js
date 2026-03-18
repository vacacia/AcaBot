const viewMeta = {
  home: { title: '首页', subtitle: '先看系统状态，再看日志。' },
  bot: { title: 'Bot', subtitle: '默认 AI、默认输入处理、默认工具和默认 skills。' },
  models: { title: '模型', subtitle: '管理 providers 和 presets。' },
  prompts: { title: 'Prompts', subtitle: 'Prompt 只有名字和内容。' },
  plugins: { title: 'Plugins', subtitle: '插件开启/关闭与 reload。' },
  skills: { title: 'Skills', subtitle: '当前已安装 skills。' },
  subagents: { title: 'Subagents', subtitle: '当前可委派执行体。' },
  sessions: { title: '会话', subtitle: '编辑具体 Session：AI / 输入处理 / 其他。' },
  system: { title: '系统', subtitle: '日志、Backend、审批与资源。' },
}

const state = {
  view: 'home',
  meta: null,
  status: null,
  catalog: null,
  botProfile: null,
  botBinding: null,
  providers: [],
  presets: [],
  selectedProviderId: '',
  selectedPresetId: '',
  prompts: [],
  selectedPromptRef: '',
  pluginConfigs: [],
  skills: [],
  subagents: [],
  sessions: [],
  selectedSessionKey: '',
  sessionDraft: null,
}

const $ = (selector) => document.querySelector(selector)
const $$ = (selector) => Array.from(document.querySelectorAll(selector))

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function showToast(message) {
  const node = $('#toast')
  node.textContent = String(message || '')
  node.hidden = false
  clearTimeout(showToast._timer)
  showToast._timer = setTimeout(() => {
    node.hidden = true
  }, 2500)
}

function handleError(error) {
  console.error(error)
  showToast(error?.message || String(error))
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const payload = await response.json()
  if (!response.ok || payload.ok !== true) {
    throw new Error(payload.error || `HTTP ${response.status}`)
  }
  return payload.data
}

function promptNameFromRef(promptRef) {
  return String(promptRef || '').replace(/^prompt\//, '')
}

function promptRefFromName(name) {
  const normalized = String(name || '').trim().replace(/^prompt\//, '')
  return normalized ? `prompt/${normalized}` : ''
}

function modelLabelForPresetId(presetId) {
  const item = (state.catalog?.model_presets || []).find((entry) => entry.preset_id === presetId)
  return item?.model || presetId || ''
}

function botAgentId() {
  return state.catalog?.bot?.agent_id || 'aca'
}

function generateId(prefix) {
  return `${prefix}:${Math.random().toString(16).slice(2, 10)}`
}

function defaultSessionDraft(sessionKey = '') {
  return {
    session_key: sessionKey,
    session_name: '',
    prompt_ref: state.botProfile?.prompt_ref || '',
    bound_preset_id: state.botBinding?.preset_id || '',
    summary_model_preset_id: state.botProfile?.summary_model_preset_id || '',
    enabled_tools: [...(state.botProfile?.enabled_tools || [])],
    skill_assignments: [...(state.botProfile?.skill_assignments || [])],
    tags: [],
    input_rules: buildDefaultInputRules(),
    binding_rule_id: '',
    event_policy_ids: {},
    inbound_rule_ids: {},
    managed_agent_id: '',
  }
}

function buildDefaultInputRules() {
  const eventTypes = state.catalog?.options?.event_types || []
  const rules = {}
  for (const eventType of eventTypes) {
    rules[eventType] = {
      enabled: true,
      run_mode: 'respond',
      persist_event: true,
      memory_scopes: ['relationship', 'user', 'channel', 'global'],
      tags: [],
    }
  }
  return rules
}

async function loadMetaAndStatus() {
  const [meta, status] = await Promise.all([
    api('/api/meta'),
    api('/api/status'),
  ])
  state.meta = meta
  state.status = status
  $('#meta-storage-mode').textContent = `storage: ${meta.storage_mode}`
  $('#meta-config-path').textContent = `config: ${meta.config_path}`
}

async function ensureCatalog(force = false) {
  if (state.catalog && !force) return state.catalog
  state.catalog = await api('/api/ui/catalog')
  return state.catalog
}

async function loadBotData() {
  await ensureCatalog(true)
  const profiles = await api('/api/profiles')
  const botId = botAgentId()
  state.botProfile = profiles.find((item) => item.agent_id === botId) || profiles[0] || null
  const bindings = await api('/api/models/bindings')
  state.botBinding = bindings.find((item) => item.target_type === 'agent' && item.target_id === botId) || null
}

async function loadModelData() {
  const [providers, presets] = await Promise.all([
    api('/api/models/providers'),
    api('/api/models/presets'),
  ])
  state.providers = providers.map((item) => ({
    provider_id: item.provider_id,
    kind: item.kind,
    base_url: item.base_url || '',
    api_key: item.api_key || '',
    api_key_env: item.api_key_env || '',
  }))
  state.presets = presets.map((item) => ({
    preset_id: item.preset_id,
    provider_id: item.provider_id,
    model: item.model,
    context_window: item.context_window,
  }))
  if (!state.selectedProviderId && state.providers.length) state.selectedProviderId = state.providers[0].provider_id
  if (!state.selectedPresetId && state.presets.length) state.selectedPresetId = state.presets[0].preset_id
}

async function loadPromptData() {
  state.prompts = await api('/api/prompts')
  if (!state.selectedPromptRef && state.prompts.length) state.selectedPromptRef = state.prompts[0].prompt_ref
}

async function loadPluginData() {
  state.pluginConfigs = (await api('/api/system/plugins/config')).items || []
}

async function loadSkillsAndSubagents() {
  const [skills, subagents] = await Promise.all([
    api('/api/skills'),
    api('/api/subagents/executors'),
  ])
  state.skills = skills
  state.subagents = subagents
}

function humanizeSessionName(sessionKey) {
  return String(sessionKey || '')
}

function groupSessionRules(bindingRules, inboundRules, eventPolicies) {
  const grouped = new Map()
  const botTools = [...(state.botProfile?.enabled_tools || [])]
  const botSkills = [...(state.botProfile?.skill_assignments || [])]
  const ensure = (sessionKey) => {
    if (!grouped.has(sessionKey)) {
      grouped.set(sessionKey, {
        ...defaultSessionDraft(sessionKey),
        session_name: humanizeSessionName(sessionKey),
      })
    }
    const item = grouped.get(sessionKey)
    item.enabled_tools = [...(item.enabled_tools || botTools)]
    item.skill_assignments = [...(item.skill_assignments || botSkills)]
    return item
  }

  for (const rule of bindingRules) {
    const scope = rule?.match?.channel_scope
    if (!scope) continue
    const item = ensure(scope)
    item.binding_rule_id = rule.rule_id || ''
    item.session_name = String(rule.metadata?.display_name || item.session_name || scope)
    item.managed_agent_id = String(rule.metadata?.managed_agent_id || '')
  }
  for (const rule of inboundRules) {
    const scope = rule?.match?.channel_scope
    const eventType = rule?.match?.event_type
    if (!scope || !eventType) continue
    const item = ensure(scope)
    item.inbound_rule_ids[eventType] = rule.rule_id || ''
    item.input_rules[eventType] ||= { enabled: true, run_mode: 'respond', persist_event: true, memory_scopes: [], tags: [] }
    item.input_rules[eventType].run_mode = rule.run_mode || 'respond'
    item.input_rules[eventType].enabled = (rule.run_mode || 'respond') !== 'silent_drop'
  }
  for (const policy of eventPolicies) {
    const scope = policy?.match?.channel_scope
    const eventType = policy?.match?.event_type
    if (!scope || !eventType) continue
    const item = ensure(scope)
    item.event_policy_ids[eventType] = policy.policy_id || ''
    item.input_rules[eventType] ||= { enabled: true, run_mode: 'respond', persist_event: true, memory_scopes: [], tags: [] }
    item.input_rules[eventType].persist_event = policy.persist_event !== false
    item.input_rules[eventType].memory_scopes = [...(policy.memory_scopes || [])]
    item.input_rules[eventType].tags = [...(policy.tags || [])]
  }
  return Array.from(grouped.values())
}

async function loadSessionData() {
  await Promise.all([ensureCatalog(true), loadBotData()])
  const [bindingRules, inboundRules, eventPolicies] = await Promise.all([
    api('/api/rules/bindings'),
    api('/api/rules/inbound'),
    api('/api/rules/event-policies'),
  ])
  state.sessions = groupSessionRules(bindingRules, inboundRules, eventPolicies)
  if (!state.selectedSessionKey && state.sessions.length) state.selectedSessionKey = state.sessions[0].session_key
  const selected = state.sessions.find((item) => item.session_key === state.selectedSessionKey)
  state.sessionDraft = selected ? structuredClone(selected) : defaultSessionDraft('')
}

function statusCard(label, value, help) {
  return `
    <article class="status-card">
      <div class="status-label">${escapeHtml(label)}</div>
      <div class="status-value">${escapeHtml(value)}</div>
      <div class="status-help">${escapeHtml(help)}</div>
    </article>
  `
}

async function renderHome() {
  await loadMetaAndStatus()
  const gateway = await api('/api/gateway/status').catch(() => ({ connected: false }))
  const backend = await api('/api/backend/status').catch(() => ({ configured: false }))
  $('#home-status-grid').innerHTML = [
    statusCard('Bot', '在线', '主进程响应正常'),
    statusCard('Gateway', gateway.connected ? 'Connected' : 'Disconnected', 'NapCat 连接状态'),
    statusCard('Backend', backend.configured ? 'Ready' : 'Unavailable', 'pi / canonical session'),
    statusCard('Runs', String((state.status?.active_runs || []).length), '当前活跃运行数'),
  ].join('')
  await renderLogs('#home-log-stream', '#home-log-level-filter', '#home-log-keyword')
}

async function renderLogs(targetSelector, levelSelector, keywordSelector) {
  const level = $(levelSelector)?.value || ''
  const keyword = $(keywordSelector)?.value || ''
  const data = await api(`/api/system/logs?level=${encodeURIComponent(level)}&keyword=${encodeURIComponent(keyword)}&limit=500`)
  const items = data.items || []
  const target = $(targetSelector)
  if (!items.length) {
    target.innerHTML = '<div class="empty">暂无日志</div>'
    return
  }
  target.innerHTML = items.map((item) => `
    <div class="log-line ${String(item.level || '').toLowerCase()}">
      <span class="ts">${escapeHtml(new Date((item.timestamp || 0) * 1000).toLocaleTimeString('zh-CN', { hour12: false }))}</span>
      <span class="lvl">${escapeHtml(item.level)}</span>
      <span class="msg">${escapeHtml(item.logger)} · ${escapeHtml(item.message)}</span>
    </div>
  `).join('')
}

function renderCheckboxes(target, items, selectedValues, valueKey, labelKey, descKey = '') {
  const selected = new Set(selectedValues || [])
  target.innerHTML = (items || []).map((item) => {
    const value = item[valueKey]
    const label = item[labelKey]
    const desc = descKey ? item[descKey] : ''
    return `
      <label class="checkbox-item">
        <input type="checkbox" data-check-value="${escapeHtml(value)}" ${selected.has(value) ? 'checked' : ''}>
        <div class="checkbox-copy">
          <strong>${escapeHtml(label)}</strong>
          ${desc ? `<span>${escapeHtml(desc)}</span>` : ''}
        </div>
      </label>
    `
  }).join('') || '<div class="empty">暂无可选项</div>'
}

function checkedValues(containerSelector) {
  return Array.from($(`${containerSelector}`)?.querySelectorAll('[data-check-value]:checked') || []).map((node) => node.dataset.checkValue)
}

function renderBot() {
  const profile = state.botProfile || {}
  $('#bot-name').value = profile.name || ''
  renderSelect('#bot-prompt', state.catalog?.prompts || [], profile.prompt_ref || '', (item) => item.prompt_ref, (item) => promptNameFromRef(item.prompt_ref))
  renderSelect('#bot-model', state.catalog?.model_presets || [], state.botBinding?.preset_id || '', (item) => item.preset_id, (item) => item.model || item.preset_id)
  renderSelect('#bot-summary-model', state.catalog?.model_presets || [], profile.summary_model_preset_id || '', (item) => item.preset_id, (item) => item.model || item.preset_id, '不设置')
  renderCheckboxes($('#bot-tools'), (state.catalog?.tools || []).filter((item) => item.name !== 'skill' && item.name !== 'delegate_subagent'), profile.enabled_tools || [], 'name', 'name', 'description')
  renderCheckboxes($('#bot-skills'), state.catalog?.skills || [], (profile.skill_assignments || []).map((item) => item.skill_name), 'skill_name', 'display_name', 'description')
  const defaults = state.catalog?.options?.event_types || []
  $('#bot-input-rules').innerHTML = defaults.map((eventType) => `
    <details class="rule-card">
      <summary><span class="rule-title">${escapeHtml(eventType)}</span><span class="rule-summary">默认输入处理</span></summary>
      <div class="rule-body"><div class="empty">这一版先展示，后续再把 Bot 默认输入处理接成真实编辑。</div></div>
    </details>
  `).join('')
}

function renderSelect(selector, items, selectedValue, valueFn, labelFn, emptyLabel = '') {
  const node = $(selector)
  const options = []
  if (emptyLabel) options.push(`<option value="">${escapeHtml(emptyLabel)}</option>`)
  for (const item of items || []) {
    const value = valueFn(item)
    options.push(`<option value="${escapeHtml(value)}" ${selectedValue === value ? 'selected' : ''}>${escapeHtml(labelFn(item))}</option>`)
  }
  node.innerHTML = options.join('')
}

async function saveBot() {
  const agentId = botAgentId()
  const selectedSkillNames = checkedValues('#bot-skills').map((skill_name) => ({ skill_name }))
  await api(`/api/profiles/${encodeURIComponent(agentId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      ...state.botProfile,
      name: $('#bot-name').value.trim(),
      prompt_ref: $('#bot-prompt').value,
      default_model: modelLabelForPresetId($('#bot-model').value),
      summary_model_preset_id: $('#bot-summary-model').value,
      enabled_tools: checkedValues('#bot-tools'),
      skill_assignments: selectedSkillNames,
    }),
  })
  await syncAgentBinding(agentId, $('#bot-model').value)
  showToast('已保存 Bot 配置')
  await Promise.all([loadBotData(), ensureCatalog(true)])
  renderBot()
}

function renderProvidersAndPresets() {
  $('#providers-list').innerHTML = state.providers.map((item) => `
    <button class="conversation-item ${item.provider_id === state.selectedProviderId ? 'active' : ''}" data-provider-id="${escapeHtml(item.provider_id)}">
      <div class="conversation-name">${escapeHtml(item.provider_id)}</div>
      <div class="conversation-id">${escapeHtml(item.kind)} · ${escapeHtml(item.base_url || '-')}</div>
    </button>
  `).join('') || '<div class="empty">暂无 Provider</div>'
  $('#presets-list').innerHTML = state.presets.map((item) => `
    <button class="conversation-item ${item.preset_id === state.selectedPresetId ? 'active' : ''}" data-preset-id="${escapeHtml(item.preset_id)}">
      <div class="conversation-name">${escapeHtml(item.preset_id)}</div>
      <div class="conversation-id">${escapeHtml(item.model)} · ${escapeHtml(item.provider_id)}</div>
    </button>
  `).join('') || '<div class="empty">暂无 Preset</div>'

  $$('#providers-list [data-provider-id]').forEach((node) => node.addEventListener('click', () => {
    state.selectedProviderId = node.dataset.providerId
    fillProviderForm()
    renderProvidersAndPresets()
  }))
  $$('#presets-list [data-preset-id]').forEach((node) => node.addEventListener('click', () => {
    state.selectedPresetId = node.dataset.presetId
    fillPresetForm()
    renderProvidersAndPresets()
  }))
  fillProviderForm()
  fillPresetForm()
}

function fillProviderForm() {
  const item = state.providers.find((entry) => entry.provider_id === state.selectedProviderId) || { provider_id: '', kind: 'openai_compatible', base_url: '', api_key: '' }
  $('#provider-id').value = item.provider_id || ''
  $('#provider-kind').innerHTML = ['openai_compatible', 'anthropic', 'google_gemini'].map((kind) => `<option value="${kind}" ${item.kind === kind ? 'selected' : ''}>${kind}</option>`).join('')
  $('#provider-base-url').value = item.base_url || ''
  $('#provider-api-key').value = item.api_key || ''
}

function fillPresetForm() {
  const item = state.presets.find((entry) => entry.preset_id === state.selectedPresetId) || { preset_id: '', provider_id: state.providers[0]?.provider_id || '', model: '', context_window: 128000 }
  $('#preset-id').value = item.preset_id || ''
  renderSelect('#preset-provider-id', state.providers, item.provider_id || '', (entry) => entry.provider_id, (entry) => entry.provider_id)
  $('#preset-model').value = item.model || ''
  $('#preset-context-window').value = String(item.context_window || 128000)
}

async function saveProvider() {
  const provider_id = $('#provider-id').value.trim()
  if (!provider_id) throw new Error('Provider ID 不能为空')
  await api(`/api/models/providers/${encodeURIComponent(provider_id)}`, {
    method: 'PUT',
    body: JSON.stringify({
      kind: $('#provider-kind').value,
      base_url: $('#provider-base-url').value.trim(),
      api_key: $('#provider-api-key').value.trim(),
    }),
  })
  state.selectedProviderId = provider_id
  await Promise.all([loadModelData(), ensureCatalog(true)])
  renderProvidersAndPresets()
  showToast(`已保存 Provider: ${provider_id}`)
}

async function deleteProvider() {
  const provider_id = $('#provider-id').value.trim()
  if (!provider_id) return
  await api(`/api/models/providers/${encodeURIComponent(provider_id)}?force=true`, { method: 'DELETE' })
  state.selectedProviderId = ''
  await Promise.all([loadModelData(), ensureCatalog(true)])
  renderProvidersAndPresets()
  showToast(`已删除 Provider: ${provider_id}`)
}

async function savePreset() {
  const preset_id = $('#preset-id').value.trim()
  if (!preset_id) throw new Error('Preset ID 不能为空')
  await api(`/api/models/presets/${encodeURIComponent(preset_id)}`, {
    method: 'PUT',
    body: JSON.stringify({
      provider_id: $('#preset-provider-id').value,
      model: $('#preset-model').value.trim(),
      context_window: Number($('#preset-context-window').value || 128000),
    }),
  })
  state.selectedPresetId = preset_id
  await Promise.all([loadModelData(), ensureCatalog(true)])
  renderProvidersAndPresets()
  showToast(`已保存 Preset: ${preset_id}`)
}

async function deletePreset() {
  const preset_id = $('#preset-id').value.trim()
  if (!preset_id) return
  await api(`/api/models/presets/${encodeURIComponent(preset_id)}?force=true`, { method: 'DELETE' })
  state.selectedPresetId = ''
  await Promise.all([loadModelData(), ensureCatalog(true)])
  renderProvidersAndPresets()
  showToast(`已删除 Preset: ${preset_id}`)
}

function renderPrompts() {
  $('#prompts-list').innerHTML = state.prompts.map((item) => `
    <button class="conversation-item ${item.prompt_ref === state.selectedPromptRef ? 'active' : ''}" data-prompt-ref="${escapeHtml(item.prompt_ref)}">
      <div class="conversation-name">${escapeHtml(promptNameFromRef(item.prompt_ref))}</div>
      <div class="conversation-id">${escapeHtml((item.content || '').slice(0, 48) || '空内容')}</div>
    </button>
  `).join('') || '<div class="empty">暂无 Prompt</div>'
  $$('#prompts-list [data-prompt-ref]').forEach((node) => node.addEventListener('click', () => {
    state.selectedPromptRef = node.dataset.promptRef
    fillPromptForm()
    renderPrompts()
  }))
  fillPromptForm()
}

function fillPromptForm() {
  const item = state.prompts.find((entry) => entry.prompt_ref === state.selectedPromptRef)
  $('#prompt-name').value = item ? promptNameFromRef(item.prompt_ref) : ''
  $('#prompt-content').value = item?.content || ''
}

async function savePrompt() {
  const promptRef = promptRefFromName($('#prompt-name').value)
  if (!promptRef) throw new Error('Prompt 名称不能为空')
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, {
    method: 'PUT',
    body: JSON.stringify({ content: $('#prompt-content').value }),
  })
  state.selectedPromptRef = promptRef
  await Promise.all([loadPromptData(), ensureCatalog(true)])
  renderPrompts()
  showToast(`已保存 Prompt: ${promptNameFromRef(promptRef)}`)
}

async function deletePrompt() {
  const promptRef = promptRefFromName($('#prompt-name').value)
  if (!promptRef) return
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, { method: 'DELETE' })
  state.selectedPromptRef = ''
  await Promise.all([loadPromptData(), ensureCatalog(true)])
  renderPrompts()
  showToast(`已删除 Prompt: ${promptNameFromRef(promptRef)}`)
}

function renderPlugins() {
  $('#plugins-config-list').innerHTML = state.pluginConfigs.map((item) => `
    <div class="toggle-row">
      <div class="toggle-left">
        <strong>${escapeHtml(item.name || item.path)}</strong>
        <span>${escapeHtml(item.path)}</span>
      </div>
      <input class="switch" type="checkbox" data-plugin-path="${escapeHtml(item.path)}" ${item.enabled ? 'checked' : ''}>
    </div>
  `).join('') || '<div class="empty">当前没有可配置 plugin</div>'
}

async function savePlugins() {
  const items = state.pluginConfigs.map((item) => ({
    path: item.path,
    enabled: Boolean($(`[data-plugin-path="${CSS.escape(item.path)}"]`)?.checked),
  }))
  const result = await api('/api/system/plugins/config', {
    method: 'PUT',
    body: JSON.stringify({ items }),
  })
  state.pluginConfigs = result.items || []
  renderPlugins()
  showToast('已保存 Plugins 配置')
}

async function reloadPlugins() {
  await api('/api/plugins/reload', { method: 'POST', body: JSON.stringify({ plugin_names: [] }) })
  await loadPluginData()
  renderPlugins()
  showToast('已重新加载 Plugins')
}

function renderSkills() {
  $('#skills-list').innerHTML = state.skills.map((item) => `
    <div class="list-item">
      <div class="list-item-title">${escapeHtml(item.display_name || item.skill_name)}</div>
      <div class="list-item-meta">${escapeHtml(item.description || item.skill_name)}</div>
    </div>
  `).join('') || '<div class="empty">暂无 Skills</div>'
}

function renderSubagents() {
  $('#subagents-list').innerHTML = state.subagents.map((item) => `
    <div class="list-item">
      <div class="list-item-title">${escapeHtml(item.agent_id)}</div>
      <div class="list-item-meta">source=${escapeHtml(item.source || '-')}</div>
    </div>
  `).join('') || '<div class="empty">暂无 Subagents</div>'
}

function renderSessions() {
  const keyword = ($('#session-search').value || '').trim().toLowerCase()
  const items = state.sessions.filter((item) => {
    const text = `${item.session_name || ''} ${item.session_key || ''}`.toLowerCase()
    return !keyword || text.includes(keyword)
  })
  $('#sessions-list').innerHTML = items.map((item) => `
    <button class="conversation-item ${item.session_key === state.selectedSessionKey ? 'active' : ''}" data-session-key="${escapeHtml(item.session_key)}">
      <div class="conversation-name">${escapeHtml(item.session_name || item.session_key)}</div>
      <div class="conversation-id">${escapeHtml(item.session_key)}</div>
    </button>
  `).join('') || '<div class="empty">暂无会话配置</div>'
  $$('#sessions-list [data-session-key]').forEach((node) => node.addEventListener('click', () => {
    state.selectedSessionKey = node.dataset.sessionKey
    const selected = state.sessions.find((item) => item.session_key === state.selectedSessionKey)
    state.sessionDraft = selected ? structuredClone(selected) : defaultSessionDraft(node.dataset.sessionKey)
    fillSessionDraft()
    renderSessions()
  }))
  fillSessionDraft()
}

function fillSessionDraft() {
  const draft = state.sessionDraft || defaultSessionDraft('')
  $('#session-title').textContent = draft.session_name || 'Session'
  $('#session-id-line').textContent = `Session ID: ${draft.session_key || '-'}`
  $('#session-name').value = draft.session_name || ''
  $('#session-key').value = draft.session_key || ''
  renderSelect('#session-prompt', state.catalog?.prompts || [], draft.prompt_ref || '', (item) => item.prompt_ref, (item) => promptNameFromRef(item.prompt_ref))
  renderSelect('#session-model', state.catalog?.model_presets || [], draft.bound_preset_id || '', (item) => item.preset_id, (item) => item.model || item.preset_id)
  renderSelect('#session-summary-model', state.catalog?.model_presets || [], draft.summary_model_preset_id || '', (item) => item.preset_id, (item) => item.model || item.preset_id, '不设置')
  renderCheckboxes($('#session-tools'), (state.catalog?.tools || []).filter((item) => item.name !== 'skill' && item.name !== 'delegate_subagent'), draft.enabled_tools || [], 'name', 'name', 'description')
  renderCheckboxes($('#session-skills'), state.catalog?.skills || [], (draft.skill_assignments || []).map((item) => item.skill_name), 'skill_name', 'display_name', 'description')
  $('#session-tags').value = (draft.tags || []).join(', ')
  const eventTypes = state.catalog?.options?.event_types || []
  $('#session-input-rules').innerHTML = eventTypes.map((eventType) => {
    const rule = draft.input_rules?.[eventType] || { enabled: true, run_mode: 'respond', persist_event: true, memory_scopes: [], tags: [] }
    return `
      <details class="rule-card">
        <summary>
          <span class="rule-title">${escapeHtml(eventType)}</span>
          <span class="rule-summary">${escapeHtml(rule.run_mode)} · ${rule.persist_event ? '保存' : '不保存'} · ${(rule.memory_scopes || []).join(' / ') || '无 memory'}</span>
        </summary>
        <div class="rule-body">
          <div class="form-grid">
            <label><span>启用</span><select data-rule-field="enabled" data-event-type="${escapeHtml(eventType)}"><option value="true" ${rule.enabled ? 'selected' : ''}>是</option><option value="false" ${!rule.enabled ? 'selected' : ''}>否</option></select></label>
            <label><span>响应方式</span><select data-rule-field="run_mode" data-event-type="${escapeHtml(eventType)}"><option value="respond" ${rule.run_mode === 'respond' ? 'selected' : ''}>respond</option><option value="record_only" ${rule.run_mode === 'record_only' ? 'selected' : ''}>record_only</option><option value="silent_drop" ${rule.run_mode === 'silent_drop' ? 'selected' : ''}>silent_drop</option></select></label>
            <label><span>保存</span><select data-rule-field="persist_event" data-event-type="${escapeHtml(eventType)}"><option value="true" ${rule.persist_event ? 'selected' : ''}>是</option><option value="false" ${!rule.persist_event ? 'selected' : ''}>否</option></select></label>
            <label><span>记忆 scopes</span><input data-rule-field="memory_scopes" data-event-type="${escapeHtml(eventType)}" type="text" value="${escapeHtml((rule.memory_scopes || []).join(', '))}"></label>
            <label class="wide"><span>tags</span><input data-rule-field="tags" data-event-type="${escapeHtml(eventType)}" type="text" value="${escapeHtml((rule.tags || []).join(', '))}"></label>
          </div>
        </div>
      </details>
    `
  }).join('')
}

function readSessionDraft() {
  const draft = structuredClone(state.sessionDraft || defaultSessionDraft(''))
  draft.session_name = $('#session-name').value.trim()
  draft.prompt_ref = $('#session-prompt').value
  draft.bound_preset_id = $('#session-model').value
  draft.summary_model_preset_id = $('#session-summary-model').value
  draft.enabled_tools = checkedValues('#session-tools')
  draft.skill_assignments = checkedValues('#session-skills').map((skill_name) => ({ skill_name }))
  draft.tags = $('#session-tags').value.split(',').map((item) => item.trim()).filter(Boolean)
  const eventTypes = state.catalog?.options?.event_types || []
  draft.input_rules ||= {}
  for (const eventType of eventTypes) {
    draft.input_rules[eventType] = {
      enabled: $(`[data-rule-field="enabled"][data-event-type="${CSS.escape(eventType)}"]`)?.value === 'true',
      run_mode: $(`[data-rule-field="run_mode"][data-event-type="${CSS.escape(eventType)}"]`)?.value || 'respond',
      persist_event: $(`[data-rule-field="persist_event"][data-event-type="${CSS.escape(eventType)}"]`)?.value === 'true',
      memory_scopes: ($(`[data-rule-field="memory_scopes"][data-event-type="${CSS.escape(eventType)}"]`)?.value || '').split(',').map((item) => item.trim()).filter(Boolean),
      tags: ($(`[data-rule-field="tags"][data-event-type="${CSS.escape(eventType)}"]`)?.value || '').split(',').map((item) => item.trim()).filter(Boolean),
    }
  }
  return draft
}

function managedSessionProfileId(sessionKey) {
  return `session_${sessionKey.replace(/[^a-zA-Z0-9]+/g, '_')}`
}

async function syncAgentBinding(agentId, presetId) {
  const bindings = await api('/api/models/bindings')
  const existing = bindings.find((item) => item.target_type === 'agent' && item.target_id === agentId)
  const bindingId = existing?.binding_id || generateId('model-binding')
  if (!presetId) {
    if (existing) await api(`/api/models/bindings/${encodeURIComponent(bindingId)}`, { method: 'DELETE' })
    return
  }
  await api(`/api/models/bindings/${encodeURIComponent(bindingId)}`, {
    method: 'PUT',
    body: JSON.stringify({ target_type: 'agent', target_id: agentId, preset_id: presetId }),
  })
}

async function saveSession() {
  const draft = readSessionDraft()
  const sessionKey = draft.session_key || state.selectedSessionKey
  if (!sessionKey) throw new Error('先选择一个会话')
  const sessionName = draft.session_name || sessionKey
  const managedAgentId = draft.managed_agent_id || managedSessionProfileId(sessionKey)
  await api(`/api/profiles/${encodeURIComponent(managedAgentId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      agent_id: managedAgentId,
      name: `${sessionName}`,
      prompt_ref: draft.prompt_ref,
      default_model: modelLabelForPresetId(draft.bound_preset_id),
      summary_model_preset_id: draft.summary_model_preset_id,
      enabled_tools: draft.enabled_tools,
      skill_assignments: draft.skill_assignments,
      metadata: { managed_by: 'webui_v2_session', session_key: sessionKey },
    }),
  })
  await syncAgentBinding(managedAgentId, draft.bound_preset_id)
  const bindingRuleId = draft.binding_rule_id || generateId('session-binding')
  await api(`/api/rules/bindings/${encodeURIComponent(bindingRuleId)}`, {
    method: 'PUT',
    body: JSON.stringify({
      agent_id: managedAgentId,
      priority: 100,
      match: { channel_scope: sessionKey },
      metadata: { display_name: sessionName, managed_agent_id: managedAgentId },
    }),
  })
  for (const [eventType, rule] of Object.entries(draft.input_rules || {})) {
    const inboundRuleId = draft.inbound_rule_ids?.[eventType] || generateId(`session-inbound-${eventType}`)
    const policyId = draft.event_policy_ids?.[eventType] || generateId(`session-policy-${eventType}`)
    await api(`/api/rules/inbound/${encodeURIComponent(inboundRuleId)}`, {
      method: 'PUT',
      body: JSON.stringify({
        run_mode: rule.enabled ? rule.run_mode : 'silent_drop',
        priority: 100,
        match: { channel_scope: sessionKey, event_type: eventType },
        metadata: { display_name: sessionName },
      }),
    })
    await api(`/api/rules/event-policies/${encodeURIComponent(policyId)}`, {
      method: 'PUT',
      body: JSON.stringify({
        priority: 100,
        match: { channel_scope: sessionKey, event_type: eventType },
        persist_event: rule.persist_event,
        extract_to_memory: (rule.memory_scopes || []).length > 0,
        memory_scopes: rule.memory_scopes || [],
        tags: [...(draft.tags || []), ...(rule.tags || [])],
        metadata: { display_name: sessionName },
      }),
    })
  }
  showToast(`已保存会话: ${sessionName}`)
  await loadSessionData()
  renderSessions()
}

async function deleteSession() {
  const draft = state.sessionDraft
  if (!draft) return
  if (draft.binding_rule_id) await api(`/api/rules/bindings/${encodeURIComponent(draft.binding_rule_id)}`, { method: 'DELETE' })
  for (const ruleId of Object.values(draft.inbound_rule_ids || {})) {
    if (ruleId) await api(`/api/rules/inbound/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
  }
  for (const policyId of Object.values(draft.event_policy_ids || {})) {
    if (policyId) await api(`/api/rules/event-policies/${encodeURIComponent(policyId)}`, { method: 'DELETE' })
  }
  if (draft.managed_agent_id) {
    await api(`/api/profiles/${encodeURIComponent(draft.managed_agent_id)}`, { method: 'DELETE' }).catch(() => null)
  }
  showToast('已删除会话配置')
  state.selectedSessionKey = ''
  await loadSessionData()
  renderSessions()
}

async function renderBackendStatus() {
  const status = await api('/api/backend/status')
  const items = [
    ['configured', String(Boolean(status.configured))],
    ['session path', status.session_path || '-'],
    ['admin actor ids', (status.admin_actor_ids || []).join(', ') || '-'],
    ['active modes', String((status.active_modes || []).length)],
  ]
  $('#backend-status').innerHTML = items.map(([k, v]) => `<div class="kv-item"><strong>${escapeHtml(k)}</strong><span>${escapeHtml(v)}</span></div>`).join('')
}

async function renderApprovals() {
  const items = await api('/api/approvals')
  $('#approvals-list').innerHTML = (items || []).map((item) => `
    <div class="list-item">
      <div class="list-item-title">${escapeHtml(item.run_id || '-')}</div>
      <div class="list-item-meta">${escapeHtml(item.reason || '')}</div>
    </div>
  `).join('') || '<div class="empty">暂无审批</div>'
}

async function renderResources(kind) {
  if (kind === 'workspaces') {
    const items = await api('/api/workspaces')
    $('#resources-output').innerHTML = items.map((item) => `<div class="list-item"><div class="list-item-title">${escapeHtml(item.thread_id || '-')}</div><div class="list-item-meta">${escapeHtml(item.workspace_dir || '')}</div></div>`).join('') || '<div class="empty">暂无 workspaces</div>'
    return
  }
  if (kind === 'references') {
    const items = await api('/api/references/spaces')
    $('#resources-output').innerHTML = items.map((item) => `<div class="list-item"><div class="list-item-title">${escapeHtml(item.space_id || '-')}</div><div class="list-item-meta">${escapeHtml(item.tenant_id || '')}</div></div>`).join('') || '<div class="empty">暂无 references</div>'
  }
}

function setView(view) {
  state.view = view
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view))
  $$('.view').forEach((section) => section.classList.toggle('active', section.dataset.viewPanel === view))
  $('#page-title').textContent = viewMeta[view].title
  $('#page-subtitle').textContent = viewMeta[view].subtitle
}

async function refreshCurrentView() {
  switch (state.view) {
    case 'home':
      await renderHome()
      break
    case 'bot':
      await Promise.all([loadBotData(), ensureCatalog(true)])
      renderBot()
      break
    case 'models':
      await Promise.all([loadModelData(), ensureCatalog(true)])
      renderProvidersAndPresets()
      break
    case 'prompts':
      await Promise.all([loadPromptData(), ensureCatalog(true)])
      renderPrompts()
      break
    case 'plugins':
      await loadPluginData()
      renderPlugins()
      break
    case 'skills':
      await loadSkillsAndSubagents()
      renderSkills()
      break
    case 'subagents':
      await loadSkillsAndSubagents()
      renderSubagents()
      break
    case 'sessions':
      await loadSessionData()
      renderSessions()
      break
    case 'system':
      await Promise.all([
        renderLogs('#system-log-stream', '#system-log-level-filter', '#system-log-keyword'),
        renderBackendStatus(),
        renderApprovals(),
      ])
      break
  }
}

function bindTabs(rootId, attrName, panelAttr) {
  const root = document.getElementById(rootId)
  if (!root) return
  root.querySelectorAll(`[data-${attrName}]`).forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.dataset[attrName]
      root.querySelectorAll(`[data-${attrName}]`).forEach((node) => node.classList.toggle('active', node === button))
      document.querySelectorAll(`[data-${panelAttr}]`).forEach((panel) => panel.classList.toggle('active', panel.dataset[panelAttr] === key))
    })
  })
}

function bindEvents() {
  $$('.nav-item').forEach((item) => item.addEventListener('click', async () => {
    setView(item.dataset.view)
    await refreshCurrentView().catch(handleError)
  }))
  $('#refresh-view-btn').addEventListener('click', () => refreshCurrentView().catch(handleError))
  $('#home-log-refresh-btn').addEventListener('click', () => renderLogs('#home-log-stream', '#home-log-level-filter', '#home-log-keyword').catch(handleError))
  $('#system-log-refresh-btn').addEventListener('click', () => renderLogs('#system-log-stream', '#system-log-level-filter', '#system-log-keyword').catch(handleError))
  $('#save-bot-btn').addEventListener('click', () => saveBot().catch(handleError))
  $('#new-provider-btn').addEventListener('click', () => { state.selectedProviderId = ''; fillProviderForm(); renderProvidersAndPresets() })
  $('#save-provider-btn').addEventListener('click', () => saveProvider().catch(handleError))
  $('#delete-provider-btn').addEventListener('click', () => deleteProvider().catch(handleError))
  $('#new-preset-btn').addEventListener('click', () => { state.selectedPresetId = ''; fillPresetForm(); renderProvidersAndPresets() })
  $('#save-preset-btn').addEventListener('click', () => savePreset().catch(handleError))
  $('#delete-preset-btn').addEventListener('click', () => deletePreset().catch(handleError))
  $('#new-prompt-btn').addEventListener('click', () => { state.selectedPromptRef = ''; fillPromptForm(); renderPrompts() })
  $('#save-prompt-btn').addEventListener('click', () => savePrompt().catch(handleError))
  $('#delete-prompt-btn').addEventListener('click', () => deletePrompt().catch(handleError))
  $('#save-plugins-btn').addEventListener('click', () => savePlugins().catch(handleError))
  $('#reload-plugins-btn').addEventListener('click', () => reloadPlugins().catch(handleError))
  $('#session-search').addEventListener('input', () => renderSessions())
  $('#save-session-btn').addEventListener('click', () => saveSession().catch(handleError))
  $('#delete-session-btn').addEventListener('click', () => deleteSession().catch(handleError))
  $('#open-workspaces-btn').addEventListener('click', () => renderResources('workspaces').catch(handleError))
  $('#open-references-btn').addEventListener('click', () => renderResources('references').catch(handleError))
  bindTabs('session-tabs', 'sessionTab', 'sessionPanel')
  bindTabs('system-tabs', 'systemTab', 'systemPanel')
}

async function init() {
  bindEvents()
  setView('home')
  await refreshCurrentView()
}

init().catch(handleError)
