# 后台 Aca（基于长期 pi session）Implementation Plan

**Goal:** 把 backend 从“壳已经接上，但真实 runtime 里永远关闭”做到“真实 runtime 下可启用、真实请求可走通、文档同步完成”。

**Done already:** backend contracts、mode registry、bridge、admin entrypoint 壳、`ask_backend` tool 壳、backend control plane / http api 壳都已经有了。

**Still not done:** 真实 `pi` 还没接上，真实 configured session service 还没接上，所以现在真实 runtime 里 backend 还是关着的。

---

## Task 1: 把真实 `pi` 和真实 backend session service 接上

这一整个 task 要一次做完，不要拆碎。

### 要做什么
- 把 `src/acabot/runtime/backend/pi_adapter.py` 从 stub 改成真实 adapter
- 必须真实启动 `pi --mode rpc`
- 必须真实和 `pi` 完成 request / response
- 在 `src/acabot/runtime/backend/session.py` 里落地真正的 `ConfiguredBackendSessionService`
- `ConfiguredBackendSessionService` 必须持有：
  - `BackendSessionBindingStore`
  - `PiBackendAdapter`
- `send_change()` 真走 canonical backend session
- `query` 真走一条只读路径
- raw `pi` session 命令必须测试，预期无效：
  - 不改变 canonical binding
  - 不切走 `.acabot-runtime/backend/session.json`

### 做完后必须看到什么
- 真实 `pi --mode rpc` 可启动
- 能真实发一条请求给 `pi`
- 能真实收到一条返回
- `send_change()` 不再是 `NotImplementedError`
- `query` 不再是 `NotImplementedError`

### 主要文件
- `src/acabot/runtime/backend/session.py`
- `src/acabot/runtime/backend/pi_adapter.py`
- `src/acabot/runtime/backend/persona.py`
- `tests/runtime/backend/test_pi_adapter.py`
- `tests/runtime/backend/test_session_binding.py`
- 需要的话新增真实集成测试文件

### 这一步的硬要求
- 不准再只测 fake/stub
- 必须真实测 `pi`
- 如果这一步没成，不继续 Task 2

---

## Task 2: 把真实 runtime 启用路径全部打通

### 要做什么
- 在 `build_runtime_components()` 里根据 config 构造真正的 configured backend service
- 不能再让真实 runtime 永远 `is_configured() == False`
- 管理员入口真正打通：
  - `!`
  - `/maintain`
  - `/maintain off`
  - maintain mode follow-up
- 前台 `ask_backend` 真正打通
- `ask_backend` 必须满足：
  - 只对默认 frontstage agent 可见
  - subagent / worker 不可见
  - `visible_tools()` 和 `ToolBroker.execute()` 准入一致
  - 不再出现“看得见但执行被 broker 拒绝”
- control plane / http api 要反映真实 runtime 状态：
  - `configured` 真表示 backend 已启用
  - `session_path` 不为空
  - `session_binding` 可读

### 做完后必须看到什么
- 真实 runtime 下 backend 能被打开
- 管理员私聊 `!查询当前配置` 真能进入 backend
- 管理员私聊 `/maintain` 真能进入 backend mode
- 管理员私聊 `/maintain off` 真能退出 backend mode
- `ask_backend(query)` 真能执行
- `ask_backend(change)` 真能执行
- `/api/backend/session-path` 返回真实稳定路径

### 主要文件
- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/bootstrap/components.py`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/tool_broker/broker.py`
- `src/acabot/runtime/plugins/backend_bridge_tool.py`
- `src/acabot/runtime/plugin_manager.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/snapshots.py`
- `tests/runtime/test_backend_routing.py`
- `tests/runtime/test_tool_broker.py`
- `tests/runtime/test_tool_broker_backend_bridge.py`
- `tests/runtime/test_bootstrap.py`
- `tests/runtime/test_control_plane.py`
- `tests/runtime/test_webui_api.py`
- `tests/runtime/control/test_backend_http_api.py`

---

## Task 3: 完整验证并同步文档

### 要做什么
先完整验证，再改文档，不要反过来。

### 必跑验证
```bash
PYTHONPATH=src pytest tests/runtime/backend -v
PYTHONPATH=src pytest tests/runtime/test_backend_routing.py -v
PYTHONPATH=src pytest tests/runtime/test_tool_broker.py tests/runtime/test_tool_broker_backend_bridge.py -v
PYTHONPATH=src pytest tests/runtime/test_bootstrap.py tests/runtime/test_control_plane.py tests/runtime/test_webui_api.py tests/runtime/control/test_backend_http_api.py -v
PYTHONPATH=src pytest tests/runtime/backend/test_pi_adapter.py -v
```

### 必做手工验证
- 管理员私聊 `!查询当前配置`
- 管理员私聊 `/maintain`
- 管理员私聊 `/maintain off`
- 前台 `ask_backend(query)`
- 前台 `ask_backend(change)`
- backend 面输入 raw `pi` session 命令，确认无效且不改变 canonical binding
- 确认 `.acabot-runtime/backend/session.json` 被真实 runtime 使用
- 确认 `/api/backend/session-path` 返回真实路径

### 要同步的文档
- `docs/00-ai-entry.md`
- `docs/02-runtime-mainline.md`
- `docs/08-webui-and-control-plane.md`
- `docs/16-front-back-agents-and-self-evolution.md`

### 文档里必须写清楚
- backend 什么时候算 enabled
- `ask_backend` 的定位：标准 tool，但只给前台主 agent
- `!` / `/maintain` / `/maintain off` 的语义
- backend control plane 的 `configured` / `session_path` / `session_binding` 含义

---

## Out of scope

这次就不做：
- operation system
- artifact system
- projection system
- transcript 镜像
- 复杂 WebUI transcript viewer

backend transcript 真源仍然是 `pi` 自己的 jsonl。

---

## Completion standard

只有下面都满足，才算完成：
- 真实 `pi` 已接通
- 真实 runtime 下 backend 已启用
- `!` / `/maintain` / `/maintain off` 可用
- `ask_backend` 可用
- raw `pi` session 命令无效且不会改变 canonical binding
- control plane 返回真实 backend 状态
- 文档同步完成
