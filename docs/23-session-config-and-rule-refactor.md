# Session Config 与 Rule 重构：把“很多规则”收成“会话配置 + 少量决策层”

## 1. 这篇文档在解决什么问题

这篇文档不再沿用当前的 `binding rule / inbound rule / event policy` 思路去继续修补系统，而是从零重新回答一个问题：

> 对一个群聊 bot 来说，消息进入系统后，最合理的配置入口和决策结构到底应该是什么。

这里的目标不是做一个更大的 rule engine。恰恰相反，目标是把现在“很多规则长得很像、职责又混在一起、最后谁都说不清一条消息为什么这么跑”的状态收起来。

这篇文档和 `docs/22-work-world-computer-and-sandbox.md` 是配套关系：

- `22` 讲的是前台 Work World、computer、sandbox 的世界抽象
- `23` 讲的是消息进入系统后，谁来决定这次到底进入哪个会话配置、用哪个 profile、回不回复、存不存、记不记，以及用哪套 computer/world policy

如果 `22` 解决的是“世界长什么样”，那 `23` 解决的就是：

> **一条消息怎样被稳定地映射到一份会话配置，再从这份配置里算出各层决策结果。**

---

## 2. 为什么现有 rule 系统会让人觉得“怪”

如果只看 `src/acabot/runtime/contracts/routing.py`，现在系统里有三类规则：

- `BindingRule`
- `InboundRule`
- `EventPolicy`

它们表面上是三套不同规则，但代码形状几乎一模一样。三者都有几乎同一套匹配字段：

- `event_type`
- `message_subtype`
- `notice_type`
- `notice_subtype`
- `actor_id`
- `channel_scope`
- `targets_self`
- `mentions_self`
- `mentioned_everyone`
- `reply_targets_self`
- `sender_roles`

而且三者都各自带了一套：

- `matches()`
- `match_keys()`
- `specificity()`

这说明一个很直接的事实：

> **系统里真正存在的不是三种不同 matcher，而是一种共同 matcher 被复制了三遍。**

这不是唯一问题。更大的问题是，这三套东西处在不同决策阶段，但又都被叫成 rule，于是很容易让人误以为：

- 路由是谁处理
- 是否进入主线
- 是否持久化 / 进入长期记忆

这些事情都属于同一种决策逻辑。

实际上它们根本不是一回事。

再往外看，系统里其实还有第四条线：运行时 override。比如：

- `thread_agent_override`
- `computer_override`

这说明当前系统并不是“规则中心统一决策”，而是：

- rule
- override
- profile/config
- control plane

几条线一起在改最终行为。

所以现在这套东西让人感觉“怪怪的”，不是因为字段多，而是因为：

> **同一种 matcher 被复制了三遍，不同决策阶段又被都叫成 rule，再叠一些旁路，最后看起来什么都像规则，实际上什么都没被讲清楚。**

---

## 3. 如果从零设计，我不会设计“一个总 rule 系统”

这是这篇文档最核心的结论。

如果完全不看现有实现，我不会设计一个大而全的 rule engine。我会先拆成三件事：

- 统一的事实输入
- 统一的 matcher
- 少量不同的决策层

原因很简单：不是所有“规则”都该用同一种思路。

有些事情必须是单一胜者，例如“这条消息最终交给谁”。有些事情更适合累加，例如“这次上下文额外补哪些提示或标签”。有些事情根本不该是事件 rule，而该是稳定 policy，例如 Work World 的 computer/world policy。

所以从零设计时，我更希望系统长成：

> **Facts + 共享 Matcher + 几种不同决策引擎**

而不是继续长成：

> “三类 rule + 一些 override + 一些旁路”。

---

## 4. 第一层不是 rule，而是 Facts

任何外部消息进入系统后，第一步都应该先变成一份标准事实对象。它只回答“发生了什么”，不回答“系统应该怎么办”。

例如，一条消息标准化后，至少应该有这些事实：

- `platform`
- `event_kind`
- `scene`
  - `private`
  - `group`
  - `notice`
  - `command`
- `actor_id`
- `channel_scope`
- `thread_id`
- `targets_self`
- `mentions_self`
- `reply_targets_self`
- `mentioned_everyone`
- `sender_roles`
- `attachments_present`
- `attachment_kinds`
- `message_subtype`
- `notice_type`
- `notice_subtype`

如果后面某一层还在自己重新推导这些信息，说明 Facts 还不够完整。

所以先立一条总原则：

> **先统一输入事实，再做任何匹配和决策。**

---

## 5. 第二层是共享 Matcher，不是三套长得一样的 rule class

