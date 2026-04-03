# Feature Research

**Domain:** Agentic chatbot runtime infrastructure (plugin management, messaging, scheduling, observability, data safety, knowledge backends)
**Researched:** 2026-04-02
**Confidence:** HIGH (based on mature ecosystem analysis: NoneBot2, Koishi, LangChain/LangSmith, APScheduler, LanceDB docs, plus AcaBot codebase review)

---

## Feature Landscape

### Table Stakes (Users Expect These)

#### 1. Plugin Management

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Plugin install/uninstall via API | Every extensible platform (NoneBot2, Koishi, Home Assistant) has this | MEDIUM | AcaBot has `extensions/plugins/` but it never worked. Reconciler plan in docs/29 is the right fix. |
| Plugin enable/disable toggle | Non-destructive way to turn off misbehaving plugins; preserve config | LOW | Spec-level `enabled` flag, no code unload needed |
| Plugin config via WebUI | Operators won't edit YAML for plugin settings | MEDIUM | Needs schema declaration per plugin (JSON Schema or typed dataclass) |
| Plugin lifecycle hooks (setup/teardown) | Standard in every plugin system | LOW | Already exists as `RuntimePlugin.setup()/teardown()` ABC |
| Stable plugin identity (plugin_id) | Config/UI references must survive code refactors | LOW | Currently uses import path — fragile. Switch to declared `plugin_id` string. |
| Plugin error isolation | One bad plugin must not crash the runtime | MEDIUM | Try/except around hook calls + status reporting. Partially exists. |
| Persistent plugin state across restarts | Plugins need data dirs that survive restarts | LOW | Provide `plugin_data_dir` per plugin (already have runtime_data/) |

#### 2. Message/Action Tools

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Text reply | Fundamental — already works | LOW | Existing |
| Quote/reply-to specific message | Standard in all IM bots | LOW | OneBot v11 `reply` segment; need message_id tracking |
| Image sending (URL or file) | All mature IM bots support media | LOW | OneBot v11 `image` segment; needs tool exposure |
| @mention in reply | Expected for group contexts | LOW | OneBot v11 `at` segment |
| Message recall/delete | Clean up bot mistakes | LOW | OneBot v11 `delete_msg` API |
| Silent/record-only mode | Bot listens without replying in some contexts | LOW | Already in RouteDecision (admission: record_only/silent_drop) |

#### 3. Scheduler/Cron

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Periodic/cron tasks | Every bot framework offers this (NoneBot2 `nonebot-plugin-apscheduler`, Koishi `ctx.cron()`) | MEDIUM | APScheduler 3.x asyncio integration is the standard Python approach |
| One-shot delayed tasks | "Remind me in 30 min" is basic bot functionality | LOW | `scheduler.add_job(trigger='date')` |
| Task persistence across restarts | Scheduled reminders must survive restarts | MEDIUM | APScheduler `SQLAlchemyJobStore` or custom SQLite store |
| Task cancellation | Cancel scheduled tasks by ID | LOW | Standard scheduler API |
| Graceful shutdown (drain running tasks) | No orphaned coroutines on bot restart | MEDIUM | `scheduler.shutdown(wait=True)` + timeout |

#### 4. Observability/Logging

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Tool call logging (name, args, result summary, duration) | Operators need to debug agent behavior | MEDIUM | ToolBroker has `ToolAudit`; needs structured emission and surfacing |
| LLM token usage per run (input/output/total) | Cost monitoring is table stakes for LLM apps | LOW | litellm returns usage in response. Capture and aggregate. |
| Error logging with context (run_id, thread_id, plugin_id) | Structured debugging | LOW | Add structured fields to existing `logging.getLogger("acabot.*")` |
| Request/run latency metrics | Performance monitoring | LOW | Timestamp at pipeline entry/exit. Run state machine already exists. |
| Log viewing in WebUI | Operators won't SSH to read log files | MEDIUM | In-memory log buffer exists. Needs filtering/search. |

#### 5. Vector DB Data Safety (LanceDB)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Atomic/crash-safe writes | Data must not corrupt on crash | LOW | Lance format uses append-only manifests; inherently safe for completed writes. Verify incomplete-write handling. |
| Concurrent access protection | Background ingestor + query reads must not corrupt | MEDIUM | LanceDB Python not thread-safe by default; need asyncio Lock or single-writer pattern |
| Backup/snapshot capability | Operators expect to restore from data loss | LOW | Lance files are just directories; `cp -r`/`rsync` works. Add automated backup. |
| Data integrity validation on startup | Detect corruption before it causes silent failures | LOW | Row count checks, manifest validation |

