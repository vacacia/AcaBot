const pageMeta = {
  dashboard: {
    title: "Dashboard",
    subtitle: "运行态总览、审批入口和快速操作。",
  },
  agents: {
    title: "Agents",
    subtitle: "管理 agent profiles、默认模型、tools 和 skill assignments。",
  },
  prompts: {
    title: "Prompts",
    subtitle: "统一管理 prompt 文本，支持 inline 与 filesystem 存储。",
  },
  models: {
    title: "Models",
    subtitle: "管理 provider / preset / binding，预览 impact 与 health check。",
  },
  routing: {
    title: "Routing",
    subtitle: "管理 binding rules、inbound rules 与 event policies。",
  },
  runtime: {
    title: "Runtime",
    subtitle: "查看 threads、runs、步骤、事件和当前 thread override。",
  },
  plugins: {
    title: "Plugins",
    subtitle: "查看已加载插件、skills 与 subagent executors，并执行 reload。",
  },
};

const modelConfigs = {
  providers: {
    title: "Providers",
    singular: "Provider",
    idKey: "provider_id",
    listPath: "/api/models/providers",
    itemPath: (id) => `/api/models/providers/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/models/providers/${encodeURIComponent(id)}`,
    impactPath: (id) => `/api/models/providers/${encodeURIComponent(id)}/impact`,
    template: () => ({
      kind: "openai_compatible",
      base_url: "",
      api_key_env: "",
      default_headers: {},
      default_query: {},
      default_body: {},
    }),
  },
  presets: {
    title: "Presets",
    singular: "Preset",
    idKey: "preset_id",
    listPath: "/api/models/presets",
    itemPath: (id) => `/api/models/presets/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/models/presets/${encodeURIComponent(id)}`,
    impactPath: (id) => `/api/models/presets/${encodeURIComponent(id)}/impact`,
    healthPath: (id) => `/api/models/presets/${encodeURIComponent(id)}/health-check`,
    template: () => ({
      provider_id: "",
      model: "",
      context_window: 128000,
      supports_tools: true,
      supports_vision: false,
      max_output_tokens: null,
      model_params: {},
    }),
  },
  bindings: {
    title: "Bindings",
    singular: "Binding",
    idKey: "binding_id",
    listPath: "/api/models/bindings",
    itemPath: (id) => `/api/models/bindings/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/models/bindings/${encodeURIComponent(id)}`,
    impactPath: (id) => `/api/models/bindings/${encodeURIComponent(id)}/impact`,
    template: () => ({
      target_type: "agent",
      target_id: "",
      preset_id: "",
      preset_ids: [],
      timeout_sec: null,
    }),
  },
};

const routingConfigs = {
  bindings: {
    title: "Binding Rules",
    singular: "Binding Rule",
    idKey: "rule_id",
    listPath: "/api/rules/bindings",
    itemPath: (id) => `/api/rules/bindings/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/rules/bindings/${encodeURIComponent(id)}`,
    template: () => ({
      agent_id: "",
      priority: 100,
      match: {
        channel_scope: "",
      },
      metadata: {},
    }),
  },
  inbound: {
    title: "Inbound Rules",
    singular: "Inbound Rule",
    idKey: "rule_id",
    listPath: "/api/rules/inbound",
    itemPath: (id) => `/api/rules/inbound/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/rules/inbound/${encodeURIComponent(id)}`,
    template: () => ({
      run_mode: "respond",
      priority: 100,
      match: {
        platform: "",
        event_type: "message",
      },
      metadata: {},
    }),
  },
  "event-policies": {
    title: "Event Policies",
    singular: "Event Policy",
    idKey: "policy_id",
    listPath: "/api/rules/event-policies",
    itemPath: (id) => `/api/rules/event-policies/${encodeURIComponent(id)}`,
    deletePath: (id) => `/api/rules/event-policies/${encodeURIComponent(id)}`,
    template: () => ({
      priority: 100,
      match: {
        platform: "",
        event_type: "message",
      },
      persist_event: true,
      extract_to_memory: false,
      memory_scopes: [],
      tags: [],
      metadata: {},
    }),
  },
};

