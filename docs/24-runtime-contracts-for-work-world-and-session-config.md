# Work World 与 Session Config 的运行时契约

本文档把 `22`（Work World 世界抽象）和 `23`（Session Config 决策层设计）接起来，收成真正可以指导代码改造的运行时契约。不讨论产品愿景，只回答运行时的实际问题：消息进入后被变成什么对象、会话配置怎样被定位加载使用、各决策阶段的输入输出是什么、Work World 什么时候被构造、computer/tool/shell/attachment staging 吃什么输入。

## 总顺序

运行时主线顺序固定：

```
EventFacts → Session Locator → SessionConfig → Surface Resolution → Domain Decisions → World Input Bundle → Work World Build
```

每一层只做自己的事。Facts 回答"发生了什么"；Session Locator 回答"属于哪份会话配置"；SessionConfig 提供长期真源；Surface Resolution 把消息放到模板定义的事件面上；Domain Decisions 分别算出 routing/admission/persistence/extraction/context/computer 决策；最后整理成 World Input Bundle 交给 Work World builder 构造 `/workspace`、`/skills`、`/self` 和 execution view。

**Work World 由一组已收稳的输入构造，不由 rule 直接拼出。**

## 核心输入对象

### EventFacts

所有后续决策的统一输入，只回答"发生了什么"。最小字段：`platform`、`event_kind`、`scene`（private/group/notice/command）、`actor_id`、`channel_scope`、`thread_id`、`targets_self`、`mentions_self`、`reply_targets_self`、`mentioned_everyone`、`sender_roles`、`attachments_present`、`attachment_kinds`、`message_subtype`、`notice_type`、`notice_subtype`。如果后面 matcher 还在重新推导这些字段，说明 EventFacts 不够完整。

### SessionLocatorResult

回答"这条消息对应哪个 session config"。字段：`session_id`、`template_id`、`config_path`、`channel_scope`、`thread_id`。只负责定位会话，不解释配置内容。

### SessionConfig

人类编辑的对象，运行时唯一配置真源。两部分主结构：会话级基线信息 + 模板定义的 surface matrix。

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
      default: { profile: aca.qq.group.default }
      cases: []
    admission:
      default: { mode: respond }
      cases: []
    persistence:
      default: { persist_event: true }
      cases: []
    extraction:
      default: { tags: [] }
      cases: []
    computer:
      default: { preset: sandbox_member }
      cases: []
```

主干是**模板先定义有哪些 surface，每个 surface 按决策域提供 default + cases**。

### OriginHandle

附件相关输入。附件一开始通常不是文件而是平台引用（file_id、URL、reply 图片引用、gateway API 返回的附件引用）。只有在后续 staging 后才进入 Work World 变成 `/workspace/attachments/...` 下的正式文件对象。

## 共享 Matcher（MatchSpec）

运行时只有一种 matcher 语言。MatchSpec 只回答"什么样的 EventFacts 会命中这条 case"，不带任何业务输出。字段与 EventFacts 对应。specificity、priority、冲突检查、case 复用都围绕同一套 matcher 完成。详见 `23` 中的设计说明。

## Surface Resolution

EventFacts + SessionConfig 结合后先得到 `SurfaceResolution`：当前消息命中的 surface 是什么、在当前模板里是否存在、对应哪个配置块。完成后，后面的 domain decision 围绕当前 surface 的 `default + cases` 工作，不再跨层找规则。

## 决策对象

每个决策域都是 `default + cases` 结构（详见 `23`）。Case 输入只来自 EventFacts，输出只改自己那一域。

| Decision | 回答什么 | 关键字段 |
|----------|---------|---------|
| `RoutingDecision` | 交给谁处理（单一胜者） | actor_lane、agent_id、reason、source_case_id、priority、specificity |
| `AdmissionDecision` | 要不要进完整主线（单一胜者） | mode（respond/record_only/silent_drop）、reason、source_case_id |
| `ContextDecision` | 额外补哪些上下文（允许累加） | sticky_note_scopes、prompt_slots、retrieval_tags、context_labels、notes |
| `PersistenceDecision` | event 要不要写入事件存储 | persist_event、reason、source_case_id |
| `ExtractionDecision` | 带哪些长期记忆 tags | tags、reason、source_case_id |
| `ComputerPolicyDecision` | Work World 怎么构造（与 `22` 直接相接） | actor_kind、backend、allow_exec、allow_sessions、roots（每个 root 的可见性/可写性）、visible_skills、notes |

## 示例：管理员可 host，普通群员必须 sandbox

```yaml
surfaces:
  message.mention:
    computer:
      default:
        preset: sandbox_member
      cases:
        - case_id: admin_can_use_host
          when: { sender_roles: [admin] }
          use: { preset: host_operator }
        - case_id: ordinary_member_stays_sandboxed
          when: { sender_roles: [member] }
          use: { preset: sandbox_member }
```

输入只是 Facts 里的 `sender_roles`，输出只改 computer 这一域，不顺手改 routing 或 memory。

## Runtime 使用 Session Config 的过程

1. 把外部消息变成 EventFacts
2. SessionLocator 找到对应 SessionConfig
3. 根据模板和 Facts 做 SurfaceResolution
4. 对每个决策域分别算出 Decision
5. 把决策结果整理成 WorldInputBundle
6. 交给 Work World builder 构造 `/workspace`、`/skills`、`/self`

会话配置文件不直接"驱动 shell"或"改 computer 世界"，只通过决策对象把稳定输入喂给 Work World。

## 与 docs/22 的衔接

22 的关键约束：Work World 的构造依据是少数稳定输入，rule 不应该直接参与 computer 的路径构造。

最终进入 Work World 的是：`actor_kind`、`agent_id`、`thread_id`/`channel_scope`、`ComputerPolicyDecision`、当前附件来源（OriginHandles）。Session Config 和 cases 负责算出决策，真正构造 Work World 的是决策结果而不是配置文件原文。

`/self` 的边界写死：
- 前台 agent：可见可写
- subagent：完全不可见

这不是 Session Config 里某条 case 可以临时打开的洞，而是 ComputerPolicyDecision 和 Work World builder 的正式边界。
