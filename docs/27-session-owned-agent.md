# Session-Owned Agent 设计决策

本文档记录 session-owned agent 模型的设计决策和理由。实现参考见 `04-routing-and-profiles.md`。

## 核心决策

- `tool`、`skill`、`subagent` 是全局注册的能力目录
- 每个 session 绑定一份专属的底层 agent，这份 agent 是独立对象，不内嵌在 session 配置里
- 这份 agent 不复用，不作为多个 session 共享的 profile
- 不采用"session 选择共享 profile 再额外做 override"的产品模型——因为这会让操作者难以判断修改影响面，破坏 WebUI 控制面的可解释性
- 如果需要复用，提供"从模板创建"或"从其他 session 复制 agent 配置"的显式动作，而不是多个 session 长期共享同一个可变 agent 对象。复用的正式单位是 template 或一次性 copy

## 职责分层

| 对象 | 回答什么 |
|------|---------|
| `session` | 这个会话怎么跑 |
| `session-owned agent` | 这个会话里的前台 agent 是谁、看得到哪些能力 |
| 全局 catalog | 系统里有哪些可选资源（prompt、tool、skill、subagent） |

## 对象模型和真源目录

```text
runtime_config/sessions/
  qq/
    group/
      123456/
        session.yaml      # session 配置
        agent.yaml         # session-owned agent
    private/
      12345/
        session.yaml
        agent.yaml
```

`session.yaml` 和 `agent.yaml` 逻辑上是两个对象，物理上放在同一个 session 目录下。`session.yaml` 通过 `frontstage_agent_id` 引用 agent，不再持有旧的前台 profile 字段。

`agent.yaml` 正式字段：`agent_id`、`prompt_ref`、`visible_tools`、`visible_skills`、`visible_subagents`、`computer_policy`、可选 `model_target`。只保存对全局 catalog 资源的引用和可见性配置，不复制资源实体。

`computer_policy` 是前台 agent 的默认 computer 能力，session.yaml 的 surface computer 决策只做场景化覆盖，不反向改写 agent.yaml 真源。Run 里记录本次实际使用的 `agent_id` 只是执行快照，不反过来成为真源。

## WebUI

- 左侧导航是 Sessions
- 点进某个 session，tab 有个 Agent
- Agent tab 配：Prompt、Tools、Skills、Subagents

产品上以 session 作为操作者看到的最小配置单位，不单独把"共享 agent 选择器"做成主入口。

## 命名收束

- 旧的前台 profile 入口 → `frontstage_agent_id`
- 旧的 routing/work-world 标识 → `agent_id`
- 前台正式语义里不再把这份对象叫 `profile`
