# CONCERNS.md — Tech Debt, Bugs, Security, Performance, Fragile Areas

## 1. Security

### 1.1 WebUI HTTP API Has No Authentication
- `src/acabot/runtime/control/http_api.py` — The `RuntimeHttpApiServer` exposes a full control plane over HTTP (session management, config modification, model provider CRUD, LTM browsing/deletion, workspace operations) with **zero authentication or authorization**.
- API keys for model providers can be read/written via `/api/models/providers` endpoints — anyone with network access can exfiltrate or overwrite them.
- Default bind is `127.0.0.1` which mitigates remote access, but any local process or port-forwarded tunnel exposes everything.
- **Severity: Critical.** Must add at minimum a bearer token or session-based auth before any non-localhost deployment.

### 1.2 LTM Database Has No Access Control
- `src/acabot/runtime/memory/long_term_memory/storage.py` — LanceDB is a local file-based store (`runtime_data/ltm/`). Any process on the host can read/modify/corrupt the entire memory database.
- The `_quote_sql_text()` helper does basic escaping but LanceDB filter expressions are string-interpolated — potential for filter injection if user-influenced data reaches query parameters.
- **Noted in** `.harness/progress.md` as "LTM 数据库安全性" known issue.

### 1.3 Host Computer Backend — No Sandboxing
- `src/acabot/runtime/computer/backends.py` `HostComputerBackend` — Executes arbitrary shell commands via `asyncio.create_subprocess_shell()` **directly on the host OS** with the permissions of the AcaBot process.
- No command filtering, no allowlist, no resource limits (cgroups/ulimits), no filesystem isolation beyond the workspace directory.
- The `DockerSandboxBackend` exists but shares host filesystem via `-v` mount and network access defaults to `enabled`.
- The `allow_exec` / `allow_sessions` policy flags exist but default to `True` in `src/acabot/runtime/computer/runtime.py:71-76`.

### 1.4 Gateway Token Comparison Is Not Constant-Time
- `src/acabot/gateway/napcat.py:117` — `if auth_header != expected:` is a standard string comparison, vulnerable to timing attacks for token guessing. Low risk in practice but worth noting.

### 1.5 Config File Contains Secrets in Plaintext
- `config.yaml` stores API keys (`api_key`, `api_key_env`) directly. No encryption at rest. `.gitignore` covers `config.yaml` but not all possible paths.

---

## 2. Technical Debt

### 2.1 Reference Backend Marked for Deletion
- `.harness/progress.md` explicitly states: "Reference Backend 不再需要且设计不合理需要删除"
- Full implementation still exists across `src/acabot/runtime/references/` (4 files), `src/acabot/runtime/plugins/reference_tools.py`, and is wired into `RuntimePluginContext`.
- Every plugin context carries `reference_backend: ReferenceBackend | None` — removing it requires touching plugin manager, bootstrap, and control plane.

### 2.2 Duplicated `excerpt_bytes()` Function
- `src/acabot/runtime/computer/backends.py` — The `excerpt_bytes()` function and `__all__` export are duplicated at the bottom of the file (lines 796-855 are a verbatim copy of lines 796-825). Copy-paste artifact.

### 2.3 `RemoteComputerBackend` Is a Stub
- `src/acabot/runtime/computer/backends.py` `RemoteComputerBackend` — Every method raises `ComputerBackendNotImplemented`. Still registered in `ComputerRuntime.backends` dict at init.

### 2.4 LTM Storage Uses Full-Table Rewrite
- `src/acabot/runtime/memory/long_term_memory/storage.py` — `upsert_entries()`, `save_cursor()`, `save_failed_window()`, `delete_entry()`, `update_entry()` all call `_rewrite_table()` which does `to_arrow().to_pylist()` → filter/merge → `create_table(..., mode="overwrite")`.
- This is O(N) for every single write. Known tradeoff documented in module docstring ("先把正确行为跑通"), but will not scale past a few thousand entries.

### 2.5 Semantic Search Is In-Memory Brute Force
- `src/acabot/runtime/memory/long_term_memory/storage.py:519-538` — `semantic_search()` loads **all rows** (limit 10,000), computes cosine similarity in pure Python, and sorts. No vector index used.

### 2.6 TODO: Plugin Manager Reference Exposure
- `src/acabot/runtime/plugin_manager.py:368` — `# TODO: 收窄成 ReferenceService, 或者不暴露?`

### 2.7 TODO: Thread Compaction Concurrency
- `src/acabot/runtime/pipeline.py:160` — `TODO: single-flight thread compaction with append-only rebase` — concurrent runs on the same thread can do redundant compaction work. Compaction results may be silently discarded if the thread was modified between snapshot and apply.

### 2.8 Unified Message Tool Not Yet Implemented
- `.harness/progress.md` details a planned "统一 message 工具" design. Currently bot can only reply with plain text; no cross-session messaging, reactions, recalls, file attachments, or text-to-image rendering via tools.

