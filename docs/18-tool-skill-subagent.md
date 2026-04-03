# 工具、技能与子代理

本文档说明 bot 能力面的三个层次：tool（给模型调用的接口）、skill（按目录组织的能力包）、subagent（可被委派独立工作的 agent）。

## 概念区分

| 概念 | 定位 | 不是什么 |
|------|------|---------|
| **tool** | 给 LLM 调用的接口，只定义名字/描述/参数/执行入口/返回值 | 不决定可见性和准入（由 ToolBroker、agent 配置、world policy 控制） |
| **builtin tool** | runtime 自带的 tool，不挂在 plugin 生命周期上 | 不会因 plugin reload/disable/load failure 消失 |
| **plugin** | 外部可选扩展包，可以注册 hook 和额外 tool | 不注册 subagent；卸掉后系统只少扩展能力 |
| **skill** | 按目录组织的能力包（SKILL.md + 可选 references/scripts/assets） | 不是一个函数，是一整套"怎么做这件事"的包 |
| **subagent** | 可被主 agent 委派独立跑任务的 agent | 不是普通函数型 tool，会创建 child run 复用 runtime 执行链路 |

## Tool

### Builtin Tools

启动时由 `build_runtime_components()` → `register_core_builtin_tools(...)` 直接注册进 ToolBroker：

| 来源 | 工具 |
|------|------|
| `builtin:computer` | `read`、`write`、`edit`、`bash` |
| `builtin:message` | `message` |
| `builtin:skills` | `Skill` |
| `builtin:subagents` | `delegate_subagent`（只在当前 run 的 `visible_subagents` 非空且 catalog 可解析时暴露） |

Builtin tool 不允许被 plugin 同名覆盖。

`message` 是统一的出站消息 surface。对模型只暴露一个工具名，`action` 目前锁定为 `send` / `react` / `recall` 三种：
- `send` 产出高层 `SEND_MESSAGE_INTENT`，把 `text`、`images`、`render`、`at_user`、`target` 留给 Outbox 后续物化
- `react` 直接产出底层 `REACTION`
- `recall` 直接产出底层 `RECALL`

`message.action="send"` 已经发出内容型消息时，本轮默认 assistant 文本回复会被 runtime 抑制。所以如果一条消息里既要文字说明又要图片或渲染图，必须在同一次 `send` 调用里把 `text`、`images`、`render` 组合完整。

### 特殊 Bridge Tool

`ask_backend`：前台 Aca 通往后台 maintainer 的工具。不是 `builtin:computer`，通过 plugin 链接入，因为它是后台扩展能力不是前台基础工作区能力。

### Plugin Tools

Plugin 可以注册 hook 和额外 tool，额外 tool 参与 setup/teardown/reload 生命周期。代码在 `runtime/plugin_manager.py` 和 `runtime/plugins/`。Plugin 和 subagent 的唯一交点：plugin 提供普通 tool，subagent 的 `tools` 可以启用这些 tool。

### ToolBroker

`src/acabot/runtime/tool_broker/`，工具编排中心。职责：注册工具、保存来源、按 agent 配置过滤可见工具、按当前 run 再做真实可见性过滤、执行工具、做 approval、记录审计、累积工具副产物到 run 状态。

Run 级可见性会看 `ctx.workspace_state.available_tools`——agent 配置说"理论上能用"，world/computer 再决定"这次 run 实际能不能看到"。

---

## Skill

### 设计（不准修改）

skill 是一个按目录组织的能力包。有些能力不是一个函数，而是一整套"怎么做这件事"的包：给模型任务说明、工作步骤、按需读取的参考资料，必要时再给脚本和资源。

每个 skill 至少有 `SKILL.md`，还可以带 `references/`、`scripts/`、`assets/`。

### 加载机制（不准修改）

1. Runtime 扫描 `runtime.filesystem.skill_catalog_dirs` 指定的目录（相对路径算 `project`，`~`/绝对路径算 `user`），递归找 `**/SKILL.md`。默认扫 `./.agents/skills` 和 `~/.agents/skills`
2. 每个 SKILL.md 解析成 `SkillMeta`（name 取 frontmatter，没有就用相对目录名推导如 `foo/bar`；保存 filePath、description、scope、argument-hint、disable-model-invocation）
3. 扫描阶段保留全部 skill，不做过滤
4. 发请求前，可见 skill 的摘要注入 system prompt 的 `<system-reminder>` 块
5. 模型看到名字和描述，不知道路径
6. 模型调用 `Skill(skill="frontend-design")`，runtime 按名字找文件读 SKILL.md
7. 返回 `Launching skill` + `Base directory for this skill: /skills/<name>` + 正文
8. 后续模型沿 `/skills/<name>/references/...` 等路径用普通文件工具继续读

