# WebUI Self + Sticky Notes + Safe Session Shell Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Vue-based WebUI that exposes `Soul`, `Memory(sticky notes)`, and a first-version Session shell with only three front-end sections: `AI / 消息响应 / 其他`.

**Architecture:** Keep the current Python runtime, HTTP API server, and control plane as the backend shell. Add a shared `soul` source service for file-backed `soul`, add a sticky-note source that can read `readonly` and `editable` content for `user/channel` scopes, then replace the old static frontend with a Vue app built into `src/acabot/webui`. `MemoryBroker` is treated as retrieval-rule orchestration only; each memory type manages its own source. `soul` is required to behave as “every run always hits”, regardless of whether it physically passes through `MemoryBroker`. Session front-end stays product-shaped (`AI / 消息响应 / 其他`), and backend maps those fields into current runtime truth sources.

**Tech Stack:** Python runtime/control plane, file-backed soul source, sticky-note source with `user/channel` scope support, Vue 3, Vite, TypeScript, pytest

---

## File Structure

**Create:**

- `src/acabot/runtime/soul/source.py`
  - File-backed source for `.acabot-runtime/soul/`
  - Owns allowed filenames, path normalization, list/read/write helpers, and `task.md`
- `src/acabot/runtime/soul/__init__.py`
  - Expose `SoulSource`
- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
  - Sticky-note source for `user/channel` scopes
  - Owns scope selection, note-key enumeration, readonly/editable reads, and write helpers
- `src/acabot/runtime/memory/file_backed/__init__.py`
  - Expose `StickyNotesSource`
- `webui/package.json`
  - Vue/Vite workspace metadata and scripts
- `webui/tsconfig.json`
  - TypeScript config for the frontend
- `webui/vite.config.ts`
  - Build config that emits static assets into `src/acabot/webui`
- `webui/index.html`
  - Vite entry HTML
- `webui/src/main.ts`
  - Vue bootstrap
- `webui/src/App.vue`
  - App shell and top-level layout
- `webui/src/router.ts`
  - Client-side routing
- `webui/src/lib/api.ts`
  - Shared HTTP client for `/api/*`
- `webui/src/views/HomeView.vue`
- `webui/src/views/SoulView.vue`
- `webui/src/views/MemoryView.vue`
- `webui/src/views/BotView.vue`
- `webui/src/views/ModelsView.vue`
- `webui/src/views/PromptsView.vue`
- `webui/src/views/PluginsView.vue`
- `webui/src/views/SkillsView.vue`
- `webui/src/views/SubagentsView.vue`
- `webui/src/views/SessionsView.vue`
- `webui/src/views/SystemView.vue`
- `webui/src/components/AppSidebar.vue`
- `webui/src/components/FileEditorPane.vue`
- `webui/src/components/StickyNotePane.vue`
- `webui/src/components/StatusCard.vue`

**Modify:**

- `src/acabot/runtime/bootstrap/__init__.py`
  - Construct and pass the new `SoulSource` and `StickyNotesSource`
- `src/acabot/runtime/bootstrap/components.py`
  - Add `soul_source` and `sticky_notes_source` to `RuntimeComponents`
- `src/acabot/runtime/__init__.py`
  - Export `SoulSource` and `StickyNotesSource` if needed by tests/importers
- `src/acabot/runtime/control/control_plane.py`
  - Add `self`, sticky-note, and safe Session WebUI methods
- `src/acabot/runtime/control/http_api.py`
  - Add new `/api/self/*` and `/api/memory/sticky-notes/*` endpoints
- `src/acabot/runtime/memory/sticky_notes.py`
  - Bridge sticky-note runtime reads/writes to the chosen sticky-note source and keep tool semantics coherent
- `src/acabot/runtime/plugins/sticky_notes.py`
  - Adjust plugin behavior if needed for file-backed sticky-note storage
- `src/acabot/runtime/memory/retrieval_planner.py`
  - Add a stable `self` slot ahead of sticky notes/retrieved memory
- `src/acabot/runtime/pipeline.py`
  - Load `self` content into the frontstage run context before prompt assembly
- `tests/runtime/test_webui_api.py`
  - Add API and static shell tests
