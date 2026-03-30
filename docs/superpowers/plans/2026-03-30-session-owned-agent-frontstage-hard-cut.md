# Session-Owned Agent Frontstage Hard Cut Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前台正式真源从共享 profile 硬切到 `session.yaml + agent.yaml` 的 `session-owned agent` 模型，并上线新的 `/api/sessions` control-plane 契约。

**Architecture:** 这一版只做 backend/runtime、control plane、测试和文档清理，不做 WebUI 页面实现。运行时改成先按 `session_id` 读取 session bundle，再把 `session-owned agent` 收成当前 run 的只读 agent 快照；未配置 session 不自动创建、不进入前台执行。旧的前台 profile registry、`/api/profiles`、`frontstage_profile` 等接缝在这次改造里一次清理掉，不保留双轨兼容。

**Tech Stack:** Python 3.11, pytest, YAML filesystem source-of-truth, ThreadingHTTPServer control plane, runtime bootstrap, model target catalog

---

## Scope Check

这份 spec 虽然会动到 runtime、bootstrap、control plane 和测试，但它们都服务于同一个紧耦合目标: “前台身份真源从共享 profile 切到 session-owned agent”。不要把这次改造再拆成 “先留 profile registry 兼容、后面再清理” 的两段计划；这次计划默认就是硬切。

WebUI 页面实现不在本计划内。第一阶段只要求后端把 `/api/sessions` 的正式契约和文件真源收对。

## File Structure

### Session bundle contracts and filesystem loaders

- Create: `src/acabot/runtime/contracts/session_agent.py`
  - 定义 `SessionAgent`、`SessionBundle`、`SessionBundlePaths` 这类新的正式对象。
- Modify: `src/acabot/runtime/contracts/session_config.py`
  - 把 `frontstage_profile` / `profile_id` 之类旧前台字段收成 `frontstage_agent_id` / `agent_id`。
- Modify: `src/acabot/runtime/contracts/routing.py`
  - 用新的 run 级 agent 快照对象替换 `AgentProfile`，同时更新 docstring 语义。
- Modify: `src/acabot/runtime/contracts/context.py`
  - 把 `RunContext.profile` 收成 `RunContext.agent`。
- Modify: `src/acabot/runtime/contracts/__init__.py`
  - 导出新对象，删掉旧前台 profile 导出。
- Modify: `src/acabot/runtime/control/session_loader.py`
  - 只负责读写 `session.yaml`，并切换到 `sessions/<platform>/<scope>/<id>/session.yaml` 目录形状。
- Create: `src/acabot/runtime/control/session_agent_loader.py`
  - 负责解析 `agent.yaml`，校验内部 id、能力字段和默认 computer policy。
- Create: `src/acabot/runtime/control/session_bundle_loader.py`
  - 负责把同目录的 `session.yaml + agent.yaml` 读成完整 bundle，并提供 `path_for_session_id()` / `load_by_session_id()` / `list_session_ids()` 之类统一入口。

### Runtime route and run-context hard cut

- Modify: `src/acabot/runtime/control/session_runtime.py`
  - routing 只认 session bundle，不再回退共享 profile。
- Modify: `src/acabot/runtime/router.py`
  - 未配置 session 直接产出 `silent_drop`；已配置 session 把 `agent_id` 收进 `RouteDecision`。
- Modify: `src/acabot/runtime/app.py`
  - 不再调用 `profile_loader(decision)`；改成读取 bundle 里的 frontstage agent 快照。
- Modify: `src/acabot/runtime/model/model_resolution.py`
  - run 级模型解析改成认新的 agent 快照对象。
- Modify: `src/acabot/runtime/pipeline.py`
- Modify: `src/acabot/runtime/outbox.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/inbound/image_context.py`
- Modify: `src/acabot/runtime/inbound/message_preparation.py`
- Modify: `src/acabot/runtime/memory/context_compactor.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `src/acabot/runtime/tool_broker/contracts.py`
- Modify: `src/acabot/runtime/skills/catalog.py`
- Modify: `src/acabot/runtime/subagents/broker.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
  - 这些消费层统一从 `ctx.agent` 取 prompt / tool / skill / computer 信息，不再保留前台 `ctx.profile`。

### Bootstrap, reload and model-target wiring

- Create: `src/acabot/runtime/control/prompt_loader.py`
  - 把 prompt-only loader 从旧 `profile_loader.py` 拆出来，避免继续保留混淆文件名。
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
  - bootstrap 不再构造前台共享 profiles；改成构造 session bundle runtime 和 prompt loader。
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
  - 组装 `SessionBundleLoader`、新的 app agent loader、session-agent model targets、control plane 接线。
