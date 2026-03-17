# 前后台双 Agent 与自我进化

这一篇不是功能说明，也不是改动手册。它讲的是一个产品方向：如果 AcaBot 的主责还是在群里和人聊天，那它怎样同时拥有“给自己升级、给自己加功能”的能力，而且不把聊天主线搞坏。

## 先讲结论

不要让前台聊天 Aca 直接改自己。更稳的做法，是把系统里的长期角色拆清楚：前台 Aca 只负责对外聊天、维持公开人格和理解群聊语义；前台自己的 subagent 仍然只是受限 sandbox 里的局部 worker；后台 Aca / maintainer 则是另一个长期存在的维护人格，而且这个后台不再只是“复用一下 pi 的执行能力”，而是直接由一个注入了 Aca maintainer 人格设定的长期 `pi` session 来承载。

所以这里的结构不是“前台聊天 bot 再随手调一个维护工具”，而是“前台人格 + 后台人格 + 产品壳”。前台是默认入口；后台是维护入口；AcaBot 本体负责的是前后台的入口治理、模式切换、消息桥接、canonical session 绑定以及状态和产物的对外投影。

| 角色 | 默认入口 | 默认可见空间 | 主要职责 |
| --- | --- | --- | --- |
| 前台 Aca | 群聊、普通私聊 | `/self`、`/workspace` | 聊天、理解语义、维持公开人格、决定是否需要找后台 |
| 前台 subagent | 前台委派的局部任务 | 自己的 sandbox，比如 `/subagent/<id>/` | 受限执行、长一点但局部的工作、把结果回给前台 |
| 后台 Aca / maintainer | 管理员显式维护入口、前台桥接入口 | AcaBot 仓库根目录，外加 `.acabot-runtime/` | 改代码、改配置、补文档、跑测试、准备 reload / publish |

这里最重要的边界不是“谁更聪明”，而是“谁真正拥有维护主权”。前台不维护自己；subagent 不维护整个系统；后台 maintainer 才真正负责配置、代码、文档、测试和运行时维护。

## 为什么前台不能直接改自己

因为前台 Aca 的第一职责不是维护系统，而是保持对话稳定。它处在高频、多人打断、高噪音的群聊环境里，最重要的是持续回应、维持公开人格和 thread 上下文。如果让前台一边接消息，一边直接去动 runtime 主线、router、prompt 组装、memory 注入规则、配置真源和 reload 路径，那最容易发生的不是“它变得更强”，而是聊天体验和修复能力一起坏掉。

所以“自我进化”不应该是前台聊天闭环，而应该是后台维护闭环。前台负责识别维护意图、把请求交给后台、再把结果讲给用户；后台负责真正的维护执行、验证和回写。前台是公开入口，不是运维入口；后台才是维护入口。

## 后台就是 pi，但不是裸 pi

这里的后台不是“AcaBot 里再造一套完整后台 agent，然后它再调用 pi”。更干净的收法是：后台人格直接就是一个长期存在的 `pi` session。只是这个 `pi` 不是裸跑的，而是一个注入了 Aca maintainer 人格设定、权限边界、目录边界和行为规则的后台 Aca。

物理上，后台 `pi` 直接运行在 AcaBot 仓库根目录，把 repo 根作为自己的工作目录；同时它也能看到宿主根下的运行时目录，比如 `.acabot-runtime/`。但逻辑上，这不等于前台和 subagent 也都能看到同一块空间。前台和 subagent 仍然只看到各自映射出的可见根，而后台才拥有完整工程视图。

这也意味着，后台人格的 runtime 虽然是 `pi`，但后台人格的会话身份不应该由 `pi` 自己临时决定，而应该由 AcaBot 维护一份 canonical binding。也就是说，AcaBot 需要明确知道“当前后台 Aca 绑定到哪个 `pi` session`”，并把这份绑定保存在自己的 registry 里，比如 `.acabot-runtime/backend/session.json` 这类位置。这样系统启动、恢复、重连和健康检查时，判断的不是“现在碰巧连上了哪个 `pi` session`”，而是“后台 Aca 这个逻辑身份当前绑定的是哪一个 canonical backend session”。

raw `pi` 的 session 管理命令也不应该默认暴露给后台模式。比如管理员在后台模式里输入 `/new`，不应该直接悄悄把后台 canonical session 改掉。如果以后真的需要重置后台上下文、轮换后台 session，也应该走 AcaBot 自己的后台控制命令，而不是直接把 `pi` 的原生命令透给管理员。

