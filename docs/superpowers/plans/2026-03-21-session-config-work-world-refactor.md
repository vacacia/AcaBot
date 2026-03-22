# Session Config + Work World Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `docs/22`、`docs/23`、`docs/24` 里的新主线替换当前的 rule-driven 路由 / computer 接线：消息先变成 Facts，再命中 Session Config 和 surface，再产出 domain decisions，最后构造 Work World 并让 tool/shell/attachments 围绕同一套世界工作。

**Architecture:** 先引入新的运行时契约和会话配置解析层，再把 router/app 切到 session-driven 决策主线，随后把 `computer` 提升成 Work World runtime，把 `/workspace /skills /self`、附件 staging、file tools、shell execution view 接到同一套 world input bundle。收尾阶段清理旧的 rule / override 接口和控制面暴露。

**Tech Stack:** Python runtime、YAML session config、pytest、现有 `RuntimeApp` / `ComputerRuntime` / `ToolBroker`。

---

## File Structure Map

### New runtime contracts
- Create: `src/acabot/runtime/contracts/session_config.py`
  - `EventFacts`
  - `MatchSpec`
  - `SessionLocatorResult`
  - `SurfaceResolution`
  - `RoutingDecision`
  - `AdmissionDecision`
  - `ContextDecision`
  - `PersistenceDecision`
  - `ExtractionDecision`
  - `ComputerPolicyDecision`
  - `SessionConfig` / `SurfaceConfig` / domain case dataclasses
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/__init__.py`

### Session config loading and decision engine
- Create: `src/acabot/runtime/control/session_loader.py`
  - load templates / sessions / selectors
  - parse YAML into `SessionConfig`
- Create: `src/acabot/runtime/control/session_runtime.py`
  - build `EventFacts`
  - locate session config
  - resolve surface
  - compute domain decisions
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/config.py`
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/router.py`
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/contracts/context.py`

### Work World runtime
- Create: `src/acabot/runtime/computer/world.py`
  - `WorldInputBundle`
  - `WorldView`
  - `ResolvedWorldPath`
  - path resolver / builder
- Modify: `src/acabot/runtime/computer/contracts.py`
- Modify: `src/acabot/runtime/computer/workspace.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/plugins/computer_tool_adapter.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`

### Cleanup and operator surface
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/workspace_ops.py`
- Modify: `src/acabot/runtime/plugins/ops_control.py`
- Modify: `src/acabot/runtime/control/profile_loader.py`
- Modify: `src/acabot/runtime/control/event_policy.py`

### Tests
- Create: `tests/runtime/test_session_config_models.py`
- Create: `tests/runtime/test_session_runtime.py`
- Create: `tests/runtime/test_runtime_app_session_config.py`
- Create: `tests/runtime/test_work_world.py`
- Modify: `tests/runtime/test_computer.py`
- Modify: `tests/runtime/test_computer_tool_adapter.py`
- Modify: `tests/runtime/test_control_plane.py`

### Docs to sync after code lands
- Modify: `docs/04-routing-and-profiles.md`
- Modify: `docs/09-config-and-runtime-files.md`
- Modify: `docs/12-computer.md`

---

## Task 1: Add the new session/runtime contracts

**Files:**
- Create: `src/acabot/runtime/contracts/session_config.py`
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/__init__.py`
- Test: `tests/runtime/test_session_config_models.py`

- [ ] **Step 1: Write the failing contract tests**

```python
def test_match_spec_specificity_counts_declared_fields():
    spec = MatchSpec(scene="group", mentions_self=True, sender_roles=["admin"])
    assert spec.specificity() == 3


def test_surface_config_keeps_domain_defaults_and_cases():
    session = SessionConfig(
        session_id="qq:group:123",
        template_id="qq_group",
        surfaces={
            "message.mention": SurfaceConfig(
                routing=RoutingDomainConfig(default={"profile": "aca.default"}, cases=[]),
                admission=AdmissionDomainConfig(default={"mode": "respond"}, cases=[]),
            )
        },
    )
    assert "message.mention" in session.surfaces
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_config_models.py -v`
Expected: FAIL because `session_config.py` and exports do not exist yet.

- [ ] **Step 3: Write minimal contract models**

Implement dataclasses for:
- `EventFacts`
- `MatchSpec`
- `SessionLocatorResult`
- `SurfaceResolution`
- all domain decisions
- `SessionConfig` / `SurfaceConfig` / domain config + case models

Keep methods minimal:
- `MatchSpec.matches(facts)`
- `MatchSpec.specificity()`
- decision `to_metadata()` only if runtime currently needs metadata bridging

