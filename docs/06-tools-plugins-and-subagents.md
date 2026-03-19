# 工具、插件和子代理

这一块决定“新能力到底应该接成什么形态”。

很多功能最后写得别扭，问题不是代码细节，而是入口形态一开始选错了。

## 三种常见形态

### 1. 主线硬编码

适合:

- 每次 run 都必须发生
- 不是模型可选能力
- 明显属于 runtime 骨架

例子:

- run 生命周期推进
- outbox 发送
- thread working memory 更新

### 2. tool

适合:

- 给模型按需调用
- 有清晰的输入输出
- 有可能需要审批
- 更像“能力接口”而不是“系统阶段”

例子:

- QQ 的查人、查群、查消息工具
- QQ 的 `react_emoji`、禁言、撤回这类平台动作工具
- 让模型自己决定什么时候看图、什么时候查历史消息

### 3. plugin / hook

适合:

- 横切逻辑
- 运行时可插拔
- 需要在主线某个固定阶段插入
- 可能注册 tools / hooks / subagent executors

例子:

- 一个视频链接解析插件，在 `ON_EVENT` 或 `PRE_AGENT` 就把链接处理掉，必要时直接 `skip_agent`
- 一个日报插件，定时或主动触发，查数据库拿当天消息，总结后发到群里
- NapCat 查询工具插件，把 OneBot API 封成模型能用的 tool

## `ToolBroker` 管什么

在 `src/acabot/runtime/tool_broker/`。

它不是具体工具实现，而是工具编排中心。

主要职责:

- 注册工具
- 按 profile 过滤可见工具
- 作为统一 `tool_executor`
- 做最小 policy 检查
- 做审计
- 处理 approval
- 把工具副产物累计到 run 状态

### 这意味着什么

如果你要加一个新 tool，别直接让 agent 去碰底层基础设施。正常路径应该是:

`tool handler -> ToolBroker -> BaseAgent`

## tool 最好拿什么来举例

最贴近现在代码的例子，其实就是 NapCat API 封装成 tool。

现有 `NapCatToolsPlugin` 已经在做这件事，只是现在主要是查询类:

- `get_user_info`
- `get_group_info`
- `get_group_member_info`
- `get_group_member_list`
- `get_message`

你说的这类工具也很适合作为同一路数的扩展:

- `react_emoji`
- `group_ban`
- `recall_message`

它们本质上都是:

- 平台原生能力
- 参数边界清楚
- 适合封成一个明确 tool 给 bot 用

### 什么时候这类能力更适合 tool

如果你希望:

- bot 自己决定要不要调用
- 不同 bot / subagent 能选择是否携带
- 后面可能还要加审批

那就很适合 tool。

## `ModelAgentRuntime` 和 tool 的关系

`ModelAgentRuntime` 本身不做 policy 和审批。

它只负责:

- 向当前 run 解析可见 tools
- 调 `BaseAgent.run()`
- 把 agent 返回值标准化

所以:

- tool 可见性问题，看 `ToolBroker`
- 模型 tool 能力问题，看 `ModelAgentRuntime`
- 具体模型 tool loop 行为，看 `agent/`

## plugin manager 管什么

在 `src/acabot/runtime/plugin_manager.py`。

plugin 能做几类事:

- `setup / teardown`
- 注册 runtime hooks
- 注册 runtime tools
- 注册 subagent executor

主线 hook 点目前包括:

- `ON_EVENT`
- `PRE_AGENT`
- `POST_AGENT`
- `BEFORE_SEND`
- `ON_SENT`
- `ON_ERROR`

### 怎么判断该用 hook 还是直接改 pipeline

如果逻辑满足下面任意一条，优先考虑 hook:

- 只是给主线前后加一层逻辑
- 想开关式启用
- 不想把主线写死
- 跟某个插件能力强相关

## plugin 最好拿什么来举例

### 例子 1: 视频链接解析下载发送

这种能力更像 plugin，而不是 tool。

原因:

- 它通常不是让模型自己想“要不要调”
- 更像事件进来后，系统先做一段固定处理
- 有时甚至希望不经过 LLM，直接处理完就发

这种情况下，比较自然的接法是:

- plugin 注册 hook
- 在 `ON_EVENT` 或 `PRE_AGENT` 阶段识别链接
- 需要时直接构造动作
- 返回 `skip_agent`

也就是你说的“hook + skip_llm”这种感觉。放到当前代码语境里，更准确地说是 `hook + skip_agent`。

### 例子 2: 日报插件

这也更像 plugin。

原因:

- 它不是对某条用户消息的即时回应
- 更像定时任务或运维动作
- 它可能会查消息库、聚合数据，再调用全局 LLM 做总结，最后发群

这类能力通常是“借 AcaBot 的基础设施和模型能力”，但不走当前 bot 的一次普通对话主线。

## skill 和 subagent 到底像什么

你说“skill 和 subagent 都有点像工具”，这个判断是对的。

从使用体验上看，它们确实都像“bot 可以调用的一种能力”。区别在于承载方式不同。

## 先把 `skill` 这个词说清楚

这里的 `skill`，如果不先下定义，AI 很容易脑补错。

更接近准确说法的是:

skill 不是一个函数，也不是一个插件实例。

它更像一个可加载的“能力包”或“任务说明包”。

按 `skill creator` 那套定义去看，skill 的本质是:

- 一个自包含目录
- 里面至少有一个 `SKILL.md`
- `SKILL.md` 前面有 YAML metadata，最关键的是 `name` 和 `description`
- 还可以带 `references/`、`scripts/`、`assets/`

它解决的问题不是“直接执行某个动作”，而是:

- 给 agent 一套专门知识
- 给 agent 一套工作流程
- 给 agent 一些按需读取的参考资料
- 必要时再附带脚本和资源

如果用很人话的比喻:

- tool 更像一把扳手
- plugin 更像装在系统里的扩展部件
- skill 更像一份岗位 SOP 加工具箱说明书

## 在 AcaBot 里，skill 是怎么落地的

项目代码里已经有自己的 runtime skill package 实现，关键文件是:

- `src/acabot/runtime/skills/catalog.py`
- `src/acabot/runtime/skills/package.py`
- `src/acabot/runtime/skills/loader.py`

从这些文件看，AcaBot 里的 skill 现在更具体地是:

- 文件系统里的一组 skill package
- 每个 package 至少要有 `SKILL.md`
- runtime 会把它们读进 `SkillCatalog`
- profile 通过 `skills` 决定当前 agent 能看到哪些 skill

也就是说，在 AcaBot 这里:

- skill 先是“文档化的能力包”
- 然后才通过 catalog 和可见性接进运行时

这点和纯 tool 很不一样。tool 更像立即可执行的接口；skill 更像一份让 agent 学会怎么做事的包。

## 如果你真正想要的是“外部 agent 的 skill”

这个点要单独说清楚。

你想要的不是“AcaBot 自己发明一套 runtime 内部 skill 概念”，而是:

- 直接复用外部 agent 生态里那种 skill
- 目录结构就是外部 skill 的样子
- 里面有 `SKILL.md`
- 可能还带 `references/`、`scripts/`、`assets/`
- bot 能像外部 agent 一样去读和使用这些 skill

按这个标准看，AcaBot 现在其实已经做到了“一半”。

### 已经对上的部分

当前 skill package 的目录约定，已经和外部 agent skill 很接近:

- 必须有 `SKILL.md`
- `SKILL.md` 需要 frontmatter 里的 `name` 和 `description`
- 可选 `references/`
- 可选 `scripts/`
- 可选 `assets/`

也就是说，从文件结构上看，AcaBot 现在其实已经能读一类“外部风格”的 skill 目录。

### 还没完全对上的部分

现在 runtime 里真正暴露给 bot 的能力，主要还是这个:

- `skill(name=...)`

它当前做的事情比较克制:

- 检查这个 skill 有没有分配给当前 profile
- 读取这个 skill 的 `SKILL.md`
- 把整份 markdown 原样返回给模型

这意味着现在还没有完全做到外部 agent 那种使用体验。

还差的点主要有这些:

- 还没有真正做“渐进加载”
  现在主要是把 `SKILL.md` 整份给模型，不是像外部 agent 那样先靠 metadata 触发，再按需读取 references。
- 还没有把 `references/` 变成标准读取流程
  目录能识别，但 runtime 还没形成“模型先读 skill，再按需读 references”的正式工具链。
- 还没有把 `scripts/` 变成 skill 的自然执行面
  目录能识别，但 skill 本身不会像外部 agent 那样天然把脚本工作流接进来。
- 还没有真正的“skill 触发器”
  现在更像 profile 先分配 skill，模型再手动调用 `skill(name=...)` 去读；不是外部 agent 那种基于 metadata / 请求语义自动触发。

所以最准确的说法是:

AcaBot 现在已经有了“外部 skill package 的文件系统兼容层”，但还没有完全做出“外部 agent skill 的运行时体验层”。

## 外部 agent 的 skill 和 AcaBot runtime 的 skill，要分开看

这两个概念很像，但不完全一样。

### 外部 agent 视角