当前实现已经按这个边界落地了一部分：backend canonical session binding 现在由 AcaBot 维护在 `.acabot-runtime/backend/session.json`；configured backend session service 会显式拒绝 `/new`、`/resume`、`/fork`、`/tree`、`/compact`、`/settings`、`/model` 这类 raw `pi` session 命令进入 canonical backend 面；同时 binding 里已经保存 `session_file`，用于重启后恢复同一个 canonical `pi` session。

## 前台、subagent 和后台各自负责什么

前台 Aca 处理的是公开交互里的主链：识别谁在和自己说话、理解对方是在普通聊天，还是在提一个应该找后台的请求、维持当前 thread 的短期上下文、给出即时回应、把后台结果讲回人类能理解的形式。它可以决定“要不要找后台”，但不直接改配置、不直接改 repo、不直接运行维护链路。

前台 subagent 处理的是前台已经明确切分好的局部任务，比如长一点的检索、整理、分析，或者在自己的 sandbox 里干一段受限工作。它仍然是前台内部的 worker，不应该接管整个系统，更不应该天然看到整个 repo、配置真源和维护控制面。

后台 maintainer 处理的才是系统级事务：读取仓库、查看 `docs/`、读取和修改配置真源、查看运行时状态、运行测试、生成 patch 和说明、执行 reload / update / publish 相关动作。后台可以直接与管理员通信，但只有在显式维护入口下才会这么做。

## 进入后台只有两条路

后台不是默认入口，进入后台只有两条路。

第一条是前台桥接。普通用户仍然只和前台说话。前台判断某条消息不是普通聊天，而是一个值得找后台处理的问题，于是把这个请求发给后台。对普通用户来说，他看到的仍然是前台 Aca，只是前台在背后把事交给了后台处理。

第二条是管理员显式进入后台。这里必须是显式入口，不能含糊。约定可以是：`!` 开头表示单条透传给后台；`/maintain` 表示开启后台模式，而且只允许管理员私聊开启；`/maintain off` 表示退出后台模式。也就是说，群里默认永远还是前台人格；后台直连只属于管理员的维护场景。

这两条路的目标其实一样：最终都是在和同一个后台 Aca，也就是同一个后台 `pi` session 通信。差别只在于，前者是前台代为桥接，后者是管理员显式直连。

## 普通用户并不直接和后台交互

这里有一个很重要的边界：普通用户和后台没有直接交互关系。只有两种主体能和后台交互：管理员，或者前台。管理员通过显式维护入口直接和后台说话；前台则在内部把一条消息转成后台请求。普通用户即使在群里说了“你去改个配置”“你给自己加个功能”，也不等于后台一定会收到；前台完全可以不理会、拒绝、延后，或者选择主动向后台发起请求。

因此，对普通用户来源的后台请求，后台不应该看到整段前台对话历史，也不应该把自己理解成正在“和这个普通用户聊天”。后台收到的应该是前台布置的一张工单：一段足够清楚的任务摘要，加上最小来源引用。后台如果需要进一步回看原始上下文，也应该通过来源引用去查日志或事件，而不是要求前台把整段聊天历史灌进来。

## 前后台如何通信

前台不维护自己，前台只和后台交互。更准确地说，前台和后台的通信，本质上就是把消息发给后台 `pi`。前台不应该直接拿到 `edit_config`、`reload_plugin`、`read_repo` 这类后台能力；更合理的形态，是前台只知道自己能向后台发请求，而后台收到后再决定怎么处理。

按现在更收紧的边界，前台发给后台的请求只保留两类：`query` 和 `change`。`query` 是问后台当前状态、当前配置、生效结果；`change` 是请求后台做明确的小变更，比如改某个配置。前台不负责创建“后台 task”这一类更重的结构，因为后台本身已经是管理员的长期维护面；真正需要复杂维护、长协作、危险自我迭代的时候，更适合由管理员直接进入后台模式和后台协作，而不是让普通用户间接驱动后台重维护链路。

这里还有一个细边界：前台允许发哪些 `change`，不一定需要在外层 runtime 里死写成一长串规则。更适合的做法，是在后台 Aca 的 maintainer persona 里明确写清：前台被允许请求哪些 change、哪些 change 已经超出前台权限、超界时应该如何拒绝并要求管理员通过显式后台入口处理。外层系统只保留大的硬边界，比如普通用户不能直接进后台、前台不创建后台重维护会话；具体 `change` 的范围主要由后台 persona 自己判断。

