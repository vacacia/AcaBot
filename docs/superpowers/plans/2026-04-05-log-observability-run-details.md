# 日志可观测性增强 + Run 详情 Implementation Plan

> **For agentic workers:** Execute this plan directly in the current `main` session (no new worktree). Do spec/plan review before coding, skip per-task review during implementation, and do one overall review at the end. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 WebUI `/logs` 中直接展开完整日志安全快照，并从日志进入 run 详情查看最近 steps、tool 参数与 exec 证据，不再依赖手工 curl 或进容器排障。

**Architecture:** 复用现有 `/api/system/logs` 与 run API，但补齐三条契约：统一日志/inspection 安全快照、run steps 的 `latest=true + step_seq` 语义、run 详情请求 fresh/no-cache。前端把日志流与 run 详情拆成两个组件：`LogStreamPanel` 负责日志列表与展开交互，`RunDetailPanel` 负责拉取并展示选中 run 的详情。

**Tech Stack:** Python runtime, structlog/logging, SQLite/in-memory runtime stores, Vue 3 + TypeScript, Vite built assets, pytest

---

## File Structure

### Backend
- Modify: `src/acabot/runtime/control/log_setup.py`
  - 提供统一日志/inspection 安全快照 serializer。
- Modify: `src/acabot/runtime/control/log_buffer.py`
  - `message` 与 `extra` 入 buffer 前都走安全快照。
- Modify: `src/acabot/runtime/tool_broker/broker.py`
  - 补齐 `tool_name / run_id / thread_id / agent_id / actor_id / duration_ms / tool_arguments / tool_result_snapshot / error` 等结构化日志字段。
- Modify: `src/acabot/runtime/computer/runtime.py`
  - 在 `exec` step payload 中补 `stdout_excerpt / stderr_excerpt`。
- Modify: `src/acabot/runtime/contracts/context.py`
  - 为 `RunStep` 增加单调顺序字段（如 `step_seq`）。
- Modify: `src/acabot/runtime/storage/runs.py`
  - RunManager / store 接口透传 `step_seq`。
- Modify: `src/acabot/runtime/storage/sqlite_stores.py`
  - 保存/读取 `step_seq`，支持 `latest=true` 的 latest-N 查询语义，并处理已有 SQLite 表的升级迁移/兼容。
- Modify: `src/acabot/runtime/storage/stores.py`
  - 更新 store protocol。
- Modify: `src/acabot/runtime/control/control_plane.py`
  - run / steps API 返回 inspection serializer 安全快照；支持 `latest=true`。
- Modify: `src/acabot/runtime/control/http_api.py`
  - 解析 `latest=true` 查询参数并走 control plane。

### Frontend
- Modify: `webui/src/lib/api.ts`
  - 提供 fresh/no-cache GET helper，run 详情请求绕过默认缓存。
- Modify: `webui/src/components/LogStreamPanel.vue`
  - 增加日志展开区、完整 JSON、安全快照展示、可选 run 详情入口、feature gating props。
- Create: `webui/src/components/RunDetailPanel.vue`
  - 负责拉取 run + latest steps 并展示详情抽屉/面板。
- Modify: `webui/src/views/LogsView.vue`
  - 组装日志页与 run 详情面板，打开/关闭选中 run。
- Modify: `webui/src/views/HomeView.vue`
  - 显式保持日志预览禁用详情能力（避免复用回归）。

### Built assets
- Modify: `src/acabot/webui/index.html`
- Modify: `src/acabot/webui/assets/*`
  - 前端构建产物更新。

### Tests
- Modify: `tests/runtime/test_log_buffer.py`
  - 覆盖 message/extra 安全快照行为。
- Create or Modify: `tests/runtime/test_tool_broker_logging.py`
  - 覆盖 tool 日志字段、脱敏、截断、固定 schema。
- Modify: `tests/runtime/test_webui_api.py`
  - 覆盖 logs API 安全快照、run API 安全快照、steps latest=true、fresh/no-cache 相关客户端契约、built assets 回归。
- Modify: `tests/runtime/test_model_agent_runtime.py` or `tests/runtime/test_outbox.py` only if existing helpers are needed.

## Task 1: 先写 backend RED，钉住日志与 run-steps 契约

**Files:**
- Modify: `tests/runtime/test_log_buffer.py`
- Create/Modify: `tests/runtime/test_tool_broker_logging.py`
- Modify: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 为日志安全快照写失败测试**
  - 在 `test_log_buffer.py` 增加：
    - `message` 超长会被预算截断
    - `extra` 的敏感键会被脱敏
    - 非 JSON-safe 值会被安全字符串化/归一化

