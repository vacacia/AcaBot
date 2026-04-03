# AcaBot Directory Structure

## Top-Level Layout

```
AcaBot/
├── src/acabot/              # Python runtime source (the codebase)
├── extensions/              # User-space extensions
│   ├── plugins/             # Custom RuntimePlugin packages
│   ├── skills/              # Custom skill packages
│   └── subagents/           # Custom subagent packages
├── runtime_config/          # Live runtime configuration (sessions, agents, prompts, models)
├── runtime_config.example/  # Example runtime_config for reference
├── runtime_data/            # Persistent runtime state (SQLite DBs, workspaces, soul, sticky_notes)
├── webui/                   # Vite + TypeScript control panel frontend
├── tests/                   # Test suite
├── docs/                    # Documentation
├── ref/                     # Reference materials
├── deploy/                  # Deployment scripts
├── config.example.yaml      # Example top-level config
├── .env.example             # Example environment variables
├── pyproject.toml           # Python project metadata (uv/pip)
├── uv.lock                  # Locked dependencies
├── Dockerfile               # Full Docker image
├── Dockerfile.lite          # Minimal Docker image
├── .planning/               # Architecture & planning documents
├── .claude/                 # Claude Code configuration
└── .harness/                # Test harness configuration
```

---

## `src/acabot/` — Core Runtime Source

### Root Package

| File | Purpose |
|------|---------|
| `src/acabot/__init__.py` | Package init |
| `src/acabot/main.py` | **CLI entry point** — `main()` → `asyncio.run(_run())`. Factory functions for gateway/agent/store. Bootstrap assembly. Logging setup. Signal handling. |
| `src/acabot/config.py` | `Config` class — YAML loader, path resolution, reload, save |
| `src/acabot/context.py` | Shared context utilities |

### `src/acabot/types/` — Shared Domain Types

| File | Contents |
|------|----------|
| `src/acabot/types/__init__.py` | Re-exports: `StandardEvent`, `EventSource`, `MsgSegment`, `EventAttachment`, `ReplyReference`, `Action`, `ActionType` |
| `src/acabot/types/event.py` | `StandardEvent` dataclass — platform-agnostic inbound event |
| `src/acabot/types/action.py` | `Action` dataclass + `ActionType` enum — platform-agnostic outbound actions |

### `src/acabot/gateway/` — Platform Gateway

| File | Contents |
|------|----------|
| `src/acabot/gateway/__init__.py` | Package init |
| `src/acabot/gateway/base.py` | `BaseGateway` ABC — `start/stop/send/on_event/call_api` |
| `src/acabot/gateway/napcat.py` | `NapCatGateway` — OneBot v11 reverse-WebSocket server implementation |
| `src/acabot/gateway/onebot_message.py` | OneBot message segment parsing, text extraction, attachment conversion |

### `src/acabot/agent/` — LLM Agent Abstraction

| File | Contents |
|------|----------|
| `src/acabot/agent/__init__.py` | Re-exports: `BaseAgent`, `AgentResponse`, `ToolSpec`, `ToolExecutor`, `ToolDef`, `Attachment` |
| `src/acabot/agent/base.py` | `BaseAgent` ABC — `run()` (with tool loop) + `complete()` (no tools) |
| `src/acabot/agent/agent.py` | `LitellmAgent` — concrete implementation using litellm |
| `src/acabot/agent/response.py` | `AgentResponse` dataclass — text, attachments, tool_calls, usage, error |
| `src/acabot/agent/tool.py` | `ToolSpec`, `ToolDef`, `ToolExecutor`, `ToolExecutionResult` — tool calling contracts |

---

## Runtime Engine: `src/acabot/runtime/`

The bulk of the system. `__init__.py` is a massive facade re-exporting ~300 symbols.

