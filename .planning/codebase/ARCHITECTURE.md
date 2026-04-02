# AcaBot Architecture

## Pattern

**Layered pipeline with config-driven routing and pluggable subsystems.**

AcaBot is an agentic chatbot runtime that receives platform events through a gateway, routes them through a session-config decision engine, executes an LLM-powered agent pipeline with tool calling, and delivers responses back through the gateway. The architecture follows an inversion-of-control pattern where all components are assembled by a single bootstrap function and connected via protocol/ABC interfaces rather than concrete imports.

---

## Runtime Mainline (Request Data Flow)

```
Gateway (NapCatGateway)
  │  StandardEvent
  ▼
RuntimeApp.handle_event()
  │  route + create RunContext
  ▼
RuntimeRouter.route()
  │  delegates to SessionRuntime
  ▼
SessionRuntime
  │  EventFacts → SessionConfig → surface resolution
  │  → 7 domain decisions (routing, admission, context,
  │     persistence, extraction, computer, routing)
  │  returns RouteDecision
  ▼
RuntimeApp (continued)
  │  load agent, resolve model, open Run, persist event
  │  build RunContext
  ▼
ThreadPipeline.execute()
  │
  ├─ 1. Plugin hooks (ON_EVENT)
  ├─ 2. ComputerRuntime.prepare_run_context()
  ├─ 3. MessagePreparationService.prepare()
  ├─ 4. Append incoming message to thread working memory
  ├─ 5. ContextCompactor.compact() — token-aware truncation/summarization
  ├─ 6. RetrievalPlanner.prepare() → RetrievalPlan
  ├─ 7. MemoryBroker.retrieve() → MemoryBlock[]
  ├─ 8. Plugin hooks (PRE_AGENT)
  ├─ 9. AgentRuntime.execute() → AgentRuntimeResult
  │     └─ ModelAgentRuntime
  │         ├─ ToolRuntimeResolver → ToolRuntime (tools + executor)
  │         ├─ ContextAssembler.assemble() → system_prompt + messages
  │         └─ BaseAgent.run() → AgentResponse (with tool loop)
  ├─ 10. Plugin hooks (POST_AGENT, BEFORE_SEND)
  ├─ 11. Outbox.dispatch() → send via Gateway, persist to MessageStore
  ├─ 12. Plugin hooks (ON_SENT)
  └─ 13. Update thread working memory, finish Run
```

---

## Layers

### 1. Gateway Layer
Translates between platform-specific protocols and internal `StandardEvent`/`Action` types.

| Component | File | Role |
|-----------|------|------|
| `GatewayProtocol` | `src/acabot/runtime/gateway_protocol.py` | Structural protocol — the runtime-facing contract |
| `BaseGateway` | `src/acabot/gateway/base.py` | ABC with `start/stop/send/on_event/call_api` |
| `NapCatGateway` | `src/acabot/gateway/napcat.py` | OneBot v11 reverse-WebSocket implementation |
| OneBot message utils | `src/acabot/gateway/onebot_message.py` | Segment parsing, text extraction, attachment mapping |

### 2. Routing & Session Layer
Config-driven decision engine that maps every inbound event to a full `RouteDecision`.

| Component | File | Role |
|-----------|------|------|
| `RuntimeRouter` | `src/acabot/runtime/router.py` | Thin facade: event → SessionRuntime → RouteDecision |
| `SessionRuntime` | `src/acabot/runtime/control/session_runtime.py` | Core decision engine: facts → session → surface → 7 domain decisions |
| `SessionConfigLoader` | `src/acabot/runtime/control/session_loader.py` | Loads YAML session configs from `runtime_config/sessions/` |
| `SessionBundleLoader` | `src/acabot/runtime/control/session_bundle_loader.py` | Resolves session → agent → prompt bundle |

**Decision domains** resolved per-event from `SessionConfig` surfaces:
- **Routing** — which agent handles this event
- **Admission** — `respond` / `record_only` / `silent_drop`
- **Context** — retrieval tags, sticky note targets, context labels
- **Persistence** — whether to persist the inbound event
- **Extraction** — long-term memory tags
- **Computer** — backend, exec policy, workspace roots, visible skills

### 3. Orchestration Layer (RuntimeApp + ThreadPipeline)
The runtime's two-level execution model.

