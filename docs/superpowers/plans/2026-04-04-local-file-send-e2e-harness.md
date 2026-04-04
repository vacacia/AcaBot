# 本地文件发送 E2E 测试体系 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this task:** User explicitly approved direct work on `main`, no worktree, no per-task reviews, and one overall review only after the full plan is implemented.

**Goal:** 为本地文件发送补齐一套可重复的端到端测试体系：一条从 fake model -> `message` -> `Outbox` -> `NapCatGateway` -> OneBot probe 的 pytest 主回归，以及一条复用真实 `acabot-napcat` 的 smoke 验证路径。

**Architecture:** 测试体系分两层。第一层是可断言的 pytest E2E，使用可控的 OneBot probe 严格验证 payload 和文件可读性；第二层是黑盒 smoke，复用真实 compose 环境和扩展后的 `/api/notifications` 正式入口验证真实 NapCat 兼容性。为了避免重复实现发送合同，`message` tool 与 notifications 入口共享同一份高层 send-intent 规范化逻辑。

**Tech Stack:** Python, pytest, websockets, AcaBot runtime (`ModelAgentRuntime`, `ToolBroker`, `Outbox`, `NapCatGateway`, `RuntimeControlPlane`), docker compose

---

## File Structure

### New files
- `src/acabot/runtime/send_intent.py`
  - 统一高层 send-intent 输入规范化：`text / images / render / target / at_user / reply_to`
  - 供 `message` tool 和 `RuntimeControlPlane.post_notification()` 复用
- `src/acabot/runtime/notification_send_context.py`
  - 为 notifications 与 smoke 提供正式的 conversation -> workspace/world 解析支撑
  - 必须复用 `ComputerRuntime` / `WorkspaceManager` 的正式路径语义，而不是临时拼路径
- `tests/runtime/e2e_onebot_probe.py`
  - OneBot probe helper：反向 WS client、payload capture、按 scheme 校验 file-like ref、成功 ack / no ack 语义
- `tests/runtime/test_send_e2e.py`
  - pytest 主 E2E：fake model 真调用 `tool_executor("message", ...)`，一路打到 `NapCatGateway`
- `scripts/smoke_test_local_file_send.py`
  - 真实 compose 环境 smoke 脚本：调用扩展后的 `/api/notifications`，输出 ack / 日志 / PASS-FAIL

### Modified files
- `src/acabot/runtime/builtin_tools/message.py`
  - 改为复用 send-intent 规范化 helper，而不是自己单独规范 `images`
- `src/acabot/runtime/control/control_plane.py`
  - 扩展 `post_notification()` 支持结构化发送字段
  - 为本地图片发送解析目标会话的 workspace/world view
  - 返回足够的原始 ack 证据（至少 `status` / `retcode`）
- `src/acabot/runtime/outbox.py`
  - 如当前实现仍需补强：保证 notifications 入口创建的 `OutboxItem` 也携带正确 `world_view`
- `tests/runtime/test_outbox.py`
  - 补 notifications/world-view 相关回归（如果实现牵动 Outbox 行为）
- `tests/runtime/test_builtin_tools.py`
  - 如 `message` 改为复用共享 helper，需要补合同回归
- `tests/runtime/test_webui_api.py` 或 `tests/runtime/control/test_backend_http_api.py`
  - 为扩展后的 `/api/notifications` 入口补 API 层验证（按项目现有 API 测试组织二选一）
- `deploy/README.md`
  - 记录 smoke 脚本的使用方式

---

### Task 1: 抽出共享 send-intent 合同，打通 notifications 入口