### 扫描与解析

`FileSystemSkillPackageLoader` 在启动时和热重载时，从配置的扫描根目录递归查找所有 `SKILL.md`。配置项为 `runtime.filesystem.skill_catalog_dirs`，默认值为 `./.agents/skills`（project scope）和 `~/.agents/skills`（user scope）。

**Scope 推断规则**：相对路径（如 `./skills`）推断为 `project`，`~` 路径或绝对路径推断为 `user`。同名 skill 存在时 project 优先于 user。

**命名推导**：`skill_name` 由目录相对于扫描根的路径推导，嵌套层级用 `:` 分隔。例如 `skills/debugging/SKILL.md` 推导为 `"debugging"`，`skills/data/excel/SKILL.md` 推导为 `"data:excel"`。

**Frontmatter 解析**：`parse_skill_package()` 拆分 `SKILL.md` 的 YAML frontmatter 和正文，字段映射关系如下表：

| frontmatter 字段 | 映射目标 | 说明 |
|------------------|----------|------|
| `description` | `manifest.description` | 必填，缺失抛 `SkillPackageFormatError` |
| `name` | `manifest.metadata["display_name"]` | 控制面展示用，非寻址主键 |
| `argument-hint` | `manifest.argument_hint` | 工具调用时的参数提示 |
| `disable-model-invocation` | `manifest.disable_model_invocation` | 禁止模型主动调用 |
| 其他字段 | `manifest.metadata` | 透传，不丢失 |

格式错误的 skill 会被跳过并记录 warning，不阻塞启动。

**热重载**：`ConfigControlPlane` 在配置热更新时调用 `SkillCatalog.reload()` 重新扫描全部根目录，新增或修改的 skill 无需重启即可生效。

### 可见性

三层过滤，全部通过后 skill 才能到达模型：

| 层级 | 过滤点 | 说明 |
|------|--------|------|
| **Catalog 层** | `SkillCatalog` | skill 必须在扫描目录中存在且格式正确 |
| **Profile 层** | `profile.skills` 白名单 | 白名单中不存在的 skill 自动忽略 |
| **Run 层** | `WorldView.visible_skill_names` | session-driven computer 决策提供了 `visible_skills` 则使用，否则回退到 `profile.skills`；`/skills` root 被隐藏或列表为空时 `Skill` 工具不暴露给模型 |

同名 skill 按 `project > user` 优先级选取。

### 模型加载链路

模型本身不直接访问文件系统，它通过一条三步链路来加载和使用 skill：先在 system prompt 中看到可用 skill 的摘要列表，再通过 `Skill` 工具按名称读取完整内容，最后通过 `/skills/` 路径访问 skill 包内的参考资料和脚本。

**第一步：从 prompt 摘要中感知 skill。** 每一轮对话开始时，runtime 把当前可见 skill 的名称和描述注入到 system prompt 中。摘要只包含 `skill_name` 和 `description` 两个字段，不包含 SKILL.md 的正文内容。注入格式形如：

```
<system-reminder>
The following skills are available for use with the Skill tool:

- data:excel: 处理 Excel 文件的标准工作流。
- debugging: 系统性调试任何 bug 或测试失败。

</system-reminder>
```

如果当前 run 没有任何可见 skill（`/skills` root 被隐藏或 `visible_skill_names` 为空），runtime 不会注入这段摘要，也不会把 `Skill` 工具注册给模型。

**第二步：通过 Skill 工具加载完整内容。** 模型判断当前任务需要某个 skill 时，调用内置的 `Skill` 工具并传入 skill 名称（如 `Skill(skill="data:excel")`）。runtime 先检查请求的 skill 是否在当前 run 的可见列表中——不在则返回错误 `"Skill not assigned to current agent"`，不泄露其他 skill 信息。检查通过后，runtime 从 catalog 中读取 SKILL.md 的完整内容，标记当前 thread 已加载该 skill（供后续物化逻辑使用），返回固定格式：

```
Launching skill: data:excel

Base directory for this skill: /skills/data:excel

<SKILL.md 完整内容>
```

其中 `Base directory` 这一行告诉模型：skill 的入口说明已拿到，若 SKILL.md 正文中引用了 `references/`、`scripts/`、`assets/` 下的文件，应通过 `/skills/data:excel/...` 路径继续读取。

