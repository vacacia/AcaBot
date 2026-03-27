
# 编写代码的规范(务必遵守)

不要考虑任何兼容性, 因为那是之前犯的错误, 不需要为它兼容, 直接强硬的改过去, 甚至把错误的内容全删掉, 不用考虑平滑迁移.
要改就改彻底, 不要留下以前的任何痕迹, 不要说"不应该怎么样", 就当它没发生过, 然后把错误写在文档里(不是不应该xxx的表面陈述, 回归第一性)
如果是重构, 不要留下黑名单来断言之前的问题不存在

## 写代码
0. 任何注释都要用直白的语言, 正常说人话! 不要出现黑话(落地/落库)
1. docstring
  - 类的 docstring 用 google 风格, 并且要包含属性的类型
  - 文档级别的 docstring 描述文件的功能, 和其他组件的联系
  - 方法的 docstring 要写清楚输入输出, 和方法的功能
  - 任何方法都要有 docstring, 哪怕是`__init__` 和 helper 
2. 用简洁的中文加上 `# region `注释,方便定位
3. 每次开始修改任何一个文件前, 都要说出: 我在做什么?是计划的哪一步?我为什么这样设计?站在设计师的视角解释; 完成后, 再解释修改完成后行为的变化
4. 一组 todo/task 视为一次 commit, 而不是每一个 todo/task 都是一个commit
5. 在完成了全部 todo/task 后, 先不要 commit, 立即启动子代理 (首次使用 gpt 5.4 mini, 直到 gpt 5.4 mini 找不出问题给出通过后, 再用一次 gpt5.4 来 review) 用 superpowers review 的 skill 去 review 你这次的代码 和 测试文件.
  - 不要只完成了文件里的一个 todo/task 就去 review, 浪费时间
6. review 多次后确认无误, 更新文档. 然后给出 commit 信息, 你做的重大决策, 修改后变化的流程...全部解释清楚, 不准 commit 
7. 发现难以决策的点就停下来, 说清楚现状, 及时讨论
8. 清晰的代码目录结构, 相关的代码文件放在一个文件夹下面; 明确的代码文件夹命名, 不要用含糊不清的文件夹名; 方法名也含义清晰, 尽量长, 不要用抽象的命名
9. 测试的时候可以跳过和后端的测试, 因为后端llm有时候不稳定




# 文档

00~12, 18, 是重要的文档.
- 阅读他们
- commit之前更新他们

在 docs/HANDOFF.md 里写清楚现在的进展(没有就创建一个)
- 解释你试了什么、什么有效、什么没用, 让下一个拿到新鲜上下文的 agent 只看这个文件就能继续完成任务
- 这个文件来帮助你避免反复踩坑(不应该的设计, 要写上为什么? 采用的设计, 也要写上为什么)
- 整合相同模块的内容. 不是按日期追加, 就像数据库的日志, 合并对相同的数据库记录的不同操作
- 这不是流水账, 没意义的东西不要写, 不要废话, 每次只需要写三句话


# 项目约定

现有审计可以不考虑, 也可以删除
- 后续设计不要为了保留审计层, 去额外发明中间抽象、兼容层或者 runtime 语义。
- 如果某块旧审计已经开始反过来限制设计, 可以直接删。
审计不是后续架构演进的中心目标。不要因为“以后要不要更好审计”就把系统做复杂。

默认 yolo

## 对于文档/注释

不写“不要怎么做”, 只写现在在做什么.

设计文档不要总在前面铺很多“不要这样、不要那样”。
如果已经知道目标, 就直接写:
- 最终形态是什么
- 物理目录怎么约定
- 逻辑路径怎么约定
- 工具面是什么
- 关键组件分别做什么
把文档重点放在“最后到底要实现什么”, 不要被大量负面约束带歪。

## 全局命名约束⭐

后续 runtime、memory、tool、WebUI、control plane 相关设计, 统一使用下面这组主契约命名。

### 正式词典

- `actor_id`
  - 只表示“这条消息是谁发的 / 当前谁在发言”
  - 例子: `qq:user:12345`
- `conversation_id`
  - 表示“这条消息发生在哪个对话容器里”
  - 它是现在很多地方 `channel_scope` 的正式收束名
  - 例子: `qq:group:67890`
- `thread_id`
  - 表示 runtime 内部 thread 主线
  - 它是运行时对象, 不是平台对象
