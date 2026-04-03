# Phase 4: Unified Message Tool + Playwright - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

给 agent 完整的 QQ 消息能力（文本、引用、@ mention、reaction、撤回、图片、文转图、跨会话），通过统一的 `message` 工具表达意图，并映射到 `Action -> Outbox -> NapCat Gateway`。

渲染能力属于出站消息的表现层基础设施，不是独立 tool，也不是硬绑 Playwright 的实现细节。v1 目标是把 `send` action 的富内容发送能力收束干净，让后续 planner 可以在不重新问用户的前提下落代码。

</domain>

<decisions>
## Implementation Decisions

### 工具结构
- **D-01:** 单一 `message` 工具，`action` 参数枚举所有操作，`action` 默认值为 `"send"`
- **D-02:** v1 支持 3 个 action：`send` / `react` / `recall`

### send action 字段设计
- **D-03:** `send` action 包含以下可选字段，字段存在即代表该能力被启用：
  - `text`: `str | None` — 普通文本内容
  - `images`: `list[str] | None` — 图片本地路径或 URL 列表
  - `render`: `str | None` — 一整段待渲染源内容
  - `reply_to`: `str | None` — 被引用消息的 `message_id`
  - `at_user`: `str | None` — 要 @ 的 `user_id`
  - `target`: `str | None` — 跨会话目标，使用完整 canonical `conversation_id`
- **D-04:** `render` 不暴露 `format` 字段。v1 固定解释为 `Markdown + LaTeX math`，也就是 markdown 正文中允许 inline / block math，不承诺完整 TeX 文档编译流程
- **D-05:** `text`、`images`、`render` 可共存于同一条消息。需要组合发送说明文字时，必须使用工具自带字段表达，不能依赖最终 assistant 普通文本自动补发

### 默认回复抑制
- **D-06:** 如果 `message` 工具的 `send` action 已经发出了内容型消息，runtime 自动抑制本轮默认 assistant 文本回复，避免重复发送
- **D-07:** `react` / `recall` 这类非内容型动作不会触发默认回复抑制
- **D-08:** 工具参数说明里必须明确写清这条规则，告诉后续 agent：如果想“图片 + 说明文字”一起发，直接在 `message.action="send"` 的参数里组合 `text` / `images` / `render`

### react action 字段设计
- **D-09:** `react` action 字段：`message_id` + `emoji`
- **D-10:** `emoji` 字段接受直观名称或 Unicode emoji 字符。工具内部维护名称 / Unicode → QQ `emoji_id` 的映射
- **D-11:** 如果 `emoji` 无法映射到 QQ `emoji_id`，本次 `react` 严格失败，不做静默 fallback，也不自动改发说明文本

### recall action 字段设计
- **D-12:** `recall` action 字段：`message_id`

### 图片来源
- **D-13:** `images` 字段同时支持本地文件路径和远程 URL，由 runtime 在发送编译阶段统一物化为可发送图片消息

### 渲染架构
- **D-14:** 渲染是 optional runtime capability，不是 runtime 硬前提，也不是 `message` 工具内部实现
- **D-15:** 渲染发生在 `Outbox materialization layer`，不是 ToolBroker、Gateway 或 Work World
- **D-16:** runtime 只依赖抽象 render service，不依赖 `Playwright` 这个具体名字。Playwright 最多只是一个 backend / adapter
- **D-17:** render backend 采用 capability-based registry + lazy init。没有可用 backend 时，runtime 仍可正常启动
- **D-18:** 渲染产物放在 internal runtime artifacts，不进入 Work World，也不复用 `/workspace/attachments/...`
- **D-19:** 如果渲染失败，`render` 内容按原样降级成普通文本发送，不做 markdown 清洗或 prettify

### 跨会话 target
- **D-20:** `target` 的正式语义是 `conversation_id`，不是 `session_id`
- **D-21:** `target` 只接受完整 canonical 形式，例如 `qq:group:123456`、`qq:user:789`。不接受 `group:123456` 这类缩写

### Action 层设计
- **D-22:** `message` 工具对外保持统一 surface，但 runtime 内部不把所有动作都抬成同一层
- **D-23:** v1 只有 `send` 进入高层消息意图 Action，由 Outbox 在 materialization 阶段编译成底层发送动作
- **D-24:** `react` 和 `recall` 继续映射到现有 direct low-level Action，不经过高层内容编译链
- **D-25:** 后续如果继续扩展更多动作，只有需要内容编排、能力探测、fallback、artifact 生成的动作才进入高层 intent family。统一的是 tool surface，分层的是 runtime internals