**第三步：通过 /skills/ 路径访问 skill 资源。** 模型拿到 base directory 后，按照 SKILL.md 中的指引，通过 `/skills/` 路径继续读取 skill 包内的文件（如 `/skills/data:excel/references/spec.md`）。`/skills/` 路径并非 catalog 源目录的直接映射，而是当前 thread 可见 skill 的副本视图——当模型第一次请求某个 skill 的文件时，`ComputerRuntime` 把该 skill 的整个目录从 catalog 源复制到当前 thread 的独立副本目录中（skill 物化）。之后该 thread 对 `/skills/` 下该 skill 的所有读写操作都发生在副本上，不影响 catalog 中的原始文件，保证多个 thread 可以同时使用同一个 skill 而不互相干扰。此外，`WorldView.resolve()` 在解析 `/skills/` 路径时会检查请求的 skill 名称是否属于当前 run 的可见列表，模型不能通过路径遍历读取自己无权访问的 skill。

### 配置

```yaml
runtime:
  profiles:
    aca:
      skills:
        - data:excel
        - debugging
  filesystem:
    skill_catalog_dirs:
      - "./my-skills"              # project scope
      - "~/.agents/skills"         # user scope
```

### 数据结构

**SkillCatalog** 是统一查询入口，保留全部候选项，按规则选择正式生效的那一份。

```python
class SkillCatalog:
    def reload(self)           # 重新扫描全部
    def get(self, name)        # 按优先级取一条 manifest
    def read(self, name)       # 读取完整 SkillPackageDocument
    def visible_skills(profile)  # 按 profile.skills 过滤
```

`list_all()` 返回全部候选项，`get()` / `read()` 只返回同名中优先级最高的那一条。

**SkillPackageManifest** 贯穿发现到执行的核心数据结构（`slots=True`，字段即全部状态）：

```python
@dataclass(slots=True)
class SkillPackageManifest:
    skill_name: str              # runtime 主键，来自目录路径
    scope: str                   # "project" | "user"
    description: str             # 简短说明
    host_skill_file_path: str    # SKILL.md 的宿主机绝对路径
    argument_hint: str
    disable_model_invocation: bool
    metadata: dict
```

`skill_name` 是寻址主键（工具参数、`/skills/` 路径、prompt 摘要都用它）。`display_name` 属性来自 `metadata["display_name"]`（即 frontmatter 的 `name`），仅用于控制面展示，为空则回退 `skill_name`。派生属性如下：

| 属性 | 计算方式 | 使用场景 |
|------|----------|----------|
| `host_skill_root_path` | `Path(host_skill_file_path).parent` | 物化复制时的源目录 |
| `display_name` | `metadata.get("display_name") or skill_name` | 控制面展示 |
| `has_references` | `(root / "references").is_dir()` | payload 中标记是否有参考资源 |
| `has_scripts` | `(root / "scripts").is_dir()` | 同上 |
| `has_assets` | `(root / "assets").is_dir()` | 同上 |

**SkillPackageDocument** 在 manifest 基础上多带 SKILL.md 原始文本，只有 `Catalog.read()` 和 `Loader.read_document()` 返回：

```python
@dataclass(slots=True)
class SkillPackageDocument:
    manifest: SkillPackageManifest
    raw_markdown: str     # 含 frontmatter 的原始 SKILL.md
    body_markdown: str    # 去掉 frontmatter 后的正文
```

### 源码索引

| 文件 | 职责 |
|------|------|
| `src/acabot/runtime/skills/package.py` | 数据结构、SKILL.md 解析 |
| `src/acabot/runtime/skills/loader.py` | 文件系统扫描、命名推导 |
| `src/acabot/runtime/skills/catalog.py` | 统一查询入口、同名选择、可见性过滤 |
| `src/acabot/runtime/bootstrap/config.py` | 扫描目录解析、scope 推断 |
| `src/acabot/runtime/bootstrap/builders.py` | `build_skill_catalog()` 组件组装 |
| `src/acabot/runtime/builtin_tools/skills.py` | Skill 工具注册、可见性检查、结果格式化 |
| `src/acabot/runtime/computer/world.py` | `/skills/` 路径映射、跨 skill 读取防护 |
| `src/acabot/runtime/computer/runtime.py` | skill 物化（catalog 源 → thread 副本） |

---

## Subagent

### 定义真源

文件系统 catalog：`extensions/subagents/<name>/SUBAGENT.md`。每个 subagent 只认一个 SUBAGENT.md，frontmatter 定义 metadata（name、description、tools、model_target），正文 markdown 作为 subagent prompt。

