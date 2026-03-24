# Session / Subagent 覆盖项分析

这篇文档不是实现计划，而是给实现计划做前置分析。

目标只有一个：把当前代码里“哪些东西真的能按 session 覆盖、哪些只是运行时临时态、哪些还没有独立配置对象”讲清楚，避免后面把 WebUI 写成一个看起来很完整、实际上会互相冲突的壳。

这里要先讲清一个前提：

- Session 页面只管自己的设置
- 底层最后再抽象出 agent

所以这篇分析不是为了给 Session 页面引入“当前 agent”这种产品概念，而是为了找出哪些底层设置适合先安全暴露给 Session。

## 2026-03-18 补充决议（前端口径）

在产品层，Session 页面口径更新为：

- 前端只展示 `AI`、`消息响应`、`其他` 三块
- 前端不出现 `binding rule / inbound rule / event policy` 这些术语
- 前端不出现 `*_rule_id / policy_id` 这类实现字段

同时保留一条实现约束：

- 后端必须把这三块设置映射到真实真源（当前主要仍是 profile + binding/inbound/event-policy）
- 这类映射属于后端实现责任，不是前端概念

## 为什么要先写这篇

当前代码并不是按“Session 是一个独立配置对象”来组织的。

现在所谓 Session，更接近几个层面的组合视图：

- `binding rule`
- `inbound rule`
- `event policy`
- thread 运行时状态
- thread 上的临时 override
- workspace / computer 运行时状态

所以如果直接在 WebUI 上做“Session 配置页”，但不先分析底层真实可改项，最后很容易出现三类问题：

- 页面上看起来像一个对象，落地时其实在改三四套不同来源
- 有些设置是持久配置，有些只是运行时临时态，用户很难理解
- 两套覆盖机制叠在一起后，最终生效值不容易解释

## 先讲结论

当前代码里，和“Session 级覆盖”最接近的东西可以分成三类：

### 1. 持久配置型

这些是最适合先做成 Session 配置页的，因为它们有明确真源、能落盘、能 reload：

- `binding rule`
- `inbound rule`
- `event policy`

### 2. 运行时临时覆盖型

这些确实是按 thread / session 生效，但本质上不是配置对象，而是运行时 override：

- `thread_agent_override`
- `computer override`

### 3. 当前还不是独立配置对象的能力

这些现在有“相关实现”，但还不能直接当成 Session 独立配置项来建页：

- subagent enable / disable
- “Session 自己拥有一套 AI / tools / skills / prompt / model”的独立对象模型

## 当前代码里的 Session 到底是什么

现在路由主线里，thread / session 的核心稳定标识是：

- `channel_scope`
- `thread_id`

在默认实现里，`thread_id` 基本直接等于 `channel_scope`。

这意味着当前“Session”更接近：

- 一个会话范围
- 一个路由命中范围
- 一个 thread 状态容器

而不是一份单独的配置文档。

所以今天 WebUI 里如果要做 Session 页面，本质上是在把多套底层对象投影成一个用户可理解视图，而不是在读一个现成的 `session.yaml`。

## 哪些东西是真的可持久覆盖

### binding rule

它决定：

- 这个会话范围最终落到哪个 agent

它是当前最核心的 Session 级持久配置入口。

如果你想做：

- 某个群固定用某个 bot
- 某个会话显示名
- 某个会话绑定某个 managed agent

这条线是当前最自然的落点。

它的特点是：

- 有明确持久真源
- 已经能通过 `RuntimeConfigControlPlane` 读写
- 改完能 reload

### inbound rule

它决定：

- 某类输入在这个会话里是 `respond`
- 还是 `record_only`
- 还是 `silent_drop`

如果 Session 页要展示“输入处理”，当前最稳的真源就是它。

它的特点是：

- 也是持久真源
- 和 event type 强绑定
- 是“跑不跑完整主线”的规则，不是 agent 绑定

### event policy

它决定：

- 事件要不要持久化
- 带哪些 `tags`

如果 Session 页要展示“输入保存 / 记忆相关策略”，当前最稳的真源就是它。

它的特点是：

- 也是持久真源
- 也是按 event type 配
- 它和 inbound rule 配合使用，但职责不同

## 哪些东西只是运行时临时覆盖

### `thread_agent_override`

当前控制面已经有：

- 设置 thread agent override
- 清除 thread agent override

它的特点是：

- 按 thread 生效
- 存在于 thread metadata
- 更像临时运维开关
- 不是一份适合长期编辑的 Session 配置

如果以后在 WebUI 里暴露它，应该明确标注成：

- 临时 override
- 当前运行时状态

而不是把它和持久配置混成一类。

### `computer override`

当前 workspace / computer 也支持 thread 级 override。

它的特点和 `thread_agent_override` 很像：

- 是按 thread 生效
- 带明显运行时语义
- 可能和活动 run、活跃 session 冲突
- 改动时还会触发 cancel / stop / 清理这类运行时行为

所以它也不该被包装成普通 Session 配置项。

## 哪些东西现在还不是独立配置对象

### Session 自己拥有一套 AI 配置

从产品角度，这种页面会让人误以为：