### Root Runtime Files (Orchestration)

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/__init__.py` | (facade) | Single import surface for all runtime types |
| `src/acabot/runtime/app.py` | `RuntimeApp` | Top-level event handler. Gateway lifecycle, run creation, recovery, backend admin bypass, approval workflow |
| `src/acabot/runtime/pipeline.py` | `ThreadPipeline` | Single-run executor. Compaction → retrieval → agent → outbox → finalize |
| `src/acabot/runtime/router.py` | `RuntimeRouter` | Routes `StandardEvent` → `RouteDecision` via `SessionRuntime` |
| `src/acabot/runtime/outbox.py` | `Outbox` | Sends actions via gateway, persists assistant messages, notifies LTM |
| `src/acabot/runtime/agent_runtime.py` | `AgentRuntime` (ABC) | `execute(RunContext) → AgentRuntimeResult` |
| `src/acabot/runtime/gateway_protocol.py` | `GatewayProtocol` | Structural typing protocol for gateway |
| `src/acabot/runtime/plugin_manager.py` | `RuntimePluginManager`, `RuntimePlugin`, `RuntimeHookRegistry` | Full plugin lifecycle + hook system |
| `src/acabot/runtime/approval_resumer.py` | `ApprovalResumer`, `ToolApprovalResumer` | Resumes runs after approval decisions |

### `src/acabot/runtime/contracts/` — Runtime Data Contracts

All runtime dataclasses. No behavior, only shapes.

| File | Key Types |
|------|-----------|
| `src/acabot/runtime/contracts/__init__.py` | Re-exports all contract types |
| `src/acabot/runtime/contracts/common.py` | `RunStatus`, `RunMode`, `CommitWhen`, `DelegationMode`, `MemoryEditMode` literals |
| `src/acabot/runtime/contracts/context.py` | `RunContext`, `AgentRuntimeResult`, `PlannedAction`, `OutboxItem`, `DispatchReport`, `DeliveryResult`, `RetrievalPlan`, `PendingApproval`, `ApprovalRequired`, `RunStep`, `MessageProjection`, `ResolvedMessage`, `MemoryCandidate` |
| `src/acabot/runtime/contracts/records.py` | `RunRecord`, `ThreadRecord`, `ThreadState`, `ChannelEventRecord`, `MessageRecord`, `PendingApprovalRecord`, `RecoveryReport` |
| `src/acabot/runtime/contracts/routing.py` | `RouteDecision`, `ResolvedAgent` |
| `src/acabot/runtime/contracts/session_config.py` | `SessionConfig`, `SurfaceConfig`, `EventFacts`, `MatchSpec`, `DomainConfig`, `DomainCase`, all `*Decision` types, `SurfaceResolution`, `SessionLocatorResult` |
| `src/acabot/runtime/contracts/session_agent.py` | `SessionAgent`, `SessionBundle`, `SessionBundlePaths` |

### `src/acabot/runtime/bootstrap/` — Component Assembly

| File | Contents |
|------|----------|
| `src/acabot/runtime/bootstrap/__init__.py` | `build_runtime_components()` — the master assembly function (~400 lines) |
| `src/acabot/runtime/bootstrap/builders.py` | Individual builder functions for each subsystem component |
| `src/acabot/runtime/bootstrap/components.py` | `RuntimeComponents` dataclass — holds all assembled components |
| `src/acabot/runtime/bootstrap/config.py` | `resolve_runtime_path()` helper |
| `src/acabot/runtime/bootstrap/loaders.py` | `build_bootstrap_defaults()`, `build_prompt_loader()`, `build_session_runtime()` |

### `src/acabot/runtime/control/` — Session Config & Control Plane

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/control/session_runtime.py` | `SessionRuntime` | Core: event facts → domain decisions |
| `src/acabot/runtime/control/session_loader.py` | `SessionConfigLoader` | YAML session config loader |
| `src/acabot/runtime/control/session_bundle_loader.py` | Session bundle loader | Session → agent → prompt bundle resolution |
| `src/acabot/runtime/control/session_agent_loader.py` | Agent loader | Agent definitions from session bundles |
| `src/acabot/runtime/control/session_templates.py` | Session templates | Template inheritance for session configs |
| `src/acabot/runtime/control/prompt_loader.py` | `PromptLoader`, `FileSystemPromptLoader`, `ReloadablePromptLoader` | System prompt loading |
| `src/acabot/runtime/control/control_plane.py` | `RuntimeControlPlane` | Runtime introspection and management API |
| `src/acabot/runtime/control/config_control_plane.py` | `RuntimeConfigControlPlane` | Hot-reload: sessions, models, plugins, prompts |
| `src/acabot/runtime/control/http_api.py` | `RuntimeHttpApiServer` | HTTP API server for webui |
| `src/acabot/runtime/control/model_ops.py` | Model operations | Model management via control plane |
| `src/acabot/runtime/control/reference_ops.py` | Reference operations | Reference/notebook management |
| `src/acabot/runtime/control/workspace_ops.py` | Workspace operations | Workspace management via control plane |
| `src/acabot/runtime/control/log_buffer.py` | `InMemoryLogBuffer` | Ring buffer for recent logs (webui) |
| `src/acabot/runtime/control/snapshots.py` | Status snapshots | Serializable DTOs for API responses |
| `src/acabot/runtime/control/ui_catalog.py` | UI catalog | Catalog data for webui rendering |

