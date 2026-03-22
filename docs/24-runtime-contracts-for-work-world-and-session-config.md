# Work World 与 Session Config 的运行时契约

## 1. 这篇文档的定位

`22` 讲的是前台 Work World、computer、sandbox 的总设计。`23` 讲的是消息进入系统后的决策层，为什么应该从“很多 rule”收成“会话配置 + 少量决策层”。

这篇 `24` 再往前走一步：

> 把 `22` 和 `23` 里的抽象，收成真正可以指导代码改造的运行时契约。

它不讨论产品愿景，也不讨论长期演化方向。它只回答运行时最实际的几个问题：

- 一条消息进入系统后，先被变成什么对象
- 会话配置文件在 runtime 里怎样被定位、加载和使用
- 各个决策阶段的输入输出到底是什么
- Work World 是在什么时候被构造出来的
- `computer`、tool、shell、attachment staging 该吃什么输入

如果 `22` 解决的是“世界长什么样”，`23` 解决的是“谁来决定世界输入”，那 `24` 解决的就是：

> **这些东西在 runtime 里到底应该长成哪些正式对象，以及这些对象之间的先后关系。**

---

## 2. 总顺序：先有事实，再有决策，最后才有世界

运行时主线应该很简单，而且顺序必须固定：

```text
Facts
-> Session Locator
-> Session Config
-> Surface Resolution
-> Domain Decisions
-> World Input Bundle
-> Work World Build
```

这条顺序里，每一层都只做自己的事。

`Facts` 只回答“发生了什么”。`Session Locator` 只回答“这条消息属于哪份会话配置”。`Session Config` 提供会话的长期真源。`Surface Resolution` 负责把这条消息放到模板定义的某个事件面上。`Domain Decisions` 再分别算出 routing、admission、persistence、extraction、computer 这些决策结果。最后把这些结果整理成 `World Input Bundle`，交给 Work World builder 去构造 `/workspace /skills /self` 以及 execution view。

所以 Work World 不应该由 rule 直接拼出来，而应该由一组已经收稳的输入构造出来。

---

## 3. 核心输入对象

### 3.1. `EventFacts`

这是所有后续决策的统一输入。它只回答“发生了什么”，不回答“系统应该怎么办”。

建议最小字段至少包括：

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

如果后面 matcher 还在自己重新推导这些字段，说明 `EventFacts` 还不够完整。

### 3.2. `SessionLocatorResult`

这一层回答：

> 这条消息到底对应哪一个 session config。

最小字段建议包括：

- `session_id`
- `template_id`
- `config_path`
- `channel_scope`
- `thread_id`

这一层不解释配置内容，它只负责“定位会话”。

### 3.3. `SessionConfig`

这是人类真正编辑的对象，也是运行时的唯一配置真源。它不应该等于某个 rule 类，也不应该只是一些扁平默认值。

它应该有两部分主结构：

- 会话级基线信息
- 模板定义的 surface matrix

建议最小骨架如下：

```yaml
session:
  id: qq:group:123456
  template: qq_group
  title: 某某交流群

frontstage:
  profile: aca.qq.group.default

surfaces:
  message.mention:
    routing:
      default:
        profile: aca.qq.group.default
      cases: []

    admission:
      default:
        mode: respond
      cases: []

    persistence:
      default:
        persist_event: true
      cases: []

    extraction:
      default:
        extract_to_memory: true
        scopes: [channel]
        tags: []
      cases: []

    computer:
      default:
        preset: sandbox_member
      cases: []
```

这意味着 Session Config 的主干不是“很多 rule”，而是：

> **模板先定义有哪些 surface，每个 surface 再按决策域提供 default + cases。**

### 3.4. `OriginHandle`

附件相关输入还需要一个单独对象。因为附件一开始通常不是文件，而是平台引用。

例如：

- file_id
- URL
- reply 图片引用
- gateway API 返回的附件引用

它们都属于 `OriginHandle`。只有在后续 staging 之后，它们才会进入 Work World，变成 `/workspace/attachments/...` 下的正式文件对象。

---

## 4. 共享 matcher 应该长什么样

运行时应该只有一种 matcher 语言，而不是三套几乎一样的 rule dataclass 各自为战。

建议统一抽成 `MatchSpec`。它只负责回答：

> 什么样的 `EventFacts` 会命中这条 case。

最小字段建议包括：

- `platform`
- `event_kind`
- `scene`
- `actor_id`
- `channel_scope`
- `thread_id`
- `targets_self`
- `mentions_self`
- `reply_targets_self`
- `mentioned_everyone`
- `sender_roles`
- `message_subtype`
- `notice_type`
- `notice_subtype`
- `attachments_present`
- `attachment_kinds`

