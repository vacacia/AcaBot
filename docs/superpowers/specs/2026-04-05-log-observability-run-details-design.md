# 日志可观测性增强 + Run 详情设计

## 背景

当前 AcaBot 已经把大量运行时信息持久化到：

- 结构化日志缓冲（`/api/system/logs`）
- run 记录（`/api/runtime/runs/:run_id`）
- run steps（`/api/runtime/runs/:run_id/steps`）

但真实排障体验仍然不足，主要体现在：

1. `tool_broker` 的日志只暴露 `tool_name / duration / result_summary`，无法确认完整参数。
2. `/logs` 页面只把 `extra` 作为截断 chip 展示，不能展开看完整 JSON。
3. 虽然 runtime 已有 run / steps API，但 WebUI 没有直接入口把日志与对应 run 详情串起来。
4. `computer.exec` 的 step payload 没有带上 stdout/stderr excerpt，遇到“截图错了 / 命令失败了”时缺少直接证据。

这导致像“模型到底传了哪个 URL、执行了什么截图命令、失败时报了什么 stderr、最终发的 run 是哪个”这类问题，必须靠手工 curl API 或直接进容器排查。

## 目标

为真实线上排障提供一条完整、低摩擦的观察路径：

- 在 `/logs` 页面直接展开单条日志，查看完整 message 与完整结构化字段。
- 对带 `run_id` 的日志，直接进入对应 run 详情视图。
- 在 run 详情里查看本次执行的基础信息、metadata、steps 以及每个 step 的完整 payload 安全快照。
  - 本次范围默认展示最近 200 条 steps，并在 UI 明示“最近 200 条”；不承诺无限历史全量加载。
- 对工具执行日志补齐完整参数、错误与关键结果信息。
- 对 `computer.exec` steps 补齐 stdout/stderr excerpt，让截图、抓取、命令执行类问题能直接定位。

## 非目标

本次不做以下事项：

- 不改动 agent 的截图策略、等待策略、网页兼容性逻辑。
- 不新建独立“调试专用后门 API”。
- 不把终端 stdout 日志改成巨量原文输出；完整细节主要服务于 WebUI 内存日志面板与 runtime API。
- 不实现通用 trace/span 系统。

## 用户体验设计

### 1. `/logs` 页面增强

保留当前日志流模型与过滤能力，但增加两类能力：

#### 1.1 单条日志展开

每条日志新增“展开 / 收起”交互。展开后展示：

- 完整 `message`
- 完整 `extra` JSON（格式化展示）
- 若存在 `error` / `result_summary` / `tool_arguments` / `tool_result_snapshot` 等字段，则优先按可读块展示，再附原始 JSON

默认仍保持收起，避免日志台信息过载。

#### 1.2 从日志跳转到 run 详情

若日志 `extra` 含 `run_id`，则展示“查看 Run 详情”入口。

入口形态采用 **日志页右侧抽屉**（或等价的页内详情面板），而不是新开一个必须切路由的复杂页面。这样用户可以一边看日志流，一边检查选中的 run。

这些交互默认只在 `/logs` 页开启。首页等复用 `LogStreamPanel` 的场景保持当前轻量预览行为，不默认出现“展开详情 / 查看 Run 详情”。

这里的“完整信息”定义为：**完整的后端安全快照**，不是不受限制的原始 Python 对象。也就是说，前端应完整显示后端已经统一脱敏、统一 JSON-safe 化、统一大小预算后的 `extra` 内容，不再做第二次语义截断。

### 2. Run 详情视图

日志页内的 Run 详情面板需要展示：

#### 2.1 Run 基本信息

- `run_id`
- `status`
- `thread_id`
- `agent_id`
- `trigger_event_id`
- `started_at / finished_at`
- `error`

#### 2.2 Run metadata

以可折叠 JSON 形式展示 `metadata` 的安全快照，保留其中的重要字段高亮：

- `model_used`
- `token_usage`
- `model_snapshot`
- 路由/上下文相关元数据

#### 2.3 Run steps

按时间顺序展示 step 列表，每条 step 显示：

- `step_type`
- `status`
- `created_at`
- 摘要字段（例如 `exit_code`、`execution_cwd`、`workspace_root`）
- 完整 payload 安全快照展开区

