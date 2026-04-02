# AcaBot Directory Structure

## Top-Level Layout

```
AcaBot/
├── src/acabot/                    # Main Python package
├── extensions/                    # External extension packages
├── webui/                         # Frontend (WebUI for control plane)
├── tests/                         # Test suite
├── docs/                          # Documentation
├── ref/                           # Reference materials
├── deploy/                        # Deployment scripts
├── runtime_config/                # Runtime configuration (sessions, agents, models, prompts)
├── runtime_config.example/        # Example runtime_config for new installs
├── runtime_data/                  # Runtime data (SQLite DBs, workspaces, soul, sticky notes)
├── config.example.yaml            # Example main config
├── .env.example                   # Example environment variables
├── pyproject.toml                 # Python project metadata (uv/pip)
├── uv.lock                        # Dependency lock file
├── Dockerfile                     # Full Docker image
├── Dockerfile.lite                # Lite Docker image
├── .planning/                     # Architecture & planning documents
├── .claude/                       # Claude Code configuration
├── .harness/                      # Test harness configuration
└── .gitignore
```

## Source Package: `src/acabot/`

### Root Files

| File | Purpose |
|------|---------|
| `src/acabot/__init__.py` | Package init |
| `src/acabot/main.py` | **CLI entry point** — `main()`, factory functions, logging setup, `_run()` async bootstrap |
| `src/acabot/config.py` | `Config` class — YAML config loading, path resolution, hot reload |
| `src/acabot/context.py` | Shared context utilities |

### Types (`src/acabot/types/`)

Platform-agnostic event and action types. No runtime dependencies.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports all types |
| `event.py` | `StandardEvent`, `EventSource`, `MsgSegment`, `EventAttachment`, `ReplyReference` |
| `action.py` | `Action`, `ActionType` (SEND_TEXT, SEND_SEGMENTS, GROUP_BAN, etc.) |

### Gateway (`src/acabot/gateway/`)

Platform protocol adapters. Translates between platform-native formats and `StandardEvent`/`Action`.

| File | Key Types |
|------|-----------|
| `__init__.py` | Package init |
| `base.py` | `BaseGateway` ABC — `start()`, `stop()`, `send()`, `on_event()`, `call_api()` |
| `napcat.py` | `NapCatGateway` — WebSocket OneBot v11 implementation |
| `onebot_message.py` | OneBot message segment parsing/building |

### Agent (`src/acabot/agent/`)

LLM agent abstraction. Deliberately thin — tools are injected externally.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `base.py` | `BaseAgent` ABC — `run()` (with tool loop), `complete()` (single shot) |
| `agent.py` | `LitellmAgent` — concrete agent using litellm library |
| `tool.py` | `ToolSpec`, `ToolDef`, `ToolExecutor`, `ToolExecutionResult`, `normalize_tool_result()` |
| `response.py` | `AgentResponse`, `Attachment` |

### Session (`src/acabot/session/`)

Session-level utilities (minimal, most session logic lives in `runtime/control/`).

### WebUI Assets (`src/acabot/webui/`)

Static assets served by the HTTP API server.

---

## Runtime Engine: `src/acabot/runtime/`

The core execution engine. All runtime subsystems live here.

### Root Runtime Files

| File | Key Types | Role |
|------|-----------|------|
| `__init__.py` | **Massive facade** — re-exports ~300 symbols | Single import point for all runtime types |
| `app.py` | `RuntimeApp` | Event dispatch, run lifecycle, approval flow, recovery |
| `router.py` | `RuntimeRouter` | Delegates to `SessionRuntime`, returns `RouteDecision` |
| `pipeline.py` | `ThreadPipeline` | Single-run executor: memory → agent → outbox → finish |
| `outbox.py` | `Outbox` | Gateway send + message persistence + LTM dirty marking |
| `agent_runtime.py` | `AgentRuntime` ABC | Interface: `execute(RunContext) → AgentRuntimeResult` |
| `gateway_protocol.py` | `GatewayProtocol` | Structural Protocol for gateway dependency inversion |
| `plugin_manager.py` | `RuntimePluginManager`, `RuntimePlugin`, `RuntimeHookPoint` | Plugin lifecycle, hook registry, tool registration |
| `approval_resumer.py` | `ApprovalResumer`, `ToolApprovalResumer` | Resume execution after tool approval |

### Contracts (`src/acabot/runtime/contracts/`)

