# subagent

## subagent 是什么

subagent 是一个能被主 agent 委派出去独立工作的 agent。

主 agent 可以把上下文重、步骤多、想隔离执行面的任务外包给 subagent，最后只拿回总结结果。

- `delegate_subagent` 是前台入口
- subagent 本身是执行者

## 当前正式口径

### 1. 定义真源是文件系统 catalog

subagent 不再来自 profile 自动注册，也不来自 plugin 注册。

当前正式真源是文件系统目录：

- `.agents/subagents/<subagent_name>/SUBAGENT.md`

每个 subagent 只认一个 `SUBAGENT.md`。

`SUBAGENT.md` 负责两件事：

- frontmatter 定义 metadata
    - `name`
    - `description`
    - `tools`
    - `model_target` 可选
- 正文 markdown 直接作为 subagent prompt

### 2. session 只负责 `visible_subagents`

session-config 不负责“定义有哪些 subagent”，只负责“这次 run 能看到谁”。

也就是说：

- catalog 决定 subagent 是否存在
- `visible_subagents` 决定当前 run 是否能看见、能不能调

当前 session 没放开任何 subagent 时，`delegate_subagent` 不会暴露给模型。

### 3. plugin 不注册 subagent

plugin 和 subagent 没有直接关系。

plugin 不注册 subagent，不参与 subagent 生命周期，也不决定 subagent 可见性。

plugin 和 subagent 的唯一交点是普通 tool：

- plugin 可以提供 tool
- subagent 可以在自己的 `SUBAGENT.md` 里把这些 tool 写进 `tools`

## 当前 subagent 是怎么跑起来的

当前委派链路是：

1. session 把 `visible_subagents` 解析进当前 run 的 computer policy
2. `ToolBroker` 只在当前 run allowlist 非空且 catalog 可解析时暴露 `delegate_subagent`
3. 模型调用 `delegate_subagent`
4. builtin tool 把请求交给 `SubagentDelegationBroker`
5. broker 先按 `delegate_agent_id` 查 `SubagentCatalog`
6. `LocalSubagentExecutionService` 用 `SUBAGENT.md` 构造 synthetic child profile
7. 它会伪造一条内部事件，创建 child run
8. 再复用 runtime 自己的 `ThreadPipeline.execute(...)`
9. 但 `deliver_actions=False`，不会把 child run 的动作直接发到外部平台
10. 最后只把结果总结返回给父 run

## subagent 边界

### subagent child run 有自己的 computer 决策

当前 child run 会显式拿到 subagent 用的 computer 决策：

- `workspace` 可见
- `skills` 可见
- `self` 不可见
- `visible_subagents` 固定为空列表

### subagent child run 默认不递归

第一版里 subagent child run 看不到任何 delegation 入口。

也就是说：

- subagent 默认不能再委派 subagent
- 不做递归 delegation

### subagent 不走完整的 session-config 主线

当前子任务会共享 Work World 契约，但不会重新走完整的前台：

- session-config
- surface
- context

它不是第二个完整前台用户会话。

### subagent child run 不支持 approval resume

第一版里如果 child run 命中需要 approval 的工具，会直接失败：

- 不进入 `waiting_approval`
- 不走 generic approval replay
- 不形成隐式 continuation / 续跑路径

## 不要把 `delegate_subagent` 当成一个普通函数型 tool

`delegate_subagent` 只是前台入口。

真正发生的事情不是“跑一个小函数”，而是：

- 做一次委派编排
- 创建 child run
- 复用 runtime 执行链路
- 回收结果给父 run
