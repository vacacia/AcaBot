# 路由、Agent 和配置装配

本文档回答四个问题：一条消息为什么落到这个 thread、为什么会回复/只记录/丢弃、当前 run 为什么拿到这个 agent、agent/prompt/session config 从哪里来。

## 设计理念

### 为什么不用平行 rule

以前的思路是把不同问题分别塞进几套长得很像的规则里。问题是：消息为什么到了这个 agent、为什么会回复、为什么只记录不回复、为什么会进长期记忆、为什么这次 computer 是 host 或 docker——这些虽然都像"规则"，但不是同一种问题。如果都塞进平行 rule，最后匹配条件长得很像、决策阶段却完全不同、维护者要在脑子里把几套东西重新拼起来。

现在的思路：先把消息收成稳定事实，再按会话配置里的不同决策域，分别回答不同问题。每个问题都有自己的位置，不再混成一团。

### 为什么产品入口是 SessionConfig

对 bot 来说，最自然的产品单位是"一个会话"——这个私聊怎么处理、这个群怎么处理、这个会话默认用哪个 agent、mention bot 和普通群聊是不是同一种行为。所以主入口是 SessionConfig，贴近真实产品形态。profile 负责描述"这个 agent 是谁"，session config 负责描述"这个会话里的消息默认怎么跑"。看一个群的行为时有一个明确的落点，不需要在全局 rule 里来回翻。

### 为什么先有 Facts 再有决策

系统先把消息变成事实对象（群消息还是私聊、有没有 @bot、是不是在回复 bot、有没有附件、发送者角色、actor_id/channel_scope/thread_id），然后才进入决策层（交给谁、回不回复、进不进长期记忆、computer 配置）。把"输入是什么"和"系统怎么反应"彻底分开，好处是 debug 更容易、测试更容易、文档更清楚、新增决策域时不用重新发明消息匹配方式。

### 为什么中间还要 surface 解析

同一个会话里有很多种消息面：@bot、引用 bot、普通群聊路过、命令消息、notice。这些不该被压成一个大开关。所以先做一步 surface resolution 把当前消息放到某个明确的 surface 上，然后在这个 surface 下面分别算各决策域。surface 这层把"人类理解的消息类型"和"runtime 真正要算的决策"接起来。

### 为什么拆成不同决策域

消息进入系统后要连续回答很多不同问题：

| 决策域 | 回答什么 |
|--------|---------|
| `routing` | 交给谁 |
| `admission` | 回不回复 / 只记录 / 丢弃 |
| `persistence` | event 要不要持久化 |
| `extraction` | 带哪些长期记忆 tags |
| `context` | 当前轮上下文怎么补 |
| `computer` | computer / world 怎么配 |

同一个 surface 下按不同决策域分别算结果，每一层只回答一种问题。想改"这条消息要不要回复"就碰 admission，不用顺手改 routing 或 memory。

### SessionRuntime / RuntimeRouter / Agent 各管什么

**SessionRuntime** 是设计中心：把事件收成 EventFacts → 定位 session → 解析 surface → 算出各决策域结果。回答"这条消息在当前会话里应该怎样被解释"。

**RuntimeRouter** 是装配层：生成稳定 ID（actor_id、channel_scope、thread_id）→ 把 session runtime 算好的结果收成 RouteDecision。回答"把这些决策整理成运行时能执行的路由结果"。

**Agent 配置**（通过 SessionBundleLoader / SessionAgentLoader）只负责描述 agent 身份：agent_id、name、prompt_ref、enabled_tools、skills、computer policy。回答"这个 agent 是谁、默认带什么能力"，不回答"这条消息为什么 respond / record_only / silent_drop"。

一句话：**SessionConfig 决定消息在当前会话里怎么跑，Agent 配置决定被选中的 agent 是谁和默认能力，RuntimeRouter 把这些收成 runtime 要执行的对象。**

## 主线

```
StandardEvent → SessionRuntime → RuntimeRouter → RouteDecision → SessionBundleLoader / PromptLoader
```

## SessionRuntime

`src/acabot/runtime/control/session_runtime.py`、`session_loader.py`、`contracts/session_config.py`

SessionRuntime 提供以下决策方法（由 `RuntimeRouter.route()` 按顺序编排调用）：