const state = {
  view: "dashboard",
  meta: null,
  status: null,
  profiles: [],
  selectedProfileId: "",
  prompts: [],
  selectedPromptRef: "",
  modelKind: "providers",
  modelEntities: {
    providers: [],
    presets: [],
    bindings: [],
  },
  selectedModelIds: {
    providers: "",
    presets: "",
    bindings: "",
  },
  routingKind: "bindings",
  routingEntities: {
    bindings: [],
    inbound: [],
    "event-policies": [],
  },
  selectedRoutingIds: {
    bindings: "",
    inbound: "",
    "event-policies": "",
  },
  threads: [],
  selectedThreadId: "",
  runs: [],
  selectedRunId: "",
  plugins: [],
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok || !json.ok) {
    throw new Error(json.error || `request failed: ${path}`);
  }
  return json.data;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.hidden = true;
  }, 2600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function formatTime(timestamp) {
  if (!timestamp) return "-";
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.valueOf())) return "-";
  return date.toLocaleString("zh-CN");
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderSelectableList(container, items, activeId, labelFn, metaFn = () => "") {
  if (!items.length) {
    container.innerHTML = emptyState("暂无数据");
    return;
  }
  container.innerHTML = items
    .map((item) => {
      const id = labelFn.id ? labelFn.id(item) : item.id || item.rule_id || item.policy_id || item.agent_id || item.prompt_ref || item.run_id || item.thread_id || item.provider_id || item.preset_id || item.binding_id || item;
      return `
        <div class="list-item ${id === activeId ? "active" : ""}" data-item-id="${escapeHtml(id)}">
          <div class="list-item-title">${escapeHtml(labelFn(item))}</div>
          <div class="list-item-meta">${escapeHtml(metaFn(item) || "")}</div>
        </div>
      `;
    })
    .join("");
}

function parseJsonOrThrow(raw, fallback = {}) {
  const text = String(raw || "").trim();
  if (!text) return fallback;
  return JSON.parse(text);
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === view);
  });
  document.querySelectorAll(".view").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === view);
  });
  $("#page-title").textContent = pageMeta[view].title;
  $("#page-subtitle").textContent = pageMeta[view].subtitle;
  window.location.hash = view;
  refreshCurrentView().catch(handleError);
}