- `tests/runtime/test_pipeline_runtime.py`
  - Add `self` slot ordering/injection coverage
- `tests/runtime/test_sticky_notes_plugin.py`
  - Add file-backed sticky-note behavior coverage
- `docs/HANDOFF.md`
  - Record progress and follow-up state after implementation

**Keep as-is, but depend on:**

- `src/acabot/runtime/control/config_control_plane.py`
- `src/acabot/runtime/control/ui_catalog.py`
- `src/acabot/runtime/control/log_buffer.py`
- `docs/superpowers/specs/2026-03-18-session-subagent-overrides-analysis.md`

---

### Task 1: Lock the New Behavior with Failing Tests

**Files:**

- Modify: `tests/runtime/test_webui_api.py`
- Modify: `tests/runtime/test_pipeline_runtime.py`
- Modify: `tests/runtime/test_sticky_notes_plugin.py`

- [ ] **Step 1: Add a failing HTTP API test for `self` files**

```python
async def test_runtime_http_api_server_serves_self_files(tmp_path: Path) -> None:
    payload = await asyncio.to_thread(request_json, base_url, "/api/self/files")
    assert payload["ok"] is True
    assert any(item["name"] == "task.md" for item in payload["data"]["items"])
```

- [ ] **Step 2: Add a failing HTTP API test for sticky-note scopes and dual-zone payloads**

```python
sticky = await asyncio.to_thread(
    request_json,
    base_url,
    "/api/memory/sticky-notes/item?scope=channel&scope_key=qq:group:42&key=internship_rule",
)
assert sticky["data"]["readonly"]["content"] == "..."
assert sticky["data"]["editable"]["content"] == "..."
```

- [ ] **Step 3: Add a failing pipeline test for `self` slot order**

```python
slot_types = [slot.slot_type for slot in ctx.prompt_slots]
assert slot_types == ["self_context", "sticky_notes", "thread_summary", "retrieved_memory"]
```

- [ ] **Step 4: Add a failing test for `self` always-hit behavior**

```python
assert any(slot.slot_type == "self_context" for slot in ctx.prompt_slots)
```

- [ ] **Step 5: Add a failing sticky-notes test for filesystem-backed readonly/editable pairs**

```python
pair = source.read_pair(scope="channel", scope_key="qq:group:42", key="internship_rule")
assert pair["readonly"]["content"] == "..."
assert pair["editable"]["content"] == "..."
```

- [ ] **Step 6: Run the targeted tests and confirm they fail for the expected reasons**

Run:

```bash
PYTHONPATH=src pytest \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_sticky_notes_plugin.py -q
```

Expected:

- `self` API routes missing
- sticky-note file APIs missing
- prompt slot order missing `self_context`
- explicit always-hit `self` behavior missing

- [ ] **Step 7: Commit the red tests**

```bash
git add tests/runtime/test_webui_api.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_sticky_notes_plugin.py
git commit -m "test: cover self sticky-note and safe-session flows"
```

### Task 2: Add File-Backed `Soul` Source and Control Plane APIs

**Files:**

- Create: `src/acabot/runtime/soul/source.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Implement the `SoulSource` service**

```python
class SoulSource:
    CORE_FILES = ("identity.md", "soul.md", "state.yaml", "task.md")

    def list_files(self) -> list[dict[str, Any]]: ...
    def read_file(self, name: str) -> dict[str, Any]: ...
    def write_file(self, name: str, content: str) -> dict[str, Any]: ...
    def create_file(self, name: str, content: str = "") -> dict[str, Any]: ...
    def build_prompt_text(self) -> str: ...
