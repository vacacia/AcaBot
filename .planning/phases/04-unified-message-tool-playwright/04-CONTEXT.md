# Phase 4: Unified Message Tool + Playwright - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

给 agent 完整的 QQ 消息能力（文本/引用/@ mention/reaction/撤回/图片/文转图/跨会话），通过统一的 `message` 工具表达意图，映射到 Action -> Outbox -> NapCat Gateway。同时集成 Playwright 文转图渲染能力作为 send action 的内嵌字段。

工具层只表达意图，不直接调用 Gateway。

</domain>

<decisions>
## Implementation Decisions

### 工具结构
- **D-01:** 单一 `message` 工具，`action` 参数枚举所有操作，`action` 默认值为 `"send"`
- **D-02:** v1 支持 3 个 action：`send` / `react` / `recall`

### send action 字段设计
- **D-03:** `send` action 包含以下可选字段，字段存在即代表该能力被启用：
  - `text`: str | None — 文本内容
  - `images`: list[str] | None — 图片本地路径或 URL 列表
  - `render_to_image`: str | None — markdown 内容，工具内部调用 PlaywrightRenderer 渲染为图片后发送
  - `reply_to`: str | None — 被引用消息的 message_id
  - `at_user`: str | None — @mention 的 user_id，工具内部拼接 at segment
  - `target`: str | None — 跨会话目标，格式 Claude 自决（推荐沿用 session_key 格式如 'group:123456'）
- **D-04:** `text`、`images`、`render_to_image` 可共存于同一条消息（工具拼接多段 segments 发出）
- **D-05:** `render_to_image` 为空/None 时不启用文转图

### react action 字段设计
- **D-06:** `react` action 字段：`message_id`（目标消息）+ `emoji`（表情名称或 emoji 字符）
- **D-07:** 工具内部维护 emoji 名称 / Unicode emoji → QQ emoji_id 数字的映射表。Agent 使用直观名称，不需要知道 QQ 内部编号

### recall action 字段设计
- **D-08:** `recall` action 字段：`message_id`（要撤回的消息 ID）

### 图片来源
- **D-09:** `images` 字段同时支持本地文件路径和远程 URL，工具内部判断后拼接 OneBot v11 image segment

### Playwright 渲染
- **D-10:** `render_to_image` 字段触发渲染，流程为 markdown-it-py → HTML → Playwright screenshot → PNG 文件
- **D-11:** PlaywrightRenderer 作为独立服务，生命周期集成点 Claude 自决（参考 RuntimeScheduler 模式：bootstrap 构建实例，RuntimeApp start/stop 时管理）
- **D-12:** Singleton browser 实例，多次渲染复用，避免重复启动 Chromium

### 跨会话 target
- **D-13:** `target` 字段格式 Claude 自决。推荐沿用 session_key 格式（与现有 session_config 基础设施对齐），如 `"group:123456"` 或 `"private:789"`

### Claude's Discretion
- `target` 字段的具体格式和解析逻辑
- PlaywrightRenderer start/stop 集成到 RuntimeApp 的具体方式
- emoji 映射表的初始收录范围（至少包含 like/heart/thumbsup 等常见名称）
- `render_to_image` 渲染后临时图片文件的存储位置和清理策略
- `message` 工具注册到 BuiltinMessagingToolSurface 的具体实现方式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 现有 Action 和 Gateway 基础
- `src/acabot/types/action.py` — ActionType 枚举（当前已有 SEND_TEXT/SEND_SEGMENTS/RECALL/REACTION），Action dataclass（含 reply_to 字段）
- `src/acabot/gateway/napcat.py` — NapCatGateway 实现，`build_send_payload()` 负责 Action → OneBot v11 API JSON，`_build_msg_payload()` 处理 segment 拼接
- `src/acabot/runtime/gateway_protocol.py` — GatewayProtocol，含 `send(action)` 和 `call_api(action, params)`