这个 `MatchSpec` 本身不应该带任何业务输出。它只表达“命中条件”。

这样以后：

- specificity
- priority
- 冲突检查
- case 复用

都可以围绕同一套 matcher 语言完成，而不必在不同规则系统里复制。

---

## 5. Surface Resolution：先把消息放到某个事件面上

这一层是 `23` 里最重要的新东西，也是当前系统缺得最明显的一层。

对 bot 来说，很多行为不是“消息来了统一一套规则”，而是：

- mention bot 的群消息
- reply 给 bot 的群消息
- 普通群消息
- command 消息
- 不同 notice

本来就应该属于不同 surface。

所以在 runtime 里，`EventFacts` 和 `SessionConfig` 结合后，应该先得到一个：

### `SurfaceResolution`

它回答：

- 当前消息命中的 surface 是什么
- 这个 surface 在当前模板里是否存在
- 对应的 surface 配置块是哪一个

例如：

- `message.mention`
- `message.reply_to_bot`
- `message.plain`
- `notice.member_join`

这一层完成后，后面的 domain decision 就都围绕当前 surface 的 `default + cases` 工作，不再跨层乱找规则。

---

## 6. 决策层应该拆成哪些正式对象

这里是整套契约的核心。不是所有决策都该继续叫 rule。

### 6.1. `RoutingDecision`

它回答：

- 这条消息交给谁处理
- 用哪个前台 profile
- 进入哪个 actor lane

建议字段至少包括：

- `actor_lane`
  - `frontstage`
  - `subagent`
  - `maintainer`
- `profile_id`
- `reason`
- `source_case_id`
- `priority`
- `specificity`

这是单一胜者决策。

### 6.2. `AdmissionDecision`

它回答：

- 这条消息要不要进入完整主线

建议结果枚举仍然保持清楚：

- `respond`
- `record_only`
- `silent_drop`

建议字段：

- `mode`
- `reason`
- `source_case_id`
- `priority`
- `specificity`

这也是单一胜者决策。

### 6.3. `ContextDecision`

它回答：

- 额外要补哪些上下文
- 命中哪些 sticky note scope
- 要加哪些 prompt slot
- retrieval tags 是什么

建议字段至少包括：

- `sticky_note_scopes`
- `prompt_slots`
- `retrieval_tags`
- `context_labels`
- `notes`

这一层允许多条累加，再按明确规则 merge / append / dedupe。

### 6.4. `PersistenceDecision`

它只回答：

- 这条 event 要不要写入事件存储

建议字段：

- `persist_event`
- `reason`
- `source_case_id`
- `priority`
- `specificity`

### 6.5. `ExtractionDecision`

它回答：

- 这条 event 要不要参与 memory extraction
- 带哪些 scopes
- 带哪些 tags

建议字段：

- `extract_to_memory`
- `memory_scopes`
- `tags`
- `reason`
- `source_case_id`
- `priority`
- `specificity`

这里 `extract_to_memory` 本身建议单一胜者，`memory_scopes` / `tags` 可以在明确规则下 merge。

### 6.6. `ComputerPolicyDecision`

这是和 `22` 最直接相接的一层。它回答的是：

- backend 是 host 还是 docker
- allow_exec / allow_sessions
- 当前 actor 是否有 `/self`
- `/skills` 视图如何构造
- `/workspace` 是否只读
- shell 最终用什么 execution view

建议字段至少包括：

- `actor_kind`
  - `frontstage_agent`
  - `subagent`
  - `maintainer`
- `backend`
  - `host`
  - `docker`
  - `remote`
- `allow_exec`
- `allow_sessions`
- `roots`
  - 每个 root 的可见性 / 可写性
- `visible_skills`
- `notes`

这层不是普通事件 rule，而是 surface / profile / actor lane / session config 决策后，最终进入 Work World 的稳定 policy。

---

## 7. 每个决策域都应该是 `default + cases`

这里是本次设计和旧思路最大的区别。

不要有一个全能的 `special_cases` 或 `conditional_cases` 列表去同时修改 routing、admission、persistence、extraction、computer。那样很快又会长成一个万能规则引擎。

更稳的做法是：

> **每个 surface 下，每个决策域自己都有 `default + cases`。**

也就是说：

- `routing.default + routing.cases`
- `admission.default + admission.cases`
- `persistence.default + persistence.cases`
- `extraction.default + extraction.cases`
- `computer.default + computer.cases`