```

- [ ] **Step 2: Wire `SoulSource` into runtime bootstrap and components**

Run:

```bash
rg -n "RuntimeComponents|sticky_notes=|control_plane=" src/acabot/runtime/bootstrap
```

Expected:

- one shared `SoulSource` instance created in bootstrap
- the same instance passed to control plane and frontstage runtime path users

- [ ] **Step 3: Add control-plane methods for list/read/write/create**

```python
async def list_self_files(self) -> dict[str, Any]: ...
async def get_self_file(self, name: str) -> dict[str, Any]: ...
async def put_self_file(self, name: str, content: str) -> dict[str, Any]: ...
async def post_self_file(self, name: str, content: str = "") -> dict[str, Any]: ...
```

- [ ] **Step 4: Expose `/api/self/*` routes in `http_api.py`**

Routes to add:

- `GET /api/self/files`
- `GET /api/self/file?name=...`
- `PUT /api/self/file`
- `POST /api/self/files`

- [ ] **Step 5: Add validation tests that the spec requires**

Cover:

- illegal file names/paths are rejected
- `state.yaml` invalid YAML is rejected

- [ ] **Step 6: Re-run the `self` API tests and confirm they pass**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "self"
```

Expected:

- PASS for list/read/write/create `self` routes
- PASS for path rejection and YAML validation

- [ ] **Step 7: Commit the `self` backend work**

```bash
git add src/acabot/runtime/soul/source.py src/acabot/runtime/soul/__init__.py src/acabot/runtime/bootstrap/__init__.py src/acabot/runtime/bootstrap/components.py src/acabot/runtime/__init__.py src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/http_api.py tests/runtime/test_webui_api.py
git commit -m "feat: add file-backed soul source and webui api"
```

### Task 3: Add Sticky Notes with Readonly + Editable Zones

**Files:**

- Create: `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- Modify: `src/acabot/runtime/memory/sticky_notes.py`
- Modify: `src/acabot/runtime/plugins/sticky_notes.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Modify: `src/acabot/runtime/__init__.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Test: `tests/runtime/test_sticky_notes_plugin.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Implement the sticky-note source**

```python
class StickyNotesSource:
    def list_scopes(self) -> list[dict[str, str]]: ...
    def list_notes(self, *, scope: str, scope_key: str) -> list[dict[str, str]]: ...
    def read_pair(self, *, scope: str, scope_key: str, key: str) -> dict[str, Any]: ...
    def write_readonly(self, *, scope: str, scope_key: str, key: str, content: str) -> dict[str, Any]: ...
    def write_editable(self, *, scope: str, scope_key: str, key: str, content: str) -> dict[str, Any]: ...
```

- [ ] **Step 2: Use filesystem enumeration for scope listing**

Implementation rule:

- `GET /api/memory/sticky-notes/scopes` only面向 `user/channel`
- do not expose `relationship/global` in第一版产品层

- [ ] **Step 3: Repoint sticky-note runtime behavior to the file-backed source**

Implementation rule:

- the source of truth is the filesystem
- each note has `readonly.md` and `editable.md`
- tool/plugin behavior must stay coherent with this model
- existing `sticky_note_put/get/list/delete` semantics must be updated, not assumed
- `readonly` 人工维护，bot 不允许写
- `editable` bot 可写

- [ ] **Step 4: Add control-plane methods for sticky-note scopes, listing, reading, writing**

```python
async def list_sticky_note_scopes(self) -> list[dict[str, Any]]: ...
async def list_sticky_notes(self, *, scope: str, scope_key: str) -> dict[str, Any]: ...
async def get_sticky_note_item(self, *, scope: str, scope_key: str, key: str) -> dict[str, Any]: ...
async def put_sticky_note_editable(...): ...
async def put_sticky_note_readonly(...): ...
async def create_sticky_note(...): ...
```

- [ ] **Step 5: Expose `/api/memory/sticky-notes/*` routes**

Routes to add:

- `GET /api/memory/sticky-notes/scopes`
- `GET /api/memory/sticky-notes`
- `GET /api/memory/sticky-notes/item`
- `PUT /api/memory/sticky-notes/item`
- `PUT /api/memory/sticky-notes/readonly`
- `POST /api/memory/sticky-notes/item`

- [ ] **Step 6: Add validation/error tests**

Cover:

- missing scope returns empty list or explicit not-found
- missing note returns explicit not-found
- readonly and editable write paths are distinct
- bot 写 readonly 被拒绝

- [ ] **Step 7: Re-run sticky-note tests and confirm sticky-note behavior**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_sticky_notes_plugin.py tests/runtime/test_webui_api.py -q -k "sticky"
```

Expected:

- readonly/editable pair tests PASS
- scope enumeration works for `user/channel`
- WebUI sticky-note routes PASS

- [ ] **Step 8: Commit the sticky-note backend layer**

```bash
git add src/acabot/runtime/memory/file_backed/sticky_notes.py src/acabot/runtime/memory/file_backed/__init__.py src/acabot/runtime/memory/sticky_notes.py src/acabot/runtime/plugins/sticky_notes.py src/acabot/runtime/bootstrap/__init__.py src/acabot/runtime/bootstrap/components.py src/acabot/runtime/__init__.py src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/http_api.py tests/runtime/test_sticky_notes_plugin.py tests/runtime/test_webui_api.py
git commit -m "feat: add file-backed sticky notes for webui"
```

### Task 4: Inject `self` and Sticky Notes into Prompt Assembly

**Files:**

- Modify: `src/acabot/runtime/pipeline.py`
- Modify: `src/acabot/runtime/memory/retrieval_planner.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Test: `tests/runtime/test_pipeline_runtime.py`

- [ ] **Step 1: Encode `self` as an always-hit rule**

Implementation rule:

- `self` must behave as “every run always hits”
- whether this is physically implemented through `MemoryBroker` or not is not important
- the test should lock the behavior, not the mechanism

- [ ] **Step 2: Load `self` content before prompt assembly**

```python
self_text = self.soul_source.build_prompt_text()
ctx.metadata["self_prompt_text"] = self_text
```

- [ ] **Step 3: Add a stable `self_context` slot ahead of sticky notes**

```python
PromptSlot(
    slot_id="slot:self",
    slot_type="self_context",
    title="Self",
    content=self_text,
    position="system_message",
    message_role="system",
    stable=True,
)
```

- [ ] **Step 4: Keep sticky-note behavior scoped to `user/channel` notes**

Rule:

- readonly sticky notes inject
- editable sticky notes also inject
- `user/channel` are the only product scopes in this plan

- [ ] **Step 5: Re-run runtime prompt assembly tests**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_pipeline_runtime.py -q
```

Expected:

- `self_context` slot appears first
- readonly sticky notes still inject
- `self` appears on every run as designed

- [ ] **Step 6: Commit the runtime assembly changes**

```bash
git add src/acabot/runtime/pipeline.py src/acabot/runtime/memory/retrieval_planner.py src/acabot/runtime/bootstrap/__init__.py tests/runtime/test_pipeline_runtime.py
git commit -m "feat: inject self and sticky notes into frontstage context"
```

### Task 5: Replace the Old Static WebUI with a Vue App

**Files:**

- Create: `webui/package.json`
- Create: `webui/tsconfig.json`
- Create: `webui/vite.config.ts`
- Create: `webui/index.html`
- Create: `webui/src/main.ts`
- Create: `webui/src/App.vue`
- Create: `webui/src/router.ts`
- Create: `webui/src/lib/api.ts`
- Create: `webui/src/views/HomeView.vue`
- Create: `webui/src/views/SoulView.vue`
- Create: `webui/src/views/MemoryView.vue`
- Create: `webui/src/views/BotView.vue`
- Create: `webui/src/views/ModelsView.vue`
- Create: `webui/src/views/PromptsView.vue`
- Create: `webui/src/views/PluginsView.vue`
- Create: `webui/src/views/SkillsView.vue`
- Create: `webui/src/views/SubagentsView.vue`
- Create: `webui/src/views/SessionsView.vue`
- Create: `webui/src/views/SystemView.vue`
- Create: `webui/src/components/AppSidebar.vue`
- Create: `webui/src/components/FileEditorPane.vue`
- Create: `webui/src/components/StickyNotePane.vue`
- Create: `webui/src/components/StatusCard.vue`
- Modify: `src/acabot/webui/*` (generated build output)
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Scaffold the Vue/Vite workspace**

Use `vite.config.ts` to emit built assets into `src/acabot/webui` so the current Python static server keeps working.

- [ ] **Step 2: Build the new IA shell**

Required top-level structure:

- 首页
- 配置
- 会话
- 系统

Inside `配置`, expose:

- Self
- Memory
- Bot
- Providers
- 模型
- Prompts
- Plugins
- Skills
- Subagents

- [ ] **Step 3: Implement `Self` page editing**

Required behavior:

- list files from `/api/self/files`
- read one file
- edit one file
- save one file
- visibly distinguish `identity.md`, `soul.md`, `state.yaml`, `task.md`

- [ ] **Step 4: Implement `Memory` page sticky-note editing**

Required behavior:

- choose scope + scope key
- list note keys from filesystem-backed source
- show readonly zone and editable zone side by side
- save editable zone
- save readonly zone only from explicit human action

- [ ] **Step 5: Port the remaining high-value pages from the old shell**

Keep real functionality for:

- 首页 status/logs
- Bot
- Models / Providers
- Prompts
- Plugins
- Skills
- Subagents registry view
- Sessions safe shell

Do not regress existing save flows while replacing the UI shell.

- [ ] **Step 6: Build the frontend and run static shell smoke tests**

Run:

```bash
npm --prefix webui install
npm --prefix webui run build
PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "webui or shell"
```

Expected:

- Vite build succeeds
- `src/acabot/webui/index.html` is regenerated
- WebUI smoke tests PASS

- [ ] **Step 7: Commit the Vue frontend**

```bash
git add webui src/acabot/webui tests/runtime/test_webui_api.py
git commit -m "feat: replace static webui with vue shell"
```

### Task 6: Add Product-Shaped Session Shell (AI / 消息响应 / 其他)

**Files:**

- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `webui/src/views/SessionsView.vue`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: Add failing tests for Session product shell behavior**

Cover:

- list sessions/threads
- show current `channel_scope` / `thread_id`
- show Session AI values (prompt/model/tools/skills)
- show Session 输入处理 values (enabled/run_mode/persist/tags)
- save Session AI values
- save Session 输入处理 values
- save Session 其他 values

- [ ] **Step 2: Keep frontend model clean; map in backend**

Implementation rule:

- Session 基础信息 comes from thread/runtime state
- Session / AI + 消息响应 + 其他 is the only frontend contract
- backend maps these sections to existing truth sources (profile + rules) without exposing rule concepts in UI

- [ ] **Step 3: Implement the Vue Session view with only those product sections**

Do not include:

- any raw rule identifiers (`binding_rule_id / inbound_rule_id / event_policy_id`)
- Session-scoped subagent toggles
- runtime computer override actions in the same form

- [ ] **Step 4: Re-run session-focused tests**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_webui_api.py -q -k "session or rule"
```

Expected:

- Session shell works with product-shaped fields
- no backend rule concept leaks into front-end rendering

- [ ] **Step 5: Commit the Session product shell**

```bash
git add src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/http_api.py webui/src/views/SessionsView.vue tests/runtime/test_webui_api.py
git commit -m "feat: add product-shaped session shell with backend mapping"
```

### Task 7: Full Verification and Handoff

**Files:**

- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: Run the full targeted backend/frontend suite**

Run:

```bash
PYTHONPATH=src pytest \
  tests/runtime/test_webui_api.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_sticky_notes_plugin.py -q
```

Expected:

- PASS with no `self`/sticky-note regressions

- [ ] **Step 2: Build the frontend one more time from a clean state**

Run:

```bash
npm --prefix webui run build
```

Expected:

- clean build into `src/acabot/webui`

- [ ] **Step 3: Perform manual smoke checks**

Manual checklist:

- Open the local WebUI
- Edit `identity.md` and `task.md`
- Refresh and confirm persisted values
- Edit a sticky note editable zone and confirm it persists
- Edit a sticky note readonly zone via the explicit human flow and confirm it persists
- Open `Sessions` and modify AI / 消息响应 / 其他任意字段
- Refresh and confirm persisted values
- Trigger one normal conversation and confirm `self` content is visible to the bot
- Trigger a maintenance-chain operation and confirm `self` is not auto-injected

- [ ] **Step 4: Update `docs/HANDOFF.md`**

Record:

- what was implemented
- what verification actually passed
- known gaps
- exact commands for continuing work

- [ ] **Step 5: Commit the verification + handoff update**

```bash
git add docs/HANDOFF.md
git commit -m "docs: hand off self sticky-note and safe-session work"
```
