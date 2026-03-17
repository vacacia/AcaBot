# 后台 Aca（基于长期 pi session）Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AcaBot 拥有一个由长期 `pi` session 承载的后台维护人格，并支持前台 `query/change` 桥接、管理员 `!` 单条透传和 `/maintain` 私聊后台模式。

**Architecture:** 不在 AcaBot 内重造后台 agent runtime，而是在 `src/acabot/runtime/backend/` 下增加一个轻量 backend 壳，负责后台模式、桥接、canonical session 绑定和 query fork；后台人格本身由长期 `pi` session` 承载。后台完整 transcript 以 `pi` 自己的 session/jsonl 为真源，AcaBot 第一阶段不重建 operation/artifact 子系统，只做最小状态与入口接线。

**Tech Stack:** Python runtime, existing AcaBot router/app/pipeline/control plane, `pi --mode rpc`, runtime storage/contracts, thin backend status projection.

---

## File Structure

### New files

- `src/acabot/runtime/backend/__init__.py` — backend 子域导出。
- `src/acabot/runtime/backend/contracts.py` — backend 最小数据契约：request、source_ref。
- `src/acabot/runtime/backend/mode_registry.py` — 管理员私聊 `/maintain` 模式状态。
- `src/acabot/runtime/backend/session.py` — canonical backend session 绑定、恢复、query fork 切点管理。
- `src/acabot/runtime/backend/pi_adapter.py` — `pi --mode rpc` 适配层。
- `src/acabot/runtime/backend/persona.py` — backend Aca maintainer persona prompt 组装。
- `src/acabot/runtime/backend/bridge.py` — 前台/管理员到后台的统一桥接入口，承担最小分类与分流。

### Modified files

- `src/acabot/runtime/app.py` — 接入后台入口路由：`!`、`/maintain`、backend mode 消息分流。
- `src/acabot/runtime/router.py` — 保持最小 route 语义，必要时补后台直通信号。
- `src/acabot/runtime/bootstrap/builders.py` — backend 组件构造。
- `src/acabot/runtime/bootstrap/components.py` — 把 backend 组件纳入 RuntimeComponents。
- `src/acabot/runtime/control/control_plane.py` — 暴露 backend status / session binding 的最小控制面。
- `src/acabot/runtime/control/http_api.py` — backend HTTP endpoints。
- `src/acabot/runtime/model/model_agent_runtime.py` 或相关 frontstage 接线 — 给前台提供单一 backend bridge 能力。
- `docs/16-front-back-agents-and-self-evolution.md`
- `docs/00-ai-entry.md`
- `docs/02-runtime-mainline.md`
- `docs/08-webui-and-control-plane.md`

### Runtime directories

- `.acabot-runtime/backend/session.json` — canonical backend session binding。
- `.acabot-runtime/self/` — self 预留空间。
- `.acabot-runtime/front-workspaces/` — frontstage workspace。
- `.acabot-runtime/subagents/` — subagent sandbox roots。

> Backend canonical session 的完整 transcript / history 由 `pi` 自己管理。第一阶段不设计 `operations.py` / `artifacts.py` / transcript 镜像系统；如果 WebUI 需要看后台内容，先直接基于 `pi` 的 session/jsonl 做薄读取或展示。

---

## Routing Matrix

| Input | Preconditions | Route | Notes |
| --- | --- | --- | --- |
| 普通群聊/普通私聊消息 | 不匹配后台硬入口，且不在 backend mode | 前台主线 | 继续走现有 RuntimeApp -> Router -> Pipeline |
| `!xxx` | 管理员 | 直接送 backend bridge | 单条透传，回完后默认仍是前台 |
| `/maintain` | 管理员私聊 | enter backend mode | 仅修改 mode registry，不直接走前台聊天主线 |
| 后续私聊消息 | thread 已在 backend mode | 直接送 backend bridge | 后台 canonical session 自己承载连续上下文 |
| 前台内部 `query` | 前台 bridge 调用 | backend query fork | 从稳定切点 fork，只读，不回写 |
| 前台内部 `change` | 前台 bridge 调用 | backend canonical session | 默认同步，阻塞本次请求本身 |

**Hard rules:**
- 普通用户不能直接和后台交互。
- 前台只允许发 `query` / `change`，不创建后台重维护会话。
- `/maintain` 只允许管理员私聊开启。
- raw `pi` session 管理命令不暴露。

---

## Testing Strategy

### What to test with fakes

第一阶段不要在测试里真实启动 `pi`。统一使用 fake/stub `PiBackendAdapter`，只验证 AcaBot 这层的行为：

- backend request 契约是否正确组装
- canonical session binding 是否正确保存/加载
- backend mode registry 是否正确 enter/exit
- `!` 与 `/maintain` 的分流是否正确
- query 是否走只读 fork 调用路径
- change 是否走 canonical backend session 调用路径
- control plane / http api 是否暴露最小 backend status 与 session binding

### What not to test in phase 1

- 不测试真实 `pi --mode rpc` 端到端联通
- 不测试完整 backend transcript 解析
- 不测试 WebUI backend transcript viewer
- 不测试 operation/artifact 系统（第一阶段不做）
- 不测试 raw `pi` session 命令

### Manual verification only

以下内容只做手工验证：
- 管理员私聊发送 `!查询当前配置`
- 管理员私聊进入 `/maintain`
- 前台桥接一个 `query`
- 前台桥接一个 `change`
- 确认 `.acabot-runtime/backend/session.json` 正常生成/更新
- 确认 query fork 不回写 canonical backend session

---

## Core File APIs

### `src/acabot/runtime/backend/contracts.py`

必须定义最小对象：

```python
@dataclass(slots=True)
class BackendSourceRef:
    thread_id: str
    channel_scope: str
    event_id: str