### `src/acabot/runtime/model/` — Model Management

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/model/model_agent_runtime.py` | `ModelAgentRuntime`, `ToolRuntime`, `ToolRuntimeResolver` | Production AgentRuntime: assemble → call agent → normalize result |
| `src/acabot/runtime/model/model_registry.py` | `ModelRegistry`, `FileSystemModelRegistryManager` | Provider/preset/binding management; hot-reloadable |
| `src/acabot/runtime/model/model_resolution.py` | `resolve_model_requests_for_agent()` | Agent + decision → model request |
| `src/acabot/runtime/model/model_targets.py` | `MutableModelTargetCatalog`, `ModelTarget` | Model slot declarations (system + agent + plugin) |
| `src/acabot/runtime/model/model_embedding_runtime.py` | `ModelEmbeddingRuntime` | Embedding model calls for LTM |

### `src/acabot/runtime/memory/` — Memory System

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/memory/memory_broker.py` | `MemoryBroker`, `MemorySourceRegistry`, `MemoryBlock` | Unified retrieval with pluggable sources |
| `src/acabot/runtime/memory/retrieval_planner.py` | `RetrievalPlanner` | Plans what memory to inject per run |
| `src/acabot/runtime/memory/context_compactor.py` | `ContextCompactor`, `ContextSummarizer` | Token-aware truncation + LLM summarization |
| `src/acabot/runtime/memory/sticky_notes.py` | `StickyNoteService` | Read/write scoped notes |
| `src/acabot/runtime/memory/sticky_note_entities.py` | Sticky note data types | Entity definitions |
| `src/acabot/runtime/memory/sticky_note_renderer.py` | `StickyNoteRenderer` | Format notes for prompt injection |
| `src/acabot/runtime/memory/conversation_facts.py` | `ConversationFactReader` | Reads event/message deltas for LTM ingestion |
| `src/acabot/runtime/memory/long_term_ingestor.py` | `LongTermMemoryIngestor` | Background async fact extraction + embedding |

#### `src/acabot/runtime/memory/file_backed/`

| File | Contents |
|------|----------|
| `src/acabot/runtime/memory/file_backed/__init__.py` | `StickyNoteFileStore`, `StickyNoteRecord` |
| `src/acabot/runtime/memory/file_backed/sticky_notes.py` | File-based sticky note storage |
| `src/acabot/runtime/memory/file_backed/retrievers.py` | File-based memory retrievers |

#### `src/acabot/runtime/memory/long_term_memory/`