Plugin 不注册 subagent，不参与 subagent 生命周期。

### 注册

Subagent executor 可以从两个地方注册到 runtime。

**本地 Profile 自动注册**：`register_local_subagent_executors()` 在 bootstrap 阶段遍历所有 profile，跳过 webui 动态 session（`managed_by` 为 `webui_session` 或 `webui_v2_session`），其余都用 `LocalSubagentExecutionService` 作为执行器注册到 `SubagentExecutorRegistry`。这意味着只要在配置里多写一个 profile，主 agent 就能把它当作 subagent 委派任务过去，不需要额外配置。配置示例：

```yaml
runtime:
  profiles:
    aca:                    # 主 agent（默认 agent）
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

**Runtime Plugin 注册**：插件通过实现 `subagent_executors()` 方法声明自己的 subagent executor。每个注册项包含 `agent_id`、`executor`（一个接受 `SubagentDelegationRequest` 并返回 `SubagentDelegationResult` 的异步函数）和可选的 `metadata`。

**SubagentExecutorRegistry** 是中央注册表，按 `agent_id` 存储所有已注册的 executor：

```python
class SubagentExecutorRegistry:
    def register(self, agent_id, executor, *, source, metadata) -> None
    def get(self, agent_id) -> RegisteredSubagentExecutor | None
    def list_all(self) -> list[RegisteredSubagentExecutor]
    def unregister_source(self, source) -> list[str]
```

同一个 `agent_id` 可以被多次注册，后注册的覆盖先注册的。`unregister_source()` 用于按来源批量卸载——配置热更新时先卸载所有 `runtime:local_profile` 来源的 executor 再重新注册。

### 可见性

`ToolBroker._should_expose_delegate_tool()` 决定当前 profile 是否能看到 `delegate_subagent` 工具。只有同时满足以下条件时才暴露：

| 条件 | 说明 |
|------|------|
| 注册表中存在至少一个 `agent_id` 不同于当前 profile 的 executor | 只有自己时不暴露 |
| 当前 profile 是默认主 agent（`profile.agent_id == default_agent_id`），或未设置 `default_agent_id` | 非默认 agent 无法委派 |

Session config 的 `visible_subagents` 决定当前 run 能看到谁。Catalog 决定 subagent 是否存在，`visible_subagents` 决定能不能调。当前 session 没放开任何 subagent 时 `delegate_subagent` 不暴露给模型。

**摘要注入**：`ToolBroker` 在构建 `ToolRuntime` 时，遍历 `SubagentExecutorRegistry` 中所有已注册的 executor，过滤掉当前 profile 自己的 `agent_id`，剩余的按 `agent_id` 和 `profile_name` 生成摘要列表。这段摘要通过 `ContextAssembler` 注入到 system prompt 中（`source_kind="subagent_reminder"`，写入 `system_prompt` slot），注入格式形如：

```
Available Subagents:
- excel_worker: Excel Worker
- math_solver: Math Solver
```

每一行由 `agent_id` 和 `profile_name` 拼接，`profile_name` 来自注册时的 metadata（本地 profile 注册时取配置文件中的 `name` 字段），缺省则回退为 `agent_id`。模型拿到这段列表后才能判断应该委派给哪个 subagent。

### 委派链路

主 agent 通过调用 `delegate_subagent` 工具来委派任务。整个过程和 skill 的加载链路类似：模型先从 prompt 摘要中知道有哪些 subagent 可用，再通过工具调用触发执行，最后拿到结果摘要。

**调用与校验**：模型调用 `delegate_subagent` 并传入目标 `agent_id` 和任务描述。`BuiltinSubagentToolSurface._delegate_subagent()` 收到调用后转交给 `SubagentDelegationBroker`，Broker 在执行前做三个检查：① 当前 agent 是否是默认主 agent（非 default agent 不能委派）；② 目标 `delegate_agent_id` 是否就是自己（不能委派给自己）；③ 目标 executor 是否存在于注册表中（不存在则返回错误）。检查通过后，Broker 构造 `SubagentDelegationRequest`，包含父 run 上下文信息（`parent_run_id`、`parent_thread_id`、`parent_agent_id`）以及模型传入的 `task` 和 `payload`，然后调用目标 executor 执行。

**本地执行**：当前默认执行器是 `LocalSubagentExecutionService`，它复用 runtime 的主线执行链路但做了关键调整：

| 步骤 | 动作 |
|------|------|
| 1 | 构造 synthetic event（内部消息事件），内容为模型传入的任务描述 |
| 2 | 为委派创建或复用 child thread，标记 `thread_kind="subagent"`，metadata 中记录父 run ID |
| 3 | 加载目标 profile 对应的 prompt 和模型配置 |
| 4 | 创建 child run 并构造 `RunContext` |
| 5 | 调用 `ThreadPipeline.execute(ctx, deliver_actions=False)` 执行 |

其中 `deliver_actions=False` 是最重要的区别——child run 的输出动作不会发送到外部平台，结果只通过 `SubagentDelegationResult` 返回给父 run。

**结果返回**：执行完成后，`LocalSubagentExecutionService` 从 child run 中提取结果，构造 `SubagentDelegationResult`。`summary` 字段是父 agent 实际看到的内容，工具返回格式为 `Delegation completed for <agent_id>. subagent=<agent_id> summary=<摘要内容>`。同时在父 run 的审计步骤中追加两条记录：`started`（委派开始）和 `completed`/`failed`（委派结束），用于追踪每一次委派的完整生命周期。

### 隔离机制

**执行隔离**：每个 subagent 拥有独立的 thread 和 run，与父 agent 的对话上下文完全隔离。子 thread 的 metadata 中记录了 `parent_run_id` 建立父子关系，但 child run 的历史消息不会污染父 agent 的上下文。

**文件系统隔离**：subagent 的 computer policy 与主 agent 不同。`LocalSubagentExecutionService` 构造 `RunContext` 时设置的 policy 为：workspace 可见、skills 可见（按目标 profile 的 skills 列表过滤）、`/self` 不可见。`/self` 路径指向主 agent 的 sticky notes 等私有数据，subagent 无法访问；workspace 和 skills 是共享的，subagent 可以读取主 agent 工作区中的文件，也可以加载 skill。

**消息隔离**：`deliver_actions=False` 确保 child run 产生的消息、文件等动作不会发送到外部平台。所有输出只通过 `SubagentDelegationResult.summary` 和 `artifacts` 返回给父 agent，由父 agent 决定如何向用户展示。

### 边界

| 约束 | 说明 |
|------|------|
| 不递归 | subagent 不能再委派 subagent，`visible_subagents` 固定为空 |
| 不走完整 session-config 主线 | 共享 Work World 契约，但不重走 session-config/surface/context |
| 不支持 approval resume | 命中需要 approval 的工具直接失败，不进入 `waiting_approval` |

### 数据结构

**SubagentExecutor 协议**：任何接受 `SubagentDelegationRequest` 并返回 `SubagentDelegationResult` 的异步函数都可以作为 subagent executor。`LocalSubagentExecutionService` 实现了该协议，复用完整的 runtime 执行链路；插件也可以提供自己的实现（如把任务发送到远程服务执行）。

```python
class SubagentExecutor(Protocol):
    async def __call__(self, request: SubagentDelegationRequest) -> SubagentDelegationResult:
        ...
