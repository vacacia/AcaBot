# 工具、技能与子代理

本文档说明 bot 能力面的三个层次：tool（给模型调用的接口）、skill（按目录组织的能力包）、subagent（可被委派独立工作的 agent）。详细实现见 `docs/wiki/skill.md`、`docs/wiki/subagent.md`。

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
| `builtin:skills` | `Skill` |
| `builtin:subagents` | `delegate_subagent`（只在当前 run 的 `visible_subagents` 非空且 catalog 可解析时暴露） |

Builtin tool 不允许被 plugin 同名覆盖。

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

### 可见性

真正过滤在 prompt 注入前和 `Skill` 工具读取前，三层共同决定：

1. **SkillCatalog**：全部扫描到的 skill
2. **`agent.visible_skills`**：agent 配置里理论上能看到的 skill
3. **当前 `world_view` 的 `/skills` 可见性**：这次 run 实际暴露哪些

同名 skill 按 `project > user` 优先级选取。

---

## Subagent

### 定义真源

文件系统 catalog：`extensions/subagents/<name>/SUBAGENT.md`。每个 subagent 只认一个 SUBAGENT.md，frontmatter 定义 metadata（name、description、tools、model_target），正文 markdown 作为 subagent prompt。

Plugin 不注册 subagent，不参与 subagent 生命周期。

### 可见性

Session config 的 `visible_subagents` 决定当前 run 能看到谁。Catalog 决定 subagent 是否存在，`visible_subagents` 决定能不能调。当前 session 没放开任何 subagent 时 `delegate_subagent` 不暴露给模型。

### 委派链路

1. Session 把 `visible_subagents` 解析进当前 run 的 computer policy
2. ToolBroker 在 allowlist 非空且 catalog 可解析时暴露 `delegate_subagent`
3. 模型调用 `delegate_subagent`
4. Builtin tool → `SubagentDelegationBroker` → 按 agent_id 查 `SubagentCatalog`
5. `LocalSubagentExecutionService` 用 SUBAGENT.md 构造 synthetic child profile
6. 伪造内部事件，创建 child run，复用 `ThreadPipeline.execute()`
7. `deliver_actions=False`（不发到外部平台），只把结果总结返回父 run

### 边界

- **Child run 的 computer 决策**：workspace 可见、skills 可见、/self 不可见、visible_subagents 固定为空
- **不递归**：subagent 不能再委派 subagent
- **不走完整 session-config 主线**：共享 Work World 契约，但不重走 session-config/surface/context
- **不支持 approval resume**：命中需要 approval 的工具直接失败，不进入 waiting_approval

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
