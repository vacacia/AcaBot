# Work World：从 OpenClaw 学到的 computer 与 sandbox 总设计

## 1. 这篇文档在解决什么问题

这篇文档不再沿用旧的 `21-skill-visible-path-and-computer.md` 方案，也不把重点放在某一个 tool 或某一个目录名上。它要解决的是一个更底层的问题：

> AcaBot 以后到底要给前台 agent、subagent 和 sandbox 一个什么样的工作世界；这个世界里的文件、skill、附件、自我空间，以及 shell 执行环境，到底应该怎么统一。

如果这件事不先收稳，后面所有实现都会继续互相打架：

- 文件工具一套路径语义
- shell 一套路径语义
- skill 再自己一套入口
- 附件 staging 再漂在外面
- host backend 和 docker backend 再各自长一套

所以这篇文档的中心不是“功能列表”，而是：

> **先把前台工作世界定义清楚，再让 `computer` 和 sandbox 去承接它。**

这篇文档从 OpenClaw 学到的，不是某个路径名，而是它那种分层态度：模型世界、文件工具世界、shell 世界、backend 实现层、policy 层要清楚分开；同一个文件在这些层里可以有不同身份，但它们之间的关系必须稳定。

---

## 2. 真正值得学 OpenClaw 的，不是目录名，而是分层

OpenClaw 最值钱的，不是 `/workspace` 这个单词，也不是某个 prompt 文案，而是它承认了一件很朴素的事实：

> 同一个文件，对模型、对 runtime、对 shell，本来就不是同一个“名字”。

模型最好看到稳定的工作路径，runtime 必须知道宿主机真实路径，shell 则要工作在一个它自己真的能访问的文件系统视图里。如果系统不明确规定这几种名字之间的关系，最后一定会退化成“看起来都在一个 workspace 里，实际上每一层都在说不同的话”。

所以 AcaBot 要学 OpenClaw，不该先学“路径长什么样”，而该先学：

- 哪些层在描述模型世界
- 哪些层在描述 runtime 的真实文件位置
- 哪些层在描述 shell 的执行视图
- 哪些层负责把外部来源的附件转成世界里的正式文件对象
- 哪些层再额外加上角色和写权限限制

只要这几个层次先收稳，后面即使实现比 OpenClaw 简化很多，抽象也不会乱。

---

## 3. AcaBot 不该只有一个文件系统世界，而该有两个世界

### 3.1. Work World

前台 agent、前台 subagent，以及承载它们的 sandbox，应该共享同一个工作世界。这个世界的目标不是“完整工程维护”，而是“让模型在一个稳定、可工作的任务文件系统里工作”。

这个世界里，模型主要看到：

```text
/workspace
/skills
/self
```

这里最重要的不是名字本身，而是角色分工：

- `/workspace`：当前任务的工作面
- `/skills`：当前 actor 真正可见的能力面
- `/self`：前台 agent 的持久自我空间

### 3.2. Maintainer World

backend maintainer 不应该被强行塞进前台这一套世界里。它的职责根本不是“完成当前聊天任务”，而是维护工程：

- 看 repo 根
- 改代码
- 改配置真源
- 跑测试
- 读文档
- 处理 `.acabot-runtime/`

所以 backend maintainer 应该直接工作在 repo root 和 `.acabot-runtime/` 上。它当然也会碰文件、工具和 shell，但它不属于前台 Work World。

这里必须说死一句：

> **backend maintainer 不是 Work World 的高权限版本，而是另一套独立世界。**

### 3.3. sandbox 不是第三个世界，而是 Work World 的承载层

sandbox 不是新产品世界。它只是让 Work World 在不同 backend 上成立的执行承载层。

也就是说：

- 前台 agent 在 host 上跑，是 Work World
- 前台 agent 在 docker 里跑，还是 Work World
- subagent 在更受限环境里跑，仍然还是 Work World

sandbox 不负责定义世界，它只负责把上层已经定义好的世界真实做出来。

---

## 4. Work World 里，一个对象至少有四层身份

如果只说“模型看见 `/workspace /skills /self`”其实还不够，因为真正运行时里，同一个对象至少会同时有四种身份。

### 4.1. World Path

这是只给模型、prompt、文件工具协议看的路径。它是模型真正应该学会使用的那一层。

例如：

```text
/workspace/out/report.md
/skills/excel/SKILL.md
/self/task.md
/workspace/attachments/inbound/photo.png
```

模型不应该直接看到宿主机路径，也不应该学习 thread 物理目录。

### 4.2. Host Path

这是 AcaBot runtime 自己在宿主机上真正读写的路径。它回答的问题是：这个对象在宿主机上到底放哪。

例如：