我会单独抽一层统一 matcher，例如：

- `MatchSpec`
- 或 `EventSelector`

它只负责表达：

> “什么样的输入事实会命中这条策略。”

例如：

```yaml
when:
  scene: group
  mentions_self: true
  sender_roles: [admin]
```

这一层里不应该出现：

- `profile`
- `mode`
- `persist_event`
- `backend`

因为这些不是“匹配什么”，而是“命中后做什么”。

这样拆开以后，系统里至少终于只有一种 matcher 语言，而不是三套几乎一样的 dataclass 在各做各的事。

---

## 6. 更适合 bot 的产品入口，不是一堆散 rule，而是会话级配置文件

我觉得对 AcaBot 来说，最适合的产品形态不是让人直接编辑三套 rule，而是让人编辑：

> **会话级配置文件。**

也就是说，产品主入口应该更像：

- Telegram 私聊一个模板
- Telegram 群聊一个模板
- QQ 私聊一个模板
- QQ 群聊一个模板

然后这些模板实例化成真正的会话配置，例如：

```text
sessions/
  qq/
    group/
      123456.yaml
    user/
      998877.yaml
  telegram/
    group/
      -100123456.yaml
    user/
      555666.yaml
```

一条消息进来后，先根据它的 Facts 找到对应的 session config，再由这份配置决定：

- 默认前台 profile 是什么
- 默认怎么响应
- 默认怎么存储
- 默认怎么进记忆
- 默认 computer/world policy 是什么
- 某些更细的条件下有没有局部修正

这比让人 mentally 合并三套底层 rule，更符合 bot 这种“一个群/一个私聊本来就该有自己的配置”的产品形态。

但这里有一个非常重要的前提：

> **对外是会话配置文件，对内仍然要拆成不同决策层。**

也就是说，runtime 不应该真的把它当成“一坨万能规则”直接现查现算，而应该先把它拆译成不同的决策输入。

---

## 7. Session Config 不该太窄，它应该先有一套 Surface Matrix

前面如果只写：

- `response.default_mode`

那会太窄。真实 bot 面对的，不是一种消息，而是很多种“可配置事件面”。

对一个 `qq_group` 模板来说，至少就可能有：

- `message.mention`
- `message.reply_to_bot`
- `message.plain`
- `message.command`
- `notice.member_join`
- `notice.member_leave`
- `notice.admin_change`
- `notice.file_upload`
- `request.friend`
- `request.group_invite`
- ...

所以 Session Config 的主干，不应该只是几个默认值，而应该是一套：

> **Template-defined Surface Matrix**

也就是说，模板先定义这个会话类型下，有哪些“可配置面”；每个面再有自己的一组默认决策。

例如：

```yaml
surfaces:
  message.mention:
    routing:
      default:
        profile: aca.qq.group.default
    admission:
      default:
        mode: respond
    persistence:
      default:
        persist_event: true
    extraction:
      default:
        tags: []
    computer:
      default:
        preset: sandbox_member

  message.plain:
    admission:
      default:
        mode: record_only
```

这才比较像 bot 的真实配置面。

---

## 8. 不要有全能的 `special_cases`，而应该是每个决策域自己的局部 case

这里是这次重写最重要的修正。

我现在不建议设计一个全能的：

```yaml
special_cases:
  - when: ...
    apply:
      routing: ...
      response: ...
      persistence: ...
      extraction: ...
      computer: ...
```

因为这种结构太松了，很快又会长成一个万能规则引擎。

更稳的做法是：

> **先有 surface，再在每个决策域下面各自挂 case。**

也就是说，不是有一个大 case 列表全能修改，而是：

- `routing.default + routing.cases`
- `admission.default + admission.cases`
- `persistence.default + persistence.cases`
- `extraction.default + extraction.cases`
- `computer.default + computer.cases`

这样每个 case 的职责天然就被限制住了。它只能改自己那一域的有效决策，不能顺手改所有东西。

### 8.1. 例子：管理员可 host，普通群员必须 sandbox

这是一个很好的 computer case 例子：

```yaml
surfaces:
  message.mention:
    computer:
      default:
        preset: sandbox_member
      cases:
        - case_id: admin_can_use_host
          when:
            sender_roles: [admin]
          use:
            preset: host_operator

        - case_id: ordinary_member_stays_sandboxed
          when:
            sender_roles: [member]
          use:
            preset: sandbox_member
```

这里 `when` 的输入就是 Facts，`use` 的输出只允许改 computer 这一域。不会顺便去动 routing 或 memory。

### 8.2. 例子：普通群消息默认只记录，但带附件时进入响应