| Component | File | Role |
|-----------|------|------|
| `RuntimeApp` | `src/acabot/runtime/app.py` | Top-level event handler; owns gateway lifecycle, run creation, recovery, approval flow |
| `ThreadPipeline` | `src/acabot/runtime/pipeline.py` | Single-run executor: compaction → retrieval → agent → outbox → finalize |
| `RunContext` | `src/acabot/runtime/contracts/context.py` | Mutable bag carrying all state for one run |
| `RunManager` | `src/acabot/runtime/storage/runs.py` | Run lifecycle state machine (queued → running → completed/failed/waiting_approval) |
| `ThreadManager` | `src/acabot/runtime/storage/threads.py` | Thread state persistence (working_messages, working_summary) |

### 4. Agent / Model Layer
Bridges the runtime's `RunContext` to the LLM provider.

| Component | File | Role |
|-----------|------|------|
| `AgentRuntime` (ABC) | `src/acabot/runtime/agent_runtime.py` | Abstract interface: `execute(RunContext) → AgentRuntimeResult` |
| `ModelAgentRuntime` | `src/acabot/runtime/model/model_agent_runtime.py` | Production impl: prompt loading → context assembly → tool resolution → BaseAgent.run() → result normalization |
| `BaseAgent` (ABC) | `src/acabot/agent/base.py` | LLM call contract: `run(system_prompt, messages, model, tools, tool_executor)` |
| `LitellmAgent` | `src/acabot/agent/agent.py` | Concrete agent using litellm for multi-provider LLM calls |
| `ContextAssembler` | `src/acabot/runtime/context_assembly/assembler.py` | Merges base prompt + memory blocks + history + tool reminders into final model input |
| `ToolRuntime` / `ToolRuntimeResolver` | `src/acabot/runtime/model/model_agent_runtime.py` | Per-run tool schema + executor, resolved by ToolBroker |
| `ModelRegistry` | `src/acabot/runtime/model/model_registry.py` | Runtime model binding management (providers, presets, bindings) |
| Model resolution | `src/acabot/runtime/model/model_resolution.py` | Resolves agent → model request per run |

### 5. Memory System
Three-tier memory: working memory (thread), structured memory (sticky notes, soul), long-term memory (LTM).

| Component | File | Role |
|-----------|------|------|
| `ContextCompactor` | `src/acabot/runtime/memory/context_compactor.py` | Token-aware truncation + LLM-driven summarization of thread history |
| `RetrievalPlanner` | `src/acabot/runtime/memory/retrieval_planner.py` | Builds `RetrievalPlan` from compaction output + session context config |
| `MemoryBroker` | `src/acabot/runtime/memory/memory_broker.py` | Fan-out retrieval across registered `MemorySource` implementations |
| `MemorySourceRegistry` | `src/acabot/runtime/memory/memory_broker.py` | Registry of named memory sources with per-source policy |
| `SoulSource` | `src/acabot/runtime/soul/source.py` | `/self` file-backed identity memory (today.md, daily/) |
| `StickyNoteFileStore` | `src/acabot/runtime/memory/file_backed/sticky_notes.py` | File-backed per-scope sticky notes |
| `StickyNoteService` | `src/acabot/runtime/memory/sticky_notes.py` | Controlled read/write service for sticky notes |
| `StickyNoteRenderer` | `src/acabot/runtime/memory/sticky_note_renderer.py` | Renders sticky notes into prompt-injectable text |
| `LtmMemorySource` | `src/acabot/runtime/memory/long_term_memory/` | Embedding-based semantic search over extracted conversation facts |
| `LongTermMemoryIngestor` | `src/acabot/runtime/memory/long_term_ingestor.py` | Background async writer: conversation facts → embedding store |
| `ConversationFactReader` | `src/acabot/runtime/memory/conversation_facts.py` | Reads conversation deltas from event/message stores |

**Memory retrieval flow:**
```
ThreadPipeline
  → ContextCompactor (compress working memory)
  → RetrievalPlanner (build RetrievalPlan)
  → MemoryBroker.retrieve()
      ├─ SoulSource (identity/self context)
      ├─ StickyNoteFileStore (scoped structured notes)
      └─ LtmMemorySource (semantic search)
  → MemoryBlock[] → ContextAssembler (slot into prompt)
```

### 6. Tool System (ToolBroker)
Unified tool registration, policy enforcement, execution, and audit.