### Remaining Claude's Discretion
- `message.send` 高层 Action 的最终命名，例如 `SEND_MESSAGE`、`MESSAGE_SEND_INTENT` 或等价抽象
- render service 的具体模块拆分、构造注入点和 artifact 目录命名
- emoji 映射表的初始覆盖范围，只要能满足常见 reaction 即可
- `message` 工具在 builtin tool surface 中的具体注册方式

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 现有 Action 和 Gateway 基础
- `src/acabot/types/action.py` — ActionType 枚举（当前已有 `SEND_TEXT` / `SEND_SEGMENTS` / `RECALL` / `REACTION`），Action dataclass（含 `reply_to` 字段）
- `src/acabot/gateway/napcat.py` — NapCatGateway 实现，`build_send_payload()` 负责 `Action -> OneBot v11 API JSON`，`_build_msg_payload()` 处理 segment 拼接
- `src/acabot/runtime/gateway_protocol.py` — GatewayProtocol，含 `send(action)` 和 `call_api(action, params)`

### Outbox 层
- `src/acabot/runtime/outbox.py` — Outbox，统一出站组件，后续高层消息意图 Action 的 materialization 切口在这里

### Builtin Tools 模式
- `src/acabot/runtime/builtin_tools/computer.py` — Builtin tool surface 示例，注册模式参考
- `src/acabot/runtime/builtin_tools/__init__.py` — `register_core_builtin_tools()` 注册入口，新 messaging surface 需在此处注册

### OpenClaw 消息工具参考
- `docs/openclaw-message-tool.md` — OpenClaw message 工具分析。AcaBot 只借鉴统一 tool surface，不照搬其内部实现

### 渲染与存储相关
- `src/acabot/runtime/computer/attachments.py` — 现有 attachment staging 语义，渲染产物不应混入这里
- `src/acabot/runtime/computer/workspace.py` — Work World / workspace 语义边界，帮助说明为什么 render artifacts 不进 Work World
- `docs/12-computer.md` — computer / workspace / attachments 的正式边界说明

### Bootstrap 和生命周期
- `src/acabot/runtime/bootstrap/__init__.py` — DI 组装点，render service 在此构建和注入
- `src/acabot/runtime/app.py` — RuntimeApp 生命周期接入点

### 文档契约
- `docs/03-data-contracts.md` — Action、MessageStore、conversation_id 等契约
- `docs/07-gateway-and-channel-layer.md` — Gateway 边界，确认 render 不下沉到 gateway
- `docs/01-system-map.md` — 主线链路，确认 `Action -> Outbox -> Gateway` 主线不被破坏

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ActionType.RECALL` 已有，NapCat 已处理 `delete_msg` API 调用
- `ActionType.REACTION` 已有，reaction 只差工具层映射和 gateway 侧确认
- `Action.reply_to` 已有，`_build_msg_payload()` 已将其转换为 reply segment
- `GatewayProtocol.call_api()` 提供逃生舱，可调用任意 OneBot v11 API
- `BuiltinComputerToolSurface` 提供 builtin tool surface 的标准模式

### Established Patterns
- tool surface 类通常采用 `BUILTIN_XXX_TOOL_SOURCE` 常量 + `BuiltinXxxToolSurface` 类 + `register(tool_broker)` 方法
- ActionType 扩展在 `src/acabot/types/action.py`
- Gateway payload 扩展在 `NapCatGateway.build_send_payload()`
- `Outbox._should_persist_action()` 需要同步扩展，决定哪些动作写入 MessageStore
- runtime 基础设施通过 bootstrap 做 constructor injection，不直接写模块级单例

### Integration Points
- `builtin_tools/__init__.py` — 新 messaging surface 的注册入口
- `bootstrap/__init__.py` — 构建并注入 message tool surface 与 render service
- `outbox.py` — 高层 `send` intent 的 materialization、render 调用、fallback 处理
- `napcat.py` — 新低层发送动作的 payload 构建

</code_context>

<specifics>
## Specific Ideas

- `render` 是 `send` action 的可选字段，不是独立 action
- `render` 收一整段 rich text source，由 runtime 固定按 `Markdown + LaTeX math` 解释
- `text` 和 `render` 可以同时存在，前者用来放说明文字，后者用来生成渲染图
- 对 agent 暴露的是统一 `message` 工具；对 runtime 内部，`send` 是高层内容型动作，`react` / `recall` 仍是直通动作

</specifics>

<deferred>
## Deferred Ideas

- MSG-V2-01: 合并转发消息
- MSG-V2-02: 富文本编辑
- MSG-V2-03: Interactive components（按钮、卡片）
- MSG-V2-04: 完整 LaTeX 文档编译与模板化排版
- MSG-V2-05: 通过工具列出可用 `conversation_id` 供 agent 选择

</deferred>

---

*Phase: 04-unified-message-tool-playwright*
*Context gathered: 2026-04-04*