对常见 step 做轻量语义化渲染：

- `workspace_prepare`
- `exec`
- `approval_*`
- 其他 step 默认退回 JSON

## 数据设计

### 1. 全局日志 extra 安全快照契约

`/api/system/logs` 返回的所有日志项，都必须先经过统一的日志安全快照流程后再进入 `log_buffer`。这条规则同时适用于：

- `message`
- `extra`

且适用于所有日志，不只 tool 日志。

统一日志安全快照 serializer 的职责是：

1. 把对象转成 JSON-safe 值
2. 递归脱敏敏感键：`token / api_key / authorization / cookie / password / secret` 等
3. 对超长字符串做安全截断（仅作为保险丝；普通字段应原样保留）
4. 对单条日志 `message + extra` 施加大小预算，避免把巨大 markdown、data URL、base64、超长结果对象直接塞爆内存日志

预算定义：

- `message` 字符串最多保留 16 KiB
- 单个 `extra` 字符串字段默认最多保留 16 KiB
- 单条结构化日志 `message + extra` 总序列化预算最多 32 KiB
- 超出预算时保留前缀并追加 `…[truncated]`

因此：

- 前端展示的是**后端安全快照的完整内容**
- 前端不再做第二套语义截断规则，只负责折叠/展开 UI
- `log_buffer` 不再保存未经处理的原始 extra

### 2. Tool 日志字段增强

对以下日志：

- `Tool executed`
- `Tool rejected`
- `Tool execution failed`

统一补充结构化字段，至少包含：

- `tool_name`
- `run_id / thread_id / agent_id / actor_id`
- `duration_ms`
- `tool_arguments`：经共享 sanitizer 处理后的 arguments 快照
- `tool_result_snapshot`：固定 schema 的结果快照
- `result_summary`：当前已有摘要，保留
- `error`：失败原因

其中 `tool_result_snapshot` 固定为：

- `llm_content`
- `raw`
- `metadata`
- `attachment_count`
- `artifact_count`
- `user_action_count`

这些字段也必须复用上面的**全局 extra serializer**，而不是单独实现第二套规则。

原则：

- **终端输出仍保持短日志**，因为 stdlib formatter 只打印 message。
- **WebUI / log buffer 拿到完整 extra 的安全快照**，供展开查看。
- 不允许每个 tool 自己定义日志结果 shape，避免前端契约漂移与 JSON 序列化失败。

### 2. `computer.exec` step payload 增强

当前 `exec` step 只记录：

- `command`
- `exit_code`
- `stdout_truncated`
- `stderr_truncated`
- `execution_cwd`
- `metadata`

需补充：

- `stdout_excerpt`
- `stderr_excerpt`

以复用已有 `CommandExecutionResult` 的窗口化输出，不新引入额外采样逻辑。

### 3. API 策略

尽量复用现有 API：

- `/api/system/logs`
- `/api/runtime/runs/:run_id`
- `/api/runtime/runs/:run_id/steps`

但 run steps 这里需要一个**明确的后端契约修正**：当前接口的底层存储语义是按创建时间升序 `LIMIT N`，拿到的是最早 N 条，不符合“最近 200 条”的详情面板需求。

本次固定采用：

- `/api/runtime/runs/:run_id/steps?limit=200&latest=true`

为保证“最近 200 条”语义稳定，run step 需要补一个**单调递增的写入顺序字段**（例如 `step_seq`），由 run step append 路径分配，表示该 run 内部的真实追加顺序。

语义为：

- `latest=true` 时，后端先按 `step_seq DESC` 选出最近 200 条 steps
- 返回给前端时再按 `step_seq ASC` 重新排序，方便阅读
- `created_at` 只用于展示时间，不再承担 latest-N 选取职责
- 未传 `latest=true` 时保持现有兼容行为

本次优先不新增新的 runtime 详情接口；run 详情面板由前端并发请求 run 基本信息与 steps，再组装展示。

### 4. Run API 安全快照契约

`/api/runtime/runs/:run_id` 与 `/api/runtime/runs/:run_id/steps` 返回给前端的 `metadata` / `approval_context` / `payload` 也必须经过统一的 inspection serializer，不能把原始未处理对象直接暴露给 WebUI。