- `session_id`
  - 表示命中的 session config
  - 它是配置对象 id, 不是聊天容器 id
- `entity_ref`
  - 表示“当前被引用的实体对象”
  - sticky note、retrieval target、WebUI 新建便签、bot 工具参数统一用它
  - 它只能指向实体对象或对话容器对象
  - 它可以指向用户, 也可以指向群/频道/房间/私聊容器
  - 它不能指向 `thread_id`
  - 它不能指向 `session_id`

### 派生分类

- `entity_kind`
  - 只表示分类, 例如 `user` / `conversation`
  - 它只用于 UI 分组、局部枚举或人类阅读辅助
  - 它必须从 `entity_ref` 派生, 不是一个和 `entity_ref` 并列传来传去的主字段
- `scope`
  - 以后尽量退出主契约层
  - 它只保留在局部分类语义里, 不再承担身份主键或正式对象引用

### `entity_kind` 的正式派生规则

对于 sticky note、retrieval target、WebUI 新建便签这一类正式对象引用:

- `qq:user:12345` -> `entity_kind = user`
- `qq:group:67890` -> `entity_kind = conversation`
- `discord:channel:987654321` -> `entity_kind = conversation`
- `matrix:room:!roomid:example.org` -> `entity_kind = conversation`

也就是说:

- 指向“人”的 `entity_ref` 派生为 `user`
- 指向“群 / 频道 / 房间 / 私聊容器”这类对话容器的 `entity_ref` 派生为 `conversation`

如果某个 `entity_ref` 不能被稳定派生到 `user` 或 `conversation`, 那它对 sticky note 来说就是无效对象:

- 不能静默猜测
- 不能临时发明第三种 `entity_kind`
- 应该在 sticky note 边界直接拒绝

`entity_ref` 的合法性校验和 `entity_kind` 的派生必须复用同一个共享解析 helper, 不能让 file store、service、retriever、control plane、WebUI 各自写一套判断。

第一版这个共享规则至少要允许这些会出现在 canonical ref 里的字符:

- 字母和数字
- `:`
- `-`
- `_`
- `.`
- `@`
- `!`

除此之外, 路径分隔符和 `..` 这种会破坏目录边界的内容一律直接拒绝。

### 固定规则

- 同一个东西只保留一个主名字, 不要在不同对象之间来回换词
- sticky note / retrieval / WebUI 如果是在说“这次要引用哪个对象”, 一律用 `entity_ref`
- 消息事实如果是在说“谁在发言”, 一律用 `actor_id`
- 当前发言人是 A, 但工具或检索想看 B 的信息时:
  - `actor_id` 仍然是 A
  - B 只能写成 `entity_ref`
  - 不准把 B 也叫 `actor_id`
- 消息事实如果是在说“消息发生在哪个聊天容器里”, 一律用 `conversation_id`
- runtime 内部执行主线如果是在说“这次 run 落在哪条线程”, 一律用 `thread_id`
- 会话配置如果是在说“命中了哪份 session config”, 一律用 `session_id`
- `session_id` 和 `conversation_id` 在某些场景下值可以相同, 但语义永远不同
- 文档和代码里不要写成“`session_id` 或 `conversation_id`”, 也不要把两者混成一个概念

### 固定案例

#### 群聊里张三发消息

- `actor_id = qq:user:12345`
- `conversation_id = qq:group:67890`
- `thread_id = runtime 内部某条 thread`
- `session_id = 命中的 session config`

如果 sticky note 要读取相关便签:

- 当前发言人的 user note:
  - `entity_ref = actor_id`
- 当前对话容器的 note:
  - `entity_ref = conversation_id`

#### 私聊里和某个用户对话

- `actor_id = qq:user:12345`
- `conversation_id = qq:private:12345` 或当前系统定义的私聊容器 id
- `thread_id = runtime 内部某条 thread`
- `session_id = session:qq:private:12345`

如果 sticky note 要读取相关便签:

- 当前对话对象的 note:
  - `entity_ref = actor_id`

#### 同一个语义, 不同平台都按同一套名字表达

这些例子不是在声明“现在已经支持这些平台”, 而是在固定命名规则:

- QQ 群聊
  - `actor_id = qq:user:12345`
  - `conversation_id = qq:group:67890`
  - 当前对话容器 note:
    - `entity_ref = qq:group:67890`
  - 当前发言人 note:
    - `entity_ref = qq:user:12345`