| File | Contents |
|------|----------|
| `src/acabot/runtime/memory/long_term_memory/contracts.py` | `MemoryEntry`, `MemoryProvenance`, `LtmSearchHit`, `FactWindow` |
| `src/acabot/runtime/memory/long_term_memory/storage.py` | Persistent LTM storage backend |
| `src/acabot/runtime/memory/long_term_memory/extractor.py` | LLM-driven fact extraction |
| `src/acabot/runtime/memory/long_term_memory/model_clients.py` | `LtmEmbeddingClient`, `LtmExtractorClient` |
| `src/acabot/runtime/memory/long_term_memory/ranking.py` | Search hit relevance scoring |
| `src/acabot/runtime/memory/long_term_memory/renderer.py` | `LtmRenderer` — format hits for prompt |
| `src/acabot/runtime/memory/long_term_memory/source.py` | `LtmMemorySource` — `MemorySource` protocol impl |
| `src/acabot/runtime/memory/long_term_memory/write_port.py` | `LtmWritePort` — write extracted facts |
| `src/acabot/runtime/memory/long_term_memory/fact_ids.py` | Fact ID generation |
| `src/acabot/runtime/memory/long_term_memory/prompts/` | LTM extraction prompt templates |

### `src/acabot/runtime/computer/` — Computer Subsystem

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/computer/runtime.py` | `ComputerRuntime` | Unified entry: workspace prep, file I/O, exec, sessions, skill mirroring |
| `src/acabot/runtime/computer/contracts.py` | `ComputerBackend` ABC, `ComputerPolicy`, `ComputerRuntimeConfig`, result types | All computer domain contracts |
| `src/acabot/runtime/computer/backends.py` | `HostComputerBackend`, `DockerSandboxBackend`, `RemoteComputerBackend` | Pluggable execution backends |
| `src/acabot/runtime/computer/workspace.py` | `WorkspaceManager` | Host filesystem layout per thread |
| `src/acabot/runtime/computer/world.py` | `WorkWorldBuilder` | Virtual filesystem with `/workspace`, `/skills`, `/self` roots |
| `src/acabot/runtime/computer/attachments.py` | `AttachmentResolver`, `GatewayAttachmentResolver` | Download + stage inbound attachments |
| `src/acabot/runtime/computer/reading.py` | `format_read_text()` | Paginated text reading |
| `src/acabot/runtime/computer/editing.py` | `prepare_text_edit()` | Search-and-replace editing |
| `src/acabot/runtime/computer/media.py` | Image MIME detection, base64 content | Multimodal support |

### `src/acabot/runtime/tool_broker/` — Tool System

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/tool_broker/broker.py` | `ToolBroker` | Register, resolve visibility, execute, approval flow |
| `src/acabot/runtime/tool_broker/contracts.py` | `RegisteredTool`, `ToolHandler`, `ToolExecutionContext`, `ToolResult`, `ToolAuditRecord` | Tool domain contracts |
| `src/acabot/runtime/tool_broker/policy.py` | `ToolPolicy`, `AllowAllToolPolicy`, `ToolAudit`, `InMemoryToolAudit` | Policy + audit |

### `src/acabot/runtime/builtin_tools/` — Core Tool Implementations

| File | Contents |
|------|----------|
| `src/acabot/runtime/builtin_tools/__init__.py` | `register_core_builtin_tools()` — registers all built-in tools to ToolBroker |
| `src/acabot/runtime/builtin_tools/computer.py` | `read`, `write`, `edit`, `bash` tools |
| `src/acabot/runtime/builtin_tools/skills.py` | Skill management tools |
| `src/acabot/runtime/builtin_tools/sticky_notes.py` | Sticky note tools |
| `src/acabot/runtime/builtin_tools/subagents.py` | Subagent delegation tool |

### `src/acabot/runtime/plugins/` — Built-in Runtime Plugins