@dataclass(slots=True)
class BackendRequest:
    request_id: str
    source_kind: Literal["admin_direct", "frontstage_internal"]
    request_kind: Literal["query", "change"]
    source_ref: BackendSourceRef
    summary: str
    created_at: int
```

不要在第一阶段引入 operation / artifact 契约。

### `src/acabot/runtime/backend/mode_registry.py`

最低 API：

```python
class BackendModeRegistry:
    def enter_backend_mode(self, *, thread_id: str, actor_id: str, entered_at: int) -> None: ...
    def exit_backend_mode(self, thread_id: str) -> None: ...
    def is_backend_mode(self, thread_id: str) -> bool: ...
    def get_backend_mode(self, thread_id: str) -> BackendModeState | None: ...
```

### `src/acabot/runtime/backend/session.py`

最低 API：

```python
@dataclass(slots=True)
class BackendSessionBinding:
    backend_id: str
    transport: str
    pi_session_id: str
    created_at: int
    last_active_at: int
    status: str

class BackendSessionBindingStore:
    def load(self) -> BackendSessionBinding | None: ...
    def save(...): ...

class BackendSessionService:
    async def ensure_backend_session(self) -> BackendSessionBinding: ...
    async def send_change(self, summary: str) -> object: ...
    async def fork_query_from_stable_checkpoint(self, summary: str) -> object: ...
```

**Important:**
- query fork 的切点必须是“上一条已完成用户消息之后的稳定状态”
- 不从正在流式生成或未完成 tool loop 的瞬时态 fork
- backend canonical session 身份由 binding store 决定，不由 `pi` 自己漂移

### `src/acabot/runtime/backend/pi_adapter.py`

最低 API：

```python
class PiBackendAdapter:
    def __init__(self, command: list[str]): ...
    async def ensure_started(self) -> None: ...
    async def prompt(self, prompt: str) -> object: ...
    async def fork_from_stable_checkpoint(self, prompt: str) -> object: ...
    async def dispose(self) -> None: ...
```

第一阶段允许 `fork_from_stable_checkpoint()` 只是接口桩，真实 fork 行为先通过 fake adapter 测。

### `src/acabot/runtime/backend/persona.py`

最低 API：

```python
def build_backend_persona_prompt(...) -> str: ...
```

必须明确写入的规则：
- 后台是 Aca maintainer
- 普通用户不直接和后台交互
- 前台只发 `query/change`
- query 是只读语义
- 前台 change 的范围由 backend persona 自己判断，超界时拒绝并要求管理员显式进入后台
- raw `pi` session 命令不作为默认后台控制面

### `src/acabot/runtime/backend/bridge.py`

最低 API：

```python
class BackendBridge:
    async def handle_admin_direct(self, request: BackendRequest) -> object: ...
    async def handle_frontstage_request(self, request: BackendRequest) -> object: ...