- Telegram 群组
  - `actor_id = telegram:user:12345`
  - `conversation_id = telegram:group:-100987654321`
  - 当前对话容器 note:
    - `entity_ref = telegram:group:-100987654321`
  - 当前发言人 note:
    - `entity_ref = telegram:user:12345`

- Discord 频道
  - `actor_id = discord:user:abc123`
  - `conversation_id = discord:channel:987654321`
  - 当前对话容器 note:
    - `entity_ref = discord:channel:987654321`
  - 当前发言人 note:
    - `entity_ref = discord:user:abc123`

- Matrix 房间
  - `actor_id = matrix:user:@alice:example.org`
  - `conversation_id = matrix:room:!roomid:example.org`
  - 当前对话容器 note:
    - `entity_ref = matrix:room:!roomid:example.org`
  - 当前发言人 note:
    - `entity_ref = matrix:user:@alice:example.org`

#### 同一个对象在不同层里的名字必须固定

例子 1: 群聊事件进入系统

- 平台事实层:
  - `actor_id = qq:user:12345`
  - `conversation_id = qq:group:67890`
- session config 层:
  - `session_id = session:qq:group:67890:default`
- runtime 执行层:
  - `thread_id = thread:front:qq:group:67890`
- sticky note / retrieval 层:
  - 发言人 note: `entity_ref = qq:user:12345`
  - 对话容器 note: `entity_ref = qq:group:67890`

这里要注意:

- `conversation_id` 表示聊天容器
- `session_id` 表示命中的配置
- 它们在某些场景下值可以相同, 但永远不是一个概念

例子 2: bot 主动去看另一个人的便签

- 当前事件:
  - `actor_id = qq:user:11111`
  - `conversation_id = qq:group:67890`
- bot 想读取李四的便签:
  - `entity_ref = qq:user:22222`

这里要注意:

- `actor_id` 仍然表示当前谁在发言
- `entity_ref` 表示这次工具/检索真正引用的是谁
- 两者可以相同, 也可以不同
- `qq:user:22222` 绝对不能因为“当前要查询他”就被改叫成 `actor_id`

例子 3: 私聊里读取当前对话对象

- 当前事件:
  - `actor_id = telegram:user:55555`
  - `conversation_id = telegram:private:55555`
- sticky note:
  - `entity_ref = actor_id`

#### 名字的使用边界

- 如果你想表达“谁在发言”, 用 `actor_id`
- 如果你想表达“消息在哪个聊天容器里发生”, 用 `conversation_id`
- 如果你想表达“runtime 内部哪条执行主线”, 用 `thread_id`
- 如果你想表达“命中了哪份配置”, 用 `session_id`
- 如果你想表达“这次要引用哪个用户/群/频道/房间/私聊容器对象”, 用 `entity_ref`

#### 常见错误和正确收束

- 旧写法:
  - `channel_scope = qq:group:67890`
- 新写法:
  - `conversation_id = qq:group:67890`

- 旧写法:
  - `sticky_note_read(scope="user", entity_id="qq:user:12345")`
- 新写法:
  - `sticky_note_read(entity_ref="qq:user:12345")`

- 旧写法:
  - planner 产出 `sticky_note_scopes = ["user", "channel"]`
- 新写法:
  - planner 产出具体 `entity_ref`
  - 例如:
    - `qq:user:12345`
    - `qq:group:67890`

- 旧写法:
  - `scope + scope_key`
- 新写法:
  - 先问它是不是其实想表达一个正式对象
  - 如果是, 直接收成 `entity_ref`

### 收束规则

- 以后在代码和文档里看见旧命名, 例如:
  - `channel_scope`
  - `scope_key`
  - `sticky_note_scopes`
  - `scope + entity_id` 这种旧组合写法
- 只要正在修改那一层代码或文档, 就顺手把它收束到这套正式命名
- 不保留“旧名字也行”的双轨表达
- 发现一个对象同时带着两套同义字段时, 直接删掉重复表达, 回到这份词典

### 对 sticky note 的直接要求

- sticky note 的正式主对象引用统一用 `entity_ref`
- `entity_kind` 只用于 `user/conversation` 这种分组显示
- `entity_kind` 必须从 `entity_ref` 派生, 不是 sticky note file store / service 的外部入参
- sticky note retrieval 的正式字段形状统一收成:
  - `sticky_note_targets: list[str]`
  - 其中每个元素都必须是一个合法的 `entity_ref`