| Component | File | Role |
|-----------|------|------|
| `ToolBroker` | `src/acabot/runtime/tool_broker/broker.py` | Central registry: register/unregister tools, build ToolRuntime per run, execute tool calls |
| `ToolPolicy` | `src/acabot/runtime/tool_broker/policy.py` | Per-tool approval/deny decisions |
| `ToolAudit` | `src/acabot/runtime/tool_broker/policy.py` | Tool execution audit trail |
| `ToolExecutionContext` | `src/acabot/runtime/tool_broker/contracts.py` | Rich context passed to runtime tool handlers |

**Built-in tools** registered by `src/acabot/runtime/builtin_tools/__init__.py`:
- `computer` tools — `src/acabot/runtime/builtin_tools/computer.py` (read/write/edit/bash)
- `skills` tools — `src/acabot/runtime/builtin_tools/skills.py` (list/load/run skills)
- `sticky_notes` tools — `src/acabot/runtime/builtin_tools/sticky_notes.py` (read/write notes)
- `subagents` tools — `src/acabot/runtime/builtin_tools/subagents.py` (delegate to sub-agents)

### 7. Computer Subsystem
Sandboxed workspace and command execution per thread.

| Component | File | Role |
|-----------|------|------|
| `ComputerRuntime` | `src/acabot/runtime/computer/runtime.py` | Unified entry: workspace prep, file read/write/edit, bash exec, session management, skill mirroring |
| `WorkspaceManager` | `src/acabot/runtime/computer/workspace.py` | Host filesystem layout: per-thread workspace/attachments/skills dirs |
| `WorkWorldBuilder` | `src/acabot/runtime/computer/world.py` | Builds virtual "Work World" view with root policies (workspace/skills/self visibility) |
| `HostComputerBackend` | `src/acabot/runtime/computer/backends.py` | Direct host execution backend |
| `DockerSandboxBackend` | `src/acabot/runtime/computer/backends.py` | Docker container sandbox backend |
| `RemoteComputerBackend` | `src/acabot/runtime/computer/backends.py` | Remote execution backend |
| `AttachmentResolver` | `src/acabot/runtime/computer/attachments.py` | Downloads and stages inbound attachments to workspace |
| Contracts | `src/acabot/runtime/computer/contracts.py` | `ComputerBackend` ABC, `ComputerPolicy`, `CommandExecutionResult`, etc. |

### 8. Outbox (Delivery)

| Component | File | Role |
|-----------|------|------|
| `Outbox` | `src/acabot/runtime/outbox.py` | Sends `PlannedAction` list via Gateway, persists successful assistant messages to `MessageStore`, notifies LTM ingestor |

### 9. Plugin System

| Component | File | Role |
|-----------|------|------|
| `RuntimePlugin` (ABC) | `src/acabot/runtime/plugin_manager.py` | Plugin lifecycle: `setup() → hooks() + tools() + runtime_tools() → teardown()` |
| `RuntimePluginManager` | `src/acabot/runtime/plugin_manager.py` | Load/unload/reload plugins, manage hook registry, proxy tool registration to ToolBroker |
| `RuntimeHookRegistry` | `src/acabot/runtime/plugin_manager.py` | Priority-sorted hooks at 6 pipeline points |
| Built-in plugins | `src/acabot/runtime/plugins/` | `napcat_tools`, `ops_control`, `reference_tools`, `backend_bridge_tool` |

**Hook points:** `ON_EVENT → PRE_AGENT → POST_AGENT → BEFORE_SEND → ON_SENT → ON_ERROR`

### 10. Control Plane

| Component | File | Role |
|-----------|------|------|
| `RuntimeControlPlane` | `src/acabot/runtime/control/control_plane.py` | Runtime introspection: status, thread/run queries, model/plugin/skill/subagent management |
| `RuntimeConfigControlPlane` | `src/acabot/runtime/control/config_control_plane.py` | Config-driven hot-reload: agents, models, plugins, prompts |
| `RuntimeHttpApiServer` | `src/acabot/runtime/control/http_api.py` | HTTP API exposing control plane to webui |

### 11. Storage Layer
All stores are abstract (ABC) with in-memory and SQLite implementations.

| Store Interface | File | Implementations |
|-----------------|------|-----------------|
| `ChannelEventStore` | `src/acabot/runtime/storage/stores.py` | `InMemoryChannelEventStore`, `SQLiteChannelEventStore` |
| `MessageStore` | `src/acabot/runtime/storage/stores.py` | `InMemoryMessageStore`, `SQLiteMessageStore` |
| `ThreadStore` | `src/acabot/runtime/storage/stores.py` | `SQLiteThreadStore` |
| `RunStore` | `src/acabot/runtime/storage/stores.py` | `SQLiteRunStore` |
| `ThreadManager` | `src/acabot/runtime/storage/threads.py` | `InMemoryThreadManager`, `StoreBackedThreadManager` |
| `RunManager` | `src/acabot/runtime/storage/runs.py` | `InMemoryRunManager`, `StoreBackedRunManager` |