```

**SubagentDelegationRequest**：

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

**SubagentDelegationResult**：

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

### 源码索引

| 文件 | 职责 |
|------|------|
| `src/acabot/runtime/subagents/contracts.py` | 委派请求/结果契约 |
| `src/acabot/runtime/subagents/broker.py` | Executor 注册表、Delegation Broker |
| `src/acabot/runtime/subagents/execution.py` | 本地执行服务（复用主线 pipeline） |
| `src/acabot/runtime/builtin_tools/subagents.py` | `delegate_subagent` 工具注册与调用 |
| `src/acabot/runtime/bootstrap/builders.py` | 本地 profile 注册为 executor |
| `src/acabot/runtime/plugin_manager.py` | 插件 executor 注册 |

---

## 关键文件

| 文件 | 职责 |
|------|------|
| `runtime/builtin_tools/__init__.py` | builtin tool 注册入口 |
| `runtime/builtin_tools/computer.py` | read/write/edit/bash 工具表面 |
| `runtime/builtin_tools/skills.py` | Skill 工具表面 |
| `runtime/builtin_tools/subagents.py` | delegate_subagent 工具表面 |
| `runtime/tool_broker/broker.py` | ToolBroker 编排中心 |
| `runtime/plugin_manager.py` | Plugin 管理 |
| `runtime/skills/catalog.py` | SkillCatalog |
| `runtime/skills/package.py` | Skill 包解析 |
| `runtime/skills/loader.py` | Skill 加载 |
| `runtime/subagents/contracts.py` | Subagent 契约 |
| `runtime/subagents/broker.py` | SubagentDelegationBroker |
| `runtime/subagents/execution.py` | LocalSubagentExecutionService |