All shared data types as frozen/slotted dataclasses. **No business logic.**

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports all contract types |
| `common.py` | `RunMode`, `RunStatus`, `CommitWhen`, `DelegationMode`, `MemoryEditMode` |
| `context.py` | `RunContext`, `AgentRuntimeResult`, `PlannedAction`, `OutboxItem`, `DispatchReport`, `DeliveryResult`, `RetrievalPlan`, `PendingApproval`, `MessageProjection`, `ResolvedMessage`, `ResolvedImageInput`, `MemoryCandidate`, `RunStep` |
| `records.py` | `RunRecord`, `ThreadState`, `ThreadRecord`, `ChannelEventRecord`, `MessageRecord`, `PendingApprovalRecord`, `RecoveryReport` |
| `routing.py` | `RouteDecision`, `ResolvedAgent` |
| `session_config.py` | `SessionConfig`, `SurfaceConfig`, `EventFacts`, `MatchSpec`, `DomainConfig`, `DomainCase`, `RoutingDecision`, `AdmissionDecision`, `ContextDecision`, `PersistenceDecision`, `ExtractionDecision`, `ComputerPolicyDecision`, `SurfaceResolution`, `SessionLocatorResult` |
| `session_agent.py` | `SessionAgent`, `SessionBundle`, `SessionBundlePaths` |

### Control Plane (`src/acabot/runtime/control/`)

Session config loading, runtime management, HTTP API.

| File | Key Types |
|------|-----------|
| `session_runtime.py` | `SessionRuntime` — event facts → domain decisions |
| `session_loader.py` | `SessionConfigLoader`, `StaticSessionConfigLoader` |
| `session_bundle_loader.py` | Loads session + agent + prompt as atomic bundle |
| `session_agent_loader.py` | Agent profile loading from session bundles |
| `session_templates.py` | Session template utilities |
| `prompt_loader.py` | `PromptLoader`, `FileSystemPromptLoader`, `ReloadablePromptLoader`, `ChainedPromptLoader` |
| `control_plane.py` | `RuntimeControlPlane` — introspection, status, workspace management |
| `config_control_plane.py` | `RuntimeConfigControlPlane` — hot-reload sessions, models, plugins |
| `http_api.py` | `RuntimeHttpApiServer` — aiohttp-based management API |
| `model_ops.py` | Model registry mutation operations |
| `reference_ops.py` | Reference backend operations |
| `workspace_ops.py` | Workspace management operations |
| `log_buffer.py` | `InMemoryLogBuffer`, `InMemoryLogHandler` |
| `snapshots.py` | `BackendStatusSnapshot` and other status types |
| `ui_catalog.py` | UI catalog for WebUI |

### Model Layer (`src/acabot/runtime/model/`)

LLM model resolution and the bridge between `BaseAgent` and the runtime.

| File | Key Types |
|------|-----------|
| `model_agent_runtime.py` | `ModelAgentRuntime` (implements `AgentRuntime`), `ToolRuntime`, `ToolRuntimeState`, `ToolRuntimeResolver` |
| `model_registry.py` | `ModelRegistry`, `FileSystemModelRegistryManager`, `ModelBinding`, `ModelPreset`, `ModelProvider`, `RuntimeModelRequest`, `PersistedModelSnapshot` |
| `model_resolution.py` | `resolve_model_requests_for_agent()` |
| `model_targets.py` | `ModelTarget`, `ModelCapability`, `MutableModelTargetCatalog`, `SYSTEM_MODEL_TARGETS` |
| `model_embedding_runtime.py` | `ModelEmbeddingRuntime` |

### Memory System (`src/acabot/runtime/memory/`)

Three-tier memory: working memory, compaction, long-term retrieval.

| File | Key Types |
|------|-----------|
| `memory_broker.py` | `MemoryBroker`, `MemoryBlock`, `MemorySource`, `MemorySourceRegistry`, `SharedMemoryRetrievalRequest` |
| `retrieval_planner.py` | `RetrievalPlanner` — plans what memory to inject per run |
| `context_compactor.py` | `ContextCompactor`, `ContextSummarizer`, `ModelContextSummarizer` |
| `sticky_notes.py` | `StickyNoteService` — read/write scoped notes |
| `sticky_note_entities.py` | Sticky note data structures |
| `sticky_note_renderer.py` | `StickyNoteRenderer` — format notes for prompt injection |
| `conversation_facts.py` | `ConversationFactReader`, `StoreBackedConversationFactReader` |
| `long_term_ingestor.py` | `LongTermMemoryIngestor` — background async fact extraction |

#### File-Backed Memory (`src/acabot/runtime/memory/file_backed/`)

| File | Key Types |
|------|-----------|
| `__init__.py` | `StickyNoteFileStore`, `StickyNoteRecord` |
| `sticky_notes.py` | File-based sticky note storage |
| `retrievers.py` | File-based memory retrievers |

