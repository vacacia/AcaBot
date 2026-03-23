# 工具、插件和子代理

这一篇只讲一件事：

**一项新能力在 AcaBot 里现在应该接成什么形态。**

很多功能最后写得别扭，不是因为代码细节难，而是因为入口形态一开始就选错了。

当前最重要的边界先记住：

- **tool** 是给模型调用的接口
- **builtin tool** 是 runtime 自带的前台工具
- **plugin** 是外部可选扩展
- **skill** 是模型可读的能力包
- **subagent** 是可被委派出去独立跑任务的 agent

不要再把这些东西混成一团。

---

## 先讲当前真相

现在前台真正和模型有关的能力入口，主要有这几类：

### 一、builtin tools

这是 runtime 自带的前台工具表面。

当前直接注册进 `ToolBroker` 的 builtin tool 来源是：

- `builtin:computer`
- `builtin:skills`
- `builtin:subagents`

其中模型真正能看到的工具是：

- `read`
- `write`
- `edit`
- `bash`
- `skill`
- `delegate_subagent`

这里要特别注意：

- `read / write / edit / bash` 是 **computer builtin tools**
- `skill` 是 **skills builtin tool**
- `delegate_subagent` 是 **subagents builtin tool**

它们都不是 plugin。

### 二、plugin tools 和 plugin hooks

plugin 现在主要表示外部扩展能力。

它们可以：

- 注册 hook
- 注册额外 tool
- 注册 subagent executor
- 参与 setup / teardown / reload 生命周期

但 plugin 不再承载前台基础工具。

### 三、特殊 bridge tool

当前还有一个特殊工具：

- `ask_backend`

它是前台 Aca 通往后台 maintainer 的桥。

它不是 `builtin:computer`，也不是普通文件工具。它目前还是通过 plugin 这条链接进来，因为它本质上是后台扩展能力，不是前台基础工作区能力。

---

## 先分清这五种东西

## 1. runtime 主线硬编码

适合：

- 每次 run 都必须发生
- 不该由模型自己决定
- 明显属于 runtime 骨架

现在的例子：

- `RuntimeApp.handle_event()` 的入口接线
- `SessionRuntime` 决策
- `ThreadPipeline.execute()`
- `Outbox` 发送
- thread working memory 更新
- run 收尾

如果某件事是“不管模型怎么想都必须发生”，那就属于这里。

---

## 2. tool

tool 是给 LLM 调用的接口。

tool 自己只定义这些东西：

- 名字
- 描述
- 参数
- 执行入口
- 返回值

tool 不决定：

- 当前 run 下能不能看见它
- 当前 run 下能不能调用它
- 当前 actor 能不能访问某个路径

这些都由上层控制，比如：

- `ToolBroker`
- profile
- world 可见性
- approval

### 当前 builtin tool 最典型的例子

#### computer builtin tools

定义位置：

- `src/acabot/runtime/builtin_tools/computer.py`

当前固定是：

- `read`
- `write`
- `edit`
- `bash`

它们只是薄薄一层接线，真正干活的是：

- `src/acabot/runtime/computer/runtime.py`

#### skill builtin tool

定义位置：

- `src/acabot/runtime/builtin_tools/skills.py`

当前是：

- `skill(name=...)`

它负责：

- 检查当前 skill 是否可见
- 读取 `SKILL.md`
- 把内容返回给模型

#### subagent builtin tool

定义位置：

- `src/acabot/runtime/builtin_tools/subagents.py`

当前是：

- `delegate_subagent`

它负责：

- 把委派请求转给 `SubagentDelegationBroker`

---

## 3. builtin tool

builtin tool 这个词在 AcaBot 里很重要，单独说清楚。

它表达的是：

> **runtime 自带的前台能力。**

也就是：

- 这是系统主产品的一部分
- 不该因为 plugin reload、disable、load failure 就消失
- 不该挂在 plugin 生命周期上

当前代码里，builtin tool 的注册入口在：

- `src/acabot/runtime/builtin_tools/__init__.py`
- `register_core_builtin_tools(...)`

启动时由：

- `build_runtime_components()`

直接把 builtin tools 注册进 `ToolBroker`。

### 这意味着什么

如果你在做下面这种能力：

- 读文件
- 写文件
- 改文件
- 跑 bash
- 读 skill
- 委派 subagent

优先先想：

> 这是不是 runtime 自带前台能力？

如果答案是“是”，那它更像 builtin tool，不像 plugin。

---

## 4. plugin

plugin 是 runtime 暴露给外部的可选扩展包。

它和系统主线的关系是：

- 能接进来
- 能拔出去
- 拔掉之后，系统应该只是少一项扩展能力
- 不该把前台基础能力一起带坏

当前 plugin 的核心代码在：

- `src/acabot/runtime/plugin_manager.py`
- `src/acabot/runtime/plugins/`

### plugin 现在能做什么

#### setup / teardown

plugin 可以在启动和停止时自己准备资源、清理资源。