- 这个 Session 自己直接拥有 prompt
- 这个 Session 自己直接拥有主模型 / 摘要模型
- 这个 Session 自己直接拥有 tools / skills

但当前后端并没有一个“SessionProfile”对象。

现在更接近的真实实现方式是：

- Session 命中某个 agent / profile
- profile 决定 prompt / model / tools / skills

也就是说，Session / AI 目前更适合作为底层抽象结果看待，而不是先把它当成 Session 页面上的直接产品概念。

如果硬要在第一版就做成完全独立对象，就要补一套新的配置模型，这会明显扩大范围。

### subagent enable / disable

当前代码里有这些东西：

- subagent executor registry
- executor 列表
- 本地 profile 自动注册 executor

但现在没有一套独立的“subagent enable/disable 持久配置对象”。

今天 registry 里列出来的是：

- 当前注册了哪些 executor

这不等于：

- 用户可以在配置里关闭某个 subagent
- 关闭后它在 UI 里消失
- 关闭后 runtime 也不允许委派

如果真的要做 enable / disable，至少要先回答：

1. 真源放在哪里
2. 关闭的是 profile，还是 executor，还是 delegation target
3. 关闭后如何影响已有 skill assignment

所以这块现在不能被当成“只是加个开关”。

## 为什么这些覆盖项会冲突

当前最容易冲突的点有四个。

### 1. binding rule 和 thread agent override 会冲突

一个是持久规则，一个是运行时临时 override。

如果两者同时存在，底层最终生效值要怎么解释，必须写清楚。

但这不等于 Session 页面第一版就必须展示“当前 agent”。更稳的做法是：

- Session 页面先只暴露绑定设置本身
- 真正的最终命中结果仍然留在底层抽象和运行时逻辑里

- 正常情况下谁先算
- 临时 override 是否总是压过 binding
- 清除 override 后是否恢复 binding 生效

### 2. inbound rule 和 event policy 会被用户误以为是一回事

实际上不是：

- inbound rule 决定是否进入完整主线
- event policy 决定事件持久化和记忆提取策略

如果 UI 上合成一张“输入处理表”，就必须同时展示：

- 哪部分在改 run_mode
- 哪部分在改 event / memory 行为

不然用户会以为自己改了一项，结果其实只改了一半。

### 3. Session / AI 页面容易和 profile 混掉

当前 profile 仍然是 AI 配置的真源。

如果 Session 页直接允许编辑：

- prompt
- model
- tools
- skills

那就必须先决定：

- 这是在改某个共享 profile
- 还是在创建 / 切换一个专门给这个 Session 用的 profile

不先定这个，UI 会非常误导。

### 4. computer override 和活跃运行状态会冲突

这块已经不只是配置冲突，而是运行时行为冲突：

- 改 override 可能要停 sandbox
- 可能要关 session
- 可能要 cancel 活跃 run

所以它一定要被当作运维动作，而不是普通表单字段。

## 当前最适合先做进 Session 页的范围（前端）

如果目标是“第一版先做一个不会把系统解释乱的 Session 页面”，前端只做下面三块：

### 1. Session / AI

- Prompt
- 主模型
- 摘要模型
- Tools
- Skills

### 2. Session / 消息响应

- 是否启用
- 响应方式
- 是否保存
- memory scopes
- tags

### 3. Session / 其他

- Session 级补充字段（例如 tags）

对应的实现约束：

- 前端不直接操作或展示 `binding/inbound/event-policy` 对象
- 后端提供 Session 视角 API，把前端三块设置映射到真实真源

## 当前不建议直接做成 Session 持久配置对象的范围

第一版不建议直接把下面这些做成“Session 自己的持久配置”：

- Session 自己的 prompt / model / tools / skills
- subagent enable / disable
- workspace session 管理

原因不是这些永远不能做，而是：

- 它们在当前代码里没有一个干净的单一真源
- 直接做会把 UI 先做成一个伪对象
- 后面实现时会不断补例外逻辑

## Subagent 页面在当前阶段更适合做什么

如果第一版仍然保留 `Subagents` 页面，更适合把它定义成：

- 当前 executor 注册表可视化
- executor 来源、agent_id、可见性说明
- 后续 enable/disable 的占位页

而不是现在就承诺“真正可持久 enable/disable”。

## 对后续计划的直接约束

基于当前分析，后续 implementation plan 应该调整成这样：

### 1. `Self + Sticky Notes` 可以作为主线独立推进

这部分已经有清楚边界，可以先做。

### 2. Session 页按产品口径直接落地三分区

建议只覆盖：

- Session / AI
- Session / 消息响应
- Session / 其他

并要求：

- 前端不出现底层规则概念
- 后端承担映射职责

### 3. Session 映射契约作为后端实现任务

不要把 mapping 细节泄漏到 UI 结构中。

### 4. Subagent enable / disable 单独开分析 / 设计任务

不要在这轮计划里顺手承诺它。

## 一句话版本

前端 Session 只展示 `AI / 消息响应 / 其他` 三块产品概念；`binding/inbound/event-policy` 仍可作为后端真实真源，但必须由后端做映射并对前端隐藏；`thread_agent_override` 和 `computer override` 继续作为运行时临时态，不混入 Session 主表单。