| File | Plugin | Role |
|------|--------|------|
| `src/acabot/runtime/plugins/napcat_tools.py` | `NapCatToolsPlugin` | Platform-specific tools |
| `src/acabot/runtime/plugins/ops_control.py` | `OpsControlPlugin` | Operational control tools |
| `src/acabot/runtime/plugins/reference_tools.py` | `ReferenceToolsPlugin` | Reference/notebook search tools |
| `src/acabot/runtime/plugins/backend_bridge_tool.py` | `BackendBridgeToolPlugin` | Frontstage backend bridge tool |

### `src/acabot/runtime/inbound/` — Message Preprocessing

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/inbound/message_preparation.py` | `MessagePreparationService` | Orchestrates resolution + projection |
| `src/acabot/runtime/inbound/message_resolution.py` | `MessageResolutionService` | Resolves reply chains, forwards, attachments via gateway API |
| `src/acabot/runtime/inbound/message_projection.py` | `MessageProjectionService` | Projects into model-ready format (image captioning) |
| `src/acabot/runtime/inbound/image_context.py` | `ImageContextService` | LLM-based image captioning |

### `src/acabot/runtime/context_assembly/` — Prompt Assembly

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/context_assembly/assembler.py` | `ContextAssembler` | Merges base prompt + memory blocks + history into final model input |
| `src/acabot/runtime/context_assembly/contracts.py` | `AssembledContext`, `ContextContribution` | Assembly result shapes |
| `src/acabot/runtime/context_assembly/payload_json_writer.py` | `PayloadJsonWriter` | Debug: writes final LLM payload to disk |

### `src/acabot/runtime/storage/` — Persistence

| File | Key Class | Role |
|------|-----------|------|
| `src/acabot/runtime/storage/stores.py` | `ChannelEventStore`, `MessageStore`, `ThreadStore`, `RunStore` (ABCs) | Storage interfaces |
| `src/acabot/runtime/storage/sqlite_stores.py` | `SQLiteChannelEventStore`, `SQLiteMessageStore`, `SQLiteRunStore`, `SQLiteThreadStore` | SQLite implementations |
| `src/acabot/runtime/storage/memory_store.py` | `InMemoryMessageStore` | In-memory message store |
| `src/acabot/runtime/storage/event_store.py` | `InMemoryChannelEventStore` | In-memory event store |
| `src/acabot/runtime/storage/threads.py` | `ThreadManager`, `InMemoryThreadManager`, `StoreBackedThreadManager` | Thread state management |
| `src/acabot/runtime/storage/runs.py` | `RunManager`, `InMemoryRunManager`, `StoreBackedRunManager` | Run lifecycle management |

### `src/acabot/runtime/skills/` — Skill Packages

| File | Contents |
|------|----------|
| `src/acabot/runtime/skills/catalog.py` | `SkillCatalog` — central registry |
| `src/acabot/runtime/skills/loader.py` | `FileSystemSkillPackageLoader` — discovers from `extensions/skills/` |
| `src/acabot/runtime/skills/package.py` | `SkillPackageManifest`, `SkillPackageDocument` |

### `src/acabot/runtime/subagents/` — Subagent Packages

| File | Contents |
|------|----------|
| `src/acabot/runtime/subagents/catalog.py` | `SubagentCatalog` |
| `src/acabot/runtime/subagents/broker.py` | `SubagentDelegationBroker` — validates + dispatches delegation |
| `src/acabot/runtime/subagents/execution.py` | `LocalSubagentExecutionService` — child run via pipeline |
| `src/acabot/runtime/subagents/loader.py` | `FileSystemSubagentPackageLoader` |
| `src/acabot/runtime/subagents/package.py` | `SubagentPackageManifest`, `SubagentPackageDocument` |
| `src/acabot/runtime/subagents/contracts.py` | `SubagentDelegationRequest`, `SubagentDelegationResult` |

### `src/acabot/runtime/references/` — Reference/Notebook System