- prompt 注入、retrieval target、bot 工具、WebUI 新建便签, 统一围绕 `entity_ref` 说话
- `scope + entity_id` 不再作为 sticky note 的正式主契约

### 对旧字段的理解

- 看到 `channel_scope`, 直接把它理解成 `conversation_id`
- 看到 sticky note 里的 `scope`, 优先把它理解成局部分类词; 如果它在表达对象主语义, 就顺手收成 `entity_ref` 或 `entity_kind`
- 看到 `scope + scope_key`, 优先思考它真正想表达的是不是某种 `entity_ref`


# 项目组件理解⭐

## tool

- tool 是给 LLM 调用的, 是 json 里 tool 字段下面的各个工具
- tool 自己只定义名字、描述、参数、返回值和执行入口; 
- 它不决定当前 run 下能不能看见、能不能调用。tool 的可见性和准入由上层决定, 例如 ToolBroker、profile、world policy。
- core tool 属于 runtime 自带表面; plugin 也可以额外提供 tool(plugin可以提供外部的tool, hook点的修改), 但两者不是一回事。

## plugin

- plugin 是 runtime 暴露给外部的可选扩展包, 是外部的插件, 和系统本身无关. plugin 的典型应用是:链接解析工具(hook阻断llm回复, 直接解析视频并发送)/日报分析插件(定时查数据库分析聊天记录)/查询天气插件(提供一个外部的tool, 也是tool). 和系统无关
- plugin 的代码把额外能力(hook)接进 runtime, 或提供给 llm 相应的 tool, 它描述的是“这包扩展怎么接进系统、怎么参与生命周期”
- plugin 可以提供 tool, 但 tool 不等于 plugin。tool 是给 LLM 调用的接口; plugin 只是这些 tool 可能来自的一个来源。
- builtin runtime service、core tool、主线控制组件要单独表达, 不要因为它们内部也有适配层或注册动作, 就顺手把它们都叫成 plugin。
- 判断一个东西是不是 plugin, 看的是它是不是可选扩展边界: 卸掉它后, 系统应该只是少一项扩展能力, 不该把 `read / write / edit / bash` 这类基础能力一起卸掉。

## computer

- `computer` 是前台文件工具和 shell 工具背后共用的代码。当前前台真正暴露给模型看的 builtin tool 只有:
  - `read`
  - `write`
  - `edit`
  - `bash`
- 模型不会直接看到 `computer` 这个名字。系统启动时, 会把 `computer` 的能力拆成上面这四个工具, 注册到 `ToolBroker`, 再放进发给模型的 `tools` 列表里。模型实际看到和调用的, 也是这些工具名, 不是 `computer`。
- 这些工具属于系统自带的基础工具, 不是 plugin。`computer` 负责真正干活, `ToolBroker` 负责把工具给模型看和接住模型调用。
- `computer` 现在真正负责的事情主要是:
  - 按 Work World 路径读文件
  - 按 Work World 路径写文件
  - 按 Work World 路径改文件
  - 在当前 world 里跑 `bash(command, timeout?)`
  - 维护 thread 级 workspace、附件和内部 shell 状态
- 不通过 plugin 实现, 是因为 plugin 表示可选扩展边界; 卸掉一个 plugin 后, 系统应该只是少一项扩展能力, 不该把 `read / write / edit / bash` 这种基础工具一起卸掉。
- 模型调用这些工具后, 调用会先到 `ToolBroker`, 再转回 `computer` 去真正读文件、写文件、改文件和跑命令。哪些路径能用、当前 world 能不能看到 `/workspace /skills /self`, 命令该在宿主机还是 docker 里跑, 都是上层先定好, 再交给 `computer` 执行。

## skill

当前前台正式入口是：

- prompt 里的 skill 摘要提醒
- builtin `Skill(skill=...)`
- 后续沿 `/skills/...` 继续读 skill 包里的文件

详细规则看 `docs/18-skill.md`


## 记忆

记忆层级: 
- `/self`
- sticky note
  - 当前真正暴露给产品和 WebUI 的 memory 形态
  - 目前只依附于 `user` 和 `channel` 两种 scope
  - 在需要时按对应 scope 进入上下文
    - 例如在私聊时总是会注入对应用户的 sticky note, 在群聊时也会注入发送消息人的 sticky note
- relationship memory
  - 表示和具体对象有关的长期记忆方向
  - 当前代码和产品层都还没真正做出来