- [ ] **Step 2: 运行日志缓冲测试，确认 RED**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_log_buffer.py -q`
  - Expected: 新增断言失败，提示当前 `message/extra` 仍原样入 buffer。

- [ ] **Step 3: 为 tool 日志字段写失败测试**
  - 在 `test_tool_broker_logging.py` 覆盖：
    - 成功/失败/拒绝日志都包含 `tool_name / run_id / thread_id / agent_id / actor_id / duration_ms`
    - 成功日志包含 `tool_arguments`
    - 结果字段使用固定 `tool_result_snapshot`，并断言 `llm_content / raw / metadata / attachment_count / artifact_count / user_action_count`
    - 失败日志包含 `error`
    - token/password 类参数被脱敏

- [ ] **Step 4: 运行 tool 日志测试，确认 RED**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_tool_broker_logging.py -q`
  - Expected: 失败，说明当前 broker 没有打出这些字段或没有统一 serializer。

- [ ] **Step 5: 为 run API latest/fresh 契约写失败测试**
  - 在 `test_webui_api.py` 增加：
    - `/api/runtime/runs/:id` 返回 `metadata / approval_context` 安全快照
    - `/api/runtime/runs/:id/steps?limit=2&latest=true` 返回最近两条而非最早两条
    - steps 响应包含稳定顺序字段（如 `step_seq`）
    - steps 响应里的 `payload` 是 inspection serializer 安全快照，不是原始对象
    - built asset 中存在 run detail / expanded log 入口字符串

- [ ] **Step 6: 运行 WebUI API 测试，确认 RED**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_webui_api.py -q -k "logs or runtime_runs or built_assets or latest"`
  - Expected: 新增断言失败。

## Task 2: 实现统一安全快照与 tool 日志增强

**Files:**
- Modify: `src/acabot/runtime/control/log_setup.py`
- Modify: `src/acabot/runtime/control/log_buffer.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Test: `tests/runtime/test_log_buffer.py`
- Test: `tests/runtime/test_tool_broker_logging.py`

- [ ] **Step 1: 在 `log_setup.py` 增加共享 serializer**
  - 提供小而稳定的辅助函数，例如：
    - `sanitize_log_message(...)`
    - `sanitize_log_extra(...)`
    - `sanitize_inspection_value(...)`
  - 要求：JSON-safe、脱敏、预算截断、递归处理 dict/list。

- [ ] **Step 2: 让 `InMemoryLogHandler` 在写 buffer 前处理 `message + extra`**
  - `log_buffer.py` 不再保存原始 `record.getMessage()` 与原始 extra。
  - 所有日志统一走安全快照。

- [ ] **Step 3: 在 `ToolBroker` 成功/失败/拒绝日志里补齐结构化字段**
  - 成功：`tool_arguments`、`tool_result_snapshot`、`result_summary`
  - 失败：`tool_arguments`、`error`
  - 拒绝：`tool_arguments`、`reason`
  - 复用共享 serializer，不在 broker 里另写一套脱敏逻辑。

- [ ] **Step 4: 跑后端单测，确认 GREEN**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_log_buffer.py tests/runtime/test_tool_broker_logging.py -q`
  - Expected: PASS

- [ ] **Step 5: 提交阶段性 commit**
  - Commit: `feat(logs): sanitize structured log snapshots`

## Task 3: 实现 run steps 的 latest=true + step_seq 契约

**Files:**
- Modify: `src/acabot/runtime/contracts/context.py`
- Modify: `src/acabot/runtime/storage/stores.py`
- Modify: `src/acabot/runtime/storage/runs.py`
- Modify: `src/acabot/runtime/storage/sqlite_stores.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/app.py` (若有统一 append_step helper 也要带上 step_seq 支持)
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 先为 SQLite 迁移/兼容写失败测试**
  - 覆盖已有 `run_steps` 旧表升级后缺少 `step_seq` 时的行为。
  - 断言升级后仍可 append / query，并支持 `latest=true`。

- [ ] **Step 2: 让 step 记录具备单调顺序字段**
  - 给 `RunStep` 增加 `step_seq`。
  - 在 append step 路径分配 per-run 单调递增序号。
  - SQLite / in-memory store 均保持同一语义。
  - SQLite 需要显式 schema migration / fallback 初始化，不能只依赖 `CREATE TABLE IF NOT EXISTS`。

- [ ] **Step 3: 扩展 steps 查询接口支持 `latest=true`**
  - `latest=false` 保持兼容行为。
  - `latest=true`：选最近 N 条，再按 `step_seq ASC` 返回。

- [ ] **Step 4: 在 run/steps API 输出时走 inspection serializer**
  - 至少处理：
    - run `metadata`
    - run `approval_context`
    - step `payload`

- [ ] **Step 5: 先为 `computer.exec` excerpt 写失败测试**
  - 在 `test_webui_api.py` 或更贴近 runtime 的现有测试文件中，明确断言 step payload 含 `stdout_excerpt / stderr_excerpt`。

- [ ] **Step 6: 在 `computer.exec` step payload 中补 `stdout_excerpt / stderr_excerpt`**
  - 复用已有 `CommandExecutionResult` 窗口字段。

- [ ] **Step 7: 跑 API / storage 相关测试**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_webui_api.py -q -k "runtime_runs or latest or logs"`
  - Expected: PASS