**Files:**
- Create: `src/acabot/runtime/send_intent.py`
- Modify: `src/acabot/runtime/builtin_tools/message.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/outbox.py`
- Test: `tests/runtime/test_builtin_tools.py`
- Test: `tests/runtime/test_message_tool.py`
- Test: `tests/runtime/test_outbox.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 写失败测试，锁住共享 send-intent 行为**

先写失败测试，覆盖共享 helper 和 notifications/world-view 的完整高风险矩阵：
- `/api/notifications` 接受 `text / images / render / target`
- 本地图片输入使用 workspace 相对路径
- remote URL / `data:` / `base64://` 保持透传
- render 继续可走正式高层发送入口
- 非法绝对路径 / 路径穿越被拒绝
- notifications 创建的发送动作最终带着正确 `world_view` / workspace 解析能力进入 Outbox
- 返回结果包含原始 ack 证据字段（至少 `status` / `retcode`）

示例断言结构：

```python
payload = {
    "conversation_id": "qq:user:10001",
    "images": ["x_screenshot.png"],
}
status, body = request_json_with_status(base_url, "/api/notifications", method="POST", data=payload)
assert status == 200
assert body["ok"] is True
assert body["data"]["ack"]["status"] == "ok"
```

- [ ] **Step 2: 运行定向测试，确认当前失败**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_webui_api.py -q -k "notifications"
```

Expected:
- FAIL，因为当前 `post_notification()` 只支持 `text`
- 或 FAIL，因为返回值没有足够 ack 证据

- [ ] **Step 3: 实现最小共享 helper**

在 `src/acabot/runtime/send_intent.py` 中实现一份可复用 helper，至少提供：
- `normalize_send_intent_payload(...)`
- 复用现有 `message.send` 的图片合同：
  - remote URL / `data:` / `base64://` 透传
  - 本地文件只接受安全相对路径
  - 统一规范化为 `/workspace/...`

同时新增 `src/acabot/runtime/notification_send_context.py`，明确提供：
- 从 `conversation_id` 构造正式 workspace/world 解析所需上下文
- 复用 `ComputerRuntime` / `WorkspaceManager` 的正式路径语义
- 供 `post_notification()` 和 smoke 文件准备逻辑共享

`message.py` 改为调用 send-intent helper，避免双份合同漂移。

- [ ] **Step 4: 扩展 notifications 入口最小实现**

在 `RuntimeControlPlane.post_notification()` 中：
- 接受结构化发送字段
- 组装 `SEND_MESSAGE_INTENT`
- 让返回值带上原始 ack 的关键字段
- 若发送的是 workspace 本地文件，必须调用 `notification_send_context` 中的正式 helper，补齐正式 `world_view` / `workspace_state`
- 必须维护与统一发送投影一致的 `thread_content` / source-intent 语义，避免 image-only / render-only 通知写入空白或漂移的 assistant 内容
- 如有需要，同步调整 `Outbox`，保证 notifications 入口创建的 `OutboxItem` 也能走正式 workspace 发布逻辑

- [ ] **Step 5: 运行测试确认转绿**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_builtin_tools.py tests/runtime/test_message_tool.py tests/runtime/test_outbox.py tests/runtime/test_webui_api.py -q -k "message or notifications or workspace"
```

Expected:
- PASS
- 共享 send-intent 合同没有破坏既有 `message` tool 行为

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/send_intent.py src/acabot/runtime/notification_send_context.py src/acabot/runtime/builtin_tools/message.py src/acabot/runtime/control/control_plane.py src/acabot/runtime/outbox.py tests/runtime/test_builtin_tools.py tests/runtime/test_message_tool.py tests/runtime/test_outbox.py tests/runtime/test_webui_api.py
git commit -m "feat(testing): unify send intent contract"
```

---

### Task 2: 新增 OneBot probe 与 pytest 主 E2E

**Files:**
- Create: `tests/runtime/e2e_onebot_probe.py`
- Create: `tests/runtime/test_send_e2e.py`
- Modify: `tests/runtime/test_outbox.py`（如需要补共享 helper/world-view 回归）
- Modify: `src/acabot/runtime/outbox.py`（仅当 notifications/world-view 注入需要最小补强时）

- [ ] **Step 1: 先写 probe 层失败测试**