#### 6. Reference/Knowledge Backend (RAG general)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Semantic search over stored knowledge | Core RAG pattern; table stakes for knowledge-augmented LLM | HIGH | Already have LTM with LanceDB — this IS the infrastructure |
| Source attribution | Users need to know where information came from | LOW | Return source metadata with retrieval results |

---

### Differentiators (Competitive Advantage)

#### 1. Plugin Management

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Hot reload without restart | Change plugin code without downtime; critical for single-instance bots | HIGH | Python module reload is fragile (stale refs, class identity). Reconciler "unload old + load new" is safer than true HMR. NoneBot2 has basic support; Koishi has full HMR. |
| Reconciler pattern (Package/Spec/Status) | Declarative desired-state model (like K8s) makes WebUI management robust; self-healing | HIGH | docs/29 design. Architecturally rare for chatbot runtimes — most use imperative load/unload. |
| Plugin health/status dashboard | Real-time view of state, error counts, last activity | LOW | Natural output of Reconciler Status model |
| Plugin resource usage tracking | See which plugins consume most tokens/time | MEDIUM | Requires per-plugin attribution in observability layer |

#### 2. Message/Action Tools

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Unified `message` tool (single tool, multiple actions) | LLM picks from reply/react/quote/media in one tool; reduces tool explosion | MEDIUM | Key design: one `message` tool with action param vs. separate tools per action |
| Cross-session messaging | Bot proactively messages different groups/users (e.g., notify admin, post to channel) | MEDIUM | Gateway supports target addressing; needs tool exposure. Required for scheduler notifications. |
| Text-to-image rendering (Playwright) | Rich formatted output bypassing platform text limits; rare in QQ bots | MEDIUM | Playwright + Chromium planned; `render_markdown_to_image()` in Outbox |
| Reaction/emoji response | Lightweight acknowledgment without full reply | LOW | NapCat `set_msg_emoji_like` extension API |
| Contextual action awareness | Agent knows what actions are available in current context (group vs DM) | LOW | Filter available actions by session context |

#### 3. Scheduler/Cron

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Plugin-lifecycle-bound scheduling | Auto-cancel all jobs when plugin unloads; prevents orphan timers | MEDIUM | Tag jobs with `plugin_id`, bulk cancel on teardown. Unique to runtime-aware schedulers. |
| Schedule-triggered agent runs | Cron triggers full agent pipeline (not just a callback); bot "wakes up" with full capability | MEDIUM | Powerful: proactive agent behavior on schedule. Needs isolated session context. |
| Natural language schedule creation | "Every weekday at 9am" via LLM | LOW | LLM parses to cron expression; just needs tool exposure |

#### 4. Observability/Logging

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Full run trace (pipeline spans) | See entire pipeline: compaction → retrieval → agent → outbox with timing | HIGH | OpenTelemetry-style spans. Lightweight custom tracing better than full OTel for single bot. |
| Memory operation tracing | See LTM/sticky/soul retrieval, what was injected into prompt | MEDIUM | Unique to memory-augmented agents; LangSmith doesn't trace memory architecture |
| Token budget visualization | See context window allocation (system prompt, memory, history, tools) | LOW | ContextAssembler already has this data; just needs emission |
| Per-session cost tracking | "How much does this chat cost me?" | LOW | Aggregate token usage by thread_id |
| Plugin execution time tracking | Identify slow plugins degrading response time | LOW | Wrap hook calls with timing. Surface in plugin status. |

#### 5. Vector DB Data Safety

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Versioned data with rollback | Undo bad mass-ingestion or embedding model change | MEDIUM | Lance format supports versioning natively. Expose `checkout(version)` in admin API. |
| Graceful degradation on corruption | Bot continues working (without LTM) if vector DB is damaged | MEDIUM | MemoryBroker catches LanceDB exceptions, returns empty results. Don't crash pipeline. |
| Automatic compaction | Lance fragments degrade read performance over time | LOW | Periodic `compact_files()` call. Tie to scheduler. |

