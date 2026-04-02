# AcaBot Testing Guide

## Framework & Configuration

- **pytest ≥ 8.0** + **pytest-asyncio ≥ 0.23**
- Config in `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  testpaths = ["tests"]
  ```
- `asyncio_mode = "auto"` means all `async def test_*` functions are automatically detected as async tests — no `@pytest.mark.asyncio` needed

## Test Directory Structure

```
tests/
  conftest.py              # root conftest — sys.path setup + anyio_backend fixture
  __init__.py
  test_agent.py            # unit tests for LitellmAgent
  test_gateway.py          # unit tests for NapCat gateway translation
  test_main.py             # integration: main.py startup chain / build_runtime_app
  test_config_example.py   # config validation
  types/
    test_action.py         # ActionType, Action dataclass tests
    test_event.py          # StandardEvent properties/serialization tests
  runtime/
    __init__.py
    _agent_fakes.py        # shared FakeAgent + FakeAgentResponse
    runtime_plugin_samples.py  # sample plugin implementations for tests
    test_app.py            # RuntimeApp end-to-end
    test_bootstrap.py      # build_runtime_components assembly verification
    test_pipeline_runtime.py   # ThreadPipeline unit tests
    test_outbox.py         # Outbox dispatch tests + shared FakeGateway/FakeMessageStore
    test_builtin_tools.py  # builtin tool registration chain
    test_tool_broker.py    # ToolBroker policy + execution
    test_plugin_manager.py # RuntimePluginManager lifecycle
    test_model_agent_runtime.py  # ModelAgentRuntime tests
    test_computer.py       # ComputerRuntime sandbox tests
    test_webui_api.py      # WebUI HTTP API tests (largest file ~128KB)
    backend/
      test_bridge.py
      test_contracts.py
      test_session_binding.py
      ...
    control/
      test_backend_http_api.py
    ... (60+ test files covering individual runtime components)
  fixtures/
    skills/                # fixture data for skill loading tests
      excel_processing/
      sample_configured_skill/
      invalid_missing_description/
```

## Test Organization Conventions

### Class-Based Grouping
Tests for a single component are grouped under a class:
```python
class TestLitellmAgent:
    @pytest.fixture
    def agent(self):
        return LitellmAgent()

    async def test_simple_chat(self, agent): ...
    async def test_model_override(self, agent): ...
    async def test_error_handling(self, agent): ...

class TestToolCalling:
    @pytest.fixture
    def agent(self):
        return LitellmAgent()

    async def test_tool_loop_with_explicit_tools_and_executor(self, agent): ...
```

### Standalone Functions
Simpler tests or integration tests use bare `async def test_*` functions:
```python
async def test_runtime_router_silent_drops_unconfigured_session(tmp_path: Path) -> None: ...
```

### Naming
- Test files: `test_<module_name>.py` — mirrors the source module being tested
- Test functions: `test_<what_is_being_tested>` — descriptive, snake_case, often long
- Examples: `test_tool_loop_with_explicit_tools_and_executor`, `test_explicit_tools_require_tool_executor`, `test_run_sanitizes_none_content_from_existing_history`

## Fixtures

### Root Conftest (`tests/conftest.py`)
```python
@pytest.fixture
def anyio_backend():
    return "asyncio"
```
Also adds `plugins/` to `sys.path` for plugin import support.

### Inline Fixtures
Most fixtures are defined per-class or per-file as simple factory functions:
```python
@pytest.fixture
def agent(self):
    return LitellmAgent()

@pytest.fixture
def gw(self):
    return NapCatGateway.__new__(NapCatGateway)  # skip __init__ for pure function tests
```

### Shared Helpers
Common fakes and helpers are defined in dedicated modules and imported across test files:
- `tests/runtime/test_outbox.py` exports `FakeGateway`, `FakeMessageStore`, `RecordingIngestor`
- `tests/runtime/_agent_fakes.py` exports `FakeAgent`, `FakeAgentResponse`
- `tests/runtime/test_pipeline_runtime.py` exports `FakeAgentRuntime`, `ApprovalToolAgent`
- `tests/runtime/runtime_plugin_samples.py` exports sample plugin classes

### `tmp_path` Usage
Heavy use of pytest's built-in `tmp_path` fixture for file-based tests (config, sessions, skills):
```python
async def test_runtime_router_silent_drops_unconfigured_session(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/user/10001"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    ...
```

## Mocking Patterns

### `unittest.mock.AsyncMock` + `patch`
The primary mocking tool for LLM calls and async dependencies:
```python
from unittest.mock import AsyncMock, patch

async def test_simple_chat(self, agent):
    mock_resp = AsyncMock()
    mock_resp.choices = [
        type("C", (), {"message": type("M", (), {"content": "Hello!", "tool_calls": None})()})()
    ]
    mock_resp.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})()

    with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
        resp = await agent.run(...)
```