#### Long-Term Memory (`src/acabot/runtime/memory/long_term_memory/`)

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `contracts.py` | `MemoryEntry`, `MemoryProvenance`, `LtmSearchHit`, `FactWindow` |
| `storage.py` | Persistent LTM storage |
| `extractor.py` | `LtmExtractorClient` — extract facts from conversation |
| `model_clients.py` | LTM model client implementations |
| `ranking.py` | `HitChannelScore` — relevance scoring |
| `renderer.py` | `LtmRenderer` — format LTM hits for prompt |
| `source.py` | `LtmMemorySource` — implements `MemorySource` protocol |
| `write_port.py` | `LtmWritePort` — write extracted facts |
| `fact_ids.py` | Fact ID generation |
| `prompts/` | LTM extraction prompt templates |

### Computer Subsystem (`src/acabot/runtime/computer/`)

Sandboxed workspace and execution environment.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `runtime.py` | `ComputerRuntime` — unified entry: workspace prep, file I/O, exec, sessions |
| `contracts.py` | `ComputerBackend`, `ComputerPolicy`, `ComputerRuntimeConfig`, `CommandSession`, `CommandExecutionResult`, `WorkspaceState`, `WorldPathReadResult`, `WorldPathWriteResult`, `WorldPathEditResult` |
| `backends.py` | `HostComputerBackend`, `DockerSandboxBackend`, `RemoteComputerBackend` |
| `workspace.py` | `WorkspaceManager` — host filesystem layout per thread |
| `world.py` | `WorkWorldBuilder` — virtual filesystem with `/workspace`, `/skills`, `/self` roots |
| `attachments.py` | `AttachmentResolver`, `GatewayAttachmentResolver` |
| `reading.py` | `format_read_text()` — paginated text reading |
| `editing.py` | `prepare_text_edit()` — old/new text replacement |
| `media.py` | Image MIME detection, base64 content |

### Tool System (`src/acabot/runtime/tool_broker/`)

Central tool registry, policy, and execution.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `broker.py` | `ToolBroker` — register, resolve visibility, execute, approval flow |
| `contracts.py` | `RegisteredTool`, `ToolHandler`, `ToolExecutionContext`, `ToolResult`, `ToolReplayResult`, `ToolAuditRecord`, `ToolPolicyDecision` |
| `policy.py` | `ToolPolicy`, `AllowAllToolPolicy`, `ToolAudit`, `InMemoryToolAudit` |

### Builtin Tools (`src/acabot/runtime/builtin_tools/`)

Core tools registered at bootstrap time.

| File | Tools Registered |
|------|-----------------|
| `__init__.py` | `register_core_builtin_tools()` — wires all builtins |
| `computer.py` | `read`, `write`, `edit`, `bash` |
| `skills.py` | `Skill` |
| `sticky_notes.py` | `StickyNote` |
| `subagents.py` | `delegate_subagent` |

### Skills (`src/acabot/runtime/skills/`)

Loadable skill packages (directories with `SKILL.md`).

| File | Key Types |
|------|-----------|
| `__init__.py` | `SkillCatalog`, `FileSystemSkillPackageLoader` |
| `catalog.py` | `SkillCatalog` — discovery and visibility |
| `package.py` | `SkillPackageManifest`, `SkillPackageDocument` |
| `loader.py` | `FileSystemSkillPackageLoader` |

### Subagents (`src/acabot/runtime/subagents/`)

Delegatable sub-agent packages.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `catalog.py` | `SubagentCatalog` |
| `package.py` | `SubagentPackageManifest`, `SubagentPackageDocument` |
| `loader.py` | `FileSystemSubagentPackageLoader` |
| `broker.py` | `SubagentDelegationBroker` |
| `execution.py` | `LocalSubagentExecutionService` — creates a child run via pipeline |
| `contracts.py` | `SubagentDelegationRequest`, `SubagentDelegationResult` |

### References (`src/acabot/runtime/references/`)

Knowledge base / notebook retrieval.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `contracts.py` | `ReferenceDocument`, `ReferenceHit`, `ReferenceSpace` |
| `base.py` | `ReferenceBackend` ABC |
| `local.py` | `LocalReferenceBackend` |
| `openviking.py` | `OpenVikingReferenceBackend` |
| `helpers.py` | Shared utilities |

### Soul (`src/acabot/runtime/soul/`)

Static persona/personality files.

| File | Key Types |
|------|-----------|
| `__init__.py` | `SoulSource` |
| `source.py` | `SoulSource` — reads `*.md` files from soul directory |

### Context Assembly (`src/acabot/runtime/context_assembly/`)

Final prompt construction from upstream materials.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `assembler.py` | `ContextAssembler` — weaves memory blocks + prompt + history into final context |
| `contracts.py` | `AssembledContext`, `ContextContribution` |
| `payload_json_writer.py` | `PayloadJsonWriter` — debug dump of final model payload |