---

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Plugin marketplace/registry | "Like npm for bot plugins" | Massive scope: hosting, review, trust model. Single-operator bot doesn't need ecosystem. | Git/pip install + WebUI management |
| Plugin sandboxing/permissions | "Plugins shouldn't access filesystem" | Python has no real sandboxing; false security sense. Single-operator bot = trusted plugins. | Trust at install time. Error isolation (not security isolation). |
| Plugin-to-plugin direct messaging bus | "Plugin composition" | Creates coupling, debugging nightmares, ordering issues | Shared services via ToolBroker + hook points |
| Auto-update plugins from remote | "Convenience" | Uncontrolled code changes to running bot | Manual update via WebUI with diff preview |
| Full rich-text editor in agent tool | "Beautiful formatting" | LLMs generate markdown, not platform rich text. Translation is fragile. | Markdown input + text-to-image for complex formatting |
| Voice/TTS message sending | "Multimodal" | Audio synthesis dependency, large binary handling. Out of scope for text-first bot. | Defer to v2+ if voice use cases emerge |
| Interactive message components (buttons/forms) | "Rich interactions" | Platform-dependent, breaks agent's text reasoning model | Text-based interaction; sticky notes for state |
| Distributed scheduler (multi-node) | "Scale out" | Single-instance Docker. Distributed scheduling (Redlock/etcd) adds zero value. | Single-process APScheduler with SQLite store |
| Sub-second scheduling precision | "Real-time" | asyncio not real-time. Sub-second cron is meaningless for chat bots. | 1-minute minimum granularity. Use event hooks for real-time. |
| Real-time log streaming (WebSocket) | "Live tail in browser" | Complex for rarely-used feature; SSE/polling is 95% as good | Polling-based log viewer (2-5s refresh) |
| Full OpenTelemetry integration | "Export to Datadog/Jaeger" | Infra overhead for single-operator deployment | Structured JSON logging; optional OTLP export as future add |
| Full prompt/response logging by default | "See everything" | Privacy risk, massive storage, PII in logs | Opt-in debug mode per session. Default to metadata-only. |
| Full RAG document upload pipeline | "Knowledge base management" | Massive scope (PDF parsing, chunking strategies). AcaBot knowledge comes from conversations + workspace files. | LTM for conversation knowledge. Computer subsystem reads files. Delegate to external RAG service if needed. |
| Knowledge base CRUD UI | "Manage reference documents" | Document management UI is a product in itself (Dify, FastGPT) | Operator manages files via workspace. Bot reads with computer tools. |
| Reference Backend (existing) | "Structured knowledge base" | Design fundamentally flawed per PROJECT.md; redundant with LTM | Delete. LTM + sticky notes + soul source cover all needs. Future structured KB = plugin registering as `MemorySource`. |
| Replication to remote vector DB | "High availability" | Single-instance bot. LanceDB embedded = no network latency, no infra. | File-level backup to remote storage |
| Migration to Milvus/Weaviate/Pinecone | "Production-grade" | Adds network dependency, ops burden, cost. LanceDB embedded is perfect fit. | Stay embedded. LanceDB is sufficient. |

---

## Feature Dependencies

```
[Plugin Identity (plugin_id)]
    └── enables ──> [Plugin Config via WebUI]
    └── enables ──> [Plugin Reconciler (Spec/Status)]
                        └── enables ──> [Plugin Hot Reload]
                        └── enables ──> [Plugin Health Dashboard]
    └── enables ──> [Plugin-Lifecycle-Bound Scheduling]

[Unified Message Tool]
    └── requires ──> [Message ID Tracking]
    └── requires ──> [Gateway Action Type Expansion]
    └── enables ──> [Cross-Session Messaging]
                        └── enables ──> [Cron-Triggered Notifications]
    └── enables ──> [Text-to-Image] ── requires ──> [Playwright Integration]

[Scheduler Infrastructure]
    └── requires ──> [Persistent Job Store (SQLite)]
    └── enhances ──> [LanceDB Auto-Compaction]
    └── enhances ──> [LanceDB Periodic Backup]
    └── requires ──> [Plugin Identity] (for lifecycle-bound scheduling)

[Observability]
    └── requires ──> [Trace ID Propagation]
    └── requires ──> [litellm Callback Integration]
    └── enhances ──> [Plugin Management] (health/resource tracking)

[LanceDB Data Safety]
    └── requires ──> [Concurrent Write Protection (asyncio Lock)]
    └── enhanced-by ──> [Scheduler] (periodic backups, compaction)
    └── enables ──> [Graceful Degradation]

[Delete Reference Backend] ── independent (no dependencies)
```