这属于 admission case：

```yaml
surfaces:
  message.plain:
    admission:
      default:
        mode: record_only
      cases:
        - case_id: attachment_upgrades_to_respond
          when:
            attachments_present: true
          use:
            mode: respond
```

### 8.3. 例子：reply 给 bot 时用另一个 profile

这属于 routing case：

```yaml
surfaces:
  message.reply_to_bot:
    routing:
      default:
        profile: aca.qq.group.default
      cases:
        - case_id: admin_reply_uses_admin_profile
          when:
            sender_roles: [admin]
          use:
            profile: aca.qq.group.admin
```

所以这里最关键的一句可以直接记住：

> **case 不是“修改配置文件”，而是“在某个 surface 下，按 Facts 局部修改当前决策域的 effective decision”。**

---

## 9. case 的输入输出到底应该是什么

为了让这套东西不再重新变怪，我建议把边界写得非常死。

### 9.1. case 的输入

case 的输入只允许匹配 Facts，也就是 `when` 里只能写标准化后的输入事实，例如：

- `scene`
- `event_kind`
- `mentions_self`
- `reply_targets_self`
- `sender_roles`
- `attachments_present`
- `attachment_kinds`
- `actor_id`
- `channel_scope`

不要让 case 去匹配运行时内部状态，更不要让 case 去直接判断 world 根结构。

### 9.2. case 的输出

case 的输出只允许修改当前决策域允许改的字段。

也就是：

- routing case 只能改 routing
- admission case 只能改 admission
- persistence case 只能改 persistence
- extraction case 只能改 extraction
- computer case 只能改 computer

这样一来，即使 case 很多，也不会长成万能规则引擎。

### 9.3. 如果多个域想复用同一个条件怎么办

我不建议为了避免重复，又回到“全能 case”。

更稳的做法是引入可复用 selector，例如：

```yaml
selectors:
  sender_is_admin:
    sender_roles: [admin]
```

然后不同决策域各自引用它：

```yaml
routing:
  cases:
    - case_id: admin_profile
      when_ref: sender_is_admin
      use:
        profile: aca.qq.group.admin

computer:
  cases:
    - case_id: admin_host
      when_ref: sender_is_admin
      use:
        preset: host_operator
```

这样既能复用条件，又不会重新引入一个全能 case。

---


## 11. 真正需要的决策对象是什么

如果按上面的结构走，runtime 里真正需要的对象就会变得很清楚。

### `RoutingDecision`

- `actor_lane`
- `profile_id`
- `reason`
- `source_case_id`
- `priority`
- `specificity`

### `AdmissionDecision`

- `mode`
- `reason`
- `source_case_id`

### `ContextDecision`

- `sticky_note_scopes`
- `prompt_slots`
- `retrieval_tags`
- `context_labels`
- `notes`

### `PersistenceDecision`

- `persist_event`
- `reason`
- `source_case_id`

### `ExtractionDecision`

- `tags`
- `reason`
- `source_case_id`

### `ComputerPolicyDecision`

- `actor_kind`
- `backend`
- `allow_exec`
- `allow_sessions`
- `roots`
- `visible_skills`
- `notes`

这些决策对象再进入 `docs/22` 里定义的 Work World 构造流程。

也就是说：

- `23` 负责重新定义决策层
- `22` 负责解释这些决策结果如何变成前台世界

---

## 12. 这套设计和 `docs/22` 的关系

`22` 已经明确了一条非常重要的架构约束：

> Work World 的构造依据应该是少数稳定输入；rule 不应该直接参与 computer 的路径构造。

这篇 `23` 做的事情，就是把那句约束收成更具体的配置与决策结构。

也就是说：

- Facts 提供统一输入
- Session Config 提供唯一配置真源
- Surface Matrix 提供模板级默认面
- Domain Cases 提供局部条件修正
- Final Decisions 提供稳定结果
- Work World 再根据这些稳定结果被构造出来

所以 `23` 不是和 `22` 竞争，而是在给 `22` 提供一个更合理的上游。

---

## 13. 最后的总判断

如果把整篇文档压成一句话，那就是：

> AcaBot 的 rule 重构不应该继续往“更大的 rule engine”走，而应该往“会话级配置文件 + 模板定义的 surface matrix + 各决策域自己的 default/cases + 统一 Facts/Matcher”这条路走；其中 case 只负责按 Facts 局部修改当前决策域的 effective decision，不再引入全能 `special_cases`，也不再保留通用 override 或 patch。这样既符合 bot 产品对“会话配置”的直觉，也能真正和 `docs/22` 里的 Work World 设计对齐。