- channel memory
  - 表示和具体群体有关的长期记忆方向
  - 当前代码和产品层都还没真正做出来
- thread working memory
  - 最近几轮对话的短期上下文
- event / message facts
  - 平台真实发生过什么、系统真实发送过什么

当前前台正式主线里, 这几层是这样接起来的：

- `RetrievalPlanner`
  - 负责整理这一轮 retrieval 要共享给记忆来源的原始现场, 以及 retained history / working summary 这类 thread 侧材料
- `MemoryBroker`
  - 统一向已接入的记忆来源发起 retrieval 请求, 收集返回结果, 记录失败, 再把统一结果交给 `ContextAssembler`
  - 它是 broker / aggregator
- `ContextAssembler`
  - 统一把 base prompt、tool summaries、memory blocks、working summary、retained history、current user 组装成最终模型上下文
- `ctx.system_prompt / ctx.messages`
  - 只表示最终给模型的结果, 不再表示中间态

### RetrievalPlanner、MemoryBroker 和 Retriever 的边界

当前稳定边界可以直接记成:

- `RetrievalPlanner`
  - 产出这一轮共享 retrieval context
  - 它携带的是 event / thread / context 这些现场事实
  - 它产出的 thread 侧材料主要是 retained history 和 working summary
- `MemoryBroker`
  - 把 retrieval context 转成统一 request
  - 把 request 发给各个记忆来源
  - 收集 `MemoryBlock`、汇总失败、保留可观测性
- `Retriever` / `MemorySource`
  - 是真正的记忆来源接缝
  - 解释 request 里的现场元数据
  - 决定自己的内部查询方式、命中方式和返回内容
  - 把结果交回成统一 `MemoryBlock`

这三层之间的数据方向是:

`RetrievalPlanner -> shared retrieval context -> MemoryBroker -> MemorySource -> MemoryBlock -> ContextAssembler`

只要顺着这条数据方向看代码, 边界就很清楚。

### self

`self` 是 AcaBot 里 前台 bot 维护的文件夹

它记录的是：

- Aca 经历的事件
- 它们属于 Aca 本身
- 这里记录的是 Aca 每天都发生了什么, 是 Aca 自己维护的一片与 Aca 相关的记忆区;
  - 它可以是实时性的, 临时性的(今天), 以让 Aca 了解 Aca 正在哪些群和哪些人交互;
  - Aca 把自己的一天给提炼到一个日记里面(一个 md 文档), 类似 openclaw 的 MEMORY.md
- 因为 Aca 虽然有 prompt, 有 sticky note, 还有检索的长期记忆, 但是没有一个地方可以让 Aca 记录自己在这一刻, 在这一天发生了什么, 需要这个区域来保持 Aca 行动的连贯性

- 这不是 Aca 的人格设定: Aca 的人格设定在配置的 prompt 里, 它会注入到 system prompt 里
- 具体的人物 / 群聊信息放在 sticky note
- 这些东西里, 和具体群、具体用户都无关
- 不是“杂项长期记忆”, 也不是“所有能长期保存的东西”


应该实现: 
- `self` 由 Aca 在自己的 computer 里管理
- `self` 把今天, 昨天..(可设置多久)注入上下文
- 后台 maintain bot 当然可以看见 `self` 文件, 但这和 maintain bot 无关, 后台是独立维护的工程执行面
- `self` 下的 md 文档能在 webui 里显示

当前代码里 `/self` 的文件结构已经是：

```text
/self/
  today.md
  daily/
    2026-03-23.md
```

### sticky note

它的定位是零碎但长期有用的笔记。例如：

- 这个群的群主是谁
- 这个群的风格是什么
- 这个群主要在聊什么
- 这个群有哪些黑话

bot 可以写入 sticky note, 让自己以后还能理解这些东西。

当前共识里, sticky note 对每个 scope 都分成两块：

- 只读区
  - 人工编写
  - 百分百真源
  - bot 不允许更改
- 可编辑区
  - 允许 bot 写入和更新


- `readonly` 注入上下文
- `editable` 也注入上下文

### relationship memory


### channel memory

channel memory 目前仍然是概念层级

它表达的是和具体群体有关的长期记忆方向

### thread working memory

thread working memory 是最近几轮对话的短期上下文

### event / message facts

event / message facts 负责记录真实发生过什么和真实发送过什么, 本质上就是消息聊天记录。

