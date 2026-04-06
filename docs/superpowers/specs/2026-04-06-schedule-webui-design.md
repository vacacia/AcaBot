# Schedule WebUI 设计

## 目标

为当前已落地的 `conversation_wakeup` scheduler 提供一个独立的 WebUI 页面 `/schedules`，让用户可以直接在页面里：
- 创建定时任务
- 删除定时任务
- 暂停 / 恢复已有任务
- 查看关键元数据：创建时间、最近一次执行时间、下一次执行时间

本期只覆盖 `conversation_wakeup`，不把插件侧 `plugin_handler` 混进同一个页面。

## 范围

### 包含
- 独立路由 `/schedules`
- 侧边栏新增入口
- 单列表形态的任务管理页面
- 创建任务能力
- 删除任务能力
- 启用 / 禁用能力（保留同一个 task_id，不做删后重建）
- 任务元数据展示
- WebUI API
- 后端持久化字段补齐
- 前后端测试、页面操作测试、截图验收

### 不包含
- 插件任务管理
- scheduler 触发历史明细页
- run 详情联动跳转
- WebUI 上直接展示 synthetic event / run steps 证据链

## 用户体验

### 页面定位
- 页面是一个独立的调度面板，而不是 session 配置页的附属区域。
- 页面主体是单列表，不做“上半区创建 / 下半区列表”的双区布局。
- 视觉和布局风格交给 Claude + Impeccable 自由发挥，但必须符合项目现有“精密、沉着、值得信赖”的控制台语境。
- 页面展示时间统一把后端返回的 Unix timestamp（UTC 秒）转换为浏览器本地时区显示。

### 列表页面
页面核心是一个任务列表，展示每条 `conversation_wakeup` 任务的：
- note
- conversation_id
- schedule 摘要
- enabled 状态
- created_at
- last_fired_at
- next_fire_at
- 删除操作

页面顶部可有轻量工具栏或次级操作区，但不再额外拆出一个固定“创建区”。
创建交互（抽屉 / 弹窗 / 行内编辑）由 Claude 自主决定，只要最后符合单列表主导的信息架构即可。

### 创建任务
创建任务时支持两种目标会话输入方式：
- 从已有 session / conversation 列表里选
- 手填 `conversation_id`

这里的会话选择器只是一种输入辅助：页面如果选择了现有 session，就直接把 `session.session_id` 当作 `conversation_id` 使用；真正提交给 API 的字段只有一个 `conversation_id`，不同时上传“选中的 session id + 手填 id”两套值，因此不会存在优先级冲突。

手填 `conversation_id` 不要求必须已经存在于 `/api/sessions` 列表里；scheduler 的职责是面向 conversation 语义建任务，而不是只允许给当前已有 session 建任务。

现有 session 选择器继续复用 `/api/sessions`；如果列表较大，前端先做本地搜索过滤，同时保留手填输入作为逃生口，不额外新增新的 session 搜索 API。

创建的任务类型仅限：
- `one_shot`
- `interval`
- `cron`

创建时仍然写入 `conversation_wakeup` 语义：到点后向原 conversation 投递 synthetic scheduled event，唤醒 agent。

### 开关语义
“开关”表示暂停 / 恢复同一条任务：
- 关闭时，任务保留、不可触发，并立即从 worker heap 移除
- 打开时，任务恢复、继续按原 schedule 工作
- 同一个 `task_id`、`created_at`、metadata 都保留

不采用“关闭=删除，打开=重建”的语义。

恢复规则固定为：
- `cron`：从当前时间重新计算下一个未来触发点
- `interval`：从当前时间重新计算下一次触发时间
- `one_shot`：如果原始 `fire_at` 仍在未来，则恢复该时间；如果原始 `fire_at` 已经过期，则返回冲突错误，要求用户重新创建任务，而不是偷偷改写为别的时间

`one_shot` 成功触发后的生命周期也固定：任务不会被硬删除，而是转成 disabled tombstone，保留 `task_id`、`created_at`、`last_fired_at`、`schedule`，并把 `next_fire_at` 置为 `null`；只有用户显式删除后才真正消失。

已经过期且被 disable 的 one-shot 任务也会作为 disabled 记录保留，直到用户显式删除；重启恢复时它仍然是 disabled，不自动复活，也不自动清理。

对外展示时：
- `enabled=true` 时，`next_fire_at` 必须是未来时间
- `enabled=false` 时，`next_fire_at` 固定返回 `null`

如果任务已经被 worker 取出并开始执行 callback，再收到 disable 请求，不追求撤销这次已开始的执行；disable 只保证阻止后续触发。

## 后端设计

### 统一门面
继续由 `ScheduledTaskService` 作为业务门面，不让 WebUI 直接碰底层 callback 或 store 细节。

本期新增面向 WebUI 的 `conversation_wakeup` 管理接口，职责是：
- list
- create
- enable
- disable
- delete

### 数据模型补齐
为了支撑 WebUI，需要把 scheduler 的可观察状态补齐到任务快照里：
- `created_at`
- `updated_at`
- `last_fired_at`
- `next_fire_at`
- `enabled`
- `metadata.kind`
- `metadata.conversation_id`
- `metadata.note`

其中：
- `created_at`：任务首次创建时间
- `updated_at`：最近一次状态变更时间（启停、触发后推进 next fire 等）
- `last_fired_at`：最近一次开始执行 callback 的时间；它表示“scheduler 已尝试触发这条任务”，不承诺下游 synthetic event 一定成功送达
- `next_fire_at`：下次计划触发时间；对 WebUI API 来说，禁用任务固定返回 `null`

### 调度器行为补齐
`scheduler` 核心需要补两个能力：
1. enable / disable
2. fire 后写回 `last_fired_at`