## 后台为什么只保留一个全局长期 session

如果后台是多个 session，很快就会遇到并发问题：多个群同时和前台交互，前台又把多个请求送进后台，不同后台 session 可能同时修改同一个文件、同一份配置、同一个 repo 状态，最后导致 patch 冲突、reload 语义混乱、配置真源不一致。这个问题不是细枝末节，而是结构性问题。

所以后台更合理的形态，不是每个任务一个新的 `pi` session，也不是每个前台会话对应一个后台 session，而是整个 bot 只有一个全局长期存在的后台 `pi` session。这个 session 自己承担后台人格的连续性、上下文积累和压缩。它就是系统里唯一的维护脑。

这意味着：前台桥接请求、管理员单条透传、管理员后台模式，本质上都在和同一个后台会话通信。这样后台对 repo、配置和运行时的理解才是一致的，维护上下文也才能持续积累。

## query 和 change 应该怎么跑

`query` 和 `change` 不应该走同一条执行路径。`query` 更适合从 canonical backend session fork 一个临时只读 session，在这个 fork 里附加“本次只用于查询、不做修改”的提示词，执行完就销毁，也不回写主后台 session。这样 query 不会把主后台维护脑塞满，也不会把很多轻量查询噪音积累到主上下文里。

当前实现里, 这条分流已经有真实运行路径：`change` 直接进入 configured backend session service 的 canonical `pi` session 主线；`query` 则通过 `PiBackendAdapter` 调 `get_fork_messages` + `fork`，在真实 `pi --mode rpc` 上走 fork 路径。当前 query 还不是最终最严格的“稳定切点 fork”完整版，但已经不是假壳。

这里还有一个容易忽略的细节：query fork 不应该从后台当前正在执行的瞬时态去分叉，而应该从 canonical backend session 的最近稳定切点去分叉。更具体地说，这个稳定切点可以理解成“上一条已完成用户消息之后的后台状态”。也就是说，不从当前正在生成中的 assistant message、未完成的 tool loop 或 mutation 中间态上 fork，而是从最近一个稳定 turn 结束后的状态 fork。这样 query 得到的上下文才干净，不会被后台正在做到一半的修改过程污染。

`change` 则不同。它会真正影响系统状态，所以应该直接进入 canonical backend session 主线。对前台来说，这类 `change` 默认可以保持同步：它会阻塞这一次请求本身，但不意味着整个群聊 thread 或整个群的后续消息都被卡死。这样第一版反而更简单。

这里的关键不是靠某种完美的硬权限去“管住 pi”，而是通过执行分流把请求放到不同路径：query 走只读 fork，change 走主后台 session。query fork 只用于读现成状态，不回写主后台 session；change 则直接在主后台会话里完成。这已经足以把后台结构收得很清楚。

## 后台执行不下去时怎么办

后台不是每次都能一口气把事情做完。尤其是 change，有时它会卡在需要澄清、需要授权、或者前台摘要不足的地方。这时更稳的做法，不是给后台一个模糊的“随便联系谁”能力，而是提供几种结构化出口。

如果管理员已经通过 `!` 或 `/maintain` 显式进入后台，那后台其实可以直接在当前后台会话里向管理员发问，不需要再额外绕一层。比如：需要确认某个高风险改动、需要在两个方案之间二选一、需要管理员补一段明确输入。这类情况更像后台和管理员的直接协作。

如果后台处理的是前台转来的请求，情况就不同了。这里默认不应该直接越过前台去找普通用户，更合理的顺序应该是：后台先把问题退回前台，让前台决定要不要继续问用户、要不要自己补摘要，或者是否根本不值得继续。只有在确实需要管理员裁决的情况下，后台才应该升级成找管理员。

所以这里更适合的是结构化的交互出口，而不是一个泛化的 `contact_admin`。例如：`request_admin_input` 用于向管理员补充信息，`request_admin_approval` 用于请求高风险动作审批，`return_to_frontstage` 用于把一个前台布置来的工单退回前台继续澄清。这样后台的交互状态也更容易落到后续的记录、WebUI 和审计里。

## 空间也应该分层

如果把前台、subagent 和后台角色分开，文件空间也必须一起分开。这里最容易混淆的是“物理宿主根”和“角色可见根”。第一阶段完全可以让这些东西都物理上归在 AcaBot 根目录下面，但不同角色看到的根绝对不能一样。