后续可以在 WebUI 里增加专门的查询页, 方便查看聊天记录

## WebUI 与实现约束

### WebUI
- WebUI 中要有单独的 `Memory` 页面来展示记忆的每个层级
- 允许编辑的记忆, 要可以在 webui 编辑

# 项目结构
## 读文档

   - 路由 / agent 绑定 / prompt: `04-routing-and-profiles.md`
   - 记忆 / retrieval / compaction: `05-memory-and-context.md`
   - 工具 / builtin tool / plugin / skill: `19-tool.md`
   - subagent: `20-subagent.md`
   - 平台接入 / NapCat / 事件翻译: `07-gateway-and-channel-layer.md`
   - WebUI / 控制面: `08-webui-and-control-plane.md`
   - workspace / computer / 附件 / shell session: `12-computer.md`
   - 模型 provider / preset / binding / 生效模型解析: `13-model-registry.md`
   - reference / notebook 检索后端: `14-reference-backend.md`
   - 已知问题 / 设计缺口 / 修复后该同步哪些文档: `15-known-issues-and-design-gaps.md`
   - 前后台双 agent / 自我进化方向: `16-front-back-agents-and-self-evolution.md`
   - 配置和部署: `09-config-and-runtime-files.md`、`11-deployment-reference.md`


## 这套代码里哪些文件最像“总装配图”

- `src/acabot/main.py`
  现在只负责启动和组装, 不负责业务主线。
- `src/acabot/runtime/bootstrap/`
  默认 runtime 组件都在这里接起来。
- `src/acabot/runtime/contracts/`
  核心运行时数据对象现在拆在这里。
- `src/acabot/runtime/control/config_control_plane.py`
  WebUI 能改的配置真源和热刷新逻辑大多在这里。

## 一张够用的脑图

外部世界进来时, 大致是这条线:

`NapCat -> Gateway -> RuntimeApp -> RuntimeRouter -> ThreadManager / RunManager -> ThreadPipeline -> ModelAgentRuntime -> Outbox -> Gateway`

同时还有几条侧边线:

- `ChannelEventStore` 记录外部事件事实
- `MessageStore` 记录真正送达的消息事实
- `MemoryStore` 存长期记忆
- `ToolBroker` 负责工具可见性、审批、前台到后台 bridge tool 和执行
- `PluginManager` 给主线插 hook / tool / executor
- `ControlPlane + HTTP API + WebUI` 负责本地运维和配置改写
- `runtime/backend/` 现在已经是一个真实接线的子域, 不只是设计草图：里面已经有 canonical session binding、configured backend session service、真实 `pi --mode rpc` adapter、管理员后台模式和前台 `ask_backend` bridge

## 这项目最容易看错的地方

### 1. 把 working memory 和长期记忆混在一起

不是一回事:

- `ThreadState.working_messages / working_summary` 是当前线程上下文(就是QQ群的对话流)
- `MemoryStore / MemoryBroker / structured_memory` 是长期记忆
- `MessageStore` 是送达事实, 不是上下文草稿
- `ChannelEventStore` 是外部事件事实, 不是 assistant 回复事实

### 2. 把 Gateway 当业务层

`gateway/napcat.py` 只该做协议翻译和 API 调用。不要把“该不该回复”“该走哪个 agent”“要不要提取记忆”这种逻辑塞进去。

### 3. 把 WebUI 当成“独立系统”

不是。WebUI 只是 `RuntimeHttpApiServer` 和 `RuntimeControlPlane` 的前端壳。前后端改动通常要一起看。

### 4. 只改前端, 不改配置真源

很多页面不是读内存状态, 而是读 / 写 runtime config 真源。你只改 `webui/src/` 里的页面或组件, 往往只改到表面。

### 5. 只改单点, 不看调用链

这个项目里很多功能跨层:

- 图片转述会同时碰 `event attachments`、`computer staging`、`model capability`、`tool/plugin`、`prompt assembly`
- 长期记忆会同时碰 `session config` 里的 persistence / extraction 决策、`memory broker`、`store`、`retrieval planner`
- WebUI 控制面板会同时碰 `app.js`、`http_api.py`、`control_plane.py`、`config_control_plane.py`

### 6. MemoryBroker 的角色

`MemoryBroker` 在主线里的角色很简单:

- 统一收发 retrieval request
- 汇总 retrieval 结果和失败
- 保持记忆来源的可观测性

