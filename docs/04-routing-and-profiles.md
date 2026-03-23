# 路由、Profile 和配置装配

这一篇回答四个问题:

1. 一条消息为什么会落到这个 thread
2. 这条消息为什么会回复 / 只记录 / 直接丢弃
3. 当前 run 为什么会拿到这个 profile
4. profile、prompt 和 session config 是从哪里来的

## 设计理念

### 1. 现在不再把“消息怎么处理”拆成很多平行 rule

以前那种思路，更像是把不同问题分别塞进几套长得很像的规则里。看起来好像很灵活，但会有一个很大的问题：

- 一条消息为什么到了这个 agent
- 为什么这条消息会回复
- 为什么这条消息只记录不回复
- 为什么这条消息会进长期记忆
- 为什么这次 computer 是 host 或 docker

这些问题虽然都像“规则”，但它们其实不是同一种问题。

如果把它们都塞进很多平行 rule 里，最后就会变成：

- 匹配条件长得很像
- 决策阶段却完全不同
- 维护的人要在脑子里把几套东西重新拼起来

所以现在改成另一种思路：

> 先把消息收成稳定事实，再按会话配置里的不同决策域，分别回答不同问题。

这样每个问题都有自己的位置，不再混成一团。

### 2. 产品入口为什么是 SessionConfig

对一个 bot 来说，最自然的产品单位其实不是“全局规则”，而是：

- 这个私聊怎么处理
- 这个群怎么处理
- 这个会话默认用哪个 profile
- 这个会话里 mention bot 和普通群聊是不是同一种行为

也就是说，人真正会稳定地思考的对象，本来就是“一个会话”。

所以现在的主入口改成 `SessionConfig`，因为它更贴近真实产品形态。

你可以把它理解成：

- profile 负责描述“这个 agent 是谁”
- session config 负责描述“这个会话里的消息默认怎么跑”

这样配置视角就和 bot 产品视角对上了。看一个群的行为时，也有一个明确的落点，不需要在很多全局 rule 里来回翻。

### 3. 为什么先有 Facts，再有决策

系统先做的是：

> 把消息变成事实对象。

例如：

- 这是群消息还是私聊
- 有没有 @bot
- 是不是在回复 bot
- 有没有附件
- 发送者是什么角色
- 当前 actor_id / channel_scope / thread_id 是什么

这些都属于“发生了什么”。

然后才进入下一层：

> 系统应该怎么处理这条消息。

例如：

- 交给哪个 profile
- 要不要 回复/记录/进长期记忆
- computer 的 host/docker/remote, workspace...

把这两层拆开以后，最大的好处是：

- debug 更容易
- 测试更容易
- 文档更容易写清楚
- 后面新增决策域时，不用重新发明一套消息匹配方式

一句话说，就是把“输入是什么”和“系统怎么反应”彻底分开。

### 4. 为什么中间还要先做 surface 解析

就算已经有了事实对象，也还不能直接开始算所有决策。

因为同一个会话里本来就可能有很多种不同的“消息面”：

- @bot
- 群里引用 bot
- 普通群聊路过消息
- 命令消息
- notice

这些场景不该被压成一个大开关。

所以现在会先做一步 `surface resolution`，把当前消息放到某个明确的 surface 上。

这样会带来两个好处：

1. 产品表达更自然
   - 维护者会直接想“群里 @bot 的消息怎么处理”，而不是想一串布尔条件
2. 后续决策更干净
   - 先选中一个 surface，再在这个 surface 下面分别算 routing / admission / persistence / extraction / computer

也就是说，surface 这层不是多余中间层，而是把“人类理解的消息类型”和“runtime 真正要算的决策”接起来的那一层。

### 5. 为什么还要拆成不同决策域

消息进入系统后，不是只回答一个问题，而是要连续回答很多不同问题。

当前主线里至少有这些：

- `routing`: 交给谁
- `admission`: 回不回复, 还是只记录, 还是直接丢掉
- `persistence`: 这条 event 要不要持久化
- `extraction`: 这条消息要不要参与长期记忆提取
- `context`: 当前轮上下文怎么补
- `computer`: 这次 computer / world 怎么配

