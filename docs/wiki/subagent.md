# Subagent 系统

## 注册

### 两个注册来源

Subagent executor 可以从两个地方注册到 runtime：

**本地 Profile**：配置文件中定义的 profile 自动注册为 subagent executor。`register_local_subagent_executors()` 在 bootstrap 阶段遍历所有 profile，跳过 webui 动态 session（`managed_by` 为 `webui_session` 或 `webui_v2_session`），其余都用 `LocalSubagentExecutionService` 作为执行器注册到 `SubagentExecutorRegistry`。

```yaml
runtime:
  profiles:
    aca:                    # 主 agent
      name: "Aca"
      prompt_ref: "prompt/aca"
      default_model: "gpt-4"
    excel_worker:           # 自动成为可委派的 subagent
      name: "Excel Worker"
      prompt_ref: "prompt/excel_worker"
      default_model: "gpt-4"
    math_solver:            # 自动成为可委派的 subagent
      name: "Math Solver"
      prompt_ref: "prompt/math_solver"
      default_model: "claude-opus"
```

这意味着只要在配置里多写一个 profile，主 agent 就能把它当作 subagent 委派任务过去，不需要额外配置。

**Runtime Plugin**：插件通过实现 `subagent_executors()` 方法声明自己的 subagent executor。每个注册项包含 `agent_id`、`executor`（一个接受 `SubagentDelegationRequest` 并返回 `SubagentDelegationResult` 的异步函数）和可选的 `metadata`。

### 注册表

`SubagentExecutorRegistry` 是中央注册表，按 `agent_id` 存储所有已注册的 executor：

```python
class SubagentExecutorRegistry:
    def register(self, agent_id, executor, *, source, metadata) -> None
    def get(self, agent_id) -> RegisteredSubagentExecutor | None
    def list_all(self) -> list[RegisteredSubagentExecutor]
    def unregister_source(self, source) -> list[str]
```

同一个 `agent_id` 可以被多次注册，后注册的会覆盖先注册的。`unregister_source()` 用于按来源批量卸载，比如配置热更新时先卸载所有 `runtime:local_profile` 来源的 executor 再重新注册。

## 可见性

### 谁能委派

`ToolBroker._should_expose_delegate_tool()` 决定当前 profile 是否能看到 `delegate_subagent` 工具。只有同时满足以下条件时才会暴露：

1. 注册表中存在至少一个 `agent_id` 不同于当前 profile 的 executor
2. 当前 profile 是默认主 agent（`profile.agent_id == default_agent_id`），或者没有设置 `default_agent_id`

非默认 agent 无法委派 subagent。注册表中只有自己（没有其他 executor）时也不会暴露。

### 摘要注入

`ToolBroker` 在构建 `ToolRuntime` 时，遍历 `SubagentExecutorRegistry` 中所有已注册的 executor，过滤掉当前 profile 自己的 `agent_id`，剩余的按 `agent_id` 和 `profile_name` 生成摘要列表。这段摘要通过 `ContextAssembler` 注入到 system prompt 中，和 skill 摘要的注入方式类似（`source_kind="subagent_reminder"`，写入 `system_prompt` slot）。

注入格式如下：

```
Available Subagents:
- excel_worker: Excel Worker
- math_solver: Math Solver
```

每一行由 `agent_id` 和 `profile_name` 拼接，`profile_name` 来自注册时的 metadata（本地 profile 注册时取的是配置文件中的 `name` 字段），缺省则回退为 `agent_id`。模型拿到这段列表后才能判断"这个任务应该委派给哪个 subagent"。

## 模型委派 Subagent 的链路

主 agent 通过调用 `delegate_subagent` 工具来委派任务，整个过程和 skill 的加载链路类似：模型先从 prompt 摘要中知道有哪些 subagent 可用，再通过工具调用触发执行，最后拿到结果摘要。

### 调用工具

模型调用 `delegate_subagent` 并传入目标 subagent 的 `agent_id` 和任务描述：

```json
{
  "delegate_agent_id": "excel_worker",
  "task": "分析这个 Excel 文件并生成汇总报告"
}
```

`BuiltinSubagentToolSurface._delegate_subagent()` 收到调用后，把请求转交给 `SubagentDelegationBroker`。Broker 在执行前做三个检查：

1. 当前 agent 是否是默认主 agent — 非 default agent 不能委派
2. 目标 `delegate_agent_id` 是否就是自己 — 不能委派给自己
3. 目标 executor 是否存在于注册表中 — 不存在则返回错误

检查通过后，Broker 构造一个标准的 `SubagentDelegationRequest`，包含父 run 的上下文信息（`parent_run_id`、`parent_thread_id`、`parent_agent_id`）以及模型传入的 `task` 和 `payload`，然后调用目标 executor 执行。