async function loadMetaAndStatus() {
  const [meta, status] = await Promise.all([
    api("/api/meta"),
    api("/api/status"),
  ]);
  state.meta = meta;
  state.status = status;
  $("#meta-storage-mode").textContent = `storage: ${meta.storage_mode}`;
  $("#meta-config-path").textContent = `config: ${meta.config_path}`;
  $("#status-strip").innerHTML = [
    ["active runs", (status.active_runs || []).length],
    ["pending approvals", (status.pending_approvals || []).length],
    ["plugins", status.loaded_plugins.length],
    ["skills", status.loaded_skills.length],
  ]
    .map(([label, value]) => `<div class="status-pill">${escapeHtml(label)}: <strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

async function loadDashboard() {
  await loadMetaAndStatus();
  const status = state.status;
  $("#stat-active-runs").textContent = (status.active_runs || []).length;
  $("#stat-pending-approvals").textContent = (status.pending_approvals || []).length;
  $("#stat-loaded-skills").textContent = status.loaded_skills.length;

  const activeRuns = $("#active-runs");
  if (!status.active_runs.length) {
    activeRuns.innerHTML = emptyState("当前没有活跃 run");
  } else {
    activeRuns.innerHTML = status.active_runs
      .map(
        (run) => `
          <div class="info-card">
            <div class="list-item-title">${escapeHtml(run.run_id)}</div>
            <div class="list-item-meta">agent=${escapeHtml(run.agent_id)} · status=${escapeHtml(run.status)} · thread=${escapeHtml(run.thread_id)}</div>
          </div>
        `,
      )
      .join("");
  }

  const approvalBox = $("#pending-approvals");
  if (!status.pending_approvals.length) {
    approvalBox.innerHTML = emptyState("当前没有待审批项");
  } else {
    approvalBox.innerHTML = status.pending_approvals
      .map(
        (item) => `
          <div class="info-card">
            <div class="list-item-title">${escapeHtml(item.run_id)}</div>
            <div class="list-item-meta">${escapeHtml(item.reason || "")}</div>
            <div class="inline-actions" style="margin-top: 12px;">
              <button class="button button-primary" data-approval-action="approve" data-run-id="${escapeHtml(item.run_id)}">Approve</button>
              <button class="button button-danger" data-approval-action="reject" data-run-id="${escapeHtml(item.run_id)}">Reject</button>
            </div>
          </div>
        `,
      )
      .join("");
    approvalBox.querySelectorAll("[data-approval-action]").forEach((button) => {
      button.addEventListener("click", async () => {
        const runId = button.dataset.runId;
        const action = button.dataset.approvalAction;
        if (action === "approve") {
          await api("/api/approvals/approve", {
            method: "POST",
            body: JSON.stringify({ run_id: runId, metadata: { source: "webui" } }),
          });
          showToast(`已批准 ${runId}`);
        } else {
          await api("/api/approvals/reject", {
            method: "POST",
            body: JSON.stringify({ run_id: runId, reason: "rejected from webui", metadata: { source: "webui" } }),
          });
          showToast(`已拒绝 ${runId}`);
        }
        await loadDashboard();
      });
    });
  }
}

async function loadProfiles() {
  state.profiles = await api("/api/profiles");
  if (!state.selectedProfileId && state.profiles.length) {
    state.selectedProfileId = state.profiles[0].agent_id;
  }
  renderSelectableList(
    $("#profiles-list"),
    state.profiles,
    state.selectedProfileId,
    (item) => item.agent_id,
    (item) => `${item.prompt_ref || "-"} · ${item.default_model || "-"}`,
  );
  const selected = state.profiles.find((item) => item.agent_id === state.selectedProfileId);
  fillProfileForm(selected || createProfileTemplate());
  $("#profiles-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedProfileId = node.dataset.itemId;
      loadProfiles().catch(handleError);
    });
  });
}

function createProfileTemplate() {
  return {
    agent_id: "",
    name: "",
    prompt_ref: "prompt/",
    default_model: "",
    enabled_tools: [],
    skill_assignments: [],
    computer: {},
  };
}

function fillProfileForm(profile) {
  $("#profile-agent-id").value = profile.agent_id || "";
  $("#profile-name").value = profile.name || "";
  $("#profile-prompt-ref").value = profile.prompt_ref || "";
  $("#profile-default-model").value = profile.default_model || "";
  $("#profile-enabled-tools").value = Array.isArray(profile.enabled_tools) ? profile.enabled_tools.join(", ") : "";
  $("#profile-skill-assignments").value = pretty(profile.skill_assignments || []);
  $("#profile-computer").value = pretty(profile.computer || {});
}

function readProfileForm() {
  return {
    agent_id: $("#profile-agent-id").value.trim(),
    name: $("#profile-name").value.trim(),
    prompt_ref: $("#profile-prompt-ref").value.trim(),
    default_model: $("#profile-default-model").value.trim(),
    enabled_tools: $("#profile-enabled-tools").value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    skill_assignments: parseJsonOrThrow($("#profile-skill-assignments").value, []),
    computer: parseJsonOrThrow($("#profile-computer").value, {}),
  };
}

async function saveProfile() {
  const payload = readProfileForm();
  await api(`/api/profiles/${encodeURIComponent(payload.agent_id)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.selectedProfileId = payload.agent_id;
  showToast(`已保存 profile: ${payload.agent_id}`);
  await loadProfiles();
}

async function deleteProfile() {
  const agentId = $("#profile-agent-id").value.trim();
  if (!agentId) return;
  await api(`/api/profiles/${encodeURIComponent(agentId)}`, { method: "DELETE" });
  showToast(`已删除 profile: ${agentId}`);
  state.selectedProfileId = "";
  await loadProfiles();
}

async function loadPrompts() {
  state.prompts = await api("/api/prompts");
  if (!state.selectedPromptRef && state.prompts.length) {
    state.selectedPromptRef = state.prompts[0].prompt_ref;
  }
  renderSelectableList(
    $("#prompts-list"),
    state.prompts,
    state.selectedPromptRef,
    (item) => item.prompt_ref,
    (item) => item.source,
  );
  const selected = state.prompts.find((item) => item.prompt_ref === state.selectedPromptRef);
  $("#prompt-ref-input").value = selected?.prompt_ref || "prompt/";
  $("#prompt-content-input").value = selected?.content || "";
  $("#prompts-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedPromptRef = node.dataset.itemId;
      loadPrompts().catch(handleError);
    });
  });
}