- Modify: `src/acabot/runtime/bootstrap/components.py`
  - 替换 `profile_loader` 导出和相关类型。
- Modify: `src/acabot/runtime/control/config_control_plane.py`
  - reload 时重建 session runtime、session-agent targets 和新的 session bundle 读写入口。
- Modify: `src/acabot/runtime/control/control_plane.py`
  - 删掉 profile CRUD 入口；接入 session CRUD。
- Modify: `src/acabot/runtime/control/model_ops.py`
  - 把对 `AgentProfileRegistry` 的前台依赖挪掉，只保留模型目录管理本身。
- Modify: `src/acabot/runtime/model/model_targets.py`
  - `agent:<agent_id>` target 不再来自共享 profile registry，而来自当前 session-owned agent 集合。
- Modify: `src/acabot/runtime/__init__.py`
  - 更新导出面，删掉旧前台 profile 对象名。
- Delete: `src/acabot/runtime/control/profile_loader.py`
  - 旧文件中的 prompt loader 代码先迁走，再完全删除这个名字。

### Control plane and API

- Modify: `src/acabot/runtime/control/config_control_plane.py`
  - 实现 `create_session()` / `list_sessions()` / `get_session_bundle()` / `update_session()` / `update_session_agent()`。
- Modify: `src/acabot/runtime/control/control_plane.py`
  - 把 `/api/sessions` 的控制面方法接进来。
- Modify: `src/acabot/runtime/control/http_api.py`
  - 实现 `POST /api/sessions`、`GET /api/sessions`、`GET /api/sessions/{id}`、`PUT /api/sessions/{id}`、`GET /api/sessions/{id}/agent`、`PUT /api/sessions/{id}/agent`，并移除 `/api/profiles`。

### Tests and fixtures

- Create: `tests/runtime/test_session_bundle_loader.py`
  - 覆盖目录形状、bundle 解析、一致性校验。
- Create: `tests/runtime/fixtures/sessions/qq/group/123456/session.yaml`
- Create: `tests/runtime/fixtures/sessions/qq/group/123456/agent.yaml`
  - 提供统一的 session bundle fixture。
- Modify: `tests/runtime/test_session_runtime.py`
- Modify: `tests/runtime/test_app.py`
- Modify: `tests/runtime/test_bootstrap.py`
- Modify: `tests/runtime/test_control_plane.py`
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `tests/runtime/control/test_backend_http_api.py`
- Modify: `tests/runtime/test_model_targets.py`
- Modify: `tests/runtime/test_model_registry.py`
- Modify: `tests/runtime/test_subagent_execution.py`
- Modify: `tests/runtime/test_subagent_session_visibility.py`
- Modify: `tests/runtime/test_tool_broker.py`
- Modify: `tests/runtime/test_builtin_tools.py`
- Modify: `tests/runtime/test_image_context.py`
- Modify: `tests/runtime/test_context_compactor.py`
- Modify: `tests/runtime/test_retrieval_planner.py`
- Delete: `tests/runtime/test_profile_loader.py`
  - 用新的 session-agent loader 测试替代。

### Docs cleanup

- Modify: `docs/00-ai-entry.md`
- Modify: `docs/04-routing-and-profiles.md`
- Modify: `docs/21-run-mechanism.md`
- Modify: `docs/27-session-owned-agent.md`
  - 只保留新的前台语义，不再把共享 profile 当正式模型描述。

## Task 1: 建立 `session.yaml + agent.yaml` 的正式 bundle 真源

**Files:**
- Create: `src/acabot/runtime/contracts/session_agent.py`
- Modify: `src/acabot/runtime/contracts/session_config.py`
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/control/session_loader.py`
- Create: `src/acabot/runtime/control/session_agent_loader.py`
- Create: `src/acabot/runtime/control/session_bundle_loader.py`
- Create: `tests/runtime/test_session_bundle_loader.py`
- Modify: `tests/runtime/test_session_runtime.py`

- [ ] **Step 1: 先写 bundle 形状和一致性校验的失败测试**

```python
def test_session_bundle_loader_reads_session_and_agent_yaml(tmp_path: Path) -> None:
    root = tmp_path / "sessions" / "qq" / "group" / "123456"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.yaml").write_text(
        "session:\\n  id: qq:group:123456\\nfrontstage:\\n  agent_id: frontstage\\n",
        encoding="utf-8",
    )
    (root / "agent.yaml").write_text(
        "agent_id: frontstage\\nprompt_ref: prompt/aca/default\\n",
        encoding="utf-8",
    )

    bundle = SessionBundleLoader(config_root=tmp_path / "sessions").load_by_session_id("qq:group:123456")

    assert bundle.session_config.frontstage_agent_id == "frontstage"
    assert bundle.frontstage_agent.agent_id == "frontstage"