更稳的物理布局，是把源码和运行时空间分开。AcaBot 仓库根目录继续放 `src/`、`docs/`、`tests/`、配置真源等工程文件；同时在仓库根下单独放一个隐藏运行时目录，比如 `.acabot-runtime/`。这个目录下面可以再放 `self/`、前台 workspace、subagent sandbox、后台任务和产物等运行时数据。这样工程主场和运行时空间不会平铺在一起。

在这个布局下，前台看到的逻辑根仍然只是 `/self` 和 `/workspace`。它们物理上可以分别映射到 `.acabot-runtime/self/` 和 `.acabot-runtime/front-workspaces/<thread-or-channel>/`，但前台工具和上下文只应该暴露这两块，而不是整个 repo。`/self` 是 Aca 自己的人格和自我状态区，放 identity、soul、state、自我日志、自我记忆以及公开人格相关的长期材料；`/workspace` 是前台聊天工作区，用来放当前会话资料、附件和图片落地结果、临时草稿以及普通聊天时需要的文件操作。

前台 subagent 也不应该看到整个宿主根。它更适合只看到自己的 sandbox，比如逻辑上的 `/subagent/<id>/`，物理上映射到 `.acabot-runtime/subagents/<id>/` 或更严格的容器挂载目录。subagent 在里面做自己的局部任务，不应该默认直通整个 repo、配置真源和全局控制面。

后台 maintainer 则不同。后台 `pi` 直接运行在 AcaBot 仓库根目录，把 repo 根作为工作目录，因此它天然能看到 `src/`、`docs/`、`tests/`、配置真源等工程内容；同时它也能看到仓库根下的 `.acabot-runtime/`，包括 `/self`、后台记录、产物和必要的运行时状态。也就是说：物理上可以都在 AcaBot 根目录下面管理，但逻辑上绝不是共享同一个可见根。后台看整个工程和运行时；前台只看 `/self + /workspace`；subagent 只看自己的 sandbox。

## 记忆也应该分层

如果以后真的想让 AcaBot 有比较稳定的“我”，记忆层就不能继续只按 thread 去想。至少应该区分五层：self memory / soul memory、relationship memory、channel memory、thread working memory、event / message facts。self memory 负责回答“我是谁、我的长期职责是什么、我的边界和风格是什么、我最近在全局范围内做过什么、我有哪些持续中的承诺和任务”；relationship memory 负责 Aca 和某个用户之间的长期关系；channel memory 负责某个群或某个频道自己的共同背景和长期约束；thread working memory 负责最近几轮对话的短期上下文；event / message facts 负责平台上真实发生过什么和实际发送过什么。前者是人格连续性，后者是客观事实层，这两种东西不能混在一起。

这一阶段不必把 self memory 全做出来，但应该提前留好位置。因为前台人格和后台人格虽然职责不同，仍然属于同一个 Aca，它们至少要共享同一套更深层的 self 空间，而不是彻底互不相认。

## 如果按这个方向落地，AcaBot 里需要哪些模块

如果按这里的设计去实现，重点不再是“再造一个后台 agent runtime”，而是“怎样把一个长期后台 `pi` session 稳稳接进 AcaBot”。更适合的做法，是在 `src/acabot/runtime/` 下新增一个明确的 `backend/` 子域，专门承接后台模式、后台桥接、后台 session、后台 operation 和产物投影。

建议的结构大概会是这样：

```text
src/acabot/runtime/
  backend/
    __init__.py
    contracts.py
    mode_registry.py
    bridge.py
    session.py
    pi_adapter.py
    persona.py
    operations.py
    artifacts.py
    projection.py
```

这些文件大致分别负责：`contracts.py` 定义后台域的数据契约，例如最小的后台请求单应至少有 `request_id`、`source_kind`、`request_kind`、`source_ref`、`summary`、`created_at` 这些字段，其中 `source_kind` 只需要表达 `admin_direct` 和 `frontstage_internal` 两种来源，`source_ref` 则至少能带上 `thread_id`、`channel_scope`、`event_id` 这些可反查引用；`mode_registry.py` 记录哪些管理员私聊当前处于 `/maintain` 模式；`bridge.py` 作为前台、管理员和后台之间的统一桥，同时承担请求分类、query/change 分流以及最小调度语义，不必再单独拆出 `policy.py` 和 `queue.py`；`session.py` 持有唯一的后台长期 session，并维护后台逻辑身份到 canonical `pi` session 的绑定，同时提供从稳定切点派生 query fork 的能力；`pi_adapter.py` 负责 AcaBot 与 `pi` 的适配，第一版更适合走 `pi --mode rpc`；`persona.py` 负责注入后台 Aca 的 maintainer 人格设定；`operations.py` 负责最小 operation log、等待状态和内部历史索引；`artifacts.py` 负责 patch、diff、测试输出、文档草稿等产物存储；`projection.py` 负责把后台结果投影成前台可转述摘要、管理员详细回复或 WebUI 视图。与这些模块配套的运行时目录则更适合放在仓库根下的 `.acabot-runtime/`，而不是和源码目录平铺混放。