在 `tests/runtime/test_send_e2e.py` 里先写最小 E2E，用例至少覆盖：
- fake agent 在 `ModelAgentRuntime` 中真实执行 `tool_executor("message", ...)`
- local workspace 图片发送最终到达 probe
- probe 收到的不是 `/workspace/...`
- probe 能真实读到文件

示例测试骨架：

```python
async def test_message_send_local_workspace_image_reaches_onebot_probe(tmp_path: Path) -> None:
    runtime = build_fake_message_runtime(tmp_path)
    result = await runtime.run_message_send(images=["x_screenshot.png"])
    assert result.ack["status"] == "ok"
    assert result.captured_file_ref != "/workspace/x_screenshot.png"
    assert result.local_file_read_ok is True
```

- [ ] **Step 2: 跑定向测试，确认当前失败**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_send_e2e.py -q
```

Expected:
- FAIL，因为 probe / harness 还不存在
- 或 FAIL，因为 world-view / ack 语义没接通

- [ ] **Step 3: 实现 OneBot probe helper**

在 `tests/runtime/e2e_onebot_probe.py` 中实现：
- 反向 WS client，连接 `NapCatGateway`
- 接收 `send_private_msg` / `send_group_msg`
- 记录 payload
- 校验 `image/file/record/video`：
  - `file://` / 本地路径 -> 真读文件
  - `http://` / `https://` / `data:` / `base64://` -> 校验透传
- 成功时返回 success ack
- **必须镜像请求中的 `echo` 字段**，显式验证 `NapCatGateway.send()` 的 request/ack 关联逻辑
- 失败时走 `no ack` / timeout 语义，不返回会被产品误判成功的 failure ack

- [ ] **Step 4: 实现通用 send-path harness**

在 `tests/runtime/test_send_e2e.py` 附近用 helper 组装最小 runtime：
- fake agent
- `ModelAgentRuntime`
- `ToolBroker`
- 必要的 `RunContext`
- `Outbox`
- `NapCatGateway`

要求：
- 优先复用正式 `ThreadPipeline` / `ComputerRuntime.prepare_run_context()` 路径来注入 `world_view` / `workspace_state`
- 如果确实不能走完整 `ThreadPipeline`，必须在测试里写明并断言当前注入对象与正式路径等价
- fake agent 必须真调 `tool_executor("message", ...)`
- 不能直接手工拼 `PlannedAction`

- [ ] **Step 5: 扩完整覆盖**

在实现补充代码前，先把以下 spec-required cases 写成失败测试；再补实现到转绿：
- workspace 本地图片发送成功
- remote URL 透传
- `data:` / `base64://` 透传
- render 发送仍可用
- 非法本地路径在入口失败

- [ ] **Step 6: 运行测试确认转绿**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_send_e2e.py tests/runtime/test_outbox.py -q
```

Expected:
- PASS
- 证明主 E2E 已经真正覆盖到 OneBot 边界

- [ ] **Step 7: Commit**

```bash
git add tests/runtime/e2e_onebot_probe.py tests/runtime/test_send_e2e.py tests/runtime/test_outbox.py src/acabot/runtime/outbox.py
git commit -m "feat(testing): add send-path e2e probe"
```

---

### Task 3: 用真实 NapCat 补 smoke 脚本

**Files:**
- Create: `scripts/smoke_test_local_file_send.py`
- Modify: `deploy/README.md`
- Modify: `src/acabot/runtime/notification_send_context.py`
- Test: 手动脚本验证（不是 pytest）

- [ ] **Step 1: 先定义脚本输入与输出契约**

脚本至少支持：
- `--conversation-id`
- `--image`（workspace 相对路径）
- `--source-file`（可选，本地源文件；若未提供则脚本自动生成最小 PNG fixture）
- `--text`（可选）
- `--render-file` 或 `--render-text`（可选，若本轮顺手覆盖）
- `--napcat-log-since`（可选）

输出至少包含：
- 发送请求摘要
- 返回 ack 的 `status` / `retcode`
- `acabot-napcat` 日志关键片段
- PASS / FAIL / SKIP/ENV-FAIL

- [ ] **Step 2: 写脚本并先让它对环境前置条件 fail-fast**

脚本先检查：
- `acabot` / `acabot-napcat` 容器是否运行
- WebUI API 是否可达
- NapCat 是否已建立 OneBot 连接

前置条件失败时退出非零并打印 `SKIP/ENV-FAIL`。

- [ ] **Step 3: 用扩展后的 notifications 入口触发真实发送**

脚本通过：
```bash
POST /api/notifications
```
发送结构化 payload 到 live `acabot`，再读取：
- API 返回的原始 ack 证据
- `docker logs acabot-napcat --since ...`

- [ ] **Step 4: 加入 workspace 文件准备逻辑**

脚本需要能：
- 根据目标会话找到或创建对应 workspace 文件
- 把测试图片放进去
- 再用相对路径调用通知入口

要求：
- 这一步必须调用 `notification_send_context` 中与生产共享的 helper
- 不能在脚本里私自重推导另一套 workspace 规则
- 不能偷偷改成直接发 `runtime_data/outbound/...`

- [ ] **Step 5: 运行 smoke 验证**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run python scripts/smoke_test_local_file_send.py --conversation-id qq:user:10001 --image x_screenshot.png
```