- [ ] **Step 8: 提交阶段性 commit**
  - Commit: `feat(runtime): add latest run steps inspection details`

## Task 4: 实现前端日志展开与 RunDetailPanel

**Files:**
- Modify: `webui/src/lib/api.ts`
- Modify: `webui/src/components/LogStreamPanel.vue`
- Create: `webui/src/components/RunDetailPanel.vue`
- Modify: `webui/src/views/LogsView.vue`
- Modify: `webui/src/views/HomeView.vue`
- Test: `tests/runtime/test_webui_api.py`

- [ ] **Step 1: 在 `api.ts` 增加 fresh GET helper**
  - 例如 `apiGetFresh()` 或等价 no-cache helper。
  - run 详情请求必须绕过默认 15 秒缓存。

- [ ] **Step 2: 为 `LogStreamPanel` 增加 feature gating props**
  - 例如：
    - `showDetails`
    - `showRunDetails`
  - 默认关闭，避免首页预览受影响。

- [ ] **Step 3: 在 `LogStreamPanel` 实现单条日志展开**
  - 收起状态：保留现有样式 + chips
  - 展开状态：
    - 完整 message
    - 完整 extra JSON
    - tool 相关字段优先可读展示

- [ ] **Step 4: 新建 `RunDetailPanel.vue`**
  - 输入：`runId`
  - 拉取：
    - `/api/runtime/runs/:run_id`
    - `/api/runtime/runs/:run_id/steps?limit=200&latest=true`
  - 展示：
    - 基础信息
    - 高亮 metadata 关键字段（至少 `model_used / token_usage / model_snapshot`）
    - `approval_context`
    - 明确的“最近 200 条”提示
    - steps 列表与 payload 展开区
    - step 级轻量语义化摘要：`workspace_prepare / exec / approval_*`
    - 其余 step 默认退回 JSON

- [ ] **Step 5: 在 `LogsView.vue` 里组装 run 详情抽屉/侧栏**
  - 从 `LogStreamPanel` 接收“查看 run”事件
  - 控制详情面板打开/关闭

- [ ] **Step 6: 在 `HomeView.vue` 显式禁用详情能力**
  - 保证首页日志预览维持简洁模式。

- [ ] **Step 7: 运行前端相关 API/asset 回归测试**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_webui_api.py -q -k "built_assets or logs or runtime_runs"`
  - Expected: PASS

- [ ] **Step 8: 构建前端并同步产物**
  - Run: `npm --prefix webui run build`
  - 然后确认 `src/acabot/webui/` 产物已更新。

- [ ] **Step 9: 提交阶段性 commit**
  - Commit: `feat(webui): add expandable logs and run details`

## Task 5: 整体验证、构建产物回归、真实复现验收

**Files:**
- Modify if needed: `deploy/README.md`（若要补一条如何用日志页排障的说明）
- Test: existing runtime suites

- [ ] **Step 1: 跑目标回归测试集合**
  - Run: `PYTHONPATH=src uv run pytest tests/runtime/test_log_buffer.py tests/runtime/test_tool_broker_logging.py tests/runtime/test_webui_api.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_context_assembler.py tests/runtime/test_message_tool.py tests/runtime/test_outbox.py tests/test_gateway.py -q`
  - Expected: PASS

- [ ] **Step 2: 如前端代码有变化，重建 `acabot` 容器**
  - Run: `cd deploy && docker compose up -d --build acabot`
  - Expected: 容器重建成功，仅影响 `acabot`。

- [ ] **Step 3: 手工验证 WebUI `/logs`**
  - 打开日志页，确认：
    - 日志可展开
    - 可看到完整 message / extra 安全快照
    - 带 `run_id` 的日志可打开 run 详情

- [ ] **Step 4: 复现一次“截图网页然后发给我”类场景**
  - 触发一个会执行 tool + exec 的 run。
  - 在 WebUI 中确认可看到：
    - tool 参数中的 URL
    - exec command
    - stdout/stderr excerpt
    - run steps

- [ ] **Step 5: 做最终总 review（不按 task 拆 review）**
  - Dispatch `reviewer` 对实现文件 + 测试结果做一次整体 review。
  - 如果有 blocking issues，统一修完再重复一次。

- [ ] **Step 6: 最终提交**
  - Commit: `feat(debug): improve log observability and run details`
