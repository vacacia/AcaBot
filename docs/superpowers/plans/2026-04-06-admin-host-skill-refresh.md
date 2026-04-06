# Admin Host Skill Refresh Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make QQ group frontstage runs route by bot-config admins (`admin_actor_ids`) instead of QQ sender roles, and add a narrow `refresh_extensions(kind="skills")` path so admin host runs can install skills into the real catalog root and make them available to later runs.

**Architecture:** Extend the session matcher contract with a dedicated `is_bot_admin` fact, wire that fact from the shared runtime admin config into `SessionRuntime`, and seed QQ group surfaces/defaults with declarative `computer.default + cases` rules. Add a small extension refresh service shared by a builtin tool and loopback HTTP endpoint; the refresh path reloads the skill catalog, rewrites the target session agent `visible_skills`, and invalidates loader snapshots so later runs see the new skills.

**Tech Stack:** Python, pytest, existing `SessionRuntime` / `RuntimeConfigControlPlane` / `RuntimeControlPlane`, builtin tool registration, local HTTP API.

---

## File Structure

- Create: `src/acabot/runtime/control/session_defaults.py` — canonical QQ session default surfaces plus QQ group tool baseline helpers
- Create: `src/acabot/runtime/control/extension_refresh.py` — shared refresh service for skill catalog reload + `visible_skills` rewrite + loader invalidation, plus host-maintenance path summary helper
- Create: `src/acabot/runtime/builtin_tools/extensions.py` — builtin `refresh_extensions` tool surface and execution-time auth
- Modify: `src/acabot/runtime/contracts/session_config.py` — add `is_bot_admin` to `EventFacts` / `MatchSpec`
- Modify: `src/acabot/runtime/control/session_loader.py` — parse `is_bot_admin` from YAML selectors/cases
- Modify: `src/acabot/runtime/control/session_runtime.py` — compute `is_bot_admin`, expose admin-set update hook, keep computer policy resolution declarative
- Modify: `src/acabot/runtime/bootstrap/loaders.py` — pass shared admin actor IDs into `SessionRuntime`
- Modify: `src/acabot/runtime/bootstrap/__init__.py` — instantiate refresh service/tool wiring before session bundle validation, bind late control-plane/tool-broker references
- Modify: `src/acabot/runtime/builtin_tools/__init__.py` — register builtin extensions tool surface
- Modify: `src/acabot/runtime/control/config_control_plane.py` — seed new `qq_group` session defaults, expose refresh core helpers, refresh session runtime on config/admin reloads
- Modify: `src/acabot/runtime/control/control_plane.py` — add wrapper method(s) for refresh, keep admin updates in sync with runtime session facts
- Modify: `src/acabot/runtime/control/http_api.py` — add loopback-only `POST /api/runtime/refresh-extensions`
- Modify: `runtime_config/sessions/qq/group/1039173249/session.yaml` — add bot-admin-aware computer cases
- Modify: `runtime_config/sessions/qq/group/1039173249/agent.yaml` — append `refresh_extensions` only after the builtin tool is registered in the same implementation slice
- Modify: `runtime_config/sessions/qq/group/1097619430/session.yaml` — add bot-admin-aware computer cases
- Modify: `runtime_config/sessions/qq/group/1097619430/agent.yaml` — append `refresh_extensions` only after the builtin tool is registered in the same implementation slice
- Modify: `runtime_config/sessions/qq/group/742824007/session.yaml` — add bot-admin-aware computer cases
- Modify: `runtime_config/sessions/qq/group/742824007/agent.yaml` — append `refresh_extensions` only after the builtin tool is registered in the same implementation slice
- Modify: `tests/runtime/test_session_config_models.py` — matcher contract coverage for `is_bot_admin`
- Modify: `tests/runtime/test_session_runtime.py` — fact-building + QQ group computer case resolution coverage
- Create: `tests/runtime/test_extension_refresh.py` — refresh core tests for catalog reload + `visible_skills` rewrite + loader invalidation
- Modify: `src/acabot/runtime/tool_broker/broker.py` — attach admin-host maintenance metadata into `ToolRuntime` for the assembler
- Modify: `src/acabot/runtime/context_assembly/assembler.py` — inject admin-host maintenance guidance only for admin+host runs
- Create: `src/acabot/runtime/context_assembly/prompts/admin_host_maintenance_reminder.md` — run-scoped host maintenance reminder template
- Modify: `tests/runtime/test_context_assembler.py` — positive/negative guidance injection coverage
- Modify: `tests/runtime/test_builtin_tools.py` — builtin tool registration + auth + delegation coverage
- Modify: `tests/runtime/test_webui_api.py` — `create_session()` defaults, admin-update propagation, QQ group tool-baseline seeding, and HTTP refresh endpoint coverage