| File | Contents |
|------|----------|
| `src/acabot/runtime/references/contracts.py` | `ReferenceDocument`, `ReferenceHit`, `ReferenceSpace` |
| `src/acabot/runtime/references/base.py` | `ReferenceBackend` ABC, `NullReferenceBackend` |
| `src/acabot/runtime/references/local.py` | `LocalReferenceBackend` — filesystem-based |
| `src/acabot/runtime/references/openviking.py` | `OpenVikingReferenceBackend` — remote vector search |
| `src/acabot/runtime/references/helpers.py` | Shared utilities |

### `src/acabot/runtime/backend/` — Admin Backend Bridge

| File | Contents |
|------|----------|
| `src/acabot/runtime/backend/contracts.py` | `BackendRequest`, `BackendSourceRef` |
| `src/acabot/runtime/backend/bridge.py` | `BackendBridge` — routes admin commands |
| `src/acabot/runtime/backend/session.py` | `BackendSessionService`, `ConfiguredBackendSessionService` |
| `src/acabot/runtime/backend/mode_registry.py` | `BackendModeRegistry` — per-thread admin mode tracking |
| `src/acabot/runtime/backend/pi_adapter.py` | `PiBackendAdapter` — subprocess-based backend execution |
| `src/acabot/runtime/backend/persona.py` | Backend persona utilities |

### `src/acabot/runtime/soul/` — Identity Memory

| File | Contents |
|------|----------|
| `src/acabot/runtime/soul/source.py` | `SoulSource` — `/self` file service (today.md, daily/, custom files) |

---

## Naming Conventions

| Pattern | Meaning | Examples |
|---------|---------|---------|
| `*_runtime.py` | Subsystem entry point | `agent_runtime`, `computer/runtime`, `model_agent_runtime` |
| `contracts.py` | Pure dataclass definitions (no behavior) | `runtime/contracts/`, `tool_broker/contracts` |
| `*_broker.py` | Fan-out/dispatch layer | `tool_broker`, `memory_broker`, `subagent broker` |
| `*_manager.py` | Lifecycle manager | `plugin_manager`, `run_manager`, `thread_manager` |
| `*_loader.py` | Reads config/packages from filesystem | `session_loader`, `prompt_loader`, `skill loader` |
| `*_catalog.py` | Registry of named entities | `skill_catalog`, `subagent_catalog` |
| `*_source.py` | Read-only data provider | `soul/source`, `ltm/source` |
| `*_store.py` | Persistence interface or impl | `message_store`, `event_store`, `sqlite_stores` |
| `builders.py` | Factory functions for bootstrap | `bootstrap/builders` |
| `policy.py` | Decision/enforcement layer | `tool_broker/policy` |
| `*Decision` | Per-event config-driven decision | `RoutingDecision`, `AdmissionDecision`, `ComputerPolicyDecision` |
| `*Result` | Operation result | `AgentRuntimeResult`, `ToolResult`, `CommandExecutionResult` |
| `*Record` | Persisted fact record | `RunRecord`, `MessageRecord`, `ChannelEventRecord` |

---

## Configuration Paths

| Path | Purpose |
|------|---------|
| `config.yaml` | Top-level config: gateway, agent, runtime, logging, plugins |
| `runtime_config/sessions/` | Per-channel session YAML configs |
| `runtime_config/agents/` | Agent definition YAML files |
| `runtime_config/prompts/` | System prompt text files |
| `runtime_config/models/` | Model registry YAML (providers, presets, bindings) |
| `runtime_data/` | Persistent data root |
| `runtime_data/soul/` | `/self` identity files |
| `runtime_data/sticky_notes/` | Per-scope sticky note files |
| `runtime_data/workspaces/` | Per-thread workspace directories |
| `extensions/plugins/` | User runtime plugins |
| `extensions/skills/` | User skill packages |
| `extensions/subagents/` | User subagent packages |