async function savePrompt() {
  const promptRef = $("#prompt-ref-input").value.trim();
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, {
    method: "PUT",
    body: JSON.stringify({ content: $("#prompt-content-input").value }),
  });
  state.selectedPromptRef = promptRef;
  showToast(`已保存 prompt: ${promptRef}`);
  await loadPrompts();
}

async function deletePrompt() {
  const promptRef = $("#prompt-ref-input").value.trim();
  if (!promptRef) return;
  await api(`/api/prompt?prompt_ref=${encodeURIComponent(promptRef)}`, { method: "DELETE" });
  state.selectedPromptRef = "";
  showToast(`已删除 prompt: ${promptRef}`);
  await loadPrompts();
}

async function loadModelEntities() {
  const config = modelConfigs[state.modelKind];
  state.modelEntities[state.modelKind] = await api(config.listPath);
  if (!state.selectedModelIds[state.modelKind] && state.modelEntities[state.modelKind].length) {
    state.selectedModelIds[state.modelKind] = state.modelEntities[state.modelKind][0][config.idKey];
  }
  renderSelectableList(
    $("#models-entity-list"),
    state.modelEntities[state.modelKind],
    state.selectedModelIds[state.modelKind],
    (item) => item[config.idKey],
    (item) => {
      if (state.modelKind === "providers") return item.kind || "-";
      if (state.modelKind === "presets") return `${item.provider_id || "-"} · ${item.model || "-"}`;
      return `${item.target_type || "-"}:${item.target_id || "-"}`;
    },
  );
  $("#models-list-title").textContent = config.title;
  $("#models-editor-title").textContent = `${config.singular} Editor`;
  const selectedId = state.selectedModelIds[state.modelKind];
  const selected = state.modelEntities[state.modelKind].find((item) => item[config.idKey] === selectedId);
  $("#model-entity-id").value = selectedId || "";
  $("#model-entity-json").value = pretty(selected ? stripId(selected, config.idKey) : config.template());
  $("#model-entity-sidecar").textContent = selected ? pretty(selected) : "";
  $("#models-entity-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedModelIds[state.modelKind] = node.dataset.itemId;
      loadModelEntities().catch(handleError);
    });
  });
}

function stripId(item, idKey) {
  const data = { ...item };
  delete data[idKey];
  if (idKey === "provider_id" && data.config) {
    return {
      kind: data.kind,
      ...data.config,
    };
  }
  return data;
}

async function saveModelEntity() {
  const config = modelConfigs[state.modelKind];
  const id = $("#model-entity-id").value.trim();
  const payload = parseJsonOrThrow($("#model-entity-json").value, {});
  await api(config.itemPath(id), {
    method: "PUT",
    body: JSON.stringify({ ...payload, [config.idKey]: id }),
  });
  state.selectedModelIds[state.modelKind] = id;
  showToast(`已保存 ${config.singular}: ${id}`);
  await loadModelEntities();
}

async function deleteModelEntity() {
  const config = modelConfigs[state.modelKind];
  const id = $("#model-entity-id").value.trim();
  if (!id) return;
  await api(config.deletePath(id), { method: "DELETE" });
  showToast(`已删除 ${config.singular}: ${id}`);
  state.selectedModelIds[state.modelKind] = "";
  await loadModelEntities();
}

async function loadModelSidecar(kind) {
  const config = modelConfigs[kind];
  const id = $("#model-entity-id").value.trim();
  if (!id) return;
  const impact = await api(config.impactPath(id));
  $("#model-entity-sidecar").textContent = pretty(impact);
}

async function healthCheckPreset() {
  if (state.modelKind !== "presets") {
    showToast("Health check 只对 preset 可用");
    return;
  }
  const id = $("#model-entity-id").value.trim();
  const result = await api(modelConfigs.presets.healthPath(id), { method: "POST" });
  $("#model-entity-sidecar").textContent = pretty(result);
}

async function reloadModelRegistry() {
  const result = await api("/api/models/reload", { method: "POST" });
  $("#model-entity-sidecar").textContent = pretty(result);
  showToast("model registry 已 reload");
  await loadModelEntities();
}