1. `build_facts(event)` — 标准化成 EventFacts（同时生成 actor_id、channel_scope、thread_id 等稳定 ID）
2. `locate_session(facts)` — 定位 session 文件路径
3. `load_session(facts)` — 读取并解析 SessionConfig
4. `resolve_surface(...)` — 算命中的 surface
5. `resolve_routing(...)` — 走哪个 agent
6. `resolve_admission(...)` — respond / record_only / silent_drop
7. `resolve_context(...)` — retrieval tags、sticky note targets、context labels
8. `resolve_persistence(...)` — event 持久化
9. `resolve_extraction(...)` — 长期记忆 tags
10. `resolve_computer(...)` — computer/backend 决策

## RuntimeRouter

`src/acabot/runtime/router.py`

RuntimeRouter 是编排层：`route()` 方法按顺序调用 SessionRuntime 的各个方法，把决策结果收成 RouteDecision（thread_id/actor_id/channel_scope/agent/run_mode/各 decision）。稳定 ID（私聊 `qq:user:{id}`、群聊 `qq:group:{id}`，thread_id 默认等于 channel_scope）由 `SessionRuntime.build_facts()` 生成。

## run_mode

来自 session config 的 admission 决策，三个值：
- **respond**：走完整主线，调模型，发回复
- **record_only**：只记录事实和上下文，不发回复
- **silent_drop**：提前退出，不进 pipeline，不改 thread working memory

## Frontstage Agent 装配

Frontstage agent 指直接面向用户聊天的前台 agent（即 Aca 本身），与 backend agent（面向操作者的维护后台）相对。每个 session 在 `session.yaml` 中通过 `frontstage.agent_id` 指定前台 agent，对应的 agent 配置在同目录的 `agent.yaml` 中。

`session_bundle_loader.py`、`session_agent_loader.py`、`prompt_loader.py`、`config_control_plane.py`

SessionAgent（`agent.yaml`）的字段：`agent_id`、`prompt_ref`、`visible_tools`、`visible_skills`、`visible_subagents`、`computer_policy`。模型不在 session 里直接配置，主回复和 system 能力通过 `model_target / model_binding` 进入 runtime。

Agent 来源是文件系统 session bundle：
- `runtime_config/sessions/<platform>/<scope>/<id>/session.yaml`
- `runtime_config/sessions/<platform>/<scope>/<id>/agent.yaml`
- `runtime_config/prompts/`

SessionBundleLoader 承载前台 session-owned agent 真源，PromptLoader 只负责 prompt 解析。

## Prompt 解析

`src/acabot/runtime/control/prompt_loader.py`

`prompt_ref` 由 PromptLoader 解析，支持文件系统 prompt 和 chained fallback。改 prompt 功能时先确认改的是哪一层：agent 配置里对 prompt 的引用、prompt 文件本体、还是 loader 的回退顺序。

## Session Config 来源

`session_loader.py`、`session_runtime.py`、`config_control_plane.py`

生产环境从文件系统 session 目录加载：`runtime_config/sessions/` 下按 channel_scope 定位 `session.yaml`，这条线是"消息怎么决策"的主入口。测试中也可用 `StaticSessionConfigLoader` 做内存静态加载。

## WebUI 和热刷新

路径：WebUI → HTTP API → RuntimeControlPlane → RuntimeConfigControlPlane → 配置真源 / reload。

RuntimeConfigControlPlane 当前处理：session bundles、prompts、gateway、runtime plugins、session-config 驱动的 reload。

## 改动入口速查

| 想改什么 | 先看 |
|---------|------|
| 谁处理这条消息 | `session_runtime.py` routing + `router.py` + session config `routing` |
| 这条消息回不回复 | `session_runtime.py` admission + session config `admission` |
| event 持久化 / 长期记忆 | `session_runtime.py` persistence/extraction + session config 对应域 |
| agent 的模型/prompt/tools/skills | `session_bundle_loader.py` + `prompt_loader.py` + session bundle 文件 |

## 源码阅读顺序

1. `src/acabot/runtime/control/session_runtime.py`
2. `src/acabot/runtime/router.py`
3. `src/acabot/runtime/control/session_loader.py`
4. `src/acabot/runtime/control/session_bundle_loader.py`
5. `src/acabot/runtime/control/config_control_plane.py`
6. `src/acabot/runtime/bootstrap/`