比如 Codex / Claude 这类系统里的 skill，重点是:

- 触发条件
- SKILL.md 指令
- references / scripts / assets

本质上是“给 agent 的专门 onboarding”。

### AcaBot runtime 视角

AcaBot 里也是 skill package，但现在已经收口成更单纯的一层:

- `SkillCatalog`
- `skills`
- skill 摘要进入 prompt
- 模型按需读取 skill 内容

也就是:

- skill 负责表达能力包和使用说明
- subagent 负责独立执行

所以在这个项目里，skill 不再承担委派配置，而是“可被配置为可见能力包的说明和资源集合”。

## 如果以后真要做“直接使用外部 skill”

比较合理的方向不是重写 skill 格式，而是继续沿着现在这条线补运行时行为。

更实际的演进路径可能是:

1. 继续沿用外部风格目录
   - `SKILL.md`
   - `references/`
   - `scripts/`
   - `assets/`
2. 让 bot 不只是能读 `SKILL.md`
   还要能按需读取 `references/` 里的具体文件
3. 给 skill 增加更像外部 agent 的使用流程
   例如“先读 skill 本体，再按 skill 说明读取 references，再决定要不要执行脚本”
4. 再把 visible path 收口成稳定的 `/skills/...`

如果按这个方向走，那 AcaBot 的 skill 更像:

- 直接兼容外部 agent skill 的文件格式
- 再在 runtime 上补一层可见性和读取流程控制

这其实比完全发明新格式更对路。

### skill 更像什么

更像一份能力包或操作手册。

它会:

- 直接内联给当前 agent 用
- 通过可见性规则决定谁能看到它

所以它有时候看起来像 tool，有时候又更像“让模型学会一套做事方式”。

`opencode` 那种“把 skill 当工具用”的感觉，和 AcaBot 这里并不冲突。

一个更贴切的理解是:

- tool 是“你现在就可以调用的接口”
- skill 是“你应该怎么做这件事的一整套说明和资源”

如果某件事除了调用接口之外，还需要:

- 按固定步骤做
- 查参考资料
- 用一组脚本
- 遵守特定约束

那它往往更像 skill，不只是 tool。

### subagent 更像什么

更像一个专门干某类脏活的 worker。

它不是一个小接口，而是:

- 有自己的 profile
- 有自己的 model
- 有自己的 tools
- 有自己的 skills
- 可以被主 bot 委派出去跑一段独立任务

这和你说的设想是一致的: 占上下文、步骤长、主 bot 不想自己扛的活，扔给 subagent 做，最后只把结果拿回来。

## skill 和 subagent 是什么关系

从 runtime 的视角看:

- skill 是能力目录
- subagent 是可被委派执行的 agent

一个 agent 的 profile 里现在只声明 `skills`，也就是它能看到哪些 skill package。

subagent delegation 是另一条独立链:

- runtime 注册哪些 subagent executor
- 当前 agent 是否能看到 `delegate_subagent`
- `delegate_subagent` 直接按 `delegate_agent_id` 委派

两者不再通过 skill 配置互相绑定。

## bot 和 subagent 身上各自带什么

这个点也值得写明白，不然 AI 容易误会“系统里有的能力所有 agent 都自动有”。

更接近当前系统的理解是:

- 主 bot 可以选择自己暴露哪些 `tools`
- 主 bot 可以选择自己携带哪些 `skills`
- 主 bot 也可以看到并调用哪些 `subagents`
- subagent 自己也有独立的 `tools / skills / model / prompt`

也就是说:

- 能力不是全局自动共享的
- profile 才是“这个 agent 当前能看到什么能力”的关键配置点

这也是为什么 WebUI 里会把 bot 和 subagent 分开配。

## 什么时候该做成 subagent

适合:

- 任务边界明显
- 需要不同 prompt / model / tools
- 希望主 agent 委派出去

更具体一点，适合这种活:

- 上下文特别长
- 中间步骤很多
- 需要自己查资料、整理、归纳
- 主 bot 只想拿最终结论，不想把全过程都塞在自己上下文里

不适合:

- 只是一个很小的辅助函数
- 本质上是协议层或主线基础能力

## 一个更实用的速记

### tool

一个明确接口，bot 直接调用。

例子:

- 查 QQ 群成员
- QQ 禁言
- 发 reaction emoji

### plugin

系统级扩展，往主线某个阶段插。

例子:

- 视频链接自动解析并发送
- 日报汇总并定时发送

### skill

一套能力说明或工作流，可以内联，也可以委派。

例子:

- “写日报”这套流程说明
- “整理群聊重点并提炼决策”这套工作方法

### subagent