---

## Key Abstractions

| Abstraction | Purpose |
|-------------|---------|
| `StandardEvent` | Platform-agnostic inbound event (message, notice) |
| `Action` / `ActionType` | Platform-agnostic outbound action (SEND_TEXT, SEND_SEGMENTS, etc.) |
| `EventFacts` | Stable derived facts from a StandardEvent for matcher evaluation |
| `SessionConfig` / `SurfaceConfig` | Declarative per-channel config with surface-based domain decisions |
| `RouteDecision` | Complete routing + policy decision for one event |
| `RunContext` | Mutable execution bag for one run (event, decision, thread, agent, model, memory, actions, response) |
| `ResolvedAgent` | Frozen agent snapshot for one run (agent_id, prompt_ref, name, config, skills, computer_policy) |
| `AgentRuntimeResult` | Normalized result from agent execution (status, text, actions, tool_calls, approval) |
| `PlannedAction` | Action + thread_content + commit_when policy for outbox delivery |
| `MemoryBlock` | Unified memory retrieval unit with target slot + priority for assembly |
| `RetrievalPlan` | Bridge between compaction output and memory retrieval input |
| `ToolRuntime` | Per-run tool schema list + executor, resolved by ToolBroker |
| `ComputerPolicy` | Per-run sandbox policy (backend, exec, sessions, network) |
| `PendingApproval` | Approval gate for dangerous tool calls |

---

## Entry Points

| Entry | File | Description |
|-------|------|-------------|
| CLI main | `src/acabot/main.py` → `main()` | `asyncio.run(_run())`: load config → build components → start app + HTTP server → wait for signal |
| Bootstrap | `src/acabot/runtime/bootstrap/__init__.py` → `build_runtime_components()` | Single function assembling all runtime components with dependency injection |
| HTTP API | `src/acabot/runtime/control/http_api.py` | Aiohttp server exposing control plane |
| WebUI | `webui/` | Vite + TypeScript frontend |

---

## Cross-Cutting Concerns

- **Config:** `src/acabot/config.py` — YAML-based `Config` with path resolution relative to config file
- **Types:** `src/acabot/types/` — `StandardEvent`, `EventSource`, `Action`, `ActionType` shared across all layers
- **Contracts:** `src/acabot/runtime/contracts/` — All runtime dataclasses split across `common.py`, `context.py`, `records.py`, `routing.py`, `session_config.py`, `session_agent.py`
- **Logging:** Structured `logging.getLogger("acabot.*")` throughout with in-memory log buffer for webui
- **Concurrency:** Thread-level `asyncio.Lock` for working memory mutations; background ingestor for LTM writes

---

## Backend Bridge (Admin)

A secondary pathway for admin commands that bypasses the normal pipeline:

```
Gateway → RuntimeApp._handle_backend_entrypoint()
  → BackendModeRegistry (enter/exit maintain mode)
  → BackendBridge.handle_admin_direct()
  → Direct reply via Gateway (no Run, no Outbox)
```

Files: `src/acabot/runtime/backend/bridge.py`, `src/acabot/runtime/backend/session.py`, `src/acabot/runtime/backend/mode_registry.py`, `src/acabot/runtime/backend/pi_adapter.py`

---

## Subagent System

| Component | File | Role |
|-----------|------|------|
| `SubagentCatalog` | `src/acabot/runtime/subagents/catalog.py` | Discovery and manifest loading |
| `SubagentDelegationBroker` | `src/acabot/runtime/subagents/broker.py` | Validates and dispatches delegation requests |
| `LocalSubagentExecutionService` | `src/acabot/runtime/subagents/execution.py` | Executes child run through same ThreadPipeline |
| Package loader | `src/acabot/runtime/subagents/loader.py` + `package.py` | Filesystem-based subagent package discovery |

---

## Skills System

| Component | File | Role |
|-----------|------|------|
| `SkillCatalog` | `src/acabot/runtime/skills/catalog.py` | Central skill registry |
| `FileSystemSkillPackageLoader` | `src/acabot/runtime/skills/loader.py` | Discovers skill packages from filesystem |
| `SkillPackageManifest` | `src/acabot/runtime/skills/package.py` | Parsed skill package definition |