### Inline `type()` for Lightweight Stubs
Instead of full mock classes, ephemeral objects are created with `type()`:
```python
type("C", (), {"message": type("M", (), {"content": "ok", "tool_calls": None})()})()
```
This creates anonymous objects with exact attribute shapes matching LLM response structures.

### Hand-Written Fake Classes
For components with richer interfaces, dedicated fakes implement the exact duck-typed shape:

```python
# tests/runtime/_agent_fakes.py
class FakeAgent:
    def __init__(self, response: FakeAgentResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def run(self, system_prompt, messages, model=None, *, tools=None, tool_executor=None, **kw):
        self.calls.append({...})
        return self.response
```

```python
# tests/runtime/test_outbox.py
class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[Action] = []
    async def send(self, action: Action) -> dict[str, object] | None:
        self.sent.append(action)
        return {"message_id": f"msg-{len(self.sent)}", "timestamp": 123}
```

```python
# tests/runtime/test_pipeline_runtime.py
class FakeAgentRuntime(AgentRuntime):
    async def execute(self, ctx: RunContext) -> AgentRuntimeResult:
        return AgentRuntimeResult(status="completed", text="hello back", actions=[...])
```

### `__new__` Trick for Skipping `__init__`
When testing pure translation methods on a class with heavy `__init__` (e.g. WebSocket setup):
```python
@pytest.fixture
def gw(self):
    return NapCatGateway.__new__(NapCatGateway)
```

### Patch Target
Module-level references are patched at the import site:
```python
with patch("acabot.agent.agent.acompletion", return_value=mock_resp):
    ...
```

## Assertion Style

- Direct `assert` statements — no assertion helper libraries
- Specific attribute checks preferred over broad equality:
  ```python
  assert resp.text == "Hello!"
  assert resp.error is None
  assert resp.model_used == "gpt-4o-mini"
  assert len(resp.tool_calls_made) == 1
  assert resp.tool_calls_made[0].name == "get_time"
  ```
- `isinstance` checks for contract conformance:
  ```python
  assert isinstance(agent, BaseAgent)
  assert isinstance(event, StandardEvent)
  assert isinstance(resp, AgentResponse)
  ```
- `pytest.raises` for expected exceptions:
  ```python
  with pytest.raises(RuntimeError, match="tool interrupted"):
      await agent.run(...)
  ```

## Test Patterns by Component Type

### Agent Tests (`tests/test_agent.py`)
- Patch `acompletion` at module level
- Build mock LLM responses with `type()` stubs
- Verify response fields, model forwarding, error propagation, tool loop mechanics
- Tool executors are plain `async def` functions injected directly

### Gateway Tests (`tests/test_gateway.py`)
- Use `__new__` to avoid WebSocket init
- Set `gw._self_id` directly to simulate bot identity
- Provide raw OneBot v11 JSON dicts, assert `StandardEvent` field values
- Test both directions: `translate()` (inbound) and `build_send_payload()` (outbound)

### Runtime Tests (`tests/runtime/`)
- Integration-style: wire real components with fakes injected for external deps
- Use `FakeGateway`, `FakeMessageStore`, `FakeAgent`, `FakeAgentRuntime` from shared modules
- Session config is written to `tmp_path` as YAML for `SessionConfigLoader` tests
- File-based fixtures live under `tests/fixtures/`

### Bootstrap Tests (`tests/runtime/test_bootstrap.py`)
- Call `build_runtime_components()` with real `Config` and verify the assembled object graph
- Write minimal session/agent/prompt files to `tmp_path`
- Assert component types and wiring correctness

## Common Helper Patterns

### Event Factory
Tests frequently build `StandardEvent` instances inline:
```python
def _event() -> StandardEvent:
    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(platform="qq", message_type="private", user_id="10001", group_id=None),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )
```

### Session Config Writer
```python
def _write_minimal_session(base_dir: Path, *, agent_id="aca", prompt_ref="prompt/default", ...):
    session_dir = base_dir / "sessions" / "qq" / "user" / "10001"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.yaml").write_text(...)
```

### Spy / Recording Classes
Fakes often record calls for later assertion:
```python
class CountingThreadManager(InMemoryThreadManager):
    def __init__(self) -> None:
        super().__init__()
        self.save_calls = 0
    async def save(self, thread) -> None:
        self.save_calls += 1
        await super().save(thread)
```

## Coverage Notes

- No explicit coverage configuration in `pyproject.toml`
- Tests heavily cover the runtime layer (~60+ test files under `tests/runtime/`)
- Agent layer has thorough unit tests for LLM call mechanics, tool loop, and error paths
- Gateway translation has exhaustive tests for all OneBot v11 event types (message, poke, recall, member join/leave, admin change, file upload, ban, honor, title, lucky king)
- Type layer tests verify dataclass properties, serialization, and computed fields