#### hook

当前主线里的 hook 点有：

- `ON_EVENT`
- `PRE_AGENT`
- `POST_AGENT`
- `BEFORE_SEND`
- `ON_SENT`
- `ON_ERROR`

#### 注册额外 tool

plugin 可以注册普通 tool 或 runtime-native tool。

#### 注册 subagent executor

plugin 还可以声明额外的 subagent executor。

### 当前存在的 plugin 例子

现在 `src/acabot/runtime/plugins/__init__.py` 里导出的扩展插件主要有：

- `BackendBridgeToolPlugin`
- `NapCatToolsPlugin`
- `OpsControlPlugin`
- `ReferenceToolsPlugin`
- `StickyNotesPlugin`

它们都属于扩展层，不是前台 builtin computer tools。

---

## 5. skill

skill 不是一个函数，也不是一个 plugin 实例。

它更像：

> **一份能力包，一份任务说明，一组参考资料。**

最小形态至少有：

- `SKILL.md`

还可以带：

- `references/`
- `scripts/`
- `assets/`

### 当前 skill 在系统里是怎么进来的

关键代码在：

- `src/acabot/runtime/skills/catalog.py`
- `src/acabot/runtime/skills/package.py`
- `src/acabot/runtime/builtin_tools/skills.py`
- `src/acabot/runtime/computer/runtime.py`

当前主线是：

1. runtime 扫描 skill 目录，建立 `SkillCatalog`
2. profile 里的 `skills` 决定这个 agent 理论上能看到哪些 skill
3. 当前 run 的 world 再决定 `/skills/...` 里实际可见哪些 skill
4. 模型会先在 prompt 里看到可见 skill 摘要
5. 模型可以再调用 `skill(name=...)` 读取某个 `SKILL.md`
6. 模型也可以通过 `/skills/...` 路径继续读 skill 里的文件

### 当前 skill 的两个现实入口

#### 入口 1：prompt 摘要

`ModelAgentRuntime` 会把当前可见 skill 摘要拼进 system prompt。

这一步表达的是：

- 模型先知道“现在有哪些 skill 可用”

#### 入口 2：`skill(name=...)`

当前代码里仍然保留了 builtin `skill` 工具。

它会：

- 检查这个 skill 当前是不是可见
- 读取 `SKILL.md`
- 把内容返回给模型

#### 入口 3：`/skills/...`

前台 `computer` 现在已经支持稳定的 `/skills/...` 路径。

这意味着模型也能通过普通文件工具去读：

- `/skills/foo/SKILL.md`
- `/skills/foo/references/...`
- `/skills/foo/scripts/...`
- `/skills/foo/assets/...`

### 这里最重要的一点

当前 skill 设计还不是最终形态。

如果你想看“skill 当前该以哪条机制为准”，请优先看：

- `docs/18-skill.md`
- 特别是：`## 2. skill 加载机制(以此为准)`

这篇 `06` 只负责讲它在 runtime 里的当前位置，不把整份 skill 设计讨论全塞进来。

---

## 6. subagent

subagent 不是一个小接口，而是一个能被主 agent 委派出去独立工作的 agent。

它更像：

> **一个内部 worker。**

当前主线代码在：

- `src/acabot/runtime/subagents/broker.py`
- `src/acabot/runtime/subagents/execution.py`
- `src/acabot/runtime/builtin_tools/subagents.py`

### 当前 subagent 是怎么跑起来的

当前委派链路是：

1. 模型调用 `delegate_subagent`
2. builtin tool 把请求交给 `SubagentDelegationBroker`
3. broker 按 `delegate_agent_id` 找 executor
4. 当前默认本地实现是 `LocalSubagentExecutionService`
5. 它会伪造一条内部事件，创建 child run
6. 再复用 runtime 自己的 `ThreadPipeline.execute(...)`
7. 但 `deliver_actions=False`，不会把 child run 的动作直接发到外部平台
8. 最后只把结果总结返回给父 run

### 当前 subagent 最关键的边界

#### 1. subagent 不是靠 skill 绑定的

现在 `delegate_subagent` 直接按：

- `delegate_agent_id`

来委派。

它不再通过 skill 配置做这一层绑定。

#### 2. subagent child run 有自己的 computer 决策

当前 child run 会显式拿到 subagent 用的 computer 决策。

最关键的一条是：

- `/self` 对 subagent 不可见

也就是：

- `workspace` 可见
- `skills` 可见
- `self` 不可见

#### 3. subagent 不走前台那条完整的 session-config 主线

当前子任务会共享 Work World 契约，但不会重新走完整的前台：

- session-config
- surface
- context

那条主线。

它更像内部 worker run，而不是第二个完整前台用户会话。

---

## `ToolBroker` 现在到底管什么

`ToolBroker` 在：

- `src/acabot/runtime/tool_broker/`

它不是具体工具实现，而是工具编排中心。

当前主要职责有：