async function loadRoutingEntities() {
  const config = routingConfigs[state.routingKind];
  state.routingEntities[state.routingKind] = await api(config.listPath);
  if (!state.selectedRoutingIds[state.routingKind] && state.routingEntities[state.routingKind].length) {
    state.selectedRoutingIds[state.routingKind] = state.routingEntities[state.routingKind][0][config.idKey];
  }
  renderSelectableList(
    $("#routing-entity-list"),
    state.routingEntities[state.routingKind],
    state.selectedRoutingIds[state.routingKind],
    (item) => item[config.idKey],
    (item) => `priority=${item.priority ?? "-"} · match=${Object.keys(item.match || {}).join(",") || "-"}`,
  );
  $("#routing-list-title").textContent = config.title;
  $("#routing-editor-title").textContent = `${config.singular} Editor`;
  const selectedId = state.selectedRoutingIds[state.routingKind];
  const selected = state.routingEntities[state.routingKind].find((item) => item[config.idKey] === selectedId);
  $("#routing-entity-id").value = selectedId || "";
  $("#routing-entity-json").value = pretty(selected ? stripId(selected, config.idKey) : config.template());
  $("#routing-entity-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedRoutingIds[state.routingKind] = node.dataset.itemId;
      loadRoutingEntities().catch(handleError);
    });
  });
}

async function saveRoutingEntity() {
  const config = routingConfigs[state.routingKind];
  const id = $("#routing-entity-id").value.trim();
  const payload = parseJsonOrThrow($("#routing-entity-json").value, {});
  await api(config.itemPath(id), {
    method: "PUT",
    body: JSON.stringify({ ...payload, [config.idKey]: id }),
  });
  state.selectedRoutingIds[state.routingKind] = id;
  showToast(`已保存 ${config.singular}: ${id}`);
  await loadRoutingEntities();
}

async function deleteRoutingEntity() {
  const config = routingConfigs[state.routingKind];
  const id = $("#routing-entity-id").value.trim();
  if (!id) return;
  await api(config.deletePath(id), { method: "DELETE" });
  state.selectedRoutingIds[state.routingKind] = "";
  showToast(`已删除 ${config.singular}: ${id}`);
  await loadRoutingEntities();
}

async function loadRuntime() {
  const [threads, runs] = await Promise.all([
    api("/api/runtime/threads?limit=100"),
    api("/api/runtime/runs?limit=100"),
  ]);
  state.threads = threads;
  state.runs = runs;
  if (!state.selectedThreadId && threads.length) {
    state.selectedThreadId = threads[0].thread_id;
  }
  if (!state.selectedRunId && runs.length) {
    state.selectedRunId = runs[0].run_id;
  }
  renderSelectableList(
    $("#runtime-threads-list"),
    threads,
    state.selectedThreadId,
    (item) => item.thread_id,
    (item) => `${item.channel_scope || "-"} · ${formatTime(item.last_event_at)}`,
  );
  $("#runtime-threads-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedThreadId = node.dataset.itemId;
      loadRuntime().catch(handleError);
    });
  });
  renderSelectableList(
    $("#runtime-runs-list"),
    runs,
    state.selectedRunId,
    (item) => item.run_id,
    (item) => `${item.agent_id || "-"} · ${item.status || "-"}`,
  );
  $("#runtime-runs-list").querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedRunId = node.dataset.itemId;
      loadRuntime().catch(handleError);
    });
  });
  await Promise.all([loadThreadDetail(), loadRunDetail()]);
}

async function loadThreadDetail() {
  const threadId = state.selectedThreadId;
  if (!threadId) {
    $("#runtime-thread-summary").innerHTML = emptyState("未选择 thread");
    return;
  }
  const [thread, steps, events, messages, sandbox] = await Promise.all([
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/steps?limit=50`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/events?limit=30`),
    api(`/api/runtime/threads/${encodeURIComponent(threadId)}/messages?limit=30`),
    api(`/api/workspaces/${encodeURIComponent(threadId)}/sandbox`),
  ]);
  $("#thread-agent-override-input").value = thread.metadata?.thread_agent_override || "";
  $("#runtime-thread-summary").innerHTML = `
    <div class="info-card"><strong>thread_id</strong><div class="list-item-meta">${escapeHtml(thread.thread_id)}</div></div>
    <div class="info-card"><strong>channel_scope</strong><div class="list-item-meta">${escapeHtml(thread.channel_scope)}</div></div>
    <div class="info-card"><strong>last_event_at</strong><div class="list-item-meta">${escapeHtml(formatTime(thread.last_event_at))}</div></div>
    <div class="info-card"><strong>sandbox</strong><div class="list-item-meta">${escapeHtml(sandbox.backend_kind)} · active=${escapeHtml(String(sandbox.active))}</div></div>
  `;
  renderSimpleTimeline($("#runtime-thread-steps"), steps, (item) => `${item.step_type} · ${item.status}`);
  renderSimpleTimeline($("#runtime-thread-events"), events, (item) => `${item.event_type} · ${item.content_text || "-"}`);
  renderSimpleTimeline($("#runtime-thread-messages"), messages, (item) => `${item.role || item.message_type || "message"} · ${item.content_text || "-"}`);
}