一个独立 worker，拿自己的上下文和能力单独干活。

例子:

- 专门负责长文本整理的 worker
- 专门负责资料检索和总结的 worker
- 专门负责复杂运营报表的 worker

## 当前已知风险 / 缺口

这部分不是架构理想图，而是当前实现里已经看得到的问题和缺口。

### 1. direct subagent delegation 现在已经独立于 skill

当前 `delegate_subagent` 直接传 `delegate_agent_id`。

这条路径现在的关键点不是 skill policy，而是:

- 当前 profile 是否真的可见这个 subagent
- tool broker 是否应该暴露 `delegate_subagent`
- subagent executor registry 里是否真的注册了这个 agent

所以如果以后你要继续修 subagent 可见性或能力隔离，这里要看的是 subagent 自己的可见性规则，不是 skill 配置。

### 2. skill 现在更像“可读能力包”，下一步是把读取路径做完整

当前 `skill(name=...)` 主要还是读 `SKILL.md`。

目录层面已经兼容外部 skill 风格，但运行时体验还缺这些:

- `references/` 的正式按需读取流程
- `scripts/` 的自然执行面
- 更稳定的 `/skills/...` visible path

所以如果以后 AcaBot 真正要把方案 A 做完整，这一段还要继续补。

## 如果改这里，通常同步哪些文档

- `06-tools-plugins-and-subagents.md`
- `02-runtime-mainline.md`
- 如果影响典型接入方式，再看 `10-change-playbooks.md`

## 图片转述 / VLM 这种需求适合接在哪

先别急着选。

通常有三种落法:

### 方案 A: 主线预处理

优点:

- 每次有图片都稳定执行

缺点:

- 主线更重
- 容易把所有消息都拖慢

### 方案 B: tool

优点:

- 模型按需调用
- 容易做审批和能力隔离

缺点:

- 模型必须知道何时调用
- 首轮自动体验不一定稳定

### 方案 C: plugin + hook

优点:

- 可以在 `PRE_AGENT` 或更早阶段自动注入结果

缺点:

- 需要比较清楚地控制副作用和开关

在 AcaBot 里，这类需求大概率不会只落一层。常见组合是:

- Gateway / Event 层补齐附件信息
- computer 层做本地 staging
- plugin 或 tool 层做 VLM 调用
- pipeline / retrieval 层决定怎么把结果注入 prompt

### 当前项目已经落地的版本

图片理解现在不是 plugin/tool 主导，而是 runtime core service:

- `computer` 负责 staging
- `ImageContextService` 负责 caption、reply 图片重解析、vision 注入
- `pipeline` 负责把 caption 写进 working memory，并在当前轮按需追加 image parts

也就是说，这块现在已经偏“主线预处理 + computer 基础设施”的组合。

## 当前已经存在的 plugin 方向

看 `src/acabot/runtime/plugins/` 可以大概知道已有思路:

- `computer_tool_adapter`
- `skill_tool`
- `subagent_delegation`
- `sticky_notes`
- `napcat_tools`
- `reference_tools`
- `ops_control`

这说明项目已经倾向于把“能力暴露给模型”的事情做成 plugin / tool，而不是继续把主线塞胖。

## 常见误区

### 1. 把 plugin 当成业务垃圾桶

plugin 适合扩展点，不适合把一堆难以归类的主线逻辑全扔进去。

### 2. 工具直接读写全局状态

最好还是通过 broker、runtime context 或明确的 store/service 接口接入。

### 3. 让 agent 直接知道太多底层细节

`BaseAgent` 最好只关心:

- prompt
- messages
- model
- tools
- tool executor

更底层的执行和权限，不该压到 agent 自己身上。

## 选型速记

### 要不要做成 tool

问自己一句:

“这能力是不是应该由模型决定何时调用？”

如果是，优先 tool。

### 要不要做成 plugin

再问一句:

“这能力是不是一种横切扩展，或者想在主线固定阶段插入？”

如果是，优先 plugin。

### 什么时候直接改 runtime 主线

只有当答案是:

“不管模型怎么想，这步都必须发生。”

## 读源码顺序建议

1. `src/acabot/runtime/tool_broker/`
2. `src/acabot/runtime/model/model_agent_runtime.py`
3. `src/acabot/runtime/plugin_manager.py`
4. `src/acabot/runtime/plugins/`
5. `src/acabot/runtime/subagents/contracts.py`
6. `src/acabot/runtime/subagents/broker.py`
7. `src/acabot/runtime/subagents/execution.py`
cabot/runtime/subagents/broker.py`
7. `src/acabot/runtime/subagents/execution.py`