- 注册工具
- 保存工具来源
- 按 profile 过滤可见工具
- 按当前 run 再做一轮真实可见性过滤
- 执行工具
- 做 approval
- 记录审计
- 把工具副产物累积到 run 状态

### 现在这里有几个重要事实

#### 1. builtin tool 不允许被 plugin 同名覆盖

如果 plugin 想注册一个和 builtin 同名的工具，`ToolBroker` 会保留 builtin 版本，不让 plugin 把它盖掉。

#### 2. run 级可见性现在会看 workspace state

比如前台 `computer` 工具是否真的可见，除了 profile 里的 `enabled_tools` 之外，还会再看当前 run 的：

- `ctx.workspace_state.available_tools`

也就是说：

- profile 说“理论上能用”
- world / computer 再决定“这次 run 实际能不能看到”

#### 3. skill 工具会按当前 run 的 skill 可见性动态变化

如果当前 run 实际没有可见 skill，`skill` 不该继续暴露一个注定失败的入口。

#### 4. `ask_backend` 还有自己的特殊可见性

它不是普通 builtin tool，也不是对所有 agent 都开放。

---

## `ask_backend` 为什么是特殊入口

`ask_backend` 当前来自：

- `src/acabot/runtime/plugins/backend_bridge_tool.py`

它的定位是：

- 前台 Aca 向后台 maintainer 发 query / change 请求

### 为什么它不属于 `builtin:computer`

因为它不是前台工作区基础能力。

它依赖：

- backend session 是否真的 configured
- 当前 agent 是否是默认前台 agent
- backend bridge 是否可用

所以它更接近：

- 一个特殊扩展入口

而不是：

- `read / write / edit / bash` 这种前台通用基础工具

---

## 什么时候该接成哪种形态

这里给一份现在最好用的速记。

## 1. 什么时候直接改 runtime 主线

如果答案是：

- 这一步每次都必须发生
- 不该由模型决定
- 属于运行时骨架

那就改：

- `RuntimeApp`
- `SessionRuntime`
- `ThreadPipeline`
- `Outbox`

这类地方。

例子：

- 路由决策
- run_mode 处理
- thread working memory 更新
- memory extraction 收尾

---

## 2. 什么时候做成 builtin tool

如果答案是：

- 这是前台 bot 的基础能力
- 模型应该可以按需调用
- 不该跟 plugin 生命周期绑死

那更像 builtin tool。

最典型的就是现在的：

- `read`
- `write`
- `edit`
- `bash`
- `skill`
- `delegate_subagent`

---

## 3. 什么时候做成 plugin

如果答案是：

- 这是外部扩展能力
- 想开关式启用
- 想在固定阶段插 hook
- 想加一组扩展 tool，但不属于前台基础工具

那更像 plugin。

例子：

- 视频链接自动解析
- 平台查询工具插件
- sticky notes 插件
- reference tools
- ops control

---

## 4. 什么时候更像 skill

如果答案是：

- 这不是一个小接口
- 而是一套做事说明、参考资料、脚本和资源

那更像 skill。

skill 更像：

- 一份能力包
- 一份操作手册
- 一套工作流程说明

---

## 5. 什么时候更像 subagent

如果答案是：

- 任务边界清楚
- 过程长
- 上下文大
- 想让主 agent 只拿结果，不想自己扛全过程

那更像 subagent。

---

## 当前最容易犯的错

## 1. 把 plugin 当成系统垃圾桶

plugin 适合扩展点，不适合把本该属于主线或 builtin tool 的东西都塞进去。

## 2. 把 builtin tool 又写回 plugin 生命周期

现在前台基础工具已经从 plugin 生命周期里拆出来了。

不要再把：

- `read`
- `write`
- `edit`
- `bash`

这种能力重新挂回 plugin。

## 3. 把 skill 和 subagent 混成一种东西

它们都像“能力”，但不是一回事：

- skill 是能力包
- subagent 是执行者

## 4. 只看 profile，不看 run 真实可见性

很多工具今天不是 profile 一层说了算，还要看：

- 当前 world
- 当前 workspace state
- 当前 visible skills
- 当前 backend 是否 configured

---

## 如果改这里，先看哪些源码

建议按这个顺序：

1. `src/acabot/runtime/builtin_tools/__init__.py`
2. `src/acabot/runtime/builtin_tools/computer.py`
3. `src/acabot/runtime/builtin_tools/skills.py`
4. `src/acabot/runtime/builtin_tools/subagents.py`
5. `src/acabot/runtime/tool_broker/broker.py`
6. `src/acabot/runtime/plugin_manager.py`
7. `src/acabot/runtime/plugins/__init__.py`
8. `src/acabot/runtime/plugins/backend_bridge_tool.py`
9. `src/acabot/runtime/subagents/broker.py`
10. `src/acabot/runtime/subagents/execution.py`

如果你只想记一句话，那就是：

> **前台基础能力走 builtin tool，外部扩展走 plugin，做事说明是 skill，独立干活的是 subagent。**