- [ ] **Step 4: Re-run the contract tests**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_config_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/contracts/session_config.py src/acabot/runtime/contracts/__init__.py src/acabot/runtime/__init__.py tests/runtime/test_session_config_models.py
git commit -m "feat: add session config runtime contracts"
```

---

## Task 2: Load session configs and resolve facts / surfaces / domain decisions

**Files:**
- Create: `src/acabot/runtime/control/session_loader.py`
- Create: `src/acabot/runtime/control/session_runtime.py`
- Modify: `src/acabot/runtime/bootstrap/config.py`
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Test: `tests/runtime/test_session_runtime.py`

- [ ] **Step 1: Write failing tests for loading and resolution**

```python
def test_session_loader_reads_surface_matrix_and_selectors(tmp_path: Path):
    config_path = tmp_path / "sessions/qq/group/123.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
        session:
          id: qq:group:123
          template: qq_group
        selectors:
          sender_is_admin:
            sender_roles: [admin]
        surfaces:
          message.mention:
            computer:
              default:
                preset: sandbox_member
              cases:
                - case_id: admin_host
                  when_ref: sender_is_admin
                  use:
                    preset: host_operator
        """,
        encoding="utf-8",
    )
    loader = SessionConfigLoader(config_root=tmp_path / "sessions")
    session = loader.load_by_session_id("qq:group:123")
    assert session.surfaces["message.mention"].computer.cases[0].use["preset"] == "host_operator"


def test_session_runtime_builds_facts_and_resolves_surface(tmp_path: Path):
    runtime = build_test_session_runtime(tmp_path)
    facts = runtime.build_facts(make_group_mention_event(sender_role="admin"))
    surface = runtime.resolve_surface(facts, runtime.load_session(facts))
    assert surface.surface_id == "message.mention"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_runtime.py -v`
Expected: FAIL because loader/runtime do not exist.

- [ ] **Step 3: Implement the loader and resolution engine**

Implement in `session_loader.py`:
- session path mapping from canonical `session_id`
- YAML parsing for selectors, surfaces, defaults, cases
- template id retention

Implement in `session_runtime.py`:
- `build_facts(StandardEvent) -> EventFacts`
- `locate_session(facts) -> SessionLocatorResult`
- `load_session(facts) -> SessionConfig`
- `resolve_surface(facts, session) -> SurfaceResolution`
- `resolve_routing/admission/persistence/extraction/computer`

First implementation scope:
- support current QQ private/group message flows
- support `message.mention`, `message.reply_to_bot`, `message.plain`, `notice.*` enough for tests
- use one shared `MatchSpec`

- [ ] **Step 4: Re-run the session runtime tests**

Run: `PYTHONPATH=src pytest tests/runtime/test_session_runtime.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/session_loader.py src/acabot/runtime/control/session_runtime.py src/acabot/runtime/bootstrap/config.py src/acabot/runtime/bootstrap/loaders.py src/acabot/runtime/bootstrap/builders.py tests/runtime/test_session_runtime.py
git commit -m "feat: add session config loader and decision engine"
```

---

## Task 3: Cut router and app over to session-driven decisions

**Files:**
- Modify: `src/acabot/runtime/router.py`
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/contracts/context.py`
- Test: `tests/runtime/test_runtime_app_session_config.py`

- [ ] **Step 1: Write a failing integration test for RuntimeApp**

```python
async def test_runtime_app_uses_session_config_for_profile_and_run_mode(tmp_path: Path):
    app = build_runtime_app_with_session_config(tmp_path)
    event = make_group_mention_event(sender_role="admin")

    await app.handle_event(event)

    run = await app.run_manager.last()
    assert run.agent_id == "aca.qq.group.default"
    assert run.decision_metadata["admission_mode"] == "respond"
    assert run.decision_metadata["surface_id"] == "message.mention"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src pytest tests/runtime/test_runtime_app_session_config.py -v`
Expected: FAIL because router/app still resolve through legacy rules.

- [ ] **Step 3: Implement the cutover**

In `router.py`:
- keep canonical id builders if still useful
- replace legacy `InboundRuleRegistry` use with session runtime decisions
- produce metadata from:
  - `surface_id`
  - `routing source`
  - `admission mode`
  - `persistence / extraction` decisions

In `app.py`:
- load profile from `RoutingDecision.profile_id`
- populate `RunContext` with facts / surface / domain decision bundle
- remove thread-level agent override application from the main path

In `context.py`:
- add fields for `event_facts`, `surface_resolution`, `routing_decision`, `admission_decision`, `persistence_decision`, `extraction_decision`, `computer_policy_decision`

- [ ] **Step 4: Re-run the integration test**

Run: `PYTHONPATH=src pytest tests/runtime/test_runtime_app_session_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/router.py src/acabot/runtime/app.py src/acabot/runtime/contracts/context.py tests/runtime/test_runtime_app_session_config.py
git commit -m "refactor: route runtime app through session config decisions"
```

---

## Task 4: Build Work World contracts and resolver

**Files:**
- Create: `src/acabot/runtime/computer/world.py`
- Modify: `src/acabot/runtime/computer/contracts.py`
- Modify: `src/acabot/runtime/computer/workspace.py`
- Test: `tests/runtime/test_work_world.py`

- [ ] **Step 1: Write failing Work World tests**

```python
def test_frontstage_world_exposes_workspace_skills_and_self(tmp_path: Path):
    bundle = make_world_input_bundle(actor_kind="frontstage_agent")
    world = WorkWorldBuilder(tmp_path).build(bundle)
    assert world.resolve("/workspace/out.txt").root_kind == "workspace"
    assert world.resolve("/skills/sample/SKILL.md").root_kind == "skills"
    assert world.resolve("/self/note.md").root_kind == "self"


def test_subagent_world_hides_self(tmp_path: Path):
    bundle = make_world_input_bundle(actor_kind="subagent")
    world = WorkWorldBuilder(tmp_path).build(bundle)
    with pytest.raises(FileNotFoundError):
        world.resolve("/self/note.md")
```

- [ ] **Step 2: Run the Work World tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/runtime/test_work_world.py -v`
Expected: FAIL because Work World builder/resolver does not exist.

- [ ] **Step 3: Implement minimal Work World builder**

In `computer/contracts.py` add:
- `WorldRootPolicy`
- `ResolvedWorldPath`
- `WorldView`
- `ExecutionView`
- `WorldInputBundle`

In `computer/world.py` implement:
- root visibility rules for `/workspace`, `/skills`, `/self`
- `WorldView.resolve(world_path)`
- host path mapping via `WorkspaceManager`
- execution view path generation

In `workspace.py` keep filesystem helpers but expose:
- workspace dir
- skills dir
- self dir
- thread-safe host path helpers

- [ ] **Step 4: Re-run the Work World tests**

Run: `PYTHONPATH=src pytest tests/runtime/test_work_world.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/computer/world.py src/acabot/runtime/computer/contracts.py src/acabot/runtime/computer/workspace.py tests/runtime/test_work_world.py
git commit -m "feat: add work world builder and path resolver"
```

---

## Task 5: Move ComputerRuntime, attachments, tools, and shell onto Work World

**Files:**
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/plugins/computer_tool_adapter.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `tests/runtime/test_computer.py`
- Modify: `tests/runtime/test_computer_tool_adapter.py`

- [ ] **Step 1: Write failing runtime/tool tests**

Add tests covering:
- `prepare_run_context()` produces a `world_view`
- inbound attachments stage into `/workspace/attachments/...`
- `read/write/ls/grep` accept world paths
- `exec` and `bash_open` use execution view rooted in the world

Example skeleton:

```python
async def test_prepare_run_context_builds_world_view(tmp_path: Path):
    runtime, ctx = build_computer_ctx(tmp_path, actor_kind="frontstage_agent")
    await runtime.prepare_run_context(ctx)
    assert ctx.world_view is not None
    assert ctx.world_view.resolve("/workspace").world_path == "/workspace"

async def test_tool_adapter_reads_by_world_path(tmp_path: Path):
    plugin, ctx = build_tool_adapter_ctx(tmp_path)
    result = await plugin._read({"path": "/workspace/demo.txt"}, ctx)
    assert "demo" in result.llm_content
```

- [ ] **Step 2: Run the affected tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/runtime/test_computer.py tests/runtime/test_computer_tool_adapter.py -v`
Expected: FAIL because runtime/tools still operate on legacy workspace-only paths.

- [ ] **Step 3: Implement minimal cutover**

In `computer/runtime.py`:
- derive `WorldInputBundle` from `RunContext`
- build and store `ctx.world_view`
- stage attachments with world paths in snapshots / metadata
- route file operations through `world.resolve()`
- keep backend choice driven by `ComputerPolicyDecision`

In `computer_tool_adapter.py`:
- accept only world paths for file tools
- resolve through `ComputerRuntime`
- stop mirroring ad-hoc path semantics inside the plugin

In `tool_broker/broker.py`:
- project `world_view` / actor kind / policy summary into tool execution context when needed

- [ ] **Step 4: Re-run the computer tests**

Run: `PYTHONPATH=src pytest tests/runtime/test_computer.py tests/runtime/test_computer_tool_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/computer/runtime.py src/acabot/runtime/plugins/computer_tool_adapter.py src/acabot/runtime/tool_broker/broker.py tests/runtime/test_computer.py tests/runtime/test_computer_tool_adapter.py
git commit -m "refactor: run computer tools and attachments through work world"
```

---

## Task 6: Clean control plane surfaces and retire legacy rule/override paths

**Files:**
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/workspace_ops.py`
- Modify: `src/acabot/runtime/plugins/ops_control.py`
- Modify: `src/acabot/runtime/control/profile_loader.py`
- Modify: `src/acabot/runtime/control/event_policy.py`
- Modify: `tests/runtime/test_control_plane.py`

- [ ] **Step 1: Write failing cleanup tests**

Add tests covering:
- control plane reports session-config-driven profile/computer state
- workspace ops continue to support pruning / sandbox stop / listing
- agent/computer switching commands are no longer tied to thread metadata overrides

Example skeleton:

```python
async def test_control_plane_reports_surface_and_profile_from_session_config(tmp_path: Path):
    control_plane = build_control_plane_with_session_config(tmp_path)
    status = await control_plane.get_status()
    assert status.active_runs[0].agent_id == "aca.qq.group.default"
```

- [ ] **Step 2: Run the control plane tests to verify they fail**

Run: `PYTHONPATH=src pytest tests/runtime/test_control_plane.py -v`
Expected: FAIL because control plane still references legacy override flows.

- [ ] **Step 3: Implement cleanup**

- remove legacy rule registries from active bootstrap path
- retire `thread_agent_override` / `computer_override` handling from runtime mainline
- keep workspace operational commands that manipulate current runtime state:
  - list workspaces
  - read files
  - prune workspace
  - stop sandbox
- make status/reporting surface session-driven decisions instead of override metadata

- [ ] **Step 4: Re-run the control plane tests**

Run: `PYTHONPATH=src pytest tests/runtime/test_control_plane.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/workspace_ops.py src/acabot/runtime/plugins/ops_control.py src/acabot/runtime/control/profile_loader.py src/acabot/runtime/control/event_policy.py tests/runtime/test_control_plane.py
git commit -m "refactor: clean control plane after session config cutover"
```

---

## Task 7: Update docs and run the verification suite

**Files:**
- Modify: `docs/04-routing-and-profiles.md`
- Modify: `docs/09-config-and-runtime-files.md`
- Modify: `docs/12-computer.md`

- [ ] **Step 1: Update the docs to match the shipped runtime**

Document:
- Session Config as the primary config source
- surface matrix and per-domain `default + cases`
- Work World roots `/workspace /skills /self`
- attachment staging into `/workspace/attachments/...`

- [ ] **Step 2: Run focused verification first**

Run:

```bash
PYTHONPATH=src pytest \
  tests/runtime/test_session_config_models.py \
  tests/runtime/test_session_runtime.py \
  tests/runtime/test_runtime_app_session_config.py \
  tests/runtime/test_work_world.py \
  tests/runtime/test_computer.py \
  tests/runtime/test_computer_tool_adapter.py \
  tests/runtime/test_control_plane.py -v
```

Expected: all PASS.

- [ ] **Step 3: Run the broader runtime suite**

Run: `PYTHONPATH=src pytest tests/runtime -v`
Expected: PASS, or only pre-existing unrelated failures.

- [ ] **Step 4: Commit docs + verification state**

```bash
git add docs/04-routing-and-profiles.md docs/09-config-and-runtime-files.md docs/12-computer.md
git commit -m "docs: document session config and work world runtime"
```

---

## Execution Notes

- Execute in an isolated git worktree before touching production files.
- Follow strict TDD for each task: write the failing test, verify the failure, implement the minimum code, re-run, then commit.
- Keep the cutover vertical: by the end of Task 3 the runtime should already be able to route through Session Config even if some legacy loaders still exist in tree.
- Keep the Work World cutover equally vertical: by the end of Task 5 the main file tools and attachments should already be using world paths even if some secondary helper APIs still need cleanup.

Plan complete and saved to `docs/superpowers/plans/2026-03-21-session-config-work-world-refactor.md`. Ready to execute?