这些问题如果混在一个大块配置里，会越来越乱。

所以现在的做法是：

> 同一个 surface 下，按不同决策域分别算结果。

这样每一层都只回答一种问题。

最大好处是边界清楚。比如你只想改“这条消息要不要回复”，那你应该碰的是 `admission`，而不是顺手改 routing 或 memory。

### 6. profile、router、session runtime 现在各管什么

这几个名字最容易被混。

#### `SessionRuntime`

它是这条设计的中心。它负责：

- 把事件收成 `EventFacts`
- 定位 session
- 解析 surface
- 算出不同决策域的结果

也就是说，它回答的是：

> 这条消息在当前会话里，应该怎样被解释。

#### `RuntimeRouter`

它不是新的规则中心。

它更像是一个装配层，负责：

- 生成稳定 ID
- 把 session runtime 算好的结果收成 `RouteDecision`
- 把后面 runtime 真正要用的信息接起来

也就是说，它回答的是：

> 把这些决策整理成运行时真正能执行的路由结果。

#### `ProfileLoader`

它只负责 profile 和 prompt 的读取，不再兼任消息决策中心。

profile 现在更像“agent 身份卡”，里面放的是：

- prompt_ref
- default_model
- enabled_tools
- skills
- computer policy 默认值

它回答的是：

> 这个 agent 是谁，它自带什么默认能力。

而不是：

> 这条消息为什么 respond / record_only / silent_drop。

### 7. 一句最该记住的话

如果你只想记住一句话，可以记这个：

> **SessionConfig 决定这条消息在当前会话里怎么跑，Profile 决定被选中的 agent 是谁、默认带什么能力，RuntimeRouter 负责把这些结果收成 runtime 真正要执行的对象。**

先抓住这句话，再去看后面的对象和文件，理解会轻松很多。

## 先看现在真正的主线

现在这条线已经收成:

`StandardEvent -> SessionRuntime -> RuntimeRouter -> RouteDecision -> ProfileLoader / PromptLoader`

这里最关键的变化是:

- 路由不再靠一堆旧 rule 文件拼出来
- 现在真正决定这条消息怎么处理的是 **SessionConfig + SessionRuntime**
- `RuntimeRouter` 负责把这些决策收成 runtime 真正要用的 `RouteDecision`

## `SessionRuntime` 现在做什么

关键文件:

- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/control/session_loader.py`
- `src/acabot/runtime/contracts/session_config.py`

它现在主要做这几件事:

1. 把 `StandardEvent` 变成稳定的 `EventFacts`
2. 定位当前消息对应的 session
3. 解析当前消息命中的 surface
4. 从 session 的各个决策域里算出:
   - routing
   - admission
   - persistence
   - extraction
   - context
   - computer

也就是说, 现在真正回答“这条消息怎么跑”的, 是 session config 里的这些决策块, 不是旧的 `binding / inbound / event policy` 三套东西。

## `RuntimeRouter` 现在做什么

关键文件:

- `src/acabot/runtime/router.py`

它负责两层事:

### 1. 先算稳定 ID

现在默认还是这组:

- `actor_id`
- `channel_scope`
- `thread_id`

当前默认规则很直接:

- 私聊: `qq:user:{user_id}`
- 群聊: `qq:group:{group_id}`
- `thread_id` 默认直接等于 `channel_scope`

### 2. 再把 session 决策收成 `RouteDecision`

`RouteDecision` 现在主要会带这些东西:

- 当前 thread / actor / channel scope
- 当前 run 用哪个 agent profile
- 当前 run 的 `run_mode`
- 路由原因和来源信息

所以如果你想改“这条消息该去哪”“该不该进完整主线”, 现在优先看的是:

- `session_runtime.py`
- `router.py`

不是旧的 rule loader。

## 现在的 `run_mode` 从哪里来

`run_mode` 现在来自 session config 里的 **admission** 决策。

最终还是这三个值:

- `respond`
- `record_only`
- `silent_drop`

它们的意思没有变:

- `respond`: 走完整主线, 可以调模型, 也可以发回复
- `record_only`: 只记录事实和上下文, 不发回复
- `silent_drop`: 提前退出, 不进入后面的完整处理

但决定它们的来源已经变了。现在不是旧 inbound rule, 而是 session surface 里的 admission 决策。

## profile 现在怎么装配

关键文件:

- `src/acabot/runtime/control/profile_loader.py`
- `src/acabot/runtime/control/config_control_plane.py`

profile 现在只负责这些事:

- agent_id
- name
- prompt_ref
- default_model
- enabled_tools
- skills
- computer policy

### profile 的两个来源

#### 1. inline 配置

来自:

- `runtime.profiles`
- 或 runtime / agent 默认配置

#### 2. 文件系统 profile

如果开了 `runtime.filesystem.enabled = true`, 会从运行时目录继续加载:

- `profiles/`
- `prompts/`

现在 profile loader 这层已经不再承载旧 binding routing 语义了。它就是 profile / prompt 的读取层。

## prompt 现在怎么解析

关键文件:

- `src/acabot/runtime/control/profile_loader.py`

`prompt_ref` 最后由 `PromptLoader` 解析。

现在支持:

- 内存静态 prompt
- 文件系统 prompt
- chained fallback

所以如果你改 prompt 相关功能，要先确认你改的是哪一层:

- profile 里对 prompt 的引用
- prompt 文件本体
- loader 的回退顺序

## session config 现在从哪里来

关键文件:

- `src/acabot/runtime/control/session_loader.py`
- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/control/config_control_plane.py`

现在有两种常见来源:

### 1. config 里直接提供

适合简单场景, 直接跟着主配置一起走。

### 2. 文件系统 session 目录

如果 `runtime.filesystem.sessions_dir` 存在, `SessionRuntime` 会从这个目录按 `channel_scope` 读取 session config。

这条线现在才是“消息怎么决策”的主入口。

## WebUI 和热刷新现在怎么接

现在路径还是:

`WebUI -> HTTP API -> RuntimeControlPlane -> RuntimeConfigControlPlane -> 配置真源 / reload`

但要注意现在真正还能改、还能热刷新的内容已经收窄了。

当前 `RuntimeConfigControlPlane` 主要处理:

- profiles
- prompts
- gateway
- runtime plugins
- session-config 驱动的 reload

如果你还在找旧的 binding / inbound / event policy CRUD, 那已经不是现行主线了。

## 现在改动时该优先看哪里

### 想改“谁处理这条消息”

先看:

- `session_runtime.py` 里的 routing
- `router.py`
- session config 里的 `routing`

### 想改“这条消息回不回复”

先看:

- `session_runtime.py` 里的 admission
- session config 里的 `admission`

### 想改“这条消息记不记事件 / 记不记长期记忆”

先看:

- `session_runtime.py` 里的 persistence / extraction
- session config 里的 `persistence` 和 `extraction`

### 想改“这个 agent 默认用什么模型、prompt、tools、skills”

先看:

- `profile_loader.py`
- `config_control_plane.py`
- 对应的 profile / prompt 文件

## 常见误区

### 1. 在 pipeline 里重新判断 agent

不对。agent 和 run_mode 应该尽量在 session 决策阶段就算清楚。

### 2. 还把旧 rule 文件当成当前真源

现在真正生效的是 session config 决策和 profile / prompt 装配。

### 3. 改 profile 但忘了 filesystem 模式

如果 runtime 开了 filesystem, 很多值不是从主 YAML 里直接读的。你只改 inline 配置, 线上不一定生效。

## 读源码顺序建议

1. `src/acabot/runtime/control/session_runtime.py`
2. `src/acabot/runtime/router.py`
3. `src/acabot/runtime/control/session_loader.py`
4. `src/acabot/runtime/control/profile_loader.py`
5. `src/acabot/runtime/control/config_control_plane.py`
6. `src/acabot/runtime/bootstrap/`