async function saveThreadAgentOverride() {
  const threadId = state.selectedThreadId;
  const agentId = $("#thread-agent-override-input").value.trim();
  if (!threadId || !agentId) return;
  await api(`/api/runtime/threads/${encodeURIComponent(threadId)}/agent-override`, {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId }),
  });
  showToast(`thread override 已设置为 ${agentId}`);
  await loadRuntime();
}

async function clearThreadAgentOverride() {
  const threadId = state.selectedThreadId;
  if (!threadId) return;
  await api(`/api/runtime/threads/${encodeURIComponent(threadId)}/agent-override`, {
    method: "DELETE",
  });
  showToast("thread override 已清除");
  await loadRuntime();
}

async function loadRunDetail() {
  const runId = state.selectedRunId;
  if (!runId) {
    $("#runtime-run-detail").innerHTML = emptyState("未选择 run");
    $("#runtime-run-steps").innerHTML = emptyState("未选择 run");
    return;
  }
  const [run, steps] = await Promise.all([
    api(`/api/runtime/runs/${encodeURIComponent(runId)}`),
    api(`/api/runtime/runs/${encodeURIComponent(runId)}/steps?limit=80`),
  ]);
  $("#runtime-run-detail").innerHTML = `
    <div class="info-card"><strong>run_id</strong><div class="list-item-meta">${escapeHtml(run.run_id)}</div></div>
    <div class="info-card"><strong>agent</strong><div class="list-item-meta">${escapeHtml(run.agent_id)}</div></div>
    <div class="info-card"><strong>status</strong><div class="list-item-meta">${escapeHtml(run.status)}</div></div>
    <div class="info-card"><strong>thread</strong><div class="list-item-meta">${escapeHtml(run.thread_id)}</div></div>
  `;
  renderSimpleTimeline($("#runtime-run-steps"), steps, (item) => `${item.step_type} · ${item.status}`);
}

function renderSimpleTimeline(container, items, formatter) {
  if (!items.length) {
    container.innerHTML = emptyState("暂无记录");
    return;
  }
  container.innerHTML = items
    .map(
      (item) => `
        <div class="info-card">
          <div class="list-item-title">${escapeHtml(formatter(item))}</div>
          <div class="list-item-meta">${escapeHtml(formatTime(item.created_at || item.timestamp || 0))}</div>
        </div>
      `,
    )
    .join("");
}

async function loadPlugins() {
  const [plugins, status, executors] = await Promise.all([
    api("/api/plugins"),
    api("/api/status"),
    api("/api/subagents/executors"),
  ]);
  state.plugins = plugins.loaded_plugins || [];
  renderSelectableList(
    $("#plugins-list"),
    state.plugins.map((name) => ({ id: name, name })),
    "",
    (item) => item.name,
    () => "loaded",
  );
  $("#plugins-skills").innerHTML = (status.loaded_skills || [])
    .map((name) => `<div class="info-card">${escapeHtml(name)}</div>`)
    .join("") || emptyState("没有 skills");
  $("#plugins-executors").innerHTML = executors
    .map((item) => `<div class="info-card"><strong>${escapeHtml(item.agent_id)}</strong><div class="list-item-meta">${escapeHtml(item.source || "-")}</div></div>`)
    .join("") || emptyState("没有 executors");
}

async function reloadPlugins() {
  const pluginNames = $("#reload-plugins-input").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  await api("/api/plugins/reload", {
    method: "POST",
    body: JSON.stringify({ plugin_names: pluginNames }),
  });
  showToast("plugins 已 reload");
  await Promise.all([loadPlugins(), loadDashboard()]);
}

