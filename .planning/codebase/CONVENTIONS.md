# AcaBot Codebase Conventions

## Language & Runtime

- **Python 3.11+** (`pyproject.toml` requires `>=3.11`).
- `from __future__ import annotations` at the top of every module for PEP 604 union syntax (`str | None`) and forward references.
- Type checker: **Pyright** (`[tool.pyright]` in `pyproject.toml`), `pythonVersion = "3.11"`.
- Source root is `src/` (`extraPaths = ["src"]`).
- Documentation strings and code comments are written in **Chinese (中文)**; identifier names, type annotations, and log messages are in **English**.

## Project Layout

```
src/acabot/              # Main package
  agent/                 # LLM agent abstraction (BaseAgent, LitellmAgent)
    base.py              # BaseAgent ABC
    agent.py             # LitellmAgent concrete implementation
    tool.py              # ToolSpec, ToolExecutor, ToolExecutionResult, ToolDef
    response.py          # AgentResponse, ToolCallRecord, Attachment dataclasses
  config.py              # Config class — YAML loading with atomic save
  context.py             # ContextVar for current_event
  gateway/               # Platform protocol adapters (OneBot v11 / NapCat)
    base.py              # BaseGateway ABC
    napcat.py            # NapCatGateway — OneBot v11 reverse WS
  main.py                # Entry point — factory + bootstrap + asyncio.run
  runtime/               # Core execution engine — the largest subsystem
    agent_runtime.py     # AgentRuntime ABC
    app.py               # RuntimeApp — top-level event routing
    pipeline.py          # ThreadPipeline — per-run execution
    outbox.py            # Outbox — unified outbound dispatch
    router.py            # RuntimeRouter — event→session routing
    gateway_protocol.py  # GatewayProtocol (typing.Protocol)
    plugin_manager.py    # RuntimePluginManager, RuntimePlugin ABC, RuntimeHook ABC
    backend/             # Backend bridge & session management
    bootstrap/           # Component wiring (build_runtime_components)
    builtin_tools/       # Built-in tool registrations (computer, skills, sticky notes)
    computer/            # Sandbox/workspace abstractions
    context_assembly/    # Prompt slot assembly
    contracts/           # Shared dataclasses & Literal type definitions
      common.py          # RunStatus, CommitWhen, ApprovalDecision, etc.
      context.py         # RunContext, PlannedAction, AgentRuntimeResult
      records.py         # RunRecord, ThreadState, MessageRecord
      routing.py         # RouteDecision, ResolvedAgent
      session_config.py  # SessionConfig and related config dataclasses
    control/             # Control plane, HTTP API, prompt/session loaders
    inbound/             # Message preparation, projection, image context
    memory/              # Memory broker, compactor, long-term memory, sticky notes
    model/               # Model registry, agent runtime, embedding runtime
    plugins/             # Runtime extension plugins
    references/          # Reference/knowledge backends
    skills/              # Skill catalog & loader
    soul/                # Soul prompt source
    storage/             # Stores (SQLite & in-memory)
    subagents/           # Sub-agent delegation
    tool_broker/         # Tool registration, policy, audit
      contracts.py       # ToolPolicyDecision, ToolAuditRecord, ToolExecutionContext
      policy.py          # ToolPolicy, ToolAudit protocols
  session/
  types/                 # Canonical domain types (StandardEvent, Action)
    event.py             # StandardEvent, EventSource, MsgSegment, EventAttachment, ReplyReference
    action.py            # Action, ActionType
  webui/
tests/                   # Mirrors src/ layout
extensions/              # External extension packages
```

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

Dataclasses are the primary data-carrying abstraction. Two variants are used:

### `@dataclass(slots=True)` — the default for new code

Preferred for internal contracts and high-frequency objects — saves memory, prevents accidental attribute assignment:

```python
# src/acabot/runtime/contracts/context.py
@dataclass(slots=True)
class PlannedAction:
    action_id: str
    action: Action
    thread_content: str | None = None
    commit_when: CommitWhen = "success"
    metadata: dict[str, Any] = field(default_factory=dict)
```

Also: `@dataclass(frozen=True, slots=True)` for immutable value objects (e.g. `src/acabot/runtime/bootstrap/loaders.py`).

### Standard `@dataclass`

Used for top-level domain objects where `__dict__` access or inheritance is needed:

```python
# src/acabot/types/event.py
@dataclass
class StandardEvent:
    event_id: str
    event_type: str
    # ... required fields first, then optional with defaults
    operator_id: str | None = None
    mentioned_user_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Common Patterns

- **Required fields first**, then optional fields with defaults.
- Mutable defaults always use `field(default_factory=...)` — never bare `[]` or `{}`.
- A trailing `metadata: dict[str, Any] = field(default_factory=dict)` catch-all is ubiquitous.
- `__post_init__` used sparingly for field synchronization (e.g., `StandardEvent` syncs `reply_to_message_id` ↔ `reply_reference`).
- `@property` methods on dataclasses for derived values: `is_private`, `session_key`, `text`, `message_preview`, `actor_tag`, `working_memory_text`.
- Serialization via explicit `to_dict()` / `to_payload_json()` methods — no automatic serialization libraries.

## Enum Patterns

```python
# src/acabot/types/action.py
class ActionType(str, Enum):
    SEND_TEXT = "send_text"
    RECALL = "recall"
    GROUP_BAN = "group_ban"
    # ...
```

- Enums inherit `str` so values serialize naturally as strings without `.value`.
- `Literal` types preferred for internal contracts over enums: `RunStatus = Literal["queued", "running", ...]`, `CommitWhen`, `ApprovalDecision`, `DelegationMode` (see `src/acabot/runtime/contracts/common.py`).

## Async Patterns

- **All I/O operations are async** — gateway, storage, agent runs, tool execution.
- The codebase is **asyncio-native** (no trio/anyio in production code).
- Entry point: `asyncio.run(_run())` in `src/acabot/main.py`.
- `asyncio.Lock` used at the `ThreadState` level for thread-safe working memory mutations:
  ```python
  async with ctx.thread.lock:
      self._append_incoming_message(ctx)
  ```
- `ContextVar` for request-scoped state: `current_event: ContextVar[StandardEvent | None]` (`src/acabot/context.py`).
- Awaitable duck-typing for backward-compatible sync/async callables:
  ```python
  response = completion(**kwargs)
  if isawaitable(response):
      response = await response
  ```
- Signal-based shutdown: `asyncio.Event` + `loop.add_signal_handler` for SIGINT/SIGTERM.

## Error Handling

### Return-value errors (no exceptions for expected failures)

Agent and tool operations return result objects with an `error` field rather than raising:

```python
# src/acabot/agent/agent.py
if not use_model:
    return AgentResponse(error="model is required", model_used="")

# On LLM call failure:
except Exception as exc:
    logger.error("LLM call failed: %s", exc)
    return AgentResponse(error=str(exc), model_used=use_model)
```

### Literal status fields for structured outcomes

`AgentRuntimeResult.status: Literal["completed", "waiting_approval", "failed"]` — callers branch on status rather than catching exceptions.

### Custom exceptions for control flow

`ApprovalRequired` is a structured exception used to interrupt the agent tool loop when a tool needs human approval:

```python
# src/acabot/runtime/contracts/context.py
class ApprovalRequired(Exception):
    def __init__(self, *, pending_approval: PendingApproval) -> None:
        super().__init__(pending_approval.reason)
        self.pending_approval = pending_approval
```

`RuntimeError` for developer-facing invariant violations:
```python
raise RuntimeError("litellm dependency is required to run LitellmAgent")
```

### Best-effort error recovery in pipelines

The pipeline catches top-level exceptions, runs error hooks, saves state, and marks the run as failed — never crashes the process:

```python
# src/acabot/runtime/pipeline.py
except Exception as exc:
    logger.exception("ThreadPipeline crashed: run_id=%s", ctx.run.run_id)
    await self._run_error_hooks(ctx)
    await self._save_thread_safely(ctx)
    await self._mark_failed_safely(ctx.run.run_id, f"pipeline crashed: {exc}")
```

The `_*_safely` methods wrap their bodies in try/except to prevent secondary failures from masking the original error.

### Tool executor exceptions propagate

Tool executor exceptions are **not** swallowed by the agent — they bubble up to the pipeline's top-level handler. This is tested explicitly:

```python
# tests/test_agent.py
with pytest.raises(RuntimeError, match="tool interrupted"):
    await agent.run(...)