def test_session_bundle_loader_rejects_missing_catalog_reference(tmp_path: Path) -> None:
    # 写一个引用不存在 prompt/tool/skill/subagent 的 agent.yaml
    # 断言 loader 抛出明确错误，而不是静默吞掉
    ...
```

- [ ] **Step 2: 跑测试确认它先失败**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_bundle_loader.py tests/runtime/test_session_runtime.py -q`

Expected: FAIL，提示缺少 `SessionAgent` / `SessionBundleLoader` 或仍在按旧的单文件 session 形状解析。

- [ ] **Step 3: 最小实现新的 contracts 和 loaders**

```python
@dataclass(slots=True)
class SessionAgent:
    agent_id: str
    prompt_ref: str
    visible_tools: list[str] = field(default_factory=list)
    visible_skills: list[str] = field(default_factory=list)
    visible_subagents: list[str] = field(default_factory=list)
    computer_policy: ComputerPolicy | None = None
    config: dict[str, Any] = field(default_factory=dict)
```

实现要求：
- `SessionConfig.frontstage_profile` 改成 `frontstage_agent_id`
- `session_loader.py` 改为定位目录内的 `session.yaml`
- `session_agent_loader.py` 负责解析 `agent.yaml`
- `session_bundle_loader.py` 负责校验 `session.yaml.frontstage_agent_id == agent.yaml.agent_id`
- `session_bundle_loader.py` 还要校验 `prompt_ref`、`visible_tools`、`visible_skills`、`visible_subagents` 都能解析到现有 catalog
- 缺少 `agent.yaml`、字段不匹配、非 mapping YAML 都直接抛明确错误
- catalog 引用失效时直接抛明确错误，不允许静默容错

- [ ] **Step 4: 跑测试确认 bundle 解析收稳**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_bundle_loader.py tests/runtime/test_session_runtime.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/contracts/session_agent.py \
  src/acabot/runtime/contracts/session_config.py \
  src/acabot/runtime/contracts/__init__.py \
  src/acabot/runtime/control/session_loader.py \
  src/acabot/runtime/control/session_agent_loader.py \
  src/acabot/runtime/control/session_bundle_loader.py \
  tests/runtime/test_session_bundle_loader.py \
  tests/runtime/test_session_runtime.py
git commit -m "feat: add session bundle source of truth"
```

## Task 2: 把 runtime 主线从 `profile` 硬切到 run 级 `agent` 快照

**Files:**
- Modify: `src/acabot/runtime/contracts/routing.py`
- Modify: `src/acabot/runtime/contracts/context.py`
- Modify: `src/acabot/runtime/control/session_runtime.py`
- Modify: `src/acabot/runtime/router.py`
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/model/model_resolution.py`
- Modify: `src/acabot/runtime/pipeline.py`
- Modify: `src/acabot/runtime/outbox.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/inbound/image_context.py`
- Modify: `src/acabot/runtime/inbound/message_preparation.py`
- Modify: `src/acabot/runtime/memory/context_compactor.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `src/acabot/runtime/tool_broker/contracts.py`
- Modify: `src/acabot/runtime/skills/catalog.py`
- Modify: `src/acabot/runtime/subagents/broker.py`
- Modify: `src/acabot/runtime/subagents/execution.py`
- Modify: `tests/runtime/test_app.py`
- Modify: `tests/runtime/test_session_runtime.py`
- Modify: `tests/runtime/test_tool_broker.py`
- Modify: `tests/runtime/test_builtin_tools.py`
- Modify: `tests/runtime/test_image_context.py`
- Modify: `tests/runtime/test_context_compactor.py`
- Modify: `tests/runtime/test_retrieval_planner.py`
- Modify: `tests/runtime/test_subagent_execution.py`

- [ ] **Step 1: 先补失败测试，锁定两条主线行为**

```python
async def test_runtime_router_silent_drops_unconfigured_session(tmp_path: Path) -> None:
    router = RuntimeRouter(session_runtime=build_session_runtime_for(tmp_path / "sessions"))

    decision = await router.route(_group_message_event(group_id="999"))

    assert decision.run_mode == "silent_drop"
    assert decision.metadata["route_source"] == "unconfigured_session"
    assert "warning" in decision.metadata["drop_reason"]