```

最小职责：
- 根据 `request_kind` 分流 `query/change`
- `query` 调 `session.fork_query_from_stable_checkpoint()`
- `change` 调 `session.send_change()`
- 管理员直连时，后台可直接返回给管理员
- 前台桥接卡住时，默认返回前台而不是直接越过前台找普通用户

`bridge.py` 可以承担第一阶段的最小分类与分流，不单独拆 `policy.py` / `queue.py`。

---

## Task 1: 定义 backend 最小契约

**Files:**
- Create: `src/acabot/runtime/backend/contracts.py`
- Modify: `src/acabot/runtime/backend/__init__.py`
- Test: `tests/runtime/backend/test_contracts.py`

- [ ] **Step 1: 写契约测试，固定最小字段**

```python
from acabot.runtime.backend.contracts import BackendRequest, BackendSourceRef


def test_backend_request_minimal_fields():
    source_ref = BackendSourceRef(
        thread_id="thread:1",
        channel_scope="qq:group:123",
        event_id="event:1",
    )
    req = BackendRequest(
        request_id="req:1",
        source_kind="frontstage_internal",
        request_kind="query",
        source_ref=source_ref,
        summary="查询当前图片说明配置",
        created_at=123,
    )
    assert req.request_id == "req:1"
    assert req.source_kind == "frontstage_internal"
    assert req.request_kind == "query"
    assert req.source_ref.thread_id == "thread:1"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_contracts.py::test_backend_request_minimal_fields -v`
Expected: FAIL with import/module not found.

- [ ] **Step 3: 实现最小契约对象**

实现：
- `BackendSourceRef(thread_id, channel_scope, event_id)`
- `BackendRequest(request_id, source_kind, request_kind, source_ref, summary, created_at)`

注意：
- 不引入 operation / artifact 契约
- 不引入多余 response 类型
- 第一阶段只固定 bridge 需要的最小请求对象

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/backend/__init__.py src/acabot/runtime/backend/contracts.py tests/runtime/backend/test_contracts.py
git commit -m "feat(runtime): add backend contracts"
```

---

## Task 2: 实现管理员后台模式注册表

**Files:**
- Create: `src/acabot/runtime/backend/mode_registry.py`
- Test: `tests/runtime/backend/test_mode_registry.py`

- [ ] **Step 1: 写失败测试，覆盖 enter / exit / query**

```python
from acabot.runtime.backend.mode_registry import BackendModeRegistry


def test_backend_mode_registry_tracks_private_maintain_mode():
    registry = BackendModeRegistry()
    assert registry.is_backend_mode("thread:1") is False
    registry.enter_backend_mode(thread_id="thread:1", actor_id="admin:1", entered_at=1)
    assert registry.is_backend_mode("thread:1") is True
    registry.exit_backend_mode("thread:1")
    assert registry.is_backend_mode("thread:1") is False
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_mode_registry.py::test_backend_mode_registry_tracks_private_maintain_mode -v`
Expected: FAIL.

- [ ] **Step 3: 实现 `BackendModeRegistry`**

实现：
- `enter_backend_mode()`
- `exit_backend_mode()`
- `is_backend_mode()`
- `get_backend_mode()`

第一版先做内存态即可，但接口要允许后续持久化。

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_mode_registry.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/backend/mode_registry.py tests/runtime/backend/test_mode_registry.py
git commit -m "feat(runtime): add backend mode registry"
```

---

## Task 3: 实现 canonical backend session binding

**Files:**
- Create: `src/acabot/runtime/backend/session.py`
- Create: `src/acabot/runtime/backend/persona.py`
- Test: `tests/runtime/backend/test_session_binding.py`

- [ ] **Step 1: 写失败测试，固定 canonical binding 语义**

```python
from pathlib import Path
from acabot.runtime.backend.session import BackendSessionBindingStore


def test_backend_session_binding_roundtrip(tmp_path: Path):
    store = BackendSessionBindingStore(tmp_path / "session.json")
    store.save(
        backend_id="main",
        transport="rpc",
        pi_session_id="pi-session-1",
        created_at=1,
        last_active_at=2,
        status="ready",
    )
    binding = store.load()
    assert binding.backend_id == "main"
    assert binding.pi_session_id == "pi-session-1"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_session_binding.py::test_backend_session_binding_roundtrip -v`
Expected: FAIL.

- [ ] **Step 3: 实现 binding store 和 persona builder**

实现：
- `BackendSessionBinding`
- `BackendSessionBindingStore`
- `.acabot-runtime/backend/session.json` 的读写
- `build_backend_persona_prompt(...)`

注意 persona 里要明确写入：
- 后台是 Aca maintainer
- 普通用户不直接和后台交互
- 前台只发 `query/change`
- query 只读 fork
- raw `pi` session 命令不作为默认后台控制面

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_session_binding.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/backend/session.py src/acabot/runtime/backend/persona.py tests/runtime/backend/test_session_binding.py
git commit -m "feat(runtime): add backend session binding"
```

