如果完全不看现在这套 rule，我会先做一个非常强的决定：

> **我不会设计“一个总 rule 系统”。**  
> 我会设计 **一套共享匹配器 + 几个不同决策引擎**。

这是最核心的一点。

因为“规则”这个词太容易把所有事情都装进去，最后就会变成：

- 谁处理消息
- 回不回复
- 记不记事件
- 提不提记忆
- 甚至 computer 怎么长

全都叫 rule。  
这就是为什么系统最后会“怪怪的”。

如果从零开始设计，我会把它拆成下面这几层。

---

## 1. 第一层永远不是 rule，而是 Facts

也就是先把一条外部消息，统一整理成一份**标准事实**。

这份事实只回答“发生了什么”，不回答“系统应该怎么做”。

例如：

- `platform`
- `event_kind`
- `scene`：私聊 / 群聊 / notice / command
- `actor_id`
- `channel_scope`
- `thread_id`
- `mentions_self`
- `reply_targets_self`
- `targets_self`
- `mentioned_everyone`
- `sender_roles`
- `raw_message_type`
- `attachments_present`
- `attachment_kinds`

这里最关键的理念是：

> **先把输入事实标准化，再做任何决策。**

我不会让后面的 rule 自己去猜这些东西，也不会让每个 rule 系统各自重新组织一遍输入。

---

## 2. 第二层是一个共享 Matcher，而不是三套长得一样的 rule 类

我会只设计一套通用匹配器，比如叫：

- `MatchSpec`
- 或 `EventSelector`

它只负责一件事：

> **描述“这条策略适用于什么样的输入事实”。**

例如：

```yaml
when:
  platform: qq
  event_kind: message
  scene: group
  channel_scope: qq:group:123
  mentions_self: true
  sender_roles: [admin]
```

这层不带任何业务动作，不带 agent_id，不带 run_mode，不带 persist_event。  
它只是一个 selector。

这样做的好处非常大：

第一，不会再出现三套 `matches()` / `match_keys()` / `specificity()` 复制代码。  
第二，不同决策引擎都共享同一种匹配语言。  
第三，以后规则系统重构时，至少“怎么匹配输入”不会和“匹配后做什么”绑死在一起。

如果你要我一句话讲我从零开始最想避免什么，那就是：

> **不要把 matcher 和 decision 绑成一个 class。**

---

## 3. 第三层才是不同的决策引擎，而且它们的合并语义必须不同

这是我觉得现有系统最容易混的地方，也是我从零设计时最想讲清楚的地方：

> **不是所有“规则”都该用同一种决策方式。**

有的事情应该“单一胜者”，有的事情应该“多条累加”，有的事情根本就不该是 event rule。

我会至少拆成这五类。

---

### 3.1 Routing Policy：决定“谁来处理”

它回答的问题是：

- 这条消息交给哪个 actor / persona / profile
- 是前台 agent，还是某个特定 agent

这是一个**单一胜者**决策。

也就是说：

- 匹配多条没关系
- 但最终只能选一条结果
- 高优先级 + 高 specificity 决胜
- 同级冲突应该报错，不该默默吞

这一层的输出应该很小：

```yaml
then:
  actor_lane: frontstage
  profile_id: aca.main
```

我这里故意不用 `agent_id` 当唯一核心输出，而更愿意先输出：

- `actor_lane`
- `profile_id`

因为以后 actor lane 会直接影响 Work World 的构造。

---

### 3.2 Admission Policy：决定“这条消息要不要进入完整主线”

这就是现在 `run_mode` 那类东西，但我会把它命名得更清楚一点。  
它回答的是：

- `respond`
- `record_only`
- `silent_drop`

这同样应该是**单一胜者**决策。  
而且我会要求它和 Routing Policy 一样严格：

- 最终只能有一个结果
- 同级歧义要报错

因为“回不回复”这件事不能靠模糊合并。

---

### 3.3 Context Policy：决定“额外往上下文里装什么”

这一层我不会再和上面两层混。

它回答的是：

- 命中哪些 sticky note scope
- 是否追加某些 prompt slot
- 是否增加某些 retrieval tag
- 是否加一些上下文标签

这一层应该是**多条累加**，不是单一胜者。  
因为上下文本来就可能来自多个来源。

所以它的合并方式应该是：

- 所有命中的都收集
- 同类字段按明确规则 merge / append / dedupe
- 不做 winner-take-all

这是我从零设计时很想明确的一点：  
**上下文规则绝不能和路由规则用同一种解析方式。**

---

### 3.4 Persistence / Extraction Policy：决定“事件是否持久化、是否进入记忆提取”

这一层我甚至会比现在更激进一点：**我会拆成两层，而不是继续揉成一个 `EventPolicy`。**

#### 3.4.1 Persistence Policy
只回答：

- 这条 event 要不要写入事件存储

这是一个很单纯的单一胜者决策。

#### 3.4.2 Extraction Policy
只回答：