---

## 3. Performance

### 3.1 LTM Full-Table Scans
- `structured_search()` and `semantic_search()` in `src/acabot/runtime/memory/long_term_memory/storage.py` both load up to 10,000 rows per query and filter in Python. Will degrade with data growth.
- FTS index is rebuilt on every entry table rewrite (`create_fts_index("lexical_text", replace=True)` in `_rewrite_entries_table`).

### 3.2 SQLite Async Lock Contention
- `src/acabot/runtime/storage/sqlite_stores.py` — All SQLite operations go through `async with self._lock:` per store instance. Under concurrent runs, thread/run/event/message stores become serial bottlenecks.
- `check_same_thread=False` + single `asyncio.Lock` is correct but limits throughput to one query at a time per store.

### 3.3 Skill Mirroring Uses `shutil.copytree` on Every Access
- `src/acabot/runtime/computer/runtime.py` `refresh_world_skills_view()` — On every world path read/write touching `/skills`, the entire skill directory is `shutil.rmtree` + `shutil.copytree` per visible skill. No change detection or caching.

### 3.4 WebUI HTTP Server Is Thread-Based
- `src/acabot/runtime/control/http_api.py` — Uses `http.server.ThreadingHTTPServer` in a daemon thread. All API handlers bridge back to the asyncio loop via `asyncio.run_coroutine_threadsafe()`. High overhead per request; no connection reuse or streaming.

---

## 4. Fragile Areas

### 4.1 Pipeline Concurrent Run Interleaving
- `src/acabot/runtime/pipeline.py` — Multiple runs on the same thread execute concurrently. Working messages are appended under `ctx.thread.lock`, but the compaction snapshot → apply cycle has a race window. If two runs compact simultaneously, one's apply may be rejected. The code handles this gracefully (falls back to effective_* from metadata), but it means compaction results may be wasted.

### 4.2 NapCat Single-Connection Model
- `src/acabot/gateway/napcat.py` — `self._ws` is a single connection slot. If NapCat reconnects, the old reference is silently overwritten. Pending futures from the old connection are never resolved (they'll time out). No reconnection logic exists — if the WS drops, the bot is deaf until NapCat reconnects.

### 4.3 Fire-and-Forget Event Dispatch
- `src/acabot/gateway/napcat.py:142` — `asyncio.create_task(self._on_event(event))` — Inbound events are dispatched as fire-and-forget tasks. If the handler raises, the exception is logged to the task but not surfaced. No backpressure mechanism if events arrive faster than processing.

### 4.4 LanceDB FTS Index Rebuild Timing
- `src/acabot/runtime/memory/long_term_memory/storage.py:415` — The FTS index is created at `__init__` time with `replace=True`. If the process crashes mid-rewrite, the FTS index may be stale or missing on next startup.

### 4.5 World Path Traversal
- `src/acabot/runtime/computer/runtime.py:504-507` — Path traversal protection uses `host_path.relative_to(canonical_root)` to catch escapes. This is correct but only applies to the `/skills` root. The general `world_view.resolve()` path must also prevent traversal — that logic lives in `src/acabot/runtime/computer/world.py` and should be audited.

---

## 5. Incomplete Features

### 5.1 WebUI
- `.harness/progress.md`: "webui 设计不完整，缺少很多配置页面"
- No session management UI, no LTM visualization, limited model provider management.

### 5.2 Tool Ecosystem
- `.harness/progress.md`: "bot 掌握工具太少"
- Only builtin computer tools (read/write/edit/bash), sticky notes, skills, and platform-specific NapCat tools exist. No web search, calculator, calendar, or other common bot capabilities.

### 5.3 Logging and Observability
- `.harness/progress.md`: "日志过于简陋" — tool call execution process is not surfaced; LTM extraction process is invisible to operators.
- `src/acabot/runtime/control/log_buffer.py` exists but in-memory ring buffer only.

### 5.4 Multi-Platform Support
- Only QQ (via NapCat/OneBot v11) is implemented. The `BaseGateway` abstraction exists but no other gateway implementations ship.

---

## 6. Code Quality

### 6.1 Test Coverage Is Thin
- `tests/` contains tests for config, gateway, main, and agent, plus some runtime tests. Large subsystems (pipeline, computer runtime, LTM storage, plugin manager, outbox, context assembly) have no dedicated test files.

### 6.2 No Type Stubs for Dynamic Backend Selection
- `src/acabot/runtime/computer/runtime.py:80-92` — `self.backends` is `dict[str, ComputerBackend]` but `ComputerBackend` is a protocol/union. The actual type at each key is determined at runtime, making static analysis less effective.

### 6.3 Mixed Language in Comments/Docs
- Docstrings and comments alternate between Chinese and English without clear convention. Module-level docs are Chinese; some inline comments are English. Not a bug but increases cognitive load for contributors.