---

## Task 4: 实现 `pi --mode rpc` 适配层

**Files:**
- Create: `src/acabot/runtime/backend/pi_adapter.py`
- Test: `tests/runtime/backend/test_pi_adapter.py`

- [ ] **Step 1: 写失败测试，先固定 adapter 接口**

```python
from acabot.runtime.backend.pi_adapter import PiBackendAdapter


def test_pi_adapter_exposes_minimal_backend_api():
    adapter = PiBackendAdapter(command=["pi", "--mode", "rpc"])
    assert hasattr(adapter, "ensure_started")
    assert hasattr(adapter, "prompt")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_pi_adapter.py::test_pi_adapter_exposes_minimal_backend_api -v`
Expected: FAIL.

- [ ] **Step 3: 实现最小 adapter**

实现：
- 启动 `pi --mode rpc`
- 保存进程句柄
- 暴露：
  - `ensure_started()`
  - `prompt()`
  - `dispose()`

先把协议边界立起来，哪怕第一版测试用 fake transport / stub 也行。

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_pi_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/backend/pi_adapter.py tests/runtime/backend/test_pi_adapter.py
git commit -m "feat(runtime): add pi backend adapter"
```

---

## Task 5: 实现 backend bridge（分类、query/change 分流）

**Files:**
- Create: `src/acabot/runtime/backend/bridge.py`
- Test: `tests/runtime/backend/test_bridge.py`

- [ ] **Step 1: 写失败测试，固定 bridge 最小行为**

```python
from acabot.runtime.backend.bridge import BackendBridge
from acabot.runtime.backend.contracts import BackendRequest, BackendSourceRef


def test_bridge_routes_query_to_readonly_fork(fake_backend_runtime):
    bridge = fake_backend_runtime.bridge
    request = BackendRequest(
        request_id="req:1",
        source_kind="frontstage_internal",
        request_kind="query",
        source_ref=BackendSourceRef(
            thread_id="thread:1",
            channel_scope="qq:group:1",
            event_id="event:1",
        ),
        summary="查询当前配置",
        created_at=1,
    )
    result = bridge.handle_frontstage_request(request)
    assert result is not None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_bridge.py::test_bridge_routes_query_to_readonly_fork -v`
Expected: FAIL.

- [ ] **Step 3: 实现 bridge 最小行为**

实现：
- `query` → 从 canonical session 稳定切点 fork 只读 query session
- `change` → 直接送 canonical backend session
- `admin_direct` 与 `frontstage_internal` 两类来源分流
- 后台卡住时：
  - 管理员直连 → 直接问管理员
  - 前台桥接 → 默认返回前台

注意：
- 第一版把最小分类与分流收在 `bridge.py`
- 不单独拆 `policy.py` / `queue.py`
- 不在 bridge 里发明 operation/artifact 子系统

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/backend/bridge.py tests/runtime/backend/test_bridge.py
git commit -m "feat(runtime): add backend bridge"
```

---

## Task 6: 接入 RuntimeApp 的后台入口分流

**Files:**
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/router.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Test: `tests/runtime/test_backend_routing.py`

- [ ] **Step 1: 写失败测试，覆盖 `!` 与 `/maintain` 分流**

```python
def test_admin_bang_message_routes_to_backend(...):
    ...

def test_admin_private_maintain_mode_routes_followup_messages_to_backend(...):
    ...
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/test_backend_routing.py -v`
Expected: FAIL.

- [ ] **Step 3: 修改 app/bootstrap 接线**

接入：
- backend mode registry
- backend bridge
- admin `!` routing
- admin private `/maintain` mode routing
- 普通消息仍走前台主线