这样每个 case 的边界天然就被限制住了。它只能修改自己那一域的有效决策。

### 7.1. case 的输入

case 的输入只允许来自 `EventFacts`，也就是：

- `scene`
- `event_kind`
- `mentions_self`
- `reply_targets_self`
- `sender_roles`
- `attachments_present`
- `attachment_kinds`
- `actor_id`
- `channel_scope`

### 7.2. case 的输出

case 的输出只允许修改当前决策域允许改的字段。

也就是：

- routing case 只能改 routing
- admission case 只能改 admission
- persistence case 只能改 persistence
- extraction case 只能改 extraction
- computer case 只能改 computer

这意味着：

> case 不是修改配置文件，而是局部修改当前这次事件的 effective decision。

配置真源本身不变。

### 7.3. 复用条件

如果多个域需要复用同一个条件，可以单独定义 selector：

```yaml
selectors:
  sender_is_admin:
    sender_roles: [admin]
```

然后在不同域的 case 里通过 `when_ref` 引用，而不是重新引入一个万能 case 层。

---

## 8. 一个具体案例：管理员消息可 host，普通群员消息必须 sandbox

这个案例很适合说明为什么 `computer` 决策也应该挂在 surface 下面。

例如：

```yaml
surfaces:
  message.mention:
    routing:
      default:
        profile: aca.qq.group.default
      cases: []

    admission:
      default:
        mode: respond
      cases: []

    persistence:
      default:
        persist_event: true
      cases: []

    extraction:
      default:
        extract_to_memory: true
        scopes: [channel]
        tags: []
      cases: []

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

这里有几个点很清楚：

- 这是 `message.mention` surface 下的 computer 决策
- 输入只是 Facts 里的 `sender_roles`
- 输出只是 `computer` 这一域的 effective decision
- 它不顺手去改 routing、memory 或 persistence

这就比一个万能 `special_cases` 清楚得多。

---

## 9. Runtime 里到底应该怎么用 Session Config

对人类来说，主入口是会话配置文件。对 runtime 来说，真正的使用过程应该是：

1. 把外部消息变成 `EventFacts`
2. 用 `SessionLocator` 找到对应的 `SessionConfig`
3. 根据模板和 Facts 做 `SurfaceResolution`
4. 对每个决策域分别算：
   - `RoutingDecision`
   - `AdmissionDecision`
   - `ContextDecision`
   - `PersistenceDecision`
   - `ExtractionDecision`
   - `ComputerPolicyDecision`
5. 把这些决策结果整理成 `WorldInputBundle`
6. 交给 `docs/22` 定义的 Work World builder 去构造 `/workspace /skills /self`

所以会话配置文件并不会直接“驱动 shell”或“直接改 computer 世界”，它只是通过这些决策对象，把稳定输入喂给 Work World。

---

## 10. 这套契约和 `docs/22` 的衔接点

`22` 里已经有一条非常关键的约束：

> Work World 的构造依据应该是少数稳定输入；rule 不应该直接参与 computer 的路径构造。

这篇 `24` 正是把那句约束落成正式对象。

最终进入 Work World 的，不应该是 Session Config 本身，也不应该是某个 case 本身，而应该是：

- `actor_kind`
- `profile_id`
- `thread_id` / `channel_scope`
- `ComputerPolicyDecision`
- 当前附件来源（`OriginHandles`）

所以这里最关键的一层转换是：

> Session Config 和 cases 负责算出决策；真正构造 Work World 的，是决策结果，不是配置文件原文。**

这样一来，`computer` 和 sandbox 的世界才不会被“配置里随便一条 case”直接篡改结构。

特别是 `/self` 的边界，在这里必须继续写死：

- 前台 agent：`/self` 可见可写
- subagent：`/self` 完全不可见

这不是 Session Config 里某条 case 可以临时打开的洞，而是 `ComputerPolicyDecision` 和 Work World builder 的正式边界。

---

## 11. 最后的总判断

如果把整篇文档压成一句话，那就是：

> `24` 这一层运行时契约，应该把 `22` 的 Work World 和 `23` 的 Session Config 重构真正接起来：先有 `EventFacts`，再定位 `SessionConfig`，再基于模板 surface 和各决策域的 `default + cases` 算出一组稳定的决策对象，最后再把其中的 `ComputerPolicyDecision` 和附件来源一起送进 Work World builder。这样 AcaBot 才真正拥有一条清楚的主线：会话配置是唯一真源，决策层各自独立，Work World 只吃稳定输入，computer 和 sandbox 也终于不再被混杂 rule 直接塑形。