### Inbound Processing (`src/acabot/runtime/inbound/`)

Pre-agent message processing pipeline.

| File | Key Types |
|------|-----------|
| `__init__.py` | Package init |
| `message_preparation.py` | `MessagePreparationService` — orchestrates resolution + projection |
| `message_resolution.py` | `MessageResolutionService` — resolve reply chains, forward messages |
| `message_projection.py` | `MessageProjectionService` — image captions, content projection |
| `image_context.py` | `ImageContextService` — generate image captions via model |

### Backend Bridge (`src/acabot/runtime/backend/`)

Admin backend for operational control.

| File | Key Types |
|------|-----------|
| `__init__.py` | Re-exports |
| `contracts.py` | `BackendRequest`, `BackendSourceRef` |
| `bridge.py` | `BackendBridge` — routes admin requests |
| `session.py` | `BackendSessionService`, `ConfiguredBackendSessionService` |
| `mode_registry.py` | `BackendModeRegistry` — track which threads are in admin mode |
| `persona.py` | Backend persona utilities |
| `pi_adapter.py` | `PiBackendAdapter` — subprocess-based backend execution |

### Plugins (`src/acabot/runtime/plugins/`)

Concrete plugin implementations.

| File | Plugin Class |
|------|-------------|
| `napcat_tools.py` | `NapCatToolsPlugin` — platform API tools |
| `ops_control.py` | `OpsControlPlugin` — ops commands |
| `reference_tools.py` | `ReferenceToolsPlugin` — reference/KB tools |
| `backend_bridge_tool.py` | `BackendBridgeToolPlugin` — frontstage backend bridge |

### Storage (`src/acabot/runtime/storage/`)

Persistence abstractions and implementations.

| File | Key Types |
|------|-----------|
| `stores.py` | `MessageStore`, `ChannelEventStore`, `RunStore`, `ThreadStore` (Protocol ABCs) |
| `sqlite_stores.py` | `SQLiteMessageStore`, `SQLiteChannelEventStore`, `SQLiteRunStore`, `SQLiteThreadStore` |
| `memory_store.py` | `InMemoryMessageStore` |
| `event_store.py` | `InMemoryChannelEventStore` |
| `threads.py` | `ThreadManager`, `InMemoryThreadManager`, `StoreBackedThreadManager` |
| `runs.py` | `RunManager`, `InMemoryRunManager`, `StoreBackedRunManager` |

### Bootstrap (`src/acabot/runtime/bootstrap/`)

Component wiring and assembly.

| File | Purpose |
|------|---------|
| `__init__.py` | `build_runtime_components()` — the master assembly function |
| `components.py` | `RuntimeComponents` dataclass — holds all assembled components |
| `builders.py` | Individual builder functions for each subsystem |
| `loaders.py` | `BootstrapDefaults`, session/prompt/agent loader builders |
| `config.py` | `resolve_runtime_path()` and config helpers |

## Naming Conventions

| Convention | Examples |
|------------|---------|
| Classes | PascalCase: `RuntimeApp`, `ThreadPipeline`, `MemoryBroker` |
| Files | snake_case: `model_agent_runtime.py`, `session_runtime.py` |
| Contracts | Dataclasses with `slots=True`: `RunContext`, `RouteDecision`, `AgentRuntimeResult` |
| Protocols | Structural typing: `GatewayProtocol`, `MemorySource`, `ToolRuntimeResolver` |
| ABCs | Explicit ABC: `BaseAgent`, `BaseGateway`, `AgentRuntime`, `RuntimePlugin` |
| Test files | `tests/test_*.py` mirroring source structure |
| Config keys | snake_case in YAML: `runtime.plugins`, `gateway.host` |
| IDs | Prefixed strings: `session:`, `step:`, `action:`, `approval:`, `agent:` |
| Decision types | `*Decision` suffix: `RoutingDecision`, `AdmissionDecision`, `ComputerPolicyDecision` |
| Result types | `*Result` suffix: `AgentRuntimeResult`, `ToolResult`, `CommandExecutionResult` |
| Store types | `*Store` suffix: `MessageStore`, `ChannelEventStore` |
| Manager types | `*Manager` suffix: `ThreadManager`, `RunManager`, `WorkspaceManager` |
| Plugin sources | `plugin:<name>` or `builtin:<name>` tags in ToolBroker |
| World paths | Virtual: `/workspace/...`, `/skills/...`, `/self/...` |
| Channel scopes | `platform:scope_type:id` (e.g., `onebot:group:12345`, `onebot:user:67890`) |