注意：
- 不在 `router.py` 塞过多 backend 逻辑
- 主要在 `app.py` 做接线

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/test_backend_routing.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/app.py src/acabot/runtime/router.py src/acabot/runtime/bootstrap/builders.py src/acabot/runtime/bootstrap/components.py tests/runtime/test_backend_routing.py
git commit -m "feat(runtime): route admin backend entrypoints"
```

---

## Task 7: 给前台增加单一 backend bridge 能力

**Files:**
- Modify: `src/acabot/runtime/tool_broker/` 相关接线
- Modify: `src/acabot/runtime/model/model_agent_runtime.py`（如需 metadata）
- Test: `tests/runtime/backend/test_frontstage_backend_bridge.py`

- [ ] **Step 1: 写失败测试，固定前台只能发 `query/change`**

```python
def test_frontstage_backend_bridge_only_supports_query_and_change(...):
    ...
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/backend/test_frontstage_backend_bridge.py -v`
Expected: FAIL.

- [ ] **Step 3: 接入前台 bridge 能力**

实现：
- 前台单一 backend bridge 能力
- 前台写 `summary`
- 前台只允许 `query/change`
- 前台不创建后台重维护会话
- change 范围主要由 backend persona 自己判断

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/backend/test_frontstage_backend_bridge.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/tool_broker src/acabot/runtime/model/model_agent_runtime.py tests/runtime/backend/test_frontstage_backend_bridge.py
git commit -m "feat(runtime): add frontstage backend bridge"
```

---

## Task 8: 暴露最小 backend control plane / HTTP API

**Files:**
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Test: `tests/runtime/control/test_backend_http_api.py`

- [ ] **Step 1: 写失败测试，覆盖 backend status / binding API**

```python
def test_backend_status_endpoint_returns_binding(...):
    ...
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/runtime/control/test_backend_http_api.py -v`
Expected: FAIL.

- [ ] **Step 3: 实现最小 control plane 与 HTTP API**

新增最小接口：
- `get_backend_status()`
- `get_backend_session_binding()`
- `get_backend_session_path()`

注意：
- 不做 operation list
- 不做 artifact list
- 不做 backend transcript 镜像 API
- 如果 WebUI 要看后台内容，第一版直接基于 `pi` jsonl

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/runtime/control/test_backend_http_api.py -v`
Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/http_api.py tests/runtime/control/test_backend_http_api.py
git commit -m "feat(runtime): expose minimal backend control plane APIs"
```

---

## Task 9: 文档同步

**Files:**
- Modify: `docs/16-front-back-agents-and-self-evolution.md`
- Modify: `docs/00-ai-entry.md`
- Modify: `docs/02-runtime-mainline.md`
- Modify: `docs/08-webui-and-control-plane.md`

- [ ] **Step 1: 在文档里补 backend canonical session 接线**

更新内容：
- 后台就是 canonical `pi` session
- canonical binding registry
- query fork 稳定切点规则

- [ ] **Step 2: 在文档里补前台只发 `query/change`**

更新内容：
- 普通用户不直接和后台交互
- 前台只发 summary + source_ref
- backend transcript 真源归 `pi`

- [ ] **Step 3: 在文档里补 WebUI/backend 最小视图**

更新内容：
- backend session binding
- backend jsonl 作为查看真源
- 不重建 operation/artifact 子系统

- [ ] **Step 4: 校验 docs 一致性**

Run: `rg -n "backend|pi session|maintain" docs/*.md`
Expected: 关键文档表述一致，没有明显矛盾说法。

- [ ] **Step 5: 提交**

```bash
git add docs/16-front-back-agents-and-self-evolution.md docs/00-ai-entry.md docs/02-runtime-mainline.md docs/08-webui-and-control-plane.md
git commit -m "docs: describe backend aca pi integration"
```

---

## Verification Checklist

在宣称第一阶段完成前，至少执行：

- [ ] `pytest tests/runtime/backend -v`
- [ ] `pytest tests/runtime/control/test_backend_http_api.py -v`
- [ ] `pytest tests/runtime/test_backend_routing.py -v`
- [ ] 运行一次最小手工验证：
  - 管理员私聊发送 `!查询当前配置`
  - 管理员私聊进入 `/maintain`
  - 前台桥接一个 `query`
  - 前台桥接一个 `change`
- [ ] 确认 `.acabot-runtime/backend/session.json` 正常生成/更新
- [ ] 确认 query fork 不回写 canonical backend session
- [ ] 确认 WebUI / control plane 能读到 backend session binding 与 session path

---

## Notes for Execution

- 第一阶段不要重建完整 backend transcript 系统。
- 第一阶段不要设计 `operations.py` / `artifacts.py` / `projection.py`。
- backend canonical session 的完整历史以 `pi` 自己的 session/jsonl 为真源。
- AcaBot 只保留 canonical binding、mode registry、bridge 和最小 control plane 视图。
- 普通用户不能驱动 backend 重维护流程；管理员才是后台维护面的直接使用者。