- 这条 event 要不要参与 memory extraction
- 带哪些 scopes
- 带哪些 tags

这一层我会允许一部分累加，比如 tags / scopes 可以 merge，但“extract 开关”本身最好仍然有明确主导来源。

这样拆开以后，语义会清楚很多。  
因为“要不要存 event”跟“要不要提记忆”不是同一个问题，现在揉在一个 policy 里，本来就有点别扭。

---

### 3.5 World / Computer Policy：决定“这个 actor 活在什么工作世界里”

这是最重要的，也是我最不想继续叫 rule 的一层。

它不该回答“这条消息在群里被 @ 了怎么办”，而该回答：

- 这次 actor 用哪个 backend
- 是否有 `/self`
- `/self` 是否可写
- `/skills` 视图怎么构造
- `/workspace` 是否只读
- 是否允许 exec / session
- 附件如何进入 Work World

这层我不想让它成为 event-driven rule。  
我更想把它设计成：

> **profile 的稳定 policy + actor kind + thread/session identity + operator override 的合成结果**

也就是说，它主要不是“消息命中某条 rule，所以 `/self` 出现了”，而是：

- 你是前台 agent，所以有 `/self`
- 你是 subagent，所以没有 `/self`
- 你这个 profile 可见哪些 skills
- 你这个 thread 当前被 operator override 成 docker backend

这层和消息事实的关系，应该明显比上面几层更弱。

---

## 4. 所以我会把“rule”这个词主动缩小，不让它吞掉 computer

从零设计的话，我会明确规定：

> **rule 只负责事件级决策，不负责 world 结构。**

也就是说，rule 可以影响：

- 这条消息给谁
- 回不回复
- 记不记 event
- 提不提记忆
- 加哪些上下文标签

但 rule **不应该直接影响**：

- `/workspace /skills /self` 哪些根出现
- 哪个根可见 / 不可见
- 哪个根可写 / 只读
- shell 里到底出现什么执行视图
- file tools 吃什么路径协议

这些属于 Work World / Computer Policy，不该继续塞进 rule。

这是我从零设计时最强的一条边界。

---

## 5. override 要单独成体系，不要继续伪装成 rule

我会把 override 明确设计成另一类东西：

- `thread_agent_override`
- `computer override`
- operator force docker
- 临时关闭 exec

这些都不该继续和 rule 混在一起。

因为它们的语义不是“系统常态决策”，而是：

> **运行中的临时人工干预。**

所以层次应该是：

1. Facts
2. Rules / Policies 做常态决策
3. Overrides 在最后窄口覆盖部分结果

这样一来，系统才不会继续出现那种：
“表面上是 rule system，实际上很多关键行为在 app 层再偷偷改一次”的感觉。

---

## 6. 如果完全从零设计，我会给出这样的整体结构

### 6.1 输入层
- `EventFacts`
- `ThreadFacts`
- `ActorFacts`

### 6.2 共享匹配层
- `MatchSpec`

### 6.3 事件级决策层
- `RoutingPolicy`
- `AdmissionPolicy`
- `ContextPolicy`
- `PersistencePolicy`
- `ExtractionPolicy`

### 6.4 世界构造层
- `WorkWorldPolicy`
- `MaintainerWorldPolicy`
- `WorldBuilder`

### 6.5 运行时覆盖层
- `RuntimeOverride`
- `ThreadOverride`
- `OperatorOverride`

### 6.6 执行层
- `ComputerRuntime`
- `ToolBroker`
- `HostBackend`
- `DockerBackend`

你会发现这里最关键的变化是：

> **computer / world builder 不再是 rule 系统里的一个后果，而是一个独立正式层。**

这就是我觉得你现在最该做的架构动作。

---

## 7. 如果压成最短版本，我会这样设计

如果你让我只用几句话描述“从零设计 rule”，我会这么说：

我不会设计一个大而全的 rule 系统。  
我会先做一套统一 matcher，再做几种决策引擎。  
Routing 和 Admission 是单一胜者，Context 是累加合并，Persistence/Extraction 拆开，Computer/World 则根本不属于普通 event rule，而是由 actor、profile、thread 和 policy 构造出来。  
override 再单独放在最末层，明确是临时人工干预，而不是规则本体。

---

## 8. 我对你现在系统的直觉判断

如果让我很直接地说：  
我觉得你现在最该重构的，不是“把现有 rule 修顺一点”，而是：

> **先把 computer / world 从 rule 里独立出来。**

只要这一刀没切出去，后面你不管怎么整理 binding/inbound/event-policy，都会继续有一种“所有东西都还是 rule，只是名字更多了”的味道。

---

如果你要，我下一条可以继续直接给你一个**更具体的草案**，例如：

- `MatchSpec` 长什么样
- 五类 policy 各自的 `then` 长什么样
- `WorldBuilder` 的输入输出长什么样

也就是把“从零设计”再往数据结构层落一层。