### 本地执行

当前默认的执行器是 `LocalSubagentExecutionService`。它复用了 runtime 的主线执行链路，但做了一些关键调整：

1. 构造一个 synthetic event（内部消息事件），内容是模型传入的任务描述
2. 为这次委派创建或复用一个 child thread，标记 `thread_kind="subagent"`，并在 metadata 中记录父 run 的 ID
3. 加载目标 profile 对应的 prompt 和模型配置
4. 创建一个 child run，并构造 `RunContext`
5. 调用 `ThreadPipeline.execute(ctx, deliver_actions=False)` 执行

其中 `deliver_actions=False` 是最重要的区别——child run 的输出动作不会发送到外部平台（比如 QQ 消息），结果只通过 `SubagentDelegationResult` 返回给父 run。

### 结果返回

执行完成后，`LocalSubagentExecutionService` 从 child run 中提取结果，构造 `SubagentDelegationResult`：

```python
@dataclass
class SubagentDelegationResult:
    ok: bool                          # 是否成功
    delegated_run_id: str             # child run 的 ID
    summary: str                      # 执行摘要，返回给父 agent
    artifacts: list[dict]             # 副产物列表
    error: str                        # 错误信息
    metadata: dict                    # 额外元数据
```

`summary` 字段是父 agent 实际看到的内容。工具返回给模型的格式为：

```
Delegation completed for excel_worker. subagent=excel_worker summary=分析完成，共发现 3 个异常值...
```

同时在父 run 的审计步骤中追加两条记录：`started`（委派开始）和 `completed`/`failed`（委派结束），用于追踪每一次委派的完整生命周期。

## 隔离机制

### 执行隔离

每个 subagent 拥有独立的 thread 和 run，与父 agent 的对话上下文完全隔离。子 thread 的 metadata 中记录了 `parent_run_id`，建立了父子关系，但 child run 的历史消息不会污染父 agent 的上下文。

### 文件系统隔离

Subagent 的 computer policy 与主 agent 不同。在 `LocalSubagentExecutionService` 构造 `RunContext` 时，设置的 policy 为：

- `workspace`：可见
- `skills`：可见（按目标 profile 的 skills 列表过滤）
- `self`：**不可见**

`/self` 路径指向主 agent 的 sticky notes 等私有数据，subagent 无法访问。但 workspace 和 skills 是共享的，所以 subagent 可以读取主 agent 工作区中的文件，也可以加载 skill。

### 消息隔离

`deliver_actions=False` 确保 child run 产生的消息、文件等动作不会发送到外部平台。所有输出只通过 `SubagentDelegationResult.summary` 和 `artifacts` 返回给父 agent，由父 agent 决定如何向用户展示。

## 配置

```yaml
runtime:
  profiles:
    aca:                    # 主 agent（默认 agent）
      name: "Aca"
      prompt_ref: "prompt/aca"
      default_model: "gpt-4"
    excel_worker:           # 可委派的 subagent
      name: "Excel Worker"
      prompt_ref: "prompt/excel_worker"
      default_model: "gpt-4"
  plugins:
    - "my_module:MySubagentPlugin"  # 插件也可以注册 subagent
```

---

## 附录

### SubagentExecutor 协议

任何接受 `SubagentDelegationRequest` 并返回 `SubagentDelegationResult` 的异步函数都可以作为 subagent executor：

```python
class SubagentExecutor(Protocol):
    async def __call__(self, request: SubagentDelegationRequest) -> SubagentDelegationResult:
        ...
```

`LocalSubagentExecutionService` 实现了这个协议，复用了完整的 runtime 执行链路。插件也可以提供自己的实现，比如把任务发送到远程服务执行。

### SubagentDelegationRequest

```python
@dataclass
class SubagentDelegationRequest:
    parent_run_id: str
    parent_thread_id: str
    parent_agent_id: str
    actor_id: str
    channel_scope: str
    delegate_agent_id: str
    payload: dict
    metadata: dict
```

### 源码索引

| 文件 | 职责 |
|------|------|
| `src/acabot/runtime/subagents/contracts.py` | 委派请求/结果契约 |
| `src/acabot/runtime/subagents/broker.py` | Executor 注册表、Delegation Broker |
| `src/acabot/runtime/subagents/execution.py` | 本地执行服务（复用主线 pipeline） |
| `src/acabot/runtime/builtin_tools/subagents.py` | `delegate_subagent` 工具注册与调用 |
| `src/acabot/runtime/bootstrap/builders.py` | 本地 profile 注册为 executor |
| `src/acabot/runtime/plugin_manager.py` | 插件 executor 注册 |