async def test_runtime_app_builds_run_context_with_agent_snapshot(tmp_path: Path) -> None:
    # 写入 session bundle 后，断言 ctx.agent.prompt_ref 被 agent runtime 消费
    ...
```

- [ ] **Step 2: 跑这些测试确认旧逻辑先坏掉**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_runtime.py tests/runtime/test_app.py -q -k "session or agent"`

Expected: FAIL，原因应包含旧的 `frontstage_profile` / `ctx.profile` / “missing session raises hard error” 一类旧行为。

- [ ] **Step 3: 最小实现 runtime 硬切**

```python
ctx = RunContext(
    run=run,
    event=event,
    decision=decision,
    thread=thread,
    agent=resolved_agent,
    model_request=model_request,
    summary_model_request=summary_model_request,
    ...
)
```

实现要求：
- `RoutingDecision.profile_id` 改成 `agent_id`
- `SessionRuntime.resolve_routing()` 只产出当前 session bundle 的 `agent_id`
- `RuntimeRouter.route()` 遇到未配置 session 时返回 `silent_drop`，不要创建前台 run
- 未配置 session 还要留下带 `session_id` 的可观测 warning 或限流日志，不允许完全静默
- `RuntimeApp` 不再调用 `profile_loader`
- `RunContext.profile` 全部改成 `RunContext.agent`
- 工具、computer、image caption、context compactor、subagent child run 统一从 `ctx.agent` 读取 prompt/tool/skill/computer 配置

- [ ] **Step 4: 跑一组消费层测试，确认不是只有 router 过了**

Run: `PYTHONPATH=src pytest tests/runtime/test_app.py tests/runtime/test_tool_broker.py tests/runtime/test_builtin_tools.py tests/runtime/test_subagent_execution.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/contracts/routing.py \
  src/acabot/runtime/contracts/context.py \
  src/acabot/runtime/control/session_runtime.py \
  src/acabot/runtime/router.py \
  src/acabot/runtime/app.py \
  src/acabot/runtime/model/model_resolution.py \
  src/acabot/runtime/pipeline.py \
  src/acabot/runtime/outbox.py \
  src/acabot/runtime/computer/runtime.py \
  src/acabot/runtime/inbound/image_context.py \
  src/acabot/runtime/inbound/message_preparation.py \
  src/acabot/runtime/memory/context_compactor.py \
  src/acabot/runtime/tool_broker/broker.py \
  src/acabot/runtime/tool_broker/contracts.py \
  src/acabot/runtime/skills/catalog.py \
  src/acabot/runtime/subagents/broker.py \
  src/acabot/runtime/subagents/execution.py \
  tests/runtime/test_app.py \
  tests/runtime/test_session_runtime.py \
  tests/runtime/test_tool_broker.py \
  tests/runtime/test_builtin_tools.py \
  tests/runtime/test_image_context.py \
  tests/runtime/test_context_compactor.py \
  tests/runtime/test_retrieval_planner.py \
  tests/runtime/test_subagent_execution.py
git commit -m "refactor: switch runtime to session-owned agents"
```

## Task 3: 删除前台 profile registry，重接 bootstrap、reload 和 model targets

**Files:**
- Create: `src/acabot/runtime/control/prompt_loader.py`
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/model_ops.py`
- Modify: `src/acabot/runtime/model/model_targets.py`
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `tests/runtime/test_bootstrap.py`
- Modify: `tests/runtime/test_control_plane.py`
- Modify: `tests/runtime/test_model_targets.py`
- Modify: `tests/runtime/test_model_registry.py`
- Modify: `tests/test_main.py`
- Delete: `src/acabot/runtime/control/profile_loader.py`

- [ ] **Step 1: 先写失败测试，锁定 bootstrap 和 reload 的新来源**

```python
def test_bootstrap_builds_frontstage_agent_targets_from_session_bundles(tmp_path: Path) -> None:
    # 写两个 session 目录，断言 model target catalog 和 runtime app 使用 session-owned agents
    ...
```

- [ ] **Step 2: 跑测试，确认它们还在盯旧 profile registry**

Run: `PYTHONPATH=src pytest tests/runtime/test_bootstrap.py tests/runtime/test_control_plane.py tests/runtime/test_model_targets.py -q -k "session or agent"`

Expected: FAIL，原因应包含 `AgentProfileRegistry`、`profile_loader`、`build_agent_model_targets(profiles)` 一类旧接缝。

- [ ] **Step 3: 最小实现 bootstrap 和 reload 硬切**

```python
prompt_loader = ReloadablePromptLoader(build_prompt_loader(config, session_agents=session_agents))
runtime_model_target_catalog.replace_agent_targets(build_agent_model_targets(session_agents))
```

实现要求：
- prompt-only loader 从旧 `profile_loader.py` 拆到 `prompt_loader.py`
- bootstrap 不再组装前台共享 `profiles` / `AgentProfileRegistry`
- `build_agent_model_targets(...)` 改为接收当前 session-owned agent 集合
- `RuntimeConfigControlPlane.reload_runtime_configuration()` 重建 session runtime、session-agent targets、prompt loader
- `RuntimeComponents` 和 `RuntimeApp` 对外不再暴露 `profile_loader`
- 删除 `src/acabot/runtime/control/profile_loader.py`

- [ ] **Step 4: 跑 bootstrap / model suite**

Run: `PYTHONPATH=src pytest tests/runtime/test_bootstrap.py tests/runtime/test_control_plane.py tests/runtime/test_model_targets.py tests/runtime/test_model_registry.py tests/test_main.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/control/prompt_loader.py \
  src/acabot/runtime/bootstrap/loaders.py \
  src/acabot/runtime/bootstrap/__init__.py \
  src/acabot/runtime/bootstrap/components.py \
  src/acabot/runtime/control/config_control_plane.py \
  src/acabot/runtime/control/control_plane.py \
  src/acabot/runtime/control/model_ops.py \
  src/acabot/runtime/model/model_targets.py \
  src/acabot/runtime/__init__.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_control_plane.py \
  tests/runtime/test_model_targets.py \
  tests/runtime/test_model_registry.py \
  tests/test_main.py
git rm src/acabot/runtime/control/profile_loader.py
git commit -m "refactor: remove frontstage profile registry"
```

## Task 4: 上线 `/api/sessions`，只保留显式创建和 bundle 更新

**Files:**
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `tests/runtime/control/test_backend_http_api.py`

- [ ] **Step 1: 先写失败测试，锁定新的 API 契约**

```python
async def test_sessions_api_creates_bundle_and_rejects_agent_id_updates(tmp_path: Path) -> None:
    response = await request_json(
        base_url,
        "/api/sessions",
        method="POST",
        json={"session_id": "qq:group:123456", "title": "Aca Group Session"},
    )
    assert response["session"]["session_id"] == "qq:group:123456"
    assert response["session"]["frontstage_agent_id"]
    assert response["agent"]["agent_id"] == response["session"]["frontstage_agent_id"]
    assert (sessions_root / "qq" / "group" / "123456" / "session.yaml").exists()
    assert (sessions_root / "qq" / "group" / "123456" / "agent.yaml").exists()

    error = await request_json(
        base_url,
        "/api/sessions/qq%3Agroup%3A123456/agent",
        method="PUT",
        json={"agent_id": "renamed"},
        expected_status=400,
    )
    assert "agent_id" in error["error"]
```

- [ ] **Step 2: 跑测试确认 `/api/sessions` 还在 501**

Run: `PYTHONPATH=src pytest tests/runtime/test_webui_api.py tests/runtime/control/test_backend_http_api.py -q -k "sessions or agent"`

Expected: FAIL，原因应包含 `session shell redesign pending` 或旧 `/api/profiles` 路径仍被调用。

- [ ] **Step 3: 最小实现 control plane CRUD**

实现要求：
- `POST /api/sessions` 是唯一正式创建入口
- `POST /api/sessions` 创建时必须一次性写出同目录的 `session.yaml + agent.yaml`
- `frontstage_agent_id` 和 `agent_id` 由 control plane 内部分配并持久化，不由请求 payload 传入
- `GET /api/sessions` 只返回摘要，不内嵌完整 agent 配置
- `GET /api/sessions/{id}` 返回 `session`、`agent`、`paths`
- `PUT /api/sessions/{id}` 只更新 `session.yaml`
- `GET /api/sessions/{id}/agent` / `PUT /api/sessions/{id}/agent` 只读写 `agent.yaml`
- 请求里如果试图修改 `frontstage_agent_id` 或 `agent_id`，直接返回 400
- 缺少 bundle 时返回 404，不偷偷创建

- [ ] **Step 4: 跑 API 套件**

Run: `PYTHONPATH=src pytest tests/runtime/test_webui_api.py tests/runtime/control/test_backend_http_api.py -q -k "sessions or session_bundle or agent"`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add \
  src/acabot/runtime/control/config_control_plane.py \
  src/acabot/runtime/control/control_plane.py \
  src/acabot/runtime/control/http_api.py \
  tests/runtime/test_webui_api.py \
  tests/runtime/control/test_backend_http_api.py
git commit -m "feat: add session-owned agent control plane api"
```