## Task 1: Extend session matcher contracts with `is_bot_admin`

**Files:**
- Modify: `src/acabot/runtime/contracts/session_config.py`
- Modify: `src/acabot/runtime/control/session_loader.py`
- Modify: `tests/runtime/test_session_config_models.py`

- [ ] **Step 1: Write the failing matcher/model tests**

Add tests that prove:
- `MatchSpec(is_bot_admin=True)` matches only facts with `is_bot_admin=True`
- `specificity()` counts the new field
- YAML-loaded selectors/cases preserve `is_bot_admin: true`

Suggested test shape:

```python
facts = EventFacts(actor_id="qq:user:1", is_bot_admin=True)
assert MatchSpec(is_bot_admin=True).matches(facts)
assert not MatchSpec(is_bot_admin=False).matches(facts)
assert MatchSpec(scene="group", is_bot_admin=True).specificity() == 2
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_session_config_models.py tests/runtime/test_session_runtime.py -q
```

Expected: failures mentioning unexpected `is_bot_admin` field / YAML loader not preserving the new matcher key.

- [ ] **Step 3: Implement the contract + loader changes**

Make these minimal changes:
- add `is_bot_admin: bool = False` to `EventFacts`
- add `is_bot_admin: bool | None = None` to `MatchSpec`
- in `MatchSpec.matches()`, require equality when the field is declared
- in `match_keys()`, include `is_bot_admin`
- in `SessionConfigLoader._load_match_spec(...)`, parse `is_bot_admin`

Target YAML shape to support:

```yaml
selectors:
  bot_admin:
    is_bot_admin: true
```

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_session_config_models.py tests/runtime/test_session_runtime.py -q
```

Expected: PASS for the new matcher/model coverage.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/contracts/session_config.py src/acabot/runtime/control/session_loader.py tests/runtime/test_session_config_models.py tests/runtime/test_session_runtime.py
git commit -m "feat: add bot admin session matcher facts"
```

## Task 2: Wire shared admin config into `SessionRuntime`

**Files:**
- Modify: `src/acabot/runtime/control/session_runtime.py`
- Modify: `src/acabot/runtime/bootstrap/loaders.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `tests/runtime/test_session_runtime.py`
- Modify: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Write the failing runtime/admin-propagation tests**

Add tests that prove:
- `SessionRuntime.build_facts()` marks `is_bot_admin=True` when `actor_id` is in the shared admin set
- the same QQ group surface resolves `host` for bot admins and `docker` for non-admins, regardless of QQ `sender_role`
- updating admins through the control plane refreshes later session decisions without a full restart

Suggested test shape:

```python
runtime = SessionRuntime(loader, shared_admin_actor_ids={"qq:user:10001"})
facts = runtime.build_facts(event)
assert facts.is_bot_admin is True
assert runtime.resolve_computer(...).backend == "host"
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_session_runtime.py tests/runtime/test_webui_api.py -k "bot_admin or admins" -q
```

Expected: failures showing `SessionRuntime` cannot accept/update shared admin IDs yet, or admin updates do not affect session routing.

- [ ] **Step 3: Implement minimal runtime wiring**

Implement one small path only:
- update `SessionRuntime` constructor to accept `shared_admin_actor_ids: set[str] | None = None`
- compute `is_bot_admin = actor_id in self._shared_admin_actor_ids` inside `build_facts()`
- add a tiny setter like `set_shared_admin_actor_ids()` so runtime admin updates do not require object replacement everywhere
- in `bootstrap/loaders.py` and `config_control_plane.py`, build `SessionRuntime` with the same `runtime.backend.admin_actor_ids` source already used for backend mode
- in `RuntimeControlPlane.put_admins()` and reload paths, update both:
  - `self.app.backend_admin_actor_ids`
  - `self.app.router.session_runtime` shared admin set (or replace the runtime via existing rebind path)

Do **not** overload `sender_roles`.

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_session_runtime.py tests/runtime/test_webui_api.py -k "bot_admin or admins" -q
```

Expected: PASS for build-facts and admin-update propagation.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/session_runtime.py src/acabot/runtime/bootstrap/loaders.py src/acabot/runtime/control/config_control_plane.py src/acabot/runtime/control/control_plane.py tests/runtime/test_session_runtime.py tests/runtime/test_webui_api.py
git commit -m "feat: wire shared bot admins into session runtime"
```

## Task 3: Seed QQ group responding surfaces and checked-in `session.yaml` files

**Files:**
- Create: `src/acabot/runtime/control/session_defaults.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `runtime_config/sessions/qq/group/1039173249/session.yaml`
- Modify: `runtime_config/sessions/qq/group/1097619430/session.yaml`
- Modify: `runtime_config/sessions/qq/group/742824007/session.yaml`
- Modify: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Write the failing defaults tests**