```text
~/.acabot/threads/<thread_id>/workspace/out/report.md
~/.acabot/threads/<thread_id>/skills/excel/SKILL.md
~/.acabot/self/task.md
~/.acabot/threads/<thread_id>/workspace/attachments/inbound/photo.png
```

World Path 是协议身份，Host Path 是物理身份。

### 4.3. Execution View Path

这是 shell 真正工作时看到的路径。理想情况下，它尽量和 World Path 长得一样，但它不是一回事。

例如在最理想状态下，shell 里也应该真的有：

```text
/workspace
/skills
/self
```

只是这背后可能来自：

- host 上准备好的 execution view
- docker 容器里的挂载视图

shell 不该靠 prompt 想象这个世界，而应该真的踩在这套执行视图上。

### 4.4. Origin Handle

附件在进入 Work World 之前，还需要第四层身份。因为它一开始往往根本不是文件，而是平台来源，例如：

- OneBot file_id
- URL
- reply 图片引用
- gateway API 返回结果

所以附件进入系统时，先是 Origin Handle，之后才通过 staging 变成 Work World 里的正式文件对象。

举个完整例子：

```text
Origin Handle:       onebot:file_id=abc123
World Path:          /workspace/attachments/inbound/photo.png
Host Path:           ~/.acabot/threads/t1/workspace/attachments/inbound/photo.png
Execution View Path: /workspace/attachments/inbound/photo.png
```

---

## 5. Work World 里的三块根，各自到底是什么

### 5.1. `/workspace` 是工作面

`/workspace` 里放的，不是“任意文件”，而是当前这次任务里真正要加工的一切工作对象。

例如：

- 当前会话附件
- 草稿
- 中间产物
- 输出文件
- 临时脚本
- 任务相关的小型索引或缓存

如果一个东西是 thread 级、任务级、可随着工作结束被 prune 的，那它大概率就属于 `/workspace`。

附件一旦进入 Work World，也应该统一落到：

```text
/workspace/attachments/...
```

因为它从那一刻起就已经是当前任务的工作对象，而不是平台特殊对象。

### 5.2. `/skills` 是能力面

`/skills` 不是工作产物区，而是当前 actor 真正可见的能力包目录。它代表的不是“这次工作写出来的东西”，而是“这次工作可读可用的能力来源”。

里面放的是 skill 包内容，例如：

- `SKILL.md`
- `references/`
- `scripts/`
- `assets/`

例如：

```text
/skills/excel/SKILL.md
/skills/excel/references/pivot.md
/skills/excel/scripts/run.sh
/skills/excel/assets/template.xlsx
```

它默认应该是只读的，而且它不是“全局 skill 真源”，而是当前 actor 可见的 skills 视图。

### 5.3. `/self` 是前台 agent 的持久自我空间

`/self` 不是固定 prompt 包，也不是 sticky note 替代品，更不是长期向量记忆替代品。它更像：

> **前台 bot 自己长期维护的、可写的、不会随 thread 清理的自我工作区。**

这里最关键的边界已经确定：

- 前台 agent：`/self` 可见、可写
- subagent：`/self` 不可见、不可写

这不是“只读”区别，而是角色边界。subagent 是外包 worker，它可以带回结果，由前台决定是否写入 `/self`，但它自己不能看、更不能改。

---

## 6. 三条线必须拆开，但必须共享同一个 Work World

AcaBot 现在最容易混掉的，不是某个目录名，而是下面三条线：

- file tools
- `exec/bash`
- attachment staging

表面上这三件事都在谈“路径”，但它们不该共用同一种底层实现。

### 6.1. file tools 只吃 World Path

`read / write / edit / ls / grep` 最终应该非常死板。它们只接受 World Path，然后先 resolve 到 Host Path，再根据当前 actor 权限决定能不能读写。

file tools 不应该自己知道：

- `/skills` 怎么映射
- `/self` 谁能看
- 哪些根只读
- subagent 为什么看不到 `/self`

这些都应该在更高层先算完，它们只负责最终操作。

### 6.2. `exec/bash` 不重写命令，而是工作在 Execution View 里

shell 不是结构化路径 API。你给它的是整段命令，runtime 不可能可靠地重写其中所有路径，也不该假装自己能做到。

所以 shell 这条线正确的方向不是“翻译命令文本”，而是“提供一个它真的能工作的 Execution View”。

也就是说，前台 agent 的 shell 最后应该真的看到：

```text
/workspace
/skills
/self
```

subagent 的 shell 则应该只看到：

```text
/workspace
/skills
```

### 6.3. attachment staging 不是下载器，而是世界入口转换器

附件 staging 的真正完成条件，不是“文件下载成功”，而是：

> **附件已经从 Origin Handle 转换成了 Work World 文件对象。**