## Task 5: 删干净旧前台 profile 入口、fixtures 和文档

**Files:**
- Create: `tests/runtime/test_session_agent_loader.py`
- Create: `tests/runtime/fixtures/sessions/qq/group/123456/session.yaml`
- Create: `tests/runtime/fixtures/sessions/qq/group/123456/agent.yaml`
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `docs/00-ai-entry.md`
- Modify: `docs/04-routing-and-profiles.md`
- Modify: `docs/21-run-mechanism.md`
- Modify: `docs/27-session-owned-agent.md`
- Delete: `tests/runtime/test_profile_loader.py`

- [ ] **Step 1: 把旧测试先换成新 fixture 形状**

```python
def test_session_agent_loader_rejects_mismatched_internal_ids(tmp_path: Path) -> None:
    ...
```

- [ ] **Step 2: 删除旧前台 profile 断言，补齐 docs**

实现要求：
- `tests/runtime/test_profile_loader.py` 删除，用 `tests/runtime/test_session_agent_loader.py` 顶上
- `tests/runtime/test_webui_api.py` 不再断言 `/api/profiles`、`upsert_profile()`、`delete_profile()`
- 文档里的前台正式描述改成 `session-owned agent`
- 不去改历史归档 spec / plan，只清理当前正式实现文档

- [ ] **Step 3: 跑最终 targeted suite 和 grep 守门**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_bundle_loader.py tests/runtime/test_session_runtime.py tests/runtime/test_app.py tests/runtime/test_bootstrap.py tests/runtime/test_control_plane.py tests/runtime/test_webui_api.py -q`

Expected: PASS

Run: `rg -n "frontstage_profile|/api/profiles|AgentProfileRegistry|profile_loader|ctx\\.profile" src/acabot/runtime tests docs --glob '!docs/superpowers/**' --glob '!.planning/**'`

Expected: 没有命中当前正式实现文件；如果只剩历史注释或归档材料，继续补清理直到当前实现面干净。

- [ ] **Step 4: Commit**

```bash
git add \
  tests/runtime/test_session_agent_loader.py \
  tests/runtime/fixtures/sessions/qq/group/123456/session.yaml \
  tests/runtime/fixtures/sessions/qq/group/123456/agent.yaml \
  tests/runtime/test_webui_api.py \
  docs/00-ai-entry.md \
  docs/04-routing-and-profiles.md \
  docs/21-run-mechanism.md \
  docs/27-session-owned-agent.md
git rm tests/runtime/test_profile_loader.py
git commit -m "docs: remove frontstage profile semantics"
```

## Verification

在声明整个计划执行完成之前，必须至少完成这些检查：

- [ ] `PYTHONPATH=src pytest tests/runtime/test_session_bundle_loader.py tests/runtime/test_session_runtime.py tests/runtime/test_app.py -q`
- [ ] `PYTHONPATH=src pytest tests/runtime/test_bootstrap.py tests/runtime/test_control_plane.py tests/runtime/test_webui_api.py -q -k "session or agent"`
- [ ] `PYTHONPATH=src pytest tests/runtime/test_model_targets.py tests/runtime/test_model_registry.py tests/runtime/test_subagent_execution.py -q`
- [ ] `rg -n "frontstage_profile|/api/profiles|AgentProfileRegistry|profile_loader|ctx\\.profile" src/acabot/runtime tests docs --glob '!docs/superpowers/**' --glob '!.planning/**'`
- [ ] 手工确认未配置 session 的消息路径是 `silent_drop`，而不是异常或隐式创建

## Success Criteria

- 所有前台正式真源都来自 `sessions/<platform>/<scope>/<id>/session.yaml + agent.yaml`
- runtime 不再存在 “`session -> shared profile registry`” 这条前台正式解析链
- `POST/GET/PUT /api/sessions...` 可以创建和维护 session bundle
- 未配置 session 不自动创建、不进入前台执行、不回复消息
- 当前正式实现文件里不再保留前台 `profile` 语义

Plan complete and saved to `docs/superpowers/plans/2026-03-30-session-owned-agent-frontstage-hard-cut.md`. Ready to execute?