Add tests that prove a newly created `qq_group` session gets this exact responding-surface shape:
- `message.mention.admission.default.mode == "respond"`
- `message.reply_to_bot.admission.default.mode == "respond"`
- `message.plain.admission.default.mode == "record_only"`
- each of those three surfaces has `computer.default.backend == "docker"`
- each of those three surfaces has the same `is_bot_admin: true -> backend: host` case
- no dependence on QQ `sender_roles`
- the generated `agent.yaml` does **not** retain a static host default such as `computer_policy.backend: host`

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_webui_api.py -k "create_session and qq_group" -q
```

Expected: failures showing new group sessions still have no bot-admin-aware computer cases.

- [ ] **Step 3: Implement seeded surface defaults in one helper module**

Create `session_defaults.py` with a focused helper such as:
- `build_default_qq_group_surfaces()`

Pin that helper to one explicit output shape for new `qq_group` bundles:

```python
{
    "message.mention": {"admission": {"default": {"mode": "respond"}}, ...},
    "message.reply_to_bot": {"admission": {"default": {"mode": "respond"}}, ...},
    "message.plain": {"admission": {"default": {"mode": "record_only"}}, ...},
}
```

Then update `RuntimeConfigControlPlane.create_session()` so when:
- `template_id == "qq_group"`
- and caller did not provide explicit `surfaces`

it seeds the default responding surfaces.

In the same implementation slice, ensure new `qq_group` agent output does **not** preserve the old static host default from bootstrap agent `computer_policy`. For this template, the execution decision must come from `session.yaml` responding-surface computer cases rather than an agent-level `backend: host` default.

Update checked-in group `session.yaml` files to add only the new `computer` blocks on:
- `message.mention`
- `message.reply_to_bot`
- `message.plain`

Each responding surface keeps its current `admission` behavior exactly as-is, and only gains a `computer` block shaped like:

```yaml
computer:
  default:
    backend: docker
    allow_exec: true
    allow_sessions: true
  cases:
    - case_id: bot_admin_host
      when:
        is_bot_admin: true
      use:
        backend: host
        allow_exec: true
        allow_sessions: true
```

Do **not** replace whole surface blocks, and do **not** touch `agent.yaml.visible_tools` in this task; that waits until the builtin tool exists.

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_webui_api.py -k "create_session and qq_group" -q
```

Expected: PASS for seeded QQ group surface defaults.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/session_defaults.py src/acabot/runtime/control/config_control_plane.py runtime_config/sessions/qq/group/1039173249/session.yaml runtime_config/sessions/qq/group/1097619430/session.yaml runtime_config/sessions/qq/group/742824007/session.yaml tests/runtime/test_webui_api.py
git commit -m "feat: seed qq group bot-admin computer cases"
```

## Task 4: Build the shared extension refresh service

**Files:**
- Create: `src/acabot/runtime/control/extension_refresh.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/session_bundle_loader.py` (only if a tiny helper is needed for cache invalidation; otherwise avoid)
- Create: `tests/runtime/test_extension_refresh.py`

- [ ] **Step 1: Write the failing refresh-core tests**

Cover the real behavior only:
- refresh rejects when no unique project-scope skill root exists
- refresh reloads the skill catalog using the same resolver semantics as runtime discovery
- refresh rewrites `agent.yaml.visible_skills` to the full discovered winner set (stable + deduped)
- refresh drops removed/stale skill names
- refresh can recover from a session whose current `agent.yaml.visible_skills` is stale/invalid against the old catalog snapshot
- session bundle loader uses the refreshed skill-name snapshot immediately after the rewrite

Suggested test shape:

```python
result = await service.refresh_skills(session_id="qq:group:123")
assert result["kind"] == "skills"
assert result["changed"] is True
assert yaml.safe_load(agent_yaml.read_text())["visible_skills"] == ["demo-skill"]
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_extension_refresh.py -q
```

Expected: import/module-not-found or missing refresh behavior failures.

- [ ] **Step 3: Implement the minimal refresh core**

Create a focused service object that owns only:
- resolve the runtime skill roots with the same resolver semantics as `resolve_skill_catalog_dirs()`
- select the single writable `project` root, or fail clearly
- resolve the target session paths directly from `session_id` / session-dir helpers, **not** by validated `SessionBundleLoader.load_by_session_id()`
- reload the live `SkillCatalog`
- compute the effective winner set by skill name
- rewrite the target session agent `visible_skills` by editing `agent.yaml` on disk first
- call existing config-control-plane/session-bundle-loader refresh hooks so that **after** the rewrite:
  - bundle catalog snapshots are replaced
  - cached bundles are invalidated
  - validated bundle loading works again even if the old file was stale/invalid
- expose a tiny read-only helper that reports the resolved writable project skill root and target `agent.yaml` path for a given `session_id`

Keep this service independent from HTTP/tool auth. It should accept an explicit `session_id` and return a structured summary.

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_extension_refresh.py -q
```