### Dependency Notes

- **Cross-session messaging requires unified message tool:** Can't target arbitrary sessions without generalized message dispatch.
- **Plugin-lifecycle-bound scheduling requires both scheduler + plugin_id:** Need to tag jobs with plugin identity to auto-cancel on unload.
- **Cron notifications require scheduler + cross-session messaging:** Primary use case for scheduled tasks is "send message to chat X at time Y."
- **LanceDB compaction requires scheduler:** Periodic maintenance is a natural scheduler consumer.
- **Text-to-image requires Playwright:** Already planned as Docker image dependency.
- **LanceDB concurrent protection is prerequisite:** Must be in place before any other LTM improvements.
- **Delete Reference Backend is independent:** No dependencies on other features; can be done anytime.

---

## MVP Definition

### Launch With (v1)

**Plugin System:**
- [ ] Plugin identity (`plugin_id`) — foundation for all plugin features
- [ ] Plugin install/uninstall via API + WebUI — core management
- [ ] Plugin enable/disable toggle — non-destructive control
- [ ] Plugin error isolation — one bad plugin can't crash runtime
- [ ] Plugin config persistence — config survives restarts

**Message Tool:**
- [ ] Unified `message` tool (reply, quote, mention, media) — complete agent communication
- [ ] Cross-session messaging — required for scheduler notifications

**Scheduler:**
- [ ] Cron + one-shot task registration — basic scheduling
- [ ] Persistence across restarts — tasks must survive restarts
- [ ] Plugin-lifecycle-bound scheduling — auto-cleanup on unload
- [ ] Graceful shutdown — no orphaned tasks

**Observability:**
- [ ] Tool call logging with structured fields — minimum debuggability
- [ ] LLM token usage per run — cost visibility
- [ ] Error logging with run context — structured debugging

**Data Safety:**
- [ ] LanceDB concurrent write protection — prevent corruption
- [ ] Backup script/command — recovery capability
- [ ] Graceful degradation on LTM failure — don't crash if vector DB is broken

**Cleanup:**
- [ ] Delete Reference Backend — remove dead code

### Add After Validation (v1.x)

- [ ] Plugin config UI in WebUI — once schema declaration pattern is established
- [ ] Plugin hot reload — once Reconciler is stable; fragile if too early
- [ ] Text-to-image rendering — once Playwright integrated + message tool stable
- [ ] Full run trace view in WebUI — once structured logging emits trace data
- [ ] Per-session cost tracking — once token logging captures counts
- [ ] Schedule-triggered agent runs — once scheduler + pipeline integration proven
- [ ] LanceDB versioned rollback — once concurrent protection is in place
- [ ] Token budget visualization — once LLM call logging is solid

### Future Consideration (v2+)

- [ ] Conversation replay/debug — HIGH complexity; needs storage + UI
- [ ] Plugin resource usage tracking — needs mature observability first
- [ ] Plugin dependency resolution — only when plugins start composing
- [ ] Plugin marketplace — only when community of plugin authors exists
- [ ] Forward/合并转发 messages — complex OneBot construction; niche
- [ ] OpenTelemetry export — only if operator needs external observability

---

## Feature Prioritization Matrix