### Outbox 层
- `src/acabot/runtime/outbox.py` — Outbox，统一出站组件，`_should_persist_action()` 控制哪些动作写入 MessageStore

### Builtin Tools 模式
- `src/acabot/runtime/builtin_tools/computer.py` — BuiltinComputerToolSurface 示例，工具注册模式参考
- `src/acabot/runtime/builtin_tools/__init__.py` — `register_core_builtin_tools()` 注册入口，新 messaging surface 需在此处注册

### OpenClaw 消息工具参考
- `docs/openclaw-message-tool.md` — OpenClaw message 工具深度分析（单一工具 + action 参数设计，schema 合并逻辑，capability 体系）。AcaBot v1 只需其中的 send/react/recall 子集

### Bootstrap 和生命周期
- `src/acabot/runtime/bootstrap/__init__.py` — DI 组装点，PlaywrightRenderer 在此构建
- `src/acabot/runtime/app.py` — RuntimeApp start/stop，PlaywrightRenderer 生命周期集成参考
- `src/acabot/runtime/scheduler/` — RuntimeScheduler 现有集成模式参考（bootstrap 构建 → RuntimeApp 管理生命周期）

### OneBot v11 消息 segment 格式
- `src/acabot/gateway/napcat.py` §`_build_msg_payload` — text/reply/at/image segment 的拼接方式

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ActionType.RECALL` — 已有，NapCat 已处理 `delete_msg` API 调用
- `ActionType.REACTION` — 已有（但 NapCat 侧实现状态需确认）
- `Action.reply_to` — 已有，`_build_msg_payload()` 已将其转换为 reply segment
- `GatewayProtocol.call_api()` — 提供逃生舱，可调用任意 OneBot v11 API（如 `set_msg_emoji_like`）
- `BuiltinComputerToolSurface` — 工具 Surface 类的标准模式，直接照搬结构

### Established Patterns
- 工具 Surface 类：`BUILTIN_XXX_TOOL_SOURCE` 常量 + `BuiltinXxxToolSurface` 类 + `register(tool_broker)` 方法
- ActionType 枚举扩展：在 `src/acabot/types/action.py` 添加新枚举值
- Gateway payload 扩展：在 `NapCatGateway.build_send_payload()` 增加新 ActionType 的处理分支
- `Outbox._should_persist_action()` 需相应扩展，决定新 action 是否写入 MessageStore

### Integration Points
- `builtin_tools/__init__.py` — `register_core_builtin_tools()` 需要增加 messaging surface 参数和注册调用
- `bootstrap/__init__.py` — 构建 BuiltinMessagingToolSurface，注入 gateway + PlaywrightRenderer
- `app.py` — PlaywrightRenderer 的 start/stop 调用点
- `napcat.py` — 新 ActionType 的 OneBot v11 payload 构建

</code_context>

<specifics>
## Specific Ideas

- `render_to_image` 是 `send` action 的一个可选字段，不是独立 action。字段有内容即触发渲染。
- `emoji` 字段接受直观名称（"like", "heart" 等）或 Unicode emoji，工具维护映射表，agent 无需知道 QQ emoji_id 数字编号。
- QQ 的消息 reaction 使用 `set_msg_emoji_like` API（NapCat 扩展），需要数字 emoji_id，这是映射表存在的原因。
- 单一 `message` 工具覆盖所有消息操作，与 OpenClaw 设计哲学一致，但仅实现 QQ/OneBot v11 所需的最小子集。

</specifics>

<deferred>
## Deferred Ideas

- MSG-V2-01: 合并转发消息 — OneBot v11 合并转发 API 复杂，v1 不做
- MSG-V2-02: 富文本编辑
- MSG-V2-03: Interactive components（按钮、卡片）
- 跨会话 target 通过 list_sessions 查询 — 暂不实现，agent 直接提供 session_key

</deferred>

---

*Phase: 04-unified-message-tool-playwright*
*Context gathered: 2026-04-04*