Expected: PASS for root resolution, rewrite, and loader invalidation.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/extension_refresh.py src/acabot/runtime/control/config_control_plane.py src/acabot/runtime/control/control_plane.py tests/runtime/test_extension_refresh.py
git commit -m "feat: add session-scoped skill refresh service"
```

## Task 5: Inject admin-host maintenance guidance into the model context

**Files:**
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `src/acabot/runtime/context_assembly/assembler.py`
- Create: `src/acabot/runtime/context_assembly/prompts/admin_host_maintenance_reminder.md`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/control/extension_refresh.py`
- Modify: `tests/runtime/test_context_assembler.py`

- [ ] **Step 1: Write the failing guidance tests**

Add tests that prove:
- **frontstage** admin + host runs receive an extra system reminder that names:
  - the resolved writable project skill root
  - the target `agent.yaml` path
  - the rule that `/skills` is mirrored/read-only and not the install target
- non-frontstage runs (for example subagents) do **not** receive that reminder even if they are host-backed
- normal runs do **not** receive that reminder

Suggested assertion shape:

```python
assert "/skills is mirrored" in assembled.system_prompt
assert str(skill_root) in assembled.system_prompt
assert str(agent_yaml) in assembled.system_prompt
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_context_assembler.py -k "maintenance or host" -q
```

Expected: failures because no admin-host maintenance reminder is injected yet.

- [ ] **Step 3: Implement run-scoped guidance only**

Implement one narrow path:
- add a new prompt template for the maintenance reminder
- teach `ToolBroker.build_tool_runtime()` to attach an `admin_host_maintenance` metadata block only when:
  - the run is **frontstage**
  - `ctx.event_facts.is_bot_admin is True`
  - `ctx.computer_backend_kind == "host"`
- populate that metadata block from the read-only path-summary helper added in Task 4
- teach `ContextAssembler` to append the maintenance reminder only when that metadata block exists

Do **not** weaken the default `/workspace` reminder for ordinary runs, and do **not** give the carve-out to subagents or other non-frontstage paths.

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_context_assembler.py -k "maintenance or host" -q
```

Expected: PASS for positive and negative guidance coverage.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/tool_broker/broker.py src/acabot/runtime/context_assembly/assembler.py src/acabot/runtime/context_assembly/prompts/admin_host_maintenance_reminder.md src/acabot/runtime/bootstrap/__init__.py src/acabot/runtime/control/extension_refresh.py tests/runtime/test_context_assembler.py
git commit -m "feat: inject admin host maintenance guidance"
```

## Task 6: Add builtin `refresh_extensions` tool, register it early, then seed QQ group tool baselines

