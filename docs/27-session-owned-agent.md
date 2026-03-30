# Session 与 Agent 结论

- `tool`、`skill`、`subagent` 是全局注册的能力目录。
- 每个 `session` 绑定一份自己专属的底层 `agent`。这份 `agent` 是独立对象，不内嵌在 `session` 配置里。
- 这份 `agent` 不复用，不作为多个 `session` 共享的 `profile`。
- 用户在 `session` 页面配置可见 `tool`、`skill`、`subagent` 时，本质上是在配置这份 `session` 专属 `agent` 的能力可见性。
- 不采用“`session` 选择共享 `profile`，再额外做 override”的产品模型。
- 当前代码还不是这个模型。
- 当前代码仍然是“`session` 指向 `frontstage_profile`，再从全局 `profile registry` 取 `AgentProfile`”。
- 后续改造目标是把当前模型收成“`session` 绑定自己专属的独立 `agent` 对象”。


WebUI怎么做?
- 左侧导航还是 Sessions
- 点进某个 session, tab 有个 Agent
- Agent tab 里配：Prompt,Tools,Skills,Subagents


建议补充
- 产品上继续以 `session` 作为操作者看到的最小配置单位, 不单独把“共享 agent/profile 选择器”做成主入口。
- 运行时里仍然保留 `agent` 作为正式对象, 但这份 `agent` 默认属于当前 `session`, 是 `session-owned agent`, 不是多个 `session` 共同引用的活对象。
- `prompt`、`tool`、`skill`、`subagent` 继续作为全局 catalog 存在。`session-owned agent` 只保存对这些资源的引用和可见性配置, 不复制资源实体。
- `session` 页面里的 `Agent` tab, 本质上是在编辑“当前 `session` 自己那份 agent”, 不是在编辑一个可能被别的 `session` 共享的 profile。
-  `session-owned agent` 至少应包含这些正式字段: `prompt_ref`、`visible_tools`、`visible_skills`、`visible_subagents`。后续如果确实需要, 再加入 `model_target`、`computer_policy` 这类 agent 自身配置。
- 不采用“`session` 选择共享 profile, 再局部 override”的模型。因为这会让操作者难以判断修改影响面, 破坏 WebUI 控制面的可解释性。
- 如果后续确实需要复用, 应该提供“从模板创建”或“从其他 session 复制 agent 配置”的显式动作, 而不是让多个 `session` 长期共享同一个可变 agent 对象。
- 也就是说, 复用的正式单位应该是 `template` 或一次性的 `copy`, 不应该是会实时联动的共享 frontstage agent。
- 这条线下, `session` 回答“这个会话怎么跑”, `session-owned agent` 回答“这个会话里的前台 agent 是谁、看得到哪些能力”, 全局 catalog 回答“系统里有哪些可选资源”。


已确认的对象模型和真源目录

- 第一阶段正式引入 `session-owned agent`。它是独立真源对象, 不是 `session.yaml` 里的内嵌大对象。
- 一个 `session` 对应一个正式配置目录。这个目录同时承载当前 `session` 本身和它的前台 `agent` 真源。
- 正式目录形态固定为:

```text
sessions/
  qq/
    group/
      123456/
        session.yaml
        agent.yaml
    private/
      12345/
        session.yaml
        agent.yaml
```

- `session.yaml` 和 `agent.yaml` 在逻辑上是两个对象, 在物理上放在同一个 session 目录下。
- `session.yaml` 不再持有 `frontstage_profile` 这类旧字段。命名正式收成 `frontstage_agent_id`。
- `agent.yaml` 表达“这个 session 自己的前台 agent 是谁, 默认具备哪些能力”。它不是全局共享 profile, 也不是多个 session 共用的活对象。
- 全局共享的仍然是 catalog:
  - `prompt`
  - `tool`
  - `skill`
  - `subagent`
- `agent.yaml` 只保存对这些 catalog 资源的引用和可见性配置, 不复制资源实体。
- 第一阶段 `agent.yaml` 的正式字段至少包含:
  - `agent_id`
  - `prompt_ref`
  - `visible_tools`
  - `visible_skills`
  - `visible_subagents`
  - `computer_policy`
  - 可选的 `model_target`
- `agent.yaml` 里的 `computer_policy` 是前台 agent 的默认 computer 能力。
- `session.yaml` 的 surface `computer` 决策只做场景化覆盖, 不反向改写 `agent.yaml` 真源。
- run 里继续记录本次实际使用的 `agent_id`, 但它只是执行快照, 不反过来成为真源。
- 第一阶段就正式把旧词收掉:
  - `frontstage_profile` -> `frontstage_agent_id`
  - `profile_id` -> `agent_id`
  - 前台正式语义里不再把这份对象叫 `profile`
- `SessionConfig` 具体应该正式承载哪些决策域和字段, 后续单独收束, 不在这一段先写死。