## 现有代码里哪些部分可以继续复用

前台聊天主线本身不需要推翻，仍然会以 `src/acabot/runtime/app.py`、`src/acabot/runtime/router.py`、`src/acabot/runtime/pipeline.py`、`src/acabot/runtime/model/model_agent_runtime.py` 为核心。控制面和配置热刷新仍然重要，关键仍然在 `src/acabot/runtime/control/control_plane.py` 和 `src/acabot/runtime/control/config_control_plane.py`。workspace、附件、shell session 和 backend 抽象仍然会依赖 `src/acabot/runtime/computer/runtime.py`。长期记忆底层桶也仍然在 `src/acabot/runtime/memory/structured_memory.py` 这条线里。

真正新增的重点，是把“后台模式、后台桥接、后台 session、后台队列、后台产物”从这些现有模块里独立出来，形成一个清楚的 backend 域。否则这些能力最后很容易散回 `plugins/`、`control/`、`tool_broker/` 里，看起来只是系统多了一些零散功能，而不是正式多了一个后台人格。

## 这件事在当前代码里是什么状态

从方向上说，这件事现在还是明显的 TODO，但已经有一些地基。前台聊天主线已经比较清楚；前台的 tool、approval、plugin 和 subagent 接缝也已经存在；控制面和配置热刷新已经有基础设施；workspace、附件、shell session 和 backend 抽象也已经有基础设施；长期记忆底层桶也已有一部分。

但这些都不等于“后台 Aca 已经存在”。现在更准确的状态是：前台主线已经有，前台 subagent 已经有，control plane 已经有，computer 已经有，但“一个长期存在、注入 Aca maintainer 人格设定的后台 `pi` session”还没有被正式接进来；前台和后台之间也还没有正式的桥接协议、后台模式状态机、canonical session 绑定、query fork、最小 operation log 和 artifact 投影层。也就是说，现有代码已经有很多适合继续往上长的接缝，但“前台 Aca + 后台 Aca(pi) + 后台桥接入口 + 单一后台 session + query fork + operation / artifact 投影”这套完整结构还没有真正落地。

## 一开始不要做成什么样

一开始不要把前台默认暴露到整个 repo，也不要把配置真源和 control plane 直接暴露给前台，更不要让前台拿着一堆维护工具自己动系统。也不要把后台做成“每个任务一个新的 pi session”或者“每个前台 thread 各有一个后台 session”，这样很快就会遇到同一文件和同一配置被多路并发修改的问题。更不要把后台维护协议直接写死成一堆字符串前缀和正则，不要把后台维护上下文整个塞回前台聊天线程里，也不要把 raw `pi` 的 session 管理命令直接暴露给后台模式。

更稳的第一步应该是：先把后台 maintainer 定义成唯一的长期 `pi` session；先把前台到后台的桥接入口、后台模式状态、canonical session 绑定、query fork、最小 operation log 和 artifact 模型立起来；先让后台接管查询、低风险配置更新、文档更新和验证；先让它能产出 patch / diff / 测试结果；代码级上线和高风险发布仍然保留更严格的门槛。

## 这篇文档的定位

这一篇是方向说明，不是现状说明，也不是最终实现细节。它主要回答五件事：为什么 AcaBot 需要前台 Aca 和后台 maintainer 两个长期角色；为什么后台更适合直接由一个长期 `pi` session 承载；前台、subagent 和后台各自应该承担什么职责；为什么“自我进化”不该等于“前台直接改自己”；如果以后真的做这件事，架构应该往哪边收。

等真正开始实现时，至少还需要再补两类文档：一篇 how-to，解释普通用户怎样通过前台触发后台、管理员怎样用 `!` 和 `/maintain` 进入后台；一篇 reference，定义前后台桥接协议、后台模式状态机、唯一后台 session 的调度规则、query / change 的执行分流以及 operation / artifact 结构。