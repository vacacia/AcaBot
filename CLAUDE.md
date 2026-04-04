<!-- GSD:project-start source:PROJECT.md -->
## Project

所有文档/代码注释/交流过程 全部使用 中文 + 英文标点符号
阅读/data/workspace/agent/AcaBot/docs/00-ai-entry.md

如果你是 main agent:
- 遵照 GSD 的指示, **禁止做 不该你做的事情**
- 如果你是 GPT, subagent 请全部使用 GPT-5.4
- subagen 的作用是为了减少上下文污染, 所以不要自己代 subagent 工作
- 积极使用 subagent 并行工作提升效率, 禁止自己主动写代码
- subagent research 阶段禁止再派出 subagent 做重复工作, 除非是调查 *不相交的不同领域*
- subagent research 阶段禁止中断, 禁止主动下场, **必须等待直到它完成**

---

**AcaBot v2 — Runtime 基础设施强化**

AcaBot 是一个 agentic chatbot runtime，通过 Gateway 接收 IM 平台事件，经过 session-config 路由引擎、LLM agent pipeline、工具调用，最终通过 Gateway 回复。当前核心 pipeline 已稳定运行，本轮工作聚焦于 runtime 基础设施的补全和重构——插件体系、消息工具、定时任务、日志、数据安全等，让 bot 从"能跑"进化到"好用、可扩展、可观测"。

**Core Value:** **让 AcaBot 的 runtime 基础设施从 MVP 水平提升到正式可用水平：插件可管理、消息能力完整、定时任务可用、运行状态可观测。**

### Constraints

- **Tech Stack**: Python 3.11+ / asyncio，不引入新的异步框架
- **Gateway**: 当前只有 NapCat，消息工具设计需平台无关但只需 OneBot v11 实现
- **部署**: Docker Compose，镜像改动需兼容 Full + Lite 双版本
- **兼容性**: 插件重构需保证 BackendBridgeToolPlugin 过渡期可用
- **单操作者**: AcaBot 面向单个操作者，不需要多租户隔离
<!-- GSD:project-end -->

## Known Test Failures

运行全量测试时, 以下测试会失败, 属于已知问题, 不需要修复:

- `tests/runtime/backend/test_pi_adapter.py` (3 个) — 需要真实 `pi` 可执行文件, 开发环境中不存在. 运行 pytest 时用 `--ignore=tests/runtime/backend/test_pi_adapter.py` 跳过.

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
| Language | Usage | Files |
|---|---|---|
| Python 3.11+ | Backend core, agent runtime, gateway, plugins | `src/acabot/**/*.py` |
| TypeScript | WebUI frontend | `webui/src/**/*.ts` |
| YAML | Configuration (runtime config, model providers, sessions) | `config.example.yaml`, `runtime_config/**/*.yaml` |
| SQL (SQLite DDL) | Inline schema definitions in Python | `src/acabot/runtime/storage/sqlite_stores.py` |
## Runtime
- **Python >= 3.11** (`pyproject.toml` `requires-python`)
- **Node.js LTS** (installed in `Dockerfile` for Playwright / WebUI build)
- **asyncio** event loop throughout (`asyncio.run()` in `src/acabot/main.py`)
- Entrypoint: `python -m acabot.main` (registered as `acabot` console script)
## Frameworks & Core Libraries
### Python Dependencies (from `pyproject.toml`)
| Package | Version | Purpose |
|---|---|---|
| `websockets` | >= 12.0 | Reverse-WebSocket server for NapCat/OneBot v11 gateway (`src/acabot/gateway/napcat.py`) |
| `litellm` | >= 1.40.0 | Universal LLM proxy; routes to 20+ providers via `acompletion` (`src/acabot/agent/agent.py`) |
| `aiosqlite` | >= 0.20.0 | Listed dep (actual stores use synchronous `sqlite3` with `asyncio.Lock`) |
| `pyyaml` | >= 6.0 | Config & model registry YAML parsing (`src/acabot/runtime/model/model_registry.py`) |
| `python-dotenv` | >= 1.0.0 | `.env` file loading at startup (`src/acabot/main.py`) |
| `lancedb` | >= 0.25.0 | Columnar vector store for long-term memory (`src/acabot/runtime/memory/long_term_memory/storage.py`) |
| `pyarrow` | >= 18.0.0 | Arrow schema definitions for LanceDB tables |
### Python Dev Dependencies
| Package | Version | Purpose |
|---|---|---|
| `pytest` | >= 8.0 | Test runner |
| `pytest-asyncio` | >= 0.23 | Async test support |
### Dockerfile-only Libraries (not in `pyproject.toml`)
| Package | Purpose |
|---|---|
| `httpx`, `beautifulsoup4`, `lxml` | HTTP requests & HTML parsing |
| `Pillow` | Image processing |
| `markdown-it-py`, `Jinja2` | Markdown rendering, templating |
| `pandas`, `openpyxl` | Tabular data & Excel |
| `matplotlib`, `seaborn` | Charting |
| `weasyprint` | HTML-to-PDF |
| `yt-dlp` | Media download |
| `numpy`, `scipy` | Numeric/scientific computing |
| `playwright` + Chromium | Headless browser automation |
### Frontend (from `webui/package.json`)
| Package | Version | Purpose |
|---|---|---|
| `vue` | ^3.5.22 | UI framework |
| `vue-router` | ^4.5.1 | Client-side routing |
| `vite` | ^7.1.7 | Dev server & build tool |
| `typescript` | ^5.9.2 | Type checking |
| `@vitejs/plugin-vue` | ^6.0.1 | Vue SFC compilation |
## System-Level Tools (Dockerfile)
- `ffmpeg`, `imagemagick`, `graphviz` (media processing)
- `pandoc` (document conversion)
- `sqlite3` CLI
- `fonts-noto-cjk`, `fonts-noto-color-emoji` (CJK + emoji rendering)
- Standard CLI: `git`, `curl`, `wget`, `jq`, `ripgrep`, `htop`, `tree`
## Package Management
- **Python**: `uv` (`pip install uv` then `uv pip install --system .`)
- **Frontend**: `npm` (via `package-lock.json`)
- **Lock file**: `uv.lock` (477 KB, checked in)
## Configuration Architecture
### Static Config (`config.yaml`)
- Loaded from `ACABOT_CONFIG` env var or default path
- Defines: gateway bind, agent defaults, runtime persistence, context compaction, plugin list, WebUI, filesystem layout
- Template: `config.example.yaml`
### Environment Variables (`.env`)
- `OPENAI_API_KEY` (and any provider-specific keys, consumed by litellm)
- `OPENAI_API_BASE` (optional override)
- Template: `.env.example`
### Filesystem-backed Runtime Config (`runtime_config/`)
| Directory | Content |
|---|---|
| `runtime_config/models/providers/` | Provider YAML files (API keys, base URLs) |
| `runtime_config/models/presets/` | Model preset YAML (temperature, max_tokens, etc.) |
| `runtime_config/models/bindings/` | Model binding YAML (maps task targets to provider+preset) |
| `runtime_config/prompts/` | System prompt Markdown files |
| `runtime_config/sessions/` | Session configuration YAML |
| `runtime_config/plugins/` | Plugin-specific config |
## Project Structure
## Container Architecture
### Dockerfile (full image)
- Base: `python:3.11-slim`
- Includes: build tools, media tools, Node.js, Playwright+Chromium, data science libs
- Exposes: `8080` (gateway WS), `8765` (WebUI HTTP)
- `PYTHONPATH=/app/src:/app/extensions`
- Used for production with Docker Compose
### Dockerfile.lite (minimal image)
- Base: `python:3.11-slim`
- Minimal tools: `git`, `curl`, `jq`, fonts
- Still includes Playwright+Chromium
- Same ports and entrypoint
### Docker Compose (`deploy/compose.yaml`)
- `acabot` (the bot) -- built from Dockerfile
- `napcat` (`mlikiowa/napcat-docker:latest`) -- QQ protocol bridge
- Shared `acabot_network` bridge network
- Volume mounts: `config.yaml`, `.env`, `runtime_config/`, `runtime_data/`, `extensions/`
## Extensions System
- Directory: `extensions/` (mounted into container at `/app/extensions`)
- Added to `PYTHONPATH` alongside `src/`
- Subdirectories: `plugins/`, `skills/`, `subagents/`
- Plugin loading via dotted-path strings in config (e.g., `acabot.runtime.plugins.ops_control:OpsControlPlugin`)
## Compute Backends (`src/acabot/runtime/computer/backends.py`)
| Backend | Status | Description |
|---|---|---|
| `HostComputerBackend` | Implemented | Direct shell execution on host |
| `DockerSandboxBackend` | Implemented | Per-thread Docker containers (`acabot-{hash}`) |
| `RemoteComputerBackend` | Stub | Placeholder, raises `NotImplemented` |
## Type Checking & Testing
- **Pyright** configured in `pyproject.toml` (`pythonVersion = "3.11"`, `extraPaths = ["src"]`)
- **pytest** with `asyncio_mode = "auto"`, test directory: `tests/`
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Language & Runtime
- **Python 3.11+** (`pyproject.toml` requires `>=3.11`).
- `from __future__ import annotations` at the top of every module for PEP 604 union syntax (`str | None`) and forward references.
- Type checker: **Pyright** (`[tool.pyright]` in `pyproject.toml`), `pythonVersion = "3.11"`.
- Source root is `src/` (`extraPaths = ["src"]`).
- Documentation strings and code comments are written in **Chinese (中文)**; identifier names, type annotations, and log messages are in **English**.
## Project Layout
## Naming Conventions
### Modules & Files
- **snake_case** for all module names: `context_compactor.py`, `model_agent_runtime.py`.
- Contracts/types go in dedicated `contracts.py` files or `contracts/` subpackages inside each subdomain.
- Base/abstract classes live in `base.py` (e.g. `src/acabot/agent/base.py`, `src/acabot/gateway/base.py`).
- Each subpackage exposes its public API via `__init__.py`. The top-level `src/acabot/runtime/__init__.py` is a **massive facade** that re-exports ~300 symbols.
### Classes
- **PascalCase** for all classes.
- Abstract base classes use `Base` prefix or bare domain nouns + `(ABC)`: `BaseAgent` (`src/acabot/agent/base.py`), `BaseGateway` (`src/acabot/gateway/base.py`), `AgentRuntime` (`src/acabot/runtime/agent_runtime.py`), `RuntimePlugin`, `RuntimeHook`, `ThreadManager`, `RunManager`.
- **`typing.Protocol`** preferred over ABC when the caller only needs a duck-typed shape (structural subtyping): `GatewayProtocol`, `ToolExecutor`, `ContextSummarizer`, `MemorySource`, `ComputerBackend`, `WorldView`, `ToolPolicy`, `ToolAudit`, `LongTermMemoryWritePort`, `RetrievalStore`, `QueryPlannerClient`.
- Concrete implementations use descriptive prefixes: `LitellmAgent`, `NapCatGateway`, `SQLiteChannelEventStore`, `InMemoryRunManager`, `FileSystemModelRegistryManager`.
- Result/record dataclasses use domain-noun suffixes: `AgentResponse`, `ToolExecutionResult`, `ChannelEventRecord`, `RunRecord`, `ThreadState`.
- Fake/stub classes in tests use `Fake` prefix: `FakeGateway`, `FakeAgent`, `FakeAgentRuntime`, `FakeMessageStore`.
### Functions & Methods
- **snake_case** throughout.
- Private/internal methods use single underscore prefix: `_resolve_tool_runtime()`, `_build_tools_param()`, `_sanitize_messages()`, `_handle_tool_calls()`.
- Factory functions at module level: `create_*` for top-level single-object wiring (`create_gateway`, `create_agent`), `build_*` for composite assembly (`build_runtime_app`, `build_runtime_components`, `build_agent_model_targets`).
- Static helpers use `@staticmethod` freely: `_sanitize_messages`, `_get_acompletion`, `_preview_text`, `_preview_json`.
- Test helper factories use underscore prefix: `_event()`, `_profile()`, `_decision()`, `_context()`, `_model_request()`.
### Variables & Constants
- **snake_case** for variables and instance attributes.
- **UPPER_SNAKE_CASE** for module-level constants and Literal type aliases: `RunStatus`, `RunMode`, `FORMAL_TARGET_SLOTS`, `SYSTEM_MODEL_TARGETS`.
- Type aliases at module level: `ToolHandler = Callable[...]`, `GatewayFactory = Callable[[Config], GatewayProtocol]`.
- Module-level loggers: `logger = logging.getLogger("acabot.<subsystem>")` — scoped by dotted name.
- Unused args explicitly silenced: `_ = args, kwargs` or `_ = config`.
## Dataclass Patterns
### `@dataclass(slots=True)` — the default for new code
### Standard `@dataclass`
### Common Patterns
- **Required fields first**, then optional fields with defaults.
- Mutable defaults always use `field(default_factory=...)` — never bare `[]` or `{}`.
- A trailing `metadata: dict[str, Any] = field(default_factory=dict)` catch-all is ubiquitous.
- `__post_init__` used sparingly for field synchronization (e.g., `StandardEvent` syncs `reply_to_message_id` ↔ `reply_reference`).
- `@property` methods on dataclasses for derived values: `is_private`, `session_key`, `text`, `message_preview`, `actor_tag`, `working_memory_text`.
- Serialization via explicit `to_dict()` / `to_payload_json()` methods — no automatic serialization libraries.
## Enum Patterns
- Enums inherit `str` so values serialize naturally as strings without `.value`.
- `Literal` types preferred for internal contracts over enums: `RunStatus = Literal["queued", "running", ...]`, `CommitWhen`, `ApprovalDecision`, `DelegationMode` (see `src/acabot/runtime/contracts/common.py`).
## Async Patterns
- **All I/O operations are async** — gateway, storage, agent runs, tool execution.
- The codebase is **asyncio-native** (no trio/anyio in production code).
- Entry point: `asyncio.run(_run())` in `src/acabot/main.py`.
- `asyncio.Lock` used at the `ThreadState` level for thread-safe working memory mutations:
- `ContextVar` for request-scoped state: `current_event: ContextVar[StandardEvent | None]` (`src/acabot/context.py`).
- Awaitable duck-typing for backward-compatible sync/async callables:
- Signal-based shutdown: `asyncio.Event` + `loop.add_signal_handler` for SIGINT/SIGTERM.
## Error Handling
### Return-value errors (no exceptions for expected failures)
### Literal status fields for structured outcomes
### Custom exceptions for control flow
### Best-effort error recovery in pipelines
### Tool executor exceptions propagate
### Graceful degradation
## Dependency Injection & Composition
### Constructor injection (the dominant pattern)
### Factory functions for wiring
- `create_gateway(config)`, `create_agent(config)` — simple single-object factories in `src/acabot/main.py`
- `build_runtime_components(config, *, gateway, agent, ...)` — root composition function in `src/acabot/runtime/bootstrap/`
- Optional collaborators default to `None`; the component either uses a no-op fallback or skips that feature
### Protocol-based abstractions at boundaries
- `BaseAgent` (ABC) — `src/acabot/agent/base.py`
- `BaseGateway` (ABC) — `src/acabot/gateway/base.py`
- `AgentRuntime` (ABC) — `src/acabot/runtime/agent_runtime.py`
- `ToolExecutor` (Protocol) — `src/acabot/agent/tool.py`
- `GatewayProtocol` (Protocol) — `src/acabot/runtime/gateway_protocol.py`
- `ToolPolicy` / `ToolAudit` (Protocol) — `src/acabot/runtime/tool_broker/policy.py`
### Context Object Pattern
## Logging
- `logging.getLogger("acabot.<module>")` per module: `"acabot.agent"`, `"acabot.runtime.pipeline"`, `"acabot.runtime.plugin"`, `"acabot.gateway"`.
- Log format: `%(asctime)s [%(name)s] %(levelname)s: %(message)s`
- Structured key=value format in log messages:
- `logger.exception(...)` only in catch blocks.
- `logger.debug` for operational details; `logger.info` for lifecycle milestones; `logger.warning`/`error` for failures.
- `InMemoryLogBuffer` + `InMemoryLogHandler` for runtime-accessible log ring buffer (`src/acabot/runtime/control/log_buffer.py`).
- `ColorLogFormatter` adds optional ANSI colors, respects `$NO_COLOR`.
## Import Style
- **Lazy imports** for heavy external dependencies to keep test import times fast:
- **Delayed imports in factory functions** to avoid pulling platform-specific code at module load:
- `TYPE_CHECKING` guards for circular import prevention (used extensively in `contracts/`).
- Facade `__init__.py` re-exports all stable public API (e.g. `src/acabot/runtime/__init__.py`).
## Config
- `Config` class wraps a YAML dict (`src/acabot/config.py`).
- Loaded via `Config.from_file()` with fallback chain: explicit path → `$ACABOT_CONFIG` → `config.yaml`.
- Plugin configs namespaced under `plugins.<name>` — accessed via `config.get_plugin_config("name")`.
- Atomic writes via `NamedTemporaryFile` + `Path.replace()`.
- `.env` loading via `python-dotenv` (gracefully optional).
- `config.resolve_path(raw)` resolves relative paths against the config file's directory.
## Code Organization Within Files
## Docstring Style
- **Chinese docstrings** for module-level docstrings and class descriptions — this is a Chinese-language project.
- **Google-style** Args / Returns / Raises / Attributes sections:
- Module-level docstrings describe purpose and component relationships, sometimes with ASCII diagrams.
- Inline `NOTE:` and `TODO:` comments for design rationale.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern
## Runtime Mainline (Request Data Flow)
```
```
## Layers
### 1. Gateway Layer
| Component | File | Role |
|-----------|------|------|
| `GatewayProtocol` | `src/acabot/runtime/gateway_protocol.py` | Structural protocol — the runtime-facing contract |
| `BaseGateway` | `src/acabot/gateway/base.py` | ABC with `start/stop/send/on_event/call_api` |
| `NapCatGateway` | `src/acabot/gateway/napcat.py` | OneBot v11 reverse-WebSocket implementation |
| OneBot message utils | `src/acabot/gateway/onebot_message.py` | Segment parsing, text extraction, attachment mapping |
### 2. Routing & Session Layer
| Component | File | Role |
|-----------|------|------|
| `RuntimeRouter` | `src/acabot/runtime/router.py` | Thin facade: event → SessionRuntime → RouteDecision |
| `SessionRuntime` | `src/acabot/runtime/control/session_runtime.py` | Core decision engine: facts → session → surface → 7 domain decisions |
| `SessionConfigLoader` | `src/acabot/runtime/control/session_loader.py` | Loads YAML session configs from `runtime_config/sessions/` |
| `SessionBundleLoader` | `src/acabot/runtime/control/session_bundle_loader.py` | Resolves session → agent → prompt bundle |
- **Routing** — which agent handles this event
- **Admission** — `respond` / `record_only` / `silent_drop`
- **Context** — retrieval tags, sticky note targets, context labels
- **Persistence** — whether to persist the inbound event
- **Extraction** — long-term memory tags
- **Computer** — backend, exec policy, workspace roots, visible skills
### 3. Orchestration Layer (RuntimeApp + ThreadPipeline)
| Component | File | Role |
|-----------|------|------|
| `RuntimeApp` | `src/acabot/runtime/app.py` | Top-level event handler; owns gateway lifecycle, run creation, recovery, approval flow |
| `ThreadPipeline` | `src/acabot/runtime/pipeline.py` | Single-run executor: compaction → retrieval → agent → outbox → finalize |
| `RunContext` | `src/acabot/runtime/contracts/context.py` | Mutable bag carrying all state for one run |
| `RunManager` | `src/acabot/runtime/storage/runs.py` | Run lifecycle state machine (queued → running → completed/failed/waiting_approval) |
| `ThreadManager` | `src/acabot/runtime/storage/threads.py` | Thread state persistence (working_messages, working_summary) |
### 4. Agent / Model Layer
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
```
```
### 6. Tool System (ToolBroker)
| Component | File | Role |
|-----------|------|------|
| `ToolBroker` | `src/acabot/runtime/tool_broker/broker.py` | Central registry: register/unregister tools, build ToolRuntime per run, execute tool calls |
| `ToolPolicy` | `src/acabot/runtime/tool_broker/policy.py` | Per-tool approval/deny decisions |
| `ToolAudit` | `src/acabot/runtime/tool_broker/policy.py` | Tool execution audit trail |
| `ToolExecutionContext` | `src/acabot/runtime/tool_broker/contracts.py` | Rich context passed to runtime tool handlers |
- `computer` tools — `src/acabot/runtime/builtin_tools/computer.py` (read/write/edit/bash)
- `skills` tools — `src/acabot/runtime/builtin_tools/skills.py` (list/load/run skills)
- `sticky_notes` tools — `src/acabot/runtime/builtin_tools/sticky_notes.py` (read/write notes)
- `subagents` tools — `src/acabot/runtime/builtin_tools/subagents.py` (delegate to sub-agents)
### 7. Computer Subsystem
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
### 10. Control Plane
| Component | File | Role |
|-----------|------|------|
| `RuntimeControlPlane` | `src/acabot/runtime/control/control_plane.py` | Runtime introspection: status, thread/run queries, model/plugin/skill/subagent management |
| `RuntimeConfigControlPlane` | `src/acabot/runtime/control/config_control_plane.py` | Config-driven hot-reload: agents, models, plugins, prompts |
| `RuntimeHttpApiServer` | `src/acabot/runtime/control/http_api.py` | HTTP API exposing control plane to webui |
### 11. Storage Layer
| Store Interface | File | Implementations |
|-----------------|------|-----------------|
| `ChannelEventStore` | `src/acabot/runtime/storage/stores.py` | `InMemoryChannelEventStore`, `SQLiteChannelEventStore` |
| `MessageStore` | `src/acabot/runtime/storage/stores.py` | `InMemoryMessageStore`, `SQLiteMessageStore` |
| `ThreadStore` | `src/acabot/runtime/storage/stores.py` | `SQLiteThreadStore` |
| `RunStore` | `src/acabot/runtime/storage/stores.py` | `SQLiteRunStore` |
| `ThreadManager` | `src/acabot/runtime/storage/threads.py` | `InMemoryThreadManager`, `StoreBackedThreadManager` |
| `RunManager` | `src/acabot/runtime/storage/runs.py` | `InMemoryRunManager`, `StoreBackedRunManager` |
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
## Entry Points
| Entry | File | Description |
|-------|------|-------------|
| CLI main | `src/acabot/main.py` → `main()` | `asyncio.run(_run())`: load config → build components → start app + HTTP server → wait for signal |
| Bootstrap | `src/acabot/runtime/bootstrap/__init__.py` → `build_runtime_components()` | Single function assembling all runtime components with dependency injection |
| HTTP API | `src/acabot/runtime/control/http_api.py` | Aiohttp server exposing control plane |
| WebUI | `webui/` | Vite + TypeScript frontend |
## Cross-Cutting Concerns
- **Config:** `src/acabot/config.py` — YAML-based `Config` with path resolution relative to config file
- **Types:** `src/acabot/types/` — `StandardEvent`, `EventSource`, `Action`, `ActionType` shared across all layers
- **Contracts:** `src/acabot/runtime/contracts/` — All runtime dataclasses split across `common.py`, `context.py`, `records.py`, `routing.py`, `session_config.py`, `session_agent.py`
- **Logging:** Structured `logging.getLogger("acabot.*")` throughout with in-memory log buffer for webui
- **Concurrency:** Thread-level `asyncio.Lock` for working memory mutations; background ingestor for LTM writes
## Backend Bridge (Admin)
```
```
## Subagent System
| Component | File | Role |
|-----------|------|------|
| `SubagentCatalog` | `src/acabot/runtime/subagents/catalog.py` | Discovery and manifest loading |
| `SubagentDelegationBroker` | `src/acabot/runtime/subagents/broker.py` | Validates and dispatches delegation requests |
| `LocalSubagentExecutionService` | `src/acabot/runtime/subagents/execution.py` | Executes child run through same ThreadPipeline |
| Package loader | `src/acabot/runtime/subagents/loader.py` + `package.py` | Filesystem-based subagent package discovery |
## Skills System
| Component | File | Role |
|-----------|------|------|
| `SkillCatalog` | `src/acabot/runtime/skills/catalog.py` | Central skill registry |
| `FileSystemSkillPackageLoader` | `src/acabot/runtime/skills/loader.py` | Discovers skill packages from filesystem |
| `SkillPackageManifest` | `src/acabot/runtime/skills/package.py` | Parsed skill package definition |
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