调度器恢复时，禁用任务不应入 worker heap。
恢复启用时，应根据当前时间重新计算下一次合法触发时间，而不是简单复用可能已经过期的 `next_fire_at`。

### WebUI API
新增专用 API：
- `GET /api/schedules/conversation-wakeup`
- `POST /api/schedules/conversation-wakeup`
- `POST /api/schedules/conversation-wakeup/{task_id}/enable`
- `POST /api/schedules/conversation-wakeup/{task_id}/disable`
- `DELETE /api/schedules/conversation-wakeup/{task_id}`

返回结构统一面向页面使用，不暴露底层实现细节。

#### 任务项结构
每个任务项固定返回：
- `task_id: string`
- `owner: string`（本期固定等于 `conversation_id`；页面不依赖它做额外语义）
- `conversation_id: string`
- `note: string`
- `kind: "conversation_wakeup"`
- `schedule: { kind: "cron", spec: { expr: string } } | { kind: "interval", spec: { seconds: number } } | { kind: "one_shot", spec: { fire_at: number } }`
- `enabled: boolean`
- `created_at: number`
- `updated_at: number`
- `last_fired_at: number | null`
- `next_fire_at: number | null`

#### 接口语义
- `GET /api/schedules/conversation-wakeup`
  - 支持 query：
    - `conversation_id?`
    - `enabled?`：仅接受字符串 `"true"` / `"false"`；缺失表示不过滤
    - `limit?`（默认 200，最大 500）
  - `200`
  - 返回：`{ items: TaskItem[] }`
- `POST /api/schedules/conversation-wakeup`
  - 输入：`{ conversation_id: string, schedule: { kind: "cron", spec: { expr: string } } | { kind: "interval", spec: { seconds: number } } | { kind: "one_shot", spec: { fire_at: number } }, note?: string }`
  - `note` 最长 500 字符
  - `201`
  - 返回：`TaskItem`
- `POST /api/schedules/conversation-wakeup/{task_id}/enable`
  - `200`
  - 返回：`TaskItem`
  - 如果任务不存在：`404`
  - 如果是已经过期的 disabled one-shot：`409`
  - 如果任务本来就 enabled：返回当前快照，视为幂等成功
- `POST /api/schedules/conversation-wakeup/{task_id}/disable`
  - `200`
  - 返回：`TaskItem`
  - 如果任务不存在：`404`
  - 如果任务本来就 disabled：返回当前快照，视为幂等成功
- `DELETE /api/schedules/conversation-wakeup/{task_id}`
  - 语义是硬删除
  - `200`
  - 返回：`{ task_id: string, deleted: true }`
  - 如果任务不存在：`404`

对所有接口：
- payload 非法时返回 `400`
- scheduler/service 不可用时返回 `503`
- 这里的 `503` 由 control plane 明确抛出“scheduler service unavailable”语义异常，再由 HTTP API 映射，不走模糊的通用 `500`
- 继续沿用当前 WebUI 的本地控制面信任模型，不额外引入新的鉴权层

如果页面提供“从已有会话里选”，所需候选数据继续复用现有 `/api/sessions` 列表，不额外发明新的会话目录协议。

## 前端设计边界

前端由 Claude 使用 Impeccable 自主完成视觉和布局决策，但必须满足这些硬约束：
- 路由固定为 `/schedules`
- 页面主形态是单列表
- 支持创建、删除、启停
- 支持“选现有会话 + 手填 conversation_id”
- 展示创建时间、最近执行时间、下次执行时间
- 只管理 `conversation_wakeup`
- 不把页面做成 session 配置页的附属 tab
- 页面读取 schedules 时不能使用 3 分钟 GET cache；要使用 fresh 请求或专门失效策略，保证 `last_fired_at` / `next_fire_at` 的可见刷新

也就是说，视觉风格和组件编排由 Claude 决定，业务边界和数据契约由 runtime 这边锁定。

## 测试与验收

### 后端
- scheduler store / service / runtime 新增测试：
  - enable / disable
  - `last_fired_at`
  - disabled 任务重启恢复后不会重新入 heap
  - enable 之后 `next_fire_at` 的重算
  - WebUI API create / list / enable / disable / delete
  - 非法 payload、未知 task_id、重复 enable / disable、expired one-shot enable

### 前端
- 页面基础渲染测试
- WebUI API 接线测试
- 页面操作测试：创建、暂停、恢复、删除
- 网络错误 / 超时 / 失败回滚测试

### 端到端
- 使用浏览器自动化完整操作 `/schedules`
- 必须有 1080p 页面截图
- 至少验证一条短周期任务能在页面上看见 `last_fired_at` 与 `next_fire_at` 的变化
- 至少验证一条真实任务能从页面创建后成功进入 scheduler

## 方案取舍

### 为什么独立页
因为 scheduler 是主动能力面板，不属于单个 session 配置壳层。独立页的边界更清晰，后续扩展插件任务、触发记录、运行证据时也不会把 `/sessions` 挤得更乱。

### 为什么只做 conversation_wakeup
因为这条链路已经真实落地并完成 live 验证。先围绕唯一稳定语义做出好用面板，比做一个混合任务页却半数不可用更稳。

### 为什么不规定前端细节
因为用户明确要求把前端设计交给 Claude + Impeccable，自主决定布局与风格。我这边只锁定产品边界、交互能力和接口契约，避免“视觉随意、业务散掉”。

Claude 介入的触发机制也固定：我会通过终端 `claude` 提供页面路由、API 契约、字段清单和设计上下文，让它直接产出前端 diff；验收标准由我这边负责，包括业务契约核对、浏览器操作测试和 1080p 截图。