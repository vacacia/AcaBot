# Session Config 与 Rule 重构

## 问题背景

本文档从零重新回答一个问题：对一个群聊 bot 来说，消息进入系统后，最合理的配置入口和决策结构是什么。目标不是做更大的 rule engine，而是把"很多规则长得很像、职责混在一起、最后谁都说不清一条消息为什么这么跑"的状态收起来。

与 `docs/22-work-world-computer-and-sandbox.md` 配套：22 讲前台 Work World、computer、sandbox 的世界抽象；23 讲消息进入系统后谁来决定会话配置、profile、响应方式、存储策略和 computer/world policy。22 解决"世界长什么样"，23 解决**一条消息怎样被稳定地映射到一份会话配置，再从这份配置里算出各层决策结果**。

## 旧 Rule 系统的问题

`routing.py` 里原有三类规则：`BindingRule`、`InboundRule`、`EventPolicy`。三者表面是不同规则，但代码形状几乎一样——都有同一套匹配字段（event_type、message_subtype、notice_type、notice_subtype、actor_id、channel_scope、targets_self、mentions_self、mentioned_everyone、reply_targets_self、sender_roles），都各自带一套 `matches()`、`match_keys()`、`specificity()`。

系统里真正存在的不是三种不同 matcher，而是**一种共同 matcher 被复制了三遍**。更大的问题是，这三套东西处在不同决策阶段（路由是谁处理、是否进入主线、是否持久化/进入长期记忆），但都被叫成 rule，容易让人误以为它们属于同一种决策逻辑。

系统里还有第四条线——运行时 override（`thread_agent_override`、`computer_override`）。实际上 rule、override、profile/config、control plane 几条线一起在改最终行为。同一种 matcher 被复制三遍，不同决策阶段都叫 rule，再叠一些旁路，最后什么都像规则，实际什么都没讲清楚。

## 从零设计的核心结论

不会设计一个大而全的 rule engine。会先拆成三件事：**统一的事实输入 + 统一的 matcher + 少量不同的决策层**。

不是所有"规则"都该用同一种思路：有些必须是单一胜者（"这条消息最终交给谁"），有些适合累加（"这次上下文额外补哪些标签"），有些根本不该是事件 rule 而该是稳定 policy（Work World 的 computer/world policy）。

从零设计应该长成 **Facts + 共享 Matcher + 几种不同决策引擎**，而不是"三类 rule + 一些 override + 一些旁路"。

## 第一层：Facts

任何外部消息进入系统后，第一步先变成标准事实对象。它只回答"发生了什么"，不回答"系统应该怎么办"。

标准化后的事实至少包含：`platform`、`event_kind`、`scene`（private/group/notice/command）、`actor_id`、`channel_scope`、`thread_id`、`targets_self`、`mentions_self`、`reply_targets_self`、`mentioned_everyone`、`sender_roles`、`attachments_present`、`attachment_kinds`、`message_subtype`、`notice_type`、`notice_subtype`。

如果后面某一层还在自己重新推导这些信息，说明 Facts 还不够完整。总原则：**先统一输入事实，再做任何匹配和决策。**

## 第二层：共享 Matcher

单独抽一层统一 matcher（`MatchSpec` / `EventSelector`），只负责表达"什么样的输入事实会命中这条策略"：

```yaml
when:
  scene: group
  mentions_self: true
  sender_roles: [admin]
```

matcher 里不应该出现 profile、mode、persist_event、backend——这些不是"匹配什么"，而是"命中后做什么"。系统里终于只有一种 matcher 语言。

## 产品入口：会话级配置文件

对 AcaBot 来说，最适合的产品形态不是让人直接编辑三套 rule，而是**会话级配置文件**。产品主入口是按平台 + 场景 + 会话实例组织的配置：

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

一条消息进来后，先根据 Facts 找到对应的 session config，再由这份配置决定：默认前台 agent、响应方式、存储策略、记忆提取、computer/world policy、局部修正。这比让人 mentally 合并三套底层 rule 更符合 bot 的产品形态。

重要前提：**对外是会话配置文件，对内仍然要拆成不同决策层。** runtime 不应该真的把它当成一坨万能规则直接现查现算。

## Surface Matrix

Session Config 的主干不应该只是几个默认值，而是一套 **Template-defined Surface Matrix**——模板定义这个会话类型下有哪些"可配置面"，每个面有自己的一组默认决策。

对一个 `qq_group` 模板，至少有：`message.mention`、`message.reply_to_bot`、`message.plain`、`message.command`、`notice.member_join`、`notice.member_leave`、`notice.admin_change`、`notice.file_upload` 等。

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

## Domain Cases（不是全能 special_cases）

不设计全能的 `special_cases`（一个大 case 列表能改所有域），因为这种结构太松，很快会长成万能规则引擎。

更稳的做法：**先有 surface，再在每个决策域下面各自挂 case。** 每个 case 只能改自己那一域的 effective decision：

- `routing.default + routing.cases`
- `admission.default + admission.cases`
- `persistence.default + persistence.cases`
- `extraction.default + extraction.cases`
- `computer.default + computer.cases`

### 示例：管理员可 host，普通群员必须 sandbox

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

`when` 的输入是 Facts，`use` 的输出只允许改 computer 这一域。

### 示例：普通群消息默认只记录，带附件时进入响应

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

### 示例：reply 给 bot 时管理员用另一个 profile

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

**case 不是"修改配置文件"，而是"在某个 surface 下，按 Facts 局部修改当前决策域的 effective decision"。**

## Case 的输入输出边界

### 输入

Case 的 `when` 只允许匹配 Facts（标准化后的输入事实）：scene、event_kind、mentions_self、reply_targets_self、sender_roles、attachments_present、attachment_kinds、actor_id、channel_scope。不让 case 去匹配运行时内部状态，不让 case 直接判断 world 根结构。

### 输出

Case 的 `use` 只允许修改当前决策域允许改的字段。routing case 只能改 routing，admission case 只能改 admission，以此类推。即使 case 很多也不会长成万能规则引擎。

### 复用条件

不回到"全能 case"。引入可复用 selector：

```yaml
selectors:
  sender_is_admin:
    sender_roles: [admin]
```

不同决策域各自引用：

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

既能复用条件，又不引入全能 case。

## 决策对象

| Decision | 关键字段 |
|----------|---------|
| `RoutingDecision` | actor_lane、agent_id、reason、source_case_id、priority、specificity |
| `AdmissionDecision` | mode、reason、source_case_id |
| `ContextDecision` | sticky_note_scopes、prompt_slots、retrieval_tags、context_labels、notes |
| `PersistenceDecision` | persist_event、reason、source_case_id |
| `ExtractionDecision` | tags、reason、source_case_id |
| `ComputerPolicyDecision` | actor_kind、backend、allow_exec、allow_sessions、roots、visible_skills、notes |

这些决策对象再进入 docs/22 里定义的 Work World 构造流程。23 负责定义决策层，22 负责解释决策结果如何变成前台世界。

## 与 docs/22 的关系

22 明确了一条重要架构约束：Work World 的构造依据应该是少数稳定输入，rule 不应该直接参与 computer 的路径构造。23 把这条约束收成更具体的配置与决策结构：

Facts 提供统一输入 → Session Config 提供唯一配置真源 → Surface Matrix 提供模板级默认面 → Domain Cases 提供局部条件修正 → Final Decisions 提供稳定结果 → Work World 根据这些稳定结果被构造出来。

## 总结

AcaBot 的 rule 重构不应该往"更大的 rule engine"走，而应该往**会话级配置文件 + 模板定义的 surface matrix + 各决策域自己的 default/cases + 统一 Facts/Matcher** 走。Case 只负责按 Facts 局部修改当前决策域的 effective decision，不引入全能 special_cases，不保留通用 override 或 patch。这样既符合 bot 产品对"会话配置"的直觉，也能和 docs/22 里的 Work World 设计对齐。