另外，run 详情是排障实时入口，前端请求必须**绕过默认 15 秒 GET 缓存**。也就是说，run 基本信息与 steps 拉取需要使用 no-cache/fresh 语义，不能复用当前通用 `apiGet()` 的默认缓存路径。

这个 inspection serializer 复用与日志相同的核心规则：

1. JSON-safe 化
2. 敏感键递归脱敏：`token / api_key / authorization / cookie / password / secret` 等
3. 超长字符串保险丝截断
4. 大小预算保护

预算定义：

- `run.metadata` 安全快照最多 32 KiB
- `run.approval_context` 安全快照最多 32 KiB
- 单个 `step.payload` 安全快照最多 32 KiB
- 超出预算时保留前缀并追加 `…[truncated]`

因此：

- WebUI 展示的是 inspection serializer 产出的完整安全快照
- “完整”始终指安全快照完整，不指未经限制的原始对象

## 实现边界

### 前端边界

新增一个可复用的 `RunDetailPanel`（或等价组件），职责仅限：

- 拉取 run 基本信息
- 按新的 latest-N 后端契约拉取最近 200 条 steps
- 渲染摘要 + 可展开 JSON

`LogStreamPanel` 只负责：

- 日志列表
- 日志展开/收起
- 通过显式 props 控制是否启用 run 详情入口
- 触发“查看 run”事件

建议使用类似 `showDetails` / `showRunDetails` 的 feature gating props，默认关闭；`/logs` 显式开启，首页日志预览保持关闭。

这样日志流与 run 详情职责分离，后续若要在其他页面复用 run 详情，也不必复制逻辑。

### 后端边界

- `ToolBroker`：负责补齐结构化 tool 日志字段
- `ComputerRuntime`：负责把 exec excerpt 写进 step payload
- `RuntimeHttpApiServer` / `ControlPlane`：尽量只复用已有 run API，不新增无必要聚合层
- `log_buffer` / `InMemoryLogHandler`：负责对所有日志 extra 统一做安全快照化后再入缓冲区

## 测试策略

### 后端

1. `ToolBroker` 日志测试
   - 验证成功/失败日志会带 `tool_arguments`
   - 验证结果字段使用固定 `tool_result_snapshot` schema
   - 验证失败日志会带 `error`
   - 验证敏感字段会被脱敏、超长字段会被截断

2. `computer.exec` step payload 测试
   - 验证 step payload 包含 `stdout_excerpt / stderr_excerpt`

3. WebUI API 测试
   - 验证 `/api/system/logs` 返回展开所需完整 extra 安全快照
   - 验证 `/api/runtime/runs/:run_id` 返回 `metadata / approval_context` 安全快照
   - 验证 run steps 具备单调顺序字段（如 `step_seq`）
   - 验证 `/api/runtime/runs/:run_id/steps?limit=200&latest=true` 返回最近 200 条，且顺序为 `step_seq` 正序
   - 验证 step payload 会经过 inspection serializer
   - 验证 run 详情请求走 fresh/no-cache 语义，不会读到 15 秒陈旧缓存
   - 验证该 steps 契约能被前端明确消费

### 前端 / 构建回归

1. 组件测试或 built-assets 回归测试，确保：
   - 日志页存在“展开详情 / 查看 Run 详情”入口
   - run 详情面板入口已进入产物

2. 构建后需更新 `src/acabot/webui/` 产物，并跑现有 built assets regression。

### 手工验收

以真实错误案例为验收基准：

用户再次触发“截图网页然后发给我”，在 WebUI 中应能直接看到：

- tool 参数里的目标 URL
- 执行的截图命令
- 如果失败，stderr excerpt
- 对应 run steps
- 本次 run 的基础信息与 metadata

本次验收不要求在 run 详情中额外证明 outbound/delivery 最终证据；那属于后续可观测性增强范围。

## 通过标准

满足以下条件即认为本次设计完成：

1. `/logs` 能展开看到完整结构化信息。
2. 点击带 `run_id` 的日志，可查看对应 run 详情。
3. tool 执行日志能看到完整 arguments 安全快照。
4. `exec` step 能看到 stdout/stderr excerpt。
5. 整体链路无需再依赖手工 curl 或进容器，WebUI 即可完成主要排障。 