**Files:**
- Create: `src/acabot/runtime/builtin_tools/extensions.py`
- Modify: `src/acabot/runtime/builtin_tools/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `runtime_config/sessions/qq/group/1039173249/agent.yaml`
- Modify: `runtime_config/sessions/qq/group/1097619430/agent.yaml`
- Modify: `runtime_config/sessions/qq/group/742824007/agent.yaml`
- Modify: `tests/runtime/test_builtin_tools.py`
- Modify: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Write the failing builtin-tool and tool-baseline tests**

Add tests that prove:
- `refresh_extensions` is registered as a builtin tool source before session bundle validation
- unsupported `kind` values fail clearly
- execution rejects when any of these are false:
  - current run is not the session-owned frontstage agent
  - `ctx.metadata["backend_kind"] != "host"`
  - `ctx.actor_id` is not the current bot admin actor
- admin host execution delegates to the shared refresh core
- newly created `qq_group` sessions now receive the normal tool baseline plus `refresh_extensions`

Suggested expected tool baseline:

```python
[
    "Skill",
    "ask_backend",
    "bash",
    "delegate_subagent",
    "edit",
    "message",
    "read",
    "sticky_note_append",
    "sticky_note_read",
    "write",
    "refresh_extensions",
]
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_builtin_tools.py tests/runtime/test_webui_api.py -k "refresh_extensions or qq_group" -q
```

Expected: failures because the tool is not registered and QQ group tool baselines do not include it yet.

- [ ] **Step 3: Implement early registration and baseline seeding in the same slice**

Implement `BuiltinExtensionsToolSurface` with a single tool:

```python
ToolSpec(
    name="refresh_extensions",
    parameters={
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["skills"]}},
        "required": ["kind"],
    },
)
```

Then, in the **same task**:
- register the tool name before `SessionBundleLoader` is built
- if the refresh core depends on control-plane objects created later, pass a tiny getter/closure (same pattern as the existing `_control_plane_ref`) instead of delaying tool registration
- extend `session_defaults.py` / `create_session()` QQ group baseline to append `refresh_extensions`
- update the three checked-in QQ group `agent.yaml` files to append `refresh_extensions`

Do not add dynamic visibility gating.

- [ ] **Step 4: Re-run the targeted tests and verify they pass**

Run:
```bash
pytest tests/runtime/test_builtin_tools.py tests/runtime/test_webui_api.py -k "refresh_extensions or qq_group" -q
```

Expected: PASS for registration, auth rejection, delegation, and QQ group tool baselines.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/builtin_tools/extensions.py src/acabot/runtime/builtin_tools/__init__.py src/acabot/runtime/bootstrap/__init__.py src/acabot/runtime/control/config_control_plane.py runtime_config/sessions/qq/group/1039173249/agent.yaml runtime_config/sessions/qq/group/1097619430/agent.yaml runtime_config/sessions/qq/group/742824007/agent.yaml tests/runtime/test_builtin_tools.py tests/runtime/test_webui_api.py
git commit -m "feat: add refresh extensions tool baseline"
```

## Task 7: Add loopback HTTP endpoint and complete verification

**Files:**
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `tests/runtime/test_webui_api.py`
- Re-run: `tests/runtime/test_session_config_models.py`
- Re-run: `tests/runtime/test_session_runtime.py`
- Re-run: `tests/runtime/test_context_assembler.py`
- Re-run: `tests/runtime/test_extension_refresh.py`
- Re-run: `tests/runtime/test_builtin_tools.py`

Before editing checked-in runtime config files in this phase, normalize any root-owned mounted files if needed. Per `.harness/AGENTS.md`, container-mounted permission problems may be fixed with `sudo chown`.

- [ ] **Step 1: Write the failing HTTP/API tests**

Add coverage for:
- `POST /api/runtime/refresh-extensions` requires loopback
- request must include `session_id`
- `kind="skills"` succeeds and returns the structured refresh summary
- unsupported kinds fail with a clear 400

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:
```bash
pytest tests/runtime/test_webui_api.py -k "refresh_extensions or refresh-extensions" -q
```

Expected: 404/not-found or missing-handler failures.

- [ ] **Step 3: Implement the narrow HTTP wrapper**

Add one wrapper path only:
- `RuntimeControlPlane.refresh_extensions(...)`
- `RuntimeHttpApiServer.handle_api_request(...): POST /api/runtime/refresh-extensions`

Auth rules:
- HTTP wrapper: loopback-only, explicit `session_id`
- builtin wrapper remains tool-context auth from Task 6
- both call the same shared refresh core from Task 4

Do not expose broad reload-config semantics here.

- [ ] **Step 4: Run the full focused suite and verify it passes**

Run:
```bash
pytest \
  tests/runtime/test_session_config_models.py \
  tests/runtime/test_session_runtime.py \
  tests/runtime/test_context_assembler.py \
  tests/runtime/test_extension_refresh.py \
  tests/runtime/test_builtin_tools.py \
  tests/runtime/test_webui_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/control/http_api.py src/acabot/runtime/control/control_plane.py tests/runtime/test_webui_api.py
git commit -m "feat: expose loopback extension refresh endpoint"
```

## Final Verification Checklist

- [ ] Run the full focused suite from Task 7 again after any review fixes
- [ ] Manually inspect the three checked-in QQ group bundles to confirm they all use `is_bot_admin: true` instead of `sender_roles`
- [ ] Manually inspect `refresh_extensions` auth to confirm it checks **host + bot admin + session-owned frontstage agent** and does not rely on dynamic tool visibility
- [ ] Manually inspect one assembled admin+host system prompt to confirm it includes the real skill root, target `agent.yaml`, and `/skills` mirrored-view reminder
- [ ] Review `git diff --stat` and `git diff` for scope creep before reporting completion