async function reloadRuntimeConfig() {
  await api("/api/runtime/reload-config", { method: "POST" });
  showToast("runtime 配置已 reload");
  await refreshCurrentView(true);
}

async function refreshCurrentView(forceHeader = false) {
  if (forceHeader || state.view === "dashboard") {
    await loadMetaAndStatus();
  }
  if (state.view === "dashboard") return loadDashboard();
  if (state.view === "agents") return loadProfiles();
  if (state.view === "prompts") return loadPrompts();
  if (state.view === "models") return loadModelEntities();
  if (state.view === "routing") return loadRoutingEntities();
  if (state.view === "runtime") return loadRuntime();
  if (state.view === "plugins") return loadPlugins();
}

function handleError(error) {
  console.error(error);
  showToast(error.message || "操作失败");
}

function wireEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.section));
  });
  $("#refresh-all-btn").addEventListener("click", () => refreshCurrentView(true).catch(handleError));
  $("#reload-config-btn").addEventListener("click", () => reloadRuntimeConfig().catch(handleError));
  $("#refresh-approvals-btn").addEventListener("click", () => loadDashboard().catch(handleError));

  $("#new-profile-btn").addEventListener("click", () => {
    state.selectedProfileId = "";
    fillProfileForm(createProfileTemplate());
  });
  $("#save-profile-btn").addEventListener("click", () => saveProfile().catch(handleError));
  $("#delete-profile-btn").addEventListener("click", () => deleteProfile().catch(handleError));

  $("#new-prompt-btn").addEventListener("click", () => {
    state.selectedPromptRef = "";
    $("#prompt-ref-input").value = "prompt/";
    $("#prompt-content-input").value = "";
  });
  $("#save-prompt-btn").addEventListener("click", () => savePrompt().catch(handleError));
  $("#delete-prompt-btn").addEventListener("click", () => deletePrompt().catch(handleError));

  document.querySelectorAll("[data-model-kind]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-model-kind]").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      state.modelKind = button.dataset.modelKind;
      loadModelEntities().catch(handleError);
    });
  });
  $("#new-model-entity-btn").addEventListener("click", () => {
    const config = modelConfigs[state.modelKind];
    state.selectedModelIds[state.modelKind] = "";
    $("#model-entity-id").value = "";
    $("#model-entity-json").value = pretty(config.template());
    $("#model-entity-sidecar").textContent = "";
  });
  $("#save-model-entity-btn").addEventListener("click", () => saveModelEntity().catch(handleError));
  $("#delete-model-entity-btn").addEventListener("click", () => deleteModelEntity().catch(handleError));
  $("#preview-model-impact-btn").addEventListener("click", () => loadModelSidecar(state.modelKind).catch(handleError));
  $("#health-check-preset-btn").addEventListener("click", () => healthCheckPreset().catch(handleError));
  $("#reload-model-registry-btn").addEventListener("click", () => reloadModelRegistry().catch(handleError));

  document.querySelectorAll("[data-routing-kind]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-routing-kind]").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      state.routingKind = button.dataset.routingKind;
      loadRoutingEntities().catch(handleError);
    });
  });
  $("#new-routing-entity-btn").addEventListener("click", () => {
    const config = routingConfigs[state.routingKind];
    state.selectedRoutingIds[state.routingKind] = "";
    $("#routing-entity-id").value = "";
    $("#routing-entity-json").value = pretty(config.template());
  });
  $("#save-routing-entity-btn").addEventListener("click", () => saveRoutingEntity().catch(handleError));
  $("#delete-routing-entity-btn").addEventListener("click", () => deleteRoutingEntity().catch(handleError));

  $("#refresh-runtime-btn").addEventListener("click", () => loadRuntime().catch(handleError));
  $("#save-thread-agent-override-btn").addEventListener("click", () => saveThreadAgentOverride().catch(handleError));
  $("#clear-thread-agent-override-btn").addEventListener("click", () => clearThreadAgentOverride().catch(handleError));

  $("#refresh-plugins-btn").addEventListener("click", () => loadPlugins().catch(handleError));
  $("#reload-plugins-btn").addEventListener("click", () => reloadPlugins().catch(handleError));
}

async function bootstrap() {
  wireEvents();
  const initialView = location.hash.replace("#", "");
  if (pageMeta[initialView]) {
    state.view = initialView;
  }
  setView(state.view);
}

bootstrap().catch(handleError);