```

### Graceful degradation

Components accept `| None` and fall back to defaults — `tool_broker: ToolBroker | None = None`, `computer_runtime: ComputerRuntime | None = None`, `memory_broker: MemoryBroker | None = None`.

## Dependency Injection & Composition

### Constructor injection (the dominant pattern)

All major components receive their dependencies through `__init__` keyword arguments. No global singletons, no service locators:

```python
class ThreadPipeline:
    def __init__(
        self,
        *,
        agent_runtime: AgentRuntime,
        outbox: Outbox,
        run_manager: RunManager,
        thread_manager: ThreadManager,
        memory_broker: MemoryBroker | None = None,
        # ... more optional components
    ) -> None:
```

### Factory functions for wiring

- `create_gateway(config)`, `create_agent(config)` — simple single-object factories in `src/acabot/main.py`
- `build_runtime_components(config, *, gateway, agent, ...)` — root composition function in `src/acabot/runtime/bootstrap/`
- Optional collaborators default to `None`; the component either uses a no-op fallback or skips that feature

### Protocol-based abstractions at boundaries

Core boundaries are defined as `ABC` or `Protocol` types:
- `BaseAgent` (ABC) — `src/acabot/agent/base.py`
- `BaseGateway` (ABC) — `src/acabot/gateway/base.py`
- `AgentRuntime` (ABC) — `src/acabot/runtime/agent_runtime.py`
- `ToolExecutor` (Protocol) — `src/acabot/agent/tool.py`
- `GatewayProtocol` (Protocol) — `src/acabot/runtime/gateway_protocol.py`
- `ToolPolicy` / `ToolAudit` (Protocol) — `src/acabot/runtime/tool_broker/policy.py`

### Context Object Pattern

`RunContext` is a mutable dataclass that flows through the entire pipeline, accumulating state at each stage:

```python
@dataclass(slots=True)
class RunContext:
    run: RunRecord
    event: StandardEvent
    decision: RouteDecision
    thread: ThreadState
    agent: ResolvedAgent
    # ... 30+ optional fields populated progressively
```

## Logging

- `logging.getLogger("acabot.<module>")` per module: `"acabot.agent"`, `"acabot.runtime.pipeline"`, `"acabot.runtime.plugin"`, `"acabot.gateway"`.
- Log format: `%(asctime)s [%(name)s] %(levelname)s: %(message)s`
- Structured key=value format in log messages:
  ```python
  logger.debug("LLM run request: model=%s messages=%s tools=%s", ...)
  logger.info("Run completed cleanly: run_id=%s", ctx.run.run_id)
  logger.warning("Run completed with delivery errors: run_id=%s", ...)
  logger.exception("ThreadPipeline crashed: run_id=%s", ...)
  ```
- `logger.exception(...)` only in catch blocks.
- `logger.debug` for operational details; `logger.info` for lifecycle milestones; `logger.warning`/`error` for failures.
- `InMemoryLogBuffer` + `InMemoryLogHandler` for runtime-accessible log ring buffer (`src/acabot/runtime/control/log_buffer.py`).
- `ColorLogFormatter` adds optional ANSI colors, respects `$NO_COLOR`.

## Import Style

- **Lazy imports** for heavy external dependencies to keep test import times fast:
  ```python
  try:
      from litellm import acompletion as _litellm_acompletion
  except ImportError:
      _litellm_acompletion = None
  ```
- **Delayed imports in factory functions** to avoid pulling platform-specific code at module load:
  ```python
  def create_gateway(config: Config) -> GatewayProtocol:
      from .gateway.napcat import NapCatGateway  # delayed
      return NapCatGateway(...)
  ```
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

`# region` / `# endregion` markers partition files into logical blocks for IDE folding:

```python
# region run
async def run(self, ...) -> AgentResponse:
    ...
# endregion

# region internals
def _resolve_tool_runtime(self, ...):
    ...
# endregion
```

Typical section groups: lifecycle, run/execute, protocol translation, internal helpers, legacy convenience.

## Docstring Style

- **Chinese docstrings** for module-level docstrings and class descriptions — this is a Chinese-language project.
- **Google-style** Args / Returns / Raises / Attributes sections:
  ```python
  def execute(self, ctx: RunContext, *, deliver_actions: bool = True) -> None:
      """执行一条最小 runtime 主线.

      Args:
          ctx: 当前 run 的完整执行上下文.
          deliver_actions: 是否把动作真正发到外部平台.
      """
  ```
- Module-level docstrings describe purpose and component relationships, sometimes with ASCII diagrams.
- Inline `NOTE:` and `TODO:` comments for design rationale.