| Feature | User Value | Impl Cost | Priority |
|---------|------------|-----------|----------|
| Plugin identity (plugin_id) | HIGH | LOW | P1 |
| Plugin install/uninstall API | HIGH | MEDIUM | P1 |
| Plugin enable/disable | HIGH | LOW | P1 |
| Plugin error isolation | HIGH | MEDIUM | P1 |
| Plugin config persistence | HIGH | LOW | P1 |
| Unified message tool (reply/quote/image/mention/recall) | HIGH | MEDIUM | P1 |
| Cross-session messaging | HIGH | MEDIUM | P1 |
| Scheduler (cron + one-shot + persistence) | HIGH | MEDIUM | P1 |
| Plugin-lifecycle-bound scheduling | MEDIUM | MEDIUM | P1 |
| Tool call + LLM call logging | HIGH | MEDIUM | P1 |
| LanceDB concurrent write protection | HIGH | LOW | P1 |
| LanceDB backup capability | MEDIUM | LOW | P1 |
| Graceful degradation on LTM failure | MEDIUM | MEDIUM | P1 |
| Delete Reference Backend | MEDIUM | LOW | P1 |
| Plugin config UI (WebUI) | MEDIUM | MEDIUM | P2 |
| Plugin hot reload | MEDIUM | HIGH | P2 |
| Text-to-image rendering | MEDIUM | MEDIUM | P2 |
| Reaction/emoji response | LOW | LOW | P2 |
| Per-run trace view | MEDIUM | HIGH | P2 |
| Token budget visualization | LOW | LOW | P2 |
| Per-session cost tracking | LOW | LOW | P2 |
| Schedule-triggered agent runs | MEDIUM | MEDIUM | P2 |
| LanceDB compaction | LOW | LOW | P2 |
| LanceDB versioned rollback | LOW | MEDIUM | P3 |
| Conversation replay/debug | MEDIUM | HIGH | P3 |
| Plugin dependency resolution | LOW | MEDIUM | P3 |
| Plugin marketplace | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for this milestone
- P2: Should have, add when possible
- P3: Nice to have, future milestone

---

## Competitor Feature Analysis

| Feature | NoneBot2 | Koishi | AcaBot (planned) |
|---------|----------|--------|-------------------|
| Plugin install | `nb plugin install` CLI + marketplace | `yarn add` + marketplace UI | API + WebUI + Reconciler |
| Plugin hot reload | Module reimport (fragile) | Full HMR with dependency tracking | Reconciler unload/load cycle (deferred) |
| Plugin config | `.env` + pydantic models | YAML + schema-driven UI | Plugin-declared schema + WebUI form |
| Plugin dependencies | `require("plugin_name")` | `ctx.inject()` | Declared manifest, topological load (deferred) |
| Scheduler | `nonebot-plugin-apscheduler` (community) | `ctx.cron()` built-in | Built-in APScheduler-based infra |
| Message capabilities | Rich segment model (CQ codes) | Universal message elements | Unified `message` tool for LLM agent |
| Cross-session send | `bot.send()` to arbitrary target | `ctx.broadcast()` | `message` tool with `target_session` param |
| Observability | Basic logging, community plugins | Console + database logger | Structured logging + WebUI + tool traces |
| LLM integration | Community plugins (varied) | Community plugins | Core pipeline: litellm + ToolBroker + Memory |

| Feature | LangChain/LangSmith | AcaBot (planned) |
|---------|---------------------|-------------------|
| Tool call tracing | LangSmith full trace tree | Structured tool audit + WebUI |
| Token tracking | LangSmith cost dashboard | litellm callbacks + per-run aggregation |
| Memory observability | Shows retriever calls | Memory op tracing (LTM/sticky/soul — unique) |
| RAG/Knowledge | Retrievers + vector stores | LTM (LanceDB) + sticky notes + soul; no separate "reference" |

### Key Insight

NoneBot2 and Koishi are mature **chat frameworks** but not LLM-native. Their plugin systems are well-developed but agent capabilities are bolted on. AcaBot's advantage is that the LLM agent pipeline IS the core architecture — tools, memory, and scheduling are designed around agent needs, not retrofitted. The plugin system should learn from NoneBot2/Koishi's lifecycle management while keeping AcaBot's LLM-first design.

---

## Sources

- NoneBot2 plugin system: `nonebot.dev` — plugin loading, `require()`, marketplace
- Koishi framework: `koishi.chat` — `ctx.plugin()`, `ctx.cron()`, universal message elements
- APScheduler: `apscheduler.readthedocs.io` — asyncio scheduler, job stores, triggers
- LangSmith: `docs.smith.langchain.com` — tracing, token tracking
- LanceDB: `lancedb.github.io/lancedb/` — Lance format, versioning, compaction, concurrent access
- AcaBot: `docs/29-plugin-control-plane.md` — Reconciler architecture plan
- AcaBot: `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`

---
*Feature research for: AcaBot v2 runtime infrastructure*
*Researched: 2026-04-02*
