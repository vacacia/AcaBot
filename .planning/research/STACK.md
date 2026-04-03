# Stack Research

**Domain:** Chatbot runtime infrastructure hardening (plugin system, messaging, scheduler, logging, vector DB integrity, text-to-image)
**Researched:** 2026-04-02
**Confidence:** HIGH (all recommendations verified against current releases and existing codebase constraints)

## Executive Summary

AcaBot is a Python 3.11+ asyncio chatbot runtime. This research covers six infrastructure dimensions needed for the current milestone. Key principle: **minimize new dependencies** — AcaBot already has a working pipeline, so prefer stdlib/existing-dep solutions over new frameworks.

| Dimension | Recommendation | New Deps |
|-----------|---------------|----------|
| Plugin reconciler | Custom desired-state reconciler (no library) | None |
| Unified message tool | Single `message` tool with action dispatch | None |
| Task scheduler | Custom asyncio scheduler + `cronsim` | `cronsim` |
| Structured logging | `structlog` >= 25.1.0 | `structlog` |
| LanceDB integrity | Application-level lock + backup + compact | None (update `lancedb` pin) |
| Playwright rendering | Async Playwright with singleton browser | None (already installed) |

---

## 1. Plugin Reconciler Pattern

**Recommendation: Kubernetes-style desired-state reconciliation (as designed in docs/29)**
**Confidence: HIGH**

### What to Use

The existing design in `docs/29-plugin-control-plane.md` is the right pattern. No external library needed.

| Concept | Implementation | Rationale |
|---------|---------------|-----------|
| Desired state (Spec) | `PluginSpec` YAML in `runtime_config/plugins/` | Operator intent is declarative, survives restarts |
| Observed state (Status) | `PluginStatus` JSON in `runtime_data/plugins/` | Reconciler output, WebUI reads this |
| Package catalog | `PluginPackage` from `extensions/plugins/` | Code availability is a separate concern from intent |
| Reconciler | `PluginReconciler` — pure function: `(packages, specs, host_state) -> actions` | Single convergence entry point eliminates the current 3-way split |
| Executor (Host) | `PluginRuntimeHost` — load/unload/teardown/run_hooks | Dumb executor, no decision logic |

### Why Desired-State over Imperative

- **Crash recovery**: On restart, `reconcile_all()` compares spec vs host memory state and converges. No "did the last load succeed?" ambiguity.
- **WebUI simplicity**: UI writes spec, triggers reconcile, reads status. Three clean operations instead of imperative "load this plugin now" with partial failure handling.
- **Proven at scale**: Kubernetes controllers, Terraform, Ansible — all use this pattern for exactly these reasons.

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Imperative load/unload commands | State becomes ambiguous after crashes, partial failures | Desired-state reconciliation |
| File-watching (watchdog, inotify) | Complexity, platform differences, Docker volume edge cases | Manual trigger via API + reconcile on startup |
| External orchestrators (Pluggy, stevedore, yapsy) | Over-engineered for ~10-20 plugins; AcaBot's plugin protocol is already well-defined | Custom reconciler (~200 lines) |

---

## 2. Unified Message/Action Tooling

**Recommendation: Extend existing `Action`/`ActionType` + `Outbox` with a unified `send_message` LLM tool**
**Confidence: MEDIUM — design details pending, but architecture direction is clear**

### What to Use

| Component | Approach | Rationale |
|-----------|----------|-----------|
| LLM-facing tool | Single `send_message` tool with typed `action` parameter | LLM picks action type (text, reply, reaction, image, forward); one tool reduces schema complexity |
| Message construction | `MessageSegment` dataclass (platform-agnostic) | Maps 1:1 to OneBot v11 segments today, extensible to other platforms later |
| Text-to-image | `render_markdown_to_image()` in Outbox layer (uses Playwright) | LLM calls `send_message(action="image", markdown="...")`, Outbox renders and sends |
| Cross-session messaging | `target` parameter on `send_message` with channel identifier | Gateway resolves channel; session config controls which targets are allowed |
| Platform adapter | `GatewayProtocol.send_action(Action)` — existing pattern | Keep Gateway as thin protocol bridge; action types are platform-agnostic |

### Architecture Principle

The LLM should think in terms of **intent** (reply, react, send image), not platform primitives (CQ codes, segment arrays). The Outbox translates intent to platform-specific delivery.

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Multiple send tools (send_text, send_image, send_reply, ...) | Bloats tool schema; LLMs handle fewer tools better | Single `send_message` with action discriminator |
| Direct OneBot v11 segment construction in LLM tool | Couples LLM to platform; breaks when adding Telegram/Discord | Platform-agnostic MessageSegment + Gateway adapter |
| Separate "rendering service" process | Over-engineered for single-container deployment | In-process Playwright call in Outbox |