记忆来源自己的查询方式和写入方式, 仍然留在各自来源内部。

## 改代码前的固定流程

每次都建议按这个顺序来:

1. 先判断改动属于哪一层
   - 协议层
   - runtime 主线
   - 配置与控制面
   - 记忆系统
   - 工具 / plugin / subagent
   - WebUI
2. 找主入口文件, 不要上来全文搜索到哪改哪
3. 确认输入和输出契约
   - 这层吃什么对象
   - 往下游吐什么对象
4. 列影响面
   - 配置项
   - 持久化
   - WebUI
   - 模型能力约束
   - 事件 / 消息事实记录
5. 先给变更方案, 再开始改

## 改完代码后, 不要把文档留在旧状态

以后只要改了代码, 而且改动会影响下面任意一类信息, 就应该顺手同步 `docs/`：

- 主线流程
- 模块职责
- 数据契约
- 配置项和生效路径
- WebUI / control plane 行为
- tool / plugin / skill / subagent 的接入方式
- 典型改动入口

最少要做两件事:

1. 判断现有文档有没有被改旧
2. 把受影响的文档一起更新

不要把文档当成“最后有空再补”的东西。

这套文档的目标就是让下一次新对话不用再从头读完整代码。如果代码变了、文档不跟, 文档很快就会失去价值。

这套文档的定位是:

- 尽量替代“每次都做一遍全仓扫读”
- 让 AI 能快速定位到该看的模块
- 让 AI 不必再盲目通读一堆无关文件

但它不是“永远不用再看源码”的许可证。

如果任务刚好碰到:

- 最近改过但文档还没同步的模块
- 这次文档没有覆盖到的细节实现
- 大文件里的具体边界条件

那还是应该回到对应源码做定点复读。

## 改动和文档的对照表

如果你改的是下面这些地方, 通常至少要同步这些文档。

### runtime 主线

代码范围:

- `runtime/app.py`
- `runtime/pipeline.py`
- `runtime/bootstrap/`
- `runtime/router.py`

通常要同步:

- `02-runtime-mainline.md`
- `01-system-map.md`
- 需要时 `10-change-playbooks.md`

### 数据契约

代码范围:

- `types/`
- `runtime/contracts/`

通常要同步:

- `03-data-contracts.md`
- 如果影响主线, 再看 `02-runtime-mainline.md`

### 记忆系统

代码范围:

- `runtime/memory/memory_broker.py`
- `runtime/memory/structured_memory.py`
- `runtime/memory/context_compactor.py`
- `runtime/memory/retrieval_planner.py`
- `runtime/control/event_policy.py`

通常要同步:

- `05-memory-and-context.md`
- `10-change-playbooks.md`

### tool / plugin / skill / subagent

代码范围:

- `runtime/tool_broker/`
- `runtime/plugin_manager.py`
- `runtime/plugins/`
- `runtime/skills/catalog.py`
- `runtime/subagent_*`

通常要同步:

- `19-tool.md`
- 如果是 subagent 委派或 child run 边界, 再看 `20-subagent.md`
- 如果影响主线, 再看 `02-runtime-mainline.md`
- 如果改变典型接入方式, 再看 `10-change-playbooks.md`

### gateway / 渠道层

代码范围:

- `gateway/`
- `types/event.py`
- `types/action.py`

通常要同步:

- `07-gateway-and-channel-layer.md`
- `03-data-contracts.md`

### WebUI / control plane

代码范围:

- `runtime/control/http_api.py`
- `runtime/control/control_plane.py`
- `runtime/control/config_control_plane.py`
- `webui/`

通常要同步:

- `08-webui-and-control-plane.md`
- `09-config-and-runtime-files.md`
- 需要时 `10-change-playbooks.md`

### computer

代码范围:

- `runtime/computer/`
- `runtime/builtin_tools/computer.py`

通常要同步:

- `12-computer.md`
- 如果影响 builtin tool 表面或 skill 读取路径, 再看 `19-tool.md`

### model registry

代码范围:

- `runtime/model/model_registry.py`
- `runtime/model/model_resolution.py`

通常要同步:

- `13-model-registry.md`
- `08-webui-and-control-plane.md`

### reference backend

代码范围:

- `runtime/references/`
- `runtime/plugins/reference_tools.py`

通常要同步:

- `14-reference-backend.md`
- `19-tool.md`