也就是说，一旦 staging 完成，附件就应该能像普通文件一样被 file tools、shell、vision bridge 使用，而不该继续漂在 URL、file_id、`/tmp` 这种半成品身份上。

---

## 7. `computer` 最终不该只是 workspace helper，而该是 Work World runtime

AcaBot 现有的 `computer` 已经有很好的地基：

- thread workspace
- attachment staging
- shell session
- host/docker backend
- skill mirror 接缝

但如果要认真学 OpenClaw，这一层的职责得再往上抬一层。

以后它不该只是“给模型几个工具”，而应该是：

> **在每次运行开始前，先把当前 actor 的整个工作世界装配好。**

它至少要先算出：

- 当前 actor 能看到哪些根
- 这些根在模型眼里叫什么（World Path）
- 这些根在宿主机上真正在哪里（Host Path）
- shell 里这些根怎么出现（Execution View）
- 哪些根可读、可写、完全不可见
- 附件怎样进入这套世界

这意味着 `computer` 的主入口不该再只是“确保 thread workspace 存在”，而应该是先产出一份 **World View**。它回答的问题是：

> 这次运行里，当前 actor 实际活在哪个世界。

tool adapter 之后就会自然退回纯接线层。它不再拥有路径语义，只把调用交给 `computer`。

---

## 8. sandbox 和 backend 不该定义世界，它们只承接世界

host backend 和 docker backend 最终不应该再自己定义：

- `/skills` 是什么
- `/self` 谁能看
- 附件该落哪
- subagent 能不能碰 `/self`

这些都应该已经在 `computer` 上层决定好了。backend 只承接已经装配好的 Work World。

### 8.1. host backend

host backend 以后不该只是“把 cwd 设到某个 workspace 目录”。它应该在 host 上构造出一个真正的 Execution View。

也就是说，前台 agent 的 shell 最后应该真的看到：

```text
/workspace
/skills
/self
```

subagent 则不该看到 `self`。

### 8.2. docker backend

docker backend 也不该继续只会把某个 workspace 目录挂到 `/workspace`。它最终承接的应该是整个 Execution View。

这里不需要第一阶段就做到 OpenClaw 那么复杂的 mount table / fs bridge 级别实现，但抽象必须先对齐：

> docker backend 承接的是世界，不是某个单点目录挂载。

### 8.3. sandbox 不是第三个世界

sandbox 不是新世界，它是 Work World 的执行承载层。它的职责不是重新定义前台协议，而是确保：

- file tools 的世界不变
- shell 的世界不变
- 附件进入世界的方式不变
- actor 对不同根的可见性边界不变

---

## 9. Work World 的构造依据，应该是什么；rule 又该放在哪

这里必须把一个很容易糊掉的问题单独讲清楚：

> Work World 到底依据什么被构造出来，现有 rule 系统又和它是什么关系。

我觉得结论应该非常明确：

> **Work World 的构造依据，应该是少数几个稳定输入；rule 不应该直接参与 computer 的路径构造。**

也就是说，rule 最多只能通过更上游的决策间接影响 world，例如先决定“这次是谁在工作、用哪个 profile、走哪个 backend”；但它不应该直接决定 `/workspace`、`/skills`、`/self` 这些根怎么出现、怎么映射、怎么裁剪。

### 9.1. 构造 Work World 的稳定依据

我建议以后 world builder 只看下面这些输入。

第一类是 **actor 身份**。也就是这次运行到底是前台 agent、subagent，还是 backend maintainer。它会直接决定这次运行属于 Work World 还是 Maintainer World，也会决定 `/self` 是否存在。

第二类是 **profile / capability bundle**。它回答的是：当前 actor 具备哪些 computer-facing 能力，能看到哪些 skills，默认走哪个 backend，允许不允许 exec。这一层不该再散在很多规则里，而应该成为 world builder 的正式输入。

第三类是 **thread / session 身份**。它主要决定当前工作面是哪一份实例，也就是 `/workspace` 对应哪一份 thread workspace，附件最终落到哪一份工作面，execution view 是为哪个 thread 构造的。

第四类是 **effective computer policy / override**。例如 host 还是 docker、allow_exec、allow_sessions、只读限制、thread 级 override。这一层决定的是世界由谁承接、能做什么，不是世界有哪些根。

第五类是 **当前 run 的附件来源**。也就是 Origin Handle，例如 file_id、URL、reply 引用。这一层不会改变世界结构，但会决定有哪些外部对象要进入 `/workspace/attachments/...`。

把这几类输入放在一起，其实就够构造当前 actor 的 Work World 了。

### 9.2. rule 应该怎样影响 world

rule 不是不能影响 computer，但它应该只能通过很窄的上游出口影响。

例如下面这些事情，rule 可以影响：