---

## 3. Task Scheduler Infrastructure

**Recommendation: Custom lightweight asyncio scheduler built on `asyncio.TaskGroup` (Python 3.11+)**
**Confidence: HIGH**

### Why Not APScheduler or Celery

| Alternative | Why NOT for AcaBot |
|-------------|-------------------|
| **APScheduler 4.x** | Still in alpha as of April 2026 (4.0.0a6). Docs explicitly warn: "do not use in production". No stable release timeline. |
| **APScheduler 3.x** | Threading-based, not native asyncio. `AsyncIOScheduler` is a thin wrapper with sync internals. |
| **Celery** | Requires external broker (Redis/RabbitMQ). Massive overkill for single-process bot. |
| **Huey** | Similar to Celery-lite. Still needs Redis or SQLite backend. Unnecessary for in-process scheduling. |
| **dramatiq** | Same category as Celery — distributed task queue, not in-process scheduler. |

### What to Build

```
src/acabot/runtime/scheduler.py  (~150-200 lines)
```

| Feature | Implementation |
|---------|---------------|
| Cron-like scheduling | Parse cron expressions with `cronsim` |
| Interval scheduling | `asyncio.sleep()` in a loop with cancellation token |
| One-shot delayed tasks | `asyncio.create_task()` with `asyncio.sleep(delay)` |
| Task registry | `dict[task_id, ScheduledTask]` with owner tracking (plugin_id or "core") |
| Graceful shutdown | `asyncio.TaskGroup` or manual task set with `cancel()` on `app.stop()` |
| Plugin integration | `PluginRuntimeHost.unload_plugin()` cancels all tasks owned by that plugin_id |

### Supporting Library

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `cronsim` | >= 2.6 | Cron expression parsing & evaluation | Actively maintained (used by Home Assistant, Healthchecks.io). Pure Python, no dependencies. Timezone-aware via `zoneinfo`. Replaces `croniter` which was declared unmaintained in Dec 2024 due to EU CRA. |

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `croniter` | **Unmaintained since Dec 2024.** Maintainer declared abandonment due to EU Cyber Resilience Act. PyPI package may be unpublished. | `cronsim` >= 2.6 |
| `schedule` (PyPI) | Synchronous, polling-based, not asyncio-native | Custom asyncio scheduler |
| `APScheduler 3.x` | Threading-based, awkward asyncio integration | Custom asyncio scheduler |
| `APScheduler 4.x` | Still pre-release alpha, API unstable, no production use recommended | Wait for stable release; custom is simpler for our needs |
| Raw `asyncio.sleep()` loops scattered in code | No centralized management, no cancellation on shutdown, no observability | Centralized scheduler with task registry |

---

## 4. Structured Logging

**Recommendation: `structlog` with stdlib `logging` integration**
**Confidence: HIGH**

### What to Use

| Library | Version | Purpose | Rationale |
|---------|---------|---------|-----------|
| `structlog` | >= 25.1.0 (latest: **25.5.0**, Oct 2025) | Structured logging with context binding | De facto standard for Python structured logging. Works WITH stdlib logging (not replacing it). AcaBot already uses `logging.getLogger("acabot.*")` everywhere — structlog wraps this, not replaces it. |

### Integration Pattern

```python
# Configure once at startup
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,    # async-safe context
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
```

Key features for AcaBot:

| Feature | Why It Matters |
|---------|---------------|
| `contextvars` integration | Bind `run_id`, `thread_id`, `plugin_id` once per request; all downstream logs include them automatically. Critical for async where threading.local doesn't work. |
| Stdlib compatibility | Existing `logging.getLogger()` calls continue working. Migration is incremental. |
| JSON + console output | Dev: colored console. Production: JSON for log aggregation. Switch via config. |
| In-memory log buffer | AcaBot's WebUI log viewer can consume structured events directly. |

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `loguru` | Replaces stdlib logging entirely. AcaBot has 50+ `logging.getLogger()` calls — migration is all-or-nothing. Loguru's `logger.bind()` is thread-local, not async-safe without manual `contextvars` patching. | `structlog` (wraps stdlib, async-native) |
| Plain stdlib `logging` (current state) | No structured fields, no async context propagation, no JSON output. Tool calls and LTM operations are invisible. | `structlog` on top of stdlib |
| `python-json-logger` | JSON formatting only — no context binding, no processor pipeline. | `structlog` (superset) |

---

## 5. LanceDB Data Integrity Patterns

**Recommendation: Application-level protection with asyncio.Lock + periodic backup**
**Confidence: HIGH**

### Current State

AcaBot uses LanceDB >= 0.25.0 (latest: **0.30.1**, March 2026). The LTM storage module (`storage.py`) uses synchronous LanceDB API calls. The LTM ingestor runs as a background async task.

### Data Integrity Strategy

| Concern | Solution | Rationale |
|---------|----------|-----------|
| **Concurrent writes** | `asyncio.Lock` per LanceDB connection (already partially in place) | LanceDB's Lance format supports concurrent reads but single-writer. Since AcaBot is single-process, an asyncio Lock is sufficient. |
| **Read consistency** | `read_consistency_interval=timedelta(0)` on connect | Forces strong consistency. Performance cost is negligible for AcaBot's scale (~1000s of entries, not millions). |
| **Write atomicity** | Lance format uses manifest-based commits (append-only log of data fragments) | Built into the format — each write creates a new manifest version. If the process crashes mid-write, the last committed manifest is still valid. |
| **Backup** | Periodic `shutil.copytree()` of the entire LanceDB directory to `runtime_data/backups/ltm/` | Simple, reliable. Schedule via the new scheduler infrastructure (e.g., daily). |
| **Corruption recovery** | `lancedb.connect()` on backup directory; swap paths in config | If primary is corrupted, point to last known good backup. |
| **Version pinning** | Pin `lancedb >= 0.28.0, < 1.0` in `pyproject.toml` | Lance format has had breaking changes between major versions. Pin to avoid surprise migrations. |

### LanceDB-Specific Best Practices (2025/2026)

| Practice | Detail |
|----------|--------|
| **Don't use `overwrite` mode for updates** | Use `merge_insert` (upsert) instead. Overwrite rewrites the entire table. |
| **Rebuild indexes after large batch writes** | Call `table.create_index()` after ingesting a batch, not after every single write. |
| **Use `add()` for appends, `update()` for mutations** | Don't delete-then-add; use Lance's native update path. |
| **Monitor table fragment count** | Many small writes create many fragments. Periodic `table.compact_files()` merges them. Schedule via scheduler. |

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| External WAL (write-ahead log) on top of LanceDB | Lance format already has manifest-based versioning that provides crash safety | Rely on Lance's built-in mechanism |
| Multi-process access to same LanceDB directory | Lance format is single-writer. Multiple processes = corruption risk | Single process with asyncio.Lock |
| `lancedb >= 1.0` (when it ships) | Breaking API changes likely | Pin `< 1.0`, upgrade deliberately |

### Recommended Version Update

```toml
# pyproject.toml
lancedb = ">= 0.28.0, < 1.0"   # was >= 0.25.0; 0.28+ has merge_insert improvements
pyarrow = ">= 18.0.0"           # keep as-is, compatible
```

---

## 6. Playwright Integration for Text-to-Image

**Recommendation: Direct Playwright async API for HTML-to-PNG rendering**
**Confidence: HIGH**

### Current State

Playwright + Chromium are already installed in both Full and Lite Docker images. The bot uses them for browser automation via the Computer subsystem. Current version: **1.58.0** (Jan 2026).

### What to Build

```
src/acabot/runtime/outbox_renderer.py  (~80-100 lines)
```

| Component | Implementation |
|-----------|---------------|
| `render_markdown_to_image(markdown: str, width: int = 800) -> bytes` | Async function returning PNG bytes |
| Browser lifecycle | Singleton browser instance, launched on first call, reused across renders |
| HTML template | Jinja2 template with CSS (Noto CJK fonts, code highlighting, proper margins) |
| Markdown conversion | `markdown-it-py` (already in Dockerfile) converts MD to HTML |
| Screenshot | `page.screenshot(full_page=True, type="png")` |
| Cleanup | Browser closed on `app.stop()` |

### Integration with Outbox

```python
# In Outbox.dispatch(), when action is SEND_IMAGE_FROM_MARKDOWN:
png_bytes = await self.renderer.render_markdown_to_image(markdown_text)
# Convert to base64, send as OneBot image segment
```

### Performance Considerations

| Concern | Solution |
|---------|----------|
| Cold start (~2-3s for browser launch) | Launch browser eagerly on `app.start()`, not on first render |
| Per-render latency (~200-500ms) | Acceptable for chat; reuse browser context, create new page per render |
| Memory | Single Chromium instance: ~100-200MB. Already budgeted in Docker image. |
| Concurrent renders | `asyncio.Semaphore(3)` to limit parallel page renders |

### What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `imgkit` / `wkhtmltoimage` | Requires separate wkhtmltopdf binary; worse CSS support than Chromium; project unmaintained | Playwright (already installed) |
| `weasyprint` for image output | Renders to PDF, not PNG directly. Extra conversion step. Doesn't support modern CSS well. | Playwright |
| `selenium` | Heavier, slower, requires separate WebDriver. Playwright is faster and already in the image. | Playwright |
| `markdown2image` PyPI package | Thin wrapper around Playwright; adds a dependency for ~10 lines of code | Direct Playwright API |
| Spawning new browser per render | ~2-3s cold start each time | Singleton browser with page-per-render |

---

## Supporting Libraries Summary

### New Dependencies to Add

| Library | Version | Purpose | Size Impact |
|---------|---------|---------|-------------|
| `structlog` | >= 25.1.0 | Structured logging with async context | ~200KB, pure Python |
| `cronsim` | >= 2.6 | Cron expression parsing for scheduler | ~30KB, pure Python, no deps |

### Existing Dependencies to Update

| Library | Current | Recommended | Why |
|---------|---------|-------------|-----|
| `lancedb` | >= 0.25.0 | >= 0.28.0, < 1.0 | merge_insert improvements, compact_files API |

### Dependencies Already Present (no changes needed)

| Library | Used For |
|---------|----------|
| `playwright` (1.58.0) | Text-to-image rendering (already in Docker image) |
| `markdown-it-py` (>= 3.0) | Markdown to HTML (already in Docker image) |
| `Jinja2` (>= 3.1) | HTML templates (already in Docker image) |

---

## Build In-House (Not External Libraries)

| Component | ~LOC | Why Not a Library |
|-----------|------|-------------------|
| Plugin Reconciler | ~200-300 | Domain-specific desired-state logic; no generic library fits |
| AsyncScheduler | ~150-200 | APScheduler 4 unstable, 3.x sync-first; custom asyncio scheduler is trivial with `cronsim` |
| Unified message tool | ~150 | Tool definition is AcaBot-specific; no generic library |
| PlaywrightRenderer | ~80-100 | Thin wrapper around Playwright async API |
| LanceDB integrity layer | ~100 | Wrapper adding lock + backup + validation around existing storage.py |

---

## Installation

```bash
# New core dependencies (add to pyproject.toml [dependencies])
uv pip install "structlog>=25.1.0" "cronsim>=2.6"

# Update existing (in pyproject.toml)
# lancedb >= 0.28.0, < 1.0  (was >= 0.25.0)

# No new Dockerfile changes needed — Playwright, markdown-it-py, Jinja2 already present
```

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `structlog >= 25.1` | Python 3.8+ | Uses `contextvars` (stdlib since 3.7). Supports Python 3.14. |
| `cronsim >= 2.6` | Python 3.8+ | Pure Python, no C extensions. Timezone via `zoneinfo`. |
| `lancedb 0.28-0.30` | `pyarrow >= 18.0` | Already satisfied by current `pyarrow` pin |
| `playwright 1.58` | Chromium 131+ | Docker image bundles matching Chromium |

---

## Sources

- [structlog PyPI](https://pypi.org/project/structlog/) — v25.5.0 confirmed latest (Oct 2025)
- [structlog docs](https://www.structlog.org/) — stdlib integration, contextvars, AsyncBoundLogger
- [cronsim PyPI](https://pypi.org/project/cronsim/) — v2.6 confirmed, used by Home Assistant & Healthchecks.io
- [croniter unmaintained notice](https://github.com/pallets-eco/croniter) — abandoned Dec 2024, EU CRA
- [APScheduler version history](https://apscheduler.readthedocs.io/en/master/versionhistory.html) — 4.0.0a6 still alpha, no stable release
- [LanceDB PyPI](https://pypi.org/project/lancedb/) — v0.30.1 confirmed (March 2026)
- [LanceDB tables guide](https://github.com/lancedb/lancedb/blob/main/docs/src/guides/tables.md) — concurrent access, merge_insert, compact_files
- [Playwright Python PyPI](https://pypi.org/project/playwright/) — v1.58.0 confirmed (Jan 2026)
- [Playwright Python docs](https://playwright.dev/python/docs/screenshots) — screenshot API reference
- `docs/29-plugin-control-plane.md` — existing plugin reconciler design (internal)

---
*Stack research for: AcaBot runtime infrastructure hardening*
*Researched: 2026-04-02*