Expected:
- PASS
- 原始 ack 语义明确成功（不是仅仅返回了一个非空对象）
- NapCat 日志里没有本地文件读取失败证据（不限于 `ENOENT`，也包括其他 read/copy/file 错误）
- 没有 timeout / no-ack

- [ ] **Step 6: 写 README 用法**

在 `deploy/README.md` 记录：
- 什么时候用 smoke 脚本
- 前置条件
- 成功 / 失败的典型输出解释

- [ ] **Step 7: Commit**

```bash
git add scripts/smoke_test_local_file_send.py deploy/README.md src/acabot/runtime/notification_send_context.py
git commit -m "feat(testing): add napcat smoke script"
```

---

### Task 4: 整体验证、Phase 7 回归与收尾

**Files:**
- Modify: `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md`（如果测试结果需要顺手记录）
- Modify: 相关实现文件（仅在最后一轮修 bug 时）

- [ ] **Step 1: 跑主回归集合**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_builtin_tools.py tests/runtime/test_message_tool.py tests/runtime/test_outbox.py tests/runtime/test_send_e2e.py tests/test_gateway.py -q
```

Expected:
- PASS
- `message` 合同、Outbox 发布层、Gateway 协议层、E2E harness 同时为绿

- [ ] **Step 2: 跑 API / smoke 相关回归**

Run:
```bash
cd /home/acacia/AcaBot
PYTHONPATH=src uv run pytest tests/runtime/test_webui_api.py -q -k "notifications"
PYTHONPATH=src uv run python scripts/smoke_test_local_file_send.py --conversation-id qq:user:10001 --image x_screenshot.png
```

Expected:
- pytest PASS
- smoke PASS（原始 ack 明确成功，且没有本地文件读取失败证据）

- [ ] **Step 3: 用真实测试结果回看 Phase 7 本地点是否已闭环**

检查结论至少包括：
- workspace 本地文件是否还会把 `/workspace/...` 直接传到 NapCat
- 真实 `acabot-napcat` 是否仍然报 `ENOENT`
- 如果已闭环，记录“已具备日常回归手段”
- 如果仍未闭环，继续修到 smoke 通过为止

- [ ] **Step 4: 整体代码评审（一次性）**

按用户要求，这一轮不做逐 task review；等整个 plan 完成后，只做一次完整 review。

Run reviewer with context:
- spec: `docs/superpowers/specs/2026-04-04-local-file-send-e2e-harness-design.md`
- plan: `docs/superpowers/plans/2026-04-04-local-file-send-e2e-harness.md`
- implementation diff
- verification commands and outputs

Expected:
- reviewer 给出 APPROVED

- [ ] **Step 5: Commit final fixes**

```bash
git add src tests scripts deploy .planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md
git commit -m "test: add end-to-end local file send harness"
```
