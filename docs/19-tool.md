# tool

- **tool** 是给模型调用的接口
- **builtin tool** 是 runtime 自带的 tool
- **plugin** 是外部可选扩展
- **skill** 是模型可读的能力包
- **subagent** 是可被委派出去独立跑任务的 agent
不要把这些东西混成一团

# tool 是什么
tool 是给 LLM 调用的接口

tool 自己只定义名字, 描述, 参数, 执行入口, 返回值

tool 不决定: 当前 run 下能不能看见它, 当前 run 下能不能调用它, 当前 actor 能不能访问某个路径

这些都由上层控制，比如`ToolBroker`, profile, world 可见性, approval


# tool 类型

## builtin tools
当前代码里，builtin tool 的注册入口在：
    - `src/acabot/runtime/builtin_tools/__init__.py`
    - `register_core_builtin_tools(...)`
启动时由：`build_runtime_components()` 直接把 builtin tools 注册进 `ToolBroker`


当前直接注册进 `ToolBroker` 的 builtin tool 来源是：
- `builtin:computer`
    - `read`
    - `write`
    - `edit`
    - `bash`
- `builtin:skills`
    - `Skill`
- `builtin:subagents`
    - `delegate_subagent`


- `read / write / edit / bash` 是 **computer builtin tools**
- `Skill` 是 **skills builtin tool**
- `delegate_subagent` 是 **subagents builtin tool**
- `delegate_subagent` 只是前台入口, 真正能不能看到它, 要看当前 run 的 session `visible_subagents`
- 当前 session 没放开任何 subagent 时, `delegate_subagent` 不会暴露给模型

---

为什么不用 plugin 来注册这些 tool?
- 不该因为 plugin reload、disable、load failure 就消失
- 不该挂在 plugin 生命周期上

## 特殊 bridge tool

当前还有一个特殊工具：

- `ask_backend`

它是前台 Aca 通往后台 maintainer 的工具。

它不是 `builtin:computer`，也不是普通文件工具。

它目前还是通过 plugin 这条链接进来，因为它本质上是后台扩展能力，不是前台基础工作区能力。

## 对比 plugin tools 和 plugin hooks

plugin 主要表示外部扩展能力。
不适合把本该属于主线或 builtin tool 的东西都塞进去。


plugin 可以：
    - 注册 hook
    - 注册额外 tool
    - 额外 tool 参与 setup / teardown / reload 生命周期
    - 不注册 subagent

当前 plugin 的核心代码在：
    - `src/acabot/runtime/plugin_manager.py`
    - `src/acabot/runtime/plugins/`

plugin 例子：
    - 视频链接自动解析
    - 平台查询工具插件

subagent 的定义真源现在是文件系统 `SUBAGENT.md` catalog。
plugin 和 subagent 的唯一交点是:
- plugin 可以提供普通 tool
- subagent 的 `tools` 可以启用这些 tool


# `ToolBroker` 管什么

`ToolBroker` 在：`src/acabot/runtime/tool_broker/`
它是工具编排中心

当前主要职责有：
- 注册工具
- 保存工具来源
- 按 profile 过滤可见工具
- 按当前 run 再做一轮真实可见性过滤
- 执行工具
- 做 approval
- 记录审计
- 把工具副产物累积到 run 状态

## 1. builtin tool 不允许被 plugin 同名覆盖

如果 plugin 想注册一个和 builtin 同名的工具，`ToolBroker` 会保留 builtin 版本，不让 plugin 把它盖掉。

## 2. run 级可见性现在会看 workspace state

比如前台 `computer` 工具是否真的可见，除了 profile 里的 `enabled_tools` 之外，还会再看当前 run 的：

- `ctx.workspace_state.available_tools`

也就是说：
- profile 说“理论上能用”
- world / computer 再决定“这次 run 实际能不能看到”