- 这条消息最终路由给前台 agent 还是 subagent
- 当前用了哪个 profile
- 当前 profile 可见哪些 skills
- 操作员是否把这个 thread override 成 docker backend
- 管理员是否显式进入 backend maintainer world

这些都属于“先决定谁在工作、用什么能力工作”。它们是 world builder 的输入来源之一。

但像下面这些事情，我不建议再让 rule 直接碰：

- `/self` 对 subagent 是否可见
- `/skills` 根要不要出现
- 附件到底进入哪块工作面
- file tools 吃 World Path 还是 host path
- shell 里是否真的出现 `/workspace /skills /self`

这些都应该属于 Work World 协议本身，而不是 rule engine 里一堆临时判断。

### 9.3. 为什么这件事和 rule 重构是同一个方向

你前面说“目前的 rule 管的内容太多、太混乱”，我觉得这个判断和 Work World 设计其实完全是同一个问题。

只要 rule 还能直接改：

- 哪些根出现
- 路径怎么解析
- 哪些对象属于 computer 世界
- shell 看见什么

那 Work World 就永远不可能稳定。因为上层一堆规则会偷偷改底层世界结构。

所以我更推荐把现有 rule 明确拆成三类：

- **Routing Rules**：决定消息给谁、用哪个 profile
- **Context Rules**：决定 sticky note、memory、prompt 注入
- **Computer Policy**：决定 backend、可见能力、可见 roots、可写性

其中前两类不该直接碰 computer 世界结构，第三类则应该被正式提升成 world builder 的输入，而不是继续藏在混杂 rule 里。

这一点我觉得值得直接记成一句架构约束：

> **Work World 的构造依据应该是：actor、profile、thread、computer policy 和当前附件来源。rule 只能通过“先决定 actor/profile/backend”间接影响 world，不能直接改 world 的路径结构和根可见性。**

---

## 10. 第一阶段最该先收的，不是 shell，也不是 docker，而是 file tools 的 World Path contract

如果现在就问“下一步最该先改什么”，我会很明确地选：

> **先让 `read / write / edit / ls / grep` 全部只吃 World Path。**

原因很简单。file tools 的输入是结构化的，runtime 能完全接管它的路径语义；shell 不是，docker backend 也不是。

所以第一阶段最适合做成“硬协议”的，就是 file tools。这一步做完以后，模型第一次真正拥有一套值得依赖的文件路径语言，而不是继续在相对路径、宿主机路径、skill 特殊入口、附件临时路径之间来回切换。

真正的第一阶段产物，不是一堆新功能，而是一个正式的 **World Path resolver**。它至少要回答：

- 这条路径属于哪个根
- 它映射到哪条 Host Path
- 当前 actor 对它可见吗
- 当前 actor 对它可写吗

---

## 11. attachment、`/skills`、`/self` 必须一起进入这个 contract

file tools 如果只覆盖 `/workspace`，那这套 resolver 还是残的。它只是一个 thread workspace resolver，不是 Work World resolver。

真正完整的 resolver，至少要同时覆盖三类对象：

- `/workspace/...`：当前任务工作对象
- `/skills/...`：当前 actor 真正可见的 skill 文件
- `/self/...`：前台 agent 的持久自我空间（subagent 不可见）

附件则通过 staging 进入：

```text
/workspace/attachments/...
```

只有这几块一起纳入 contract，AcaBot 才不会继续回到旧问题：

- 普通文件走 computer
- skill 继续单独走 plugin
- self 继续单独走控制面
- 附件继续自己拼路径

---

## 12. 非目标：这轮设计不该先做什么

这份设计强调先学 OpenClaw 的抽象复杂度，而不是马上复制它的实现复杂度。所以当前不该优先做这些：

- 不要先做完整 OpenClaw 式 mount table
- 不要先做 shell 命令字符串重写
- 不要先发明复杂的 `workspaceAccess` 配置矩阵
- 不要先让 backend 自己决定 `/skills` 和 `/self` 语义
- 不要先讨论 `/self` 里到底有哪些文件格式
- 不要先删掉 `skill(name=...)`

主线始终只有一句话：

> **先把前台 Work World 的协议收稳。**

---

## 13. 最后的总判断

如果把整篇文档压成一句话，那就是：

> AcaBot 真正该从 OpenClaw 学的，不是某个路径名，而是先把前台工作世界收成统一协议：模型始终活在 `/workspace /skills /self` 这套世界里；文件工具只吃 World Path；runtime 自己维护 Host Path；shell 工作在真正的 Execution View 里；附件从 Origin Handle 进入 `/workspace/attachments/...`；subagent 共享这套协议，但 `/self` 对它完全不可见；backend maintainer 则明确不属于这套世界。