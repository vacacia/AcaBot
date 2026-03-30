# Session-Owned Agent 前台真源硬切 Spec

## 目标

这份 spec 只做一件事：

- 把 AcaBot 前台正式模型从“`session -> shared profile`”硬切到“`session-owned agent`”，并把 backend/runtime 与 control plane 的正式真源、命名和接口一次收对。

这份 spec 不是实现计划。它是后续实现计划的前提。

## 第一阶段范围

第一阶段只覆盖：

- backend/runtime
- control plane
- 正式真源目录
- 前台 API 契约
- 测试与文档清理

第一阶段不覆盖：

- WebUI 具体实现
- 模板复用产品形态
- 其他未直接参与前台主线的历史兼容逻辑

WebUI 在第一阶段只需要以新的 `/api/sessions` 契约为目标，不进入本次实现范围。

## 命名决议

前台正式语义里不再继续使用 `profile` 这组词。

第一阶段开始，正式命名统一收成：

- `frontstage_profile` -> `frontstage_agent_id`
- `profile_id` -> `agent_id`
- `AgentProfile` 不再作为前台正式语义里的对象名继续演化

如果运行时仍然需要一个“本次 run 正在使用的 agent 配置快照对象”，应该优先采用更直白的新名字，例如：

- `ResolvedAgent`
- `SessionAgentSnapshot`

而不是继续沿用 `profile` 这个已经混淆过多的旧词。

## 一、正式对象与真源目录

### 1.1 正式对象

前台正式对象收成四类：

- `SessionConfig`
  - 表示当前会话自己的正式配置对象。
- `SessionAgent`
  - 表示当前会话自己的前台 agent 真源对象。
- `Catalog Objects`
  - `prompt`
  - `tool`
  - `skill`
  - `subagent`
- `Run Snapshot`
  - 表示一次实际执行使用了谁，但它不是反向真源。

其中最关键的决议是：

> 每个 `session` 都绑定自己专属的 `session-owned agent`。这份对象是独立真源, 不是共享 profile, 也不是 `session.yaml` 里的内嵌大对象。

### 1.2 正式真源目录

一个 `session` 对应一个正式配置目录。这个目录同时承载：

- 当前 `session` 本身的真源
- 当前 `session` 前台 `agent` 的真源

正式目录形态固定为：

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

这里的原则是：

- `session.yaml` 和 `agent.yaml` 在逻辑上是两个对象
- 它们在物理上放在同一个 session 目录下
- 一个 session 的正式配置盒子就在一个目录里，不再跨多个全局 registry 拼装

### 1.3 `session.yaml` 与 `agent.yaml` 的关系

- `session.yaml` 不再持有 `frontstage_profile` 这类旧字段
- `session.yaml` 改为表达“当前 session 绑定哪份前台 agent”，正式命名收成 `frontstage_agent_id`
- `agent.yaml` 表达“这个 session 自己的前台 agent 是谁，默认具备哪些能力”
- `session.yaml.frontstage_agent_id` 与同目录 `agent.yaml.agent_id` 必须一致
- loader 必须校验这两个字段的一致性，不允许静默猜测或自动修正
- `frontstage_agent_id` 是 session 底层的内部标识，不是操作者直接编辑的业务字段
- `agent.yaml.agent_id` 同样是 session 底层的内部标识，不是操作者直接编辑的业务字段
- session 创建后不允许修改 `frontstage_agent_id`
- session 创建后不允许修改 `agent.yaml.agent_id`

也就是说：

- `session.yaml` 不直接内嵌 agent 配置大对象
- `agent.yaml` 也不是全局共享 profile
- 两者是独立对象，只是放在同一个 session 目录中

### 1.4 `agent.yaml` 的正式字段

第一阶段 `agent.yaml` 的正式字段至少包含：

- `agent_id`
- `prompt_ref`
- `visible_tools`
- `visible_skills`
- `visible_subagents`
- `computer_policy`
- 可选的 `model_target`

这份对象只保存对全局 catalog 的引用和可见性配置，不复制资源实体。

## 二、Catalog 与能力边界

下列对象继续保持全局 catalog：

- `prompt`
- `tool`
- `skill`
- `subagent`

`SessionAgent` 只负责：

- 选择要引用哪个 `prompt`
- 声明哪些 `tool` 可见
- 声明哪些 `skill` 可见
- 声明哪些 `subagent` 可见
- 声明默认 `computer_policy`
- 可选声明 `model_target`

也就是说：

- 全局 catalog 回答“系统里有哪些可选资源”
- `session-owned agent` 回答“这个 session 的前台 agent 默认看得到哪些资源”

## 三、运行时正式解析路径

第一阶段前台运行时正式解析路径收成：

`StandardEvent -> SessionLocator -> SessionBundleLoader -> SessionRuntime -> RuntimeRouter -> RuntimeApp -> ThreadPipeline`

这条线里的关键变化是：

- 不再存在“`session -> frontstage_profile -> global profile registry`”这条前台正式解析链
- 当前 session 的前台身份，统一从 session 目录中的 `agent.yaml` 取

### 3.1 `SessionLocator`

`SessionLocator` 负责：

- 根据当前事件定位 `session_id`
- 根据 `session_id` 定位 `sessions/<platform>/<scope>/<id>/` 目录

### 3.2 `SessionBundleLoader`

`SessionBundleLoader` 负责把一个 session 目录读成完整 bundle。

返回的 bundle 至少包含：

- `session_config`
- `frontstage_agent`
- `paths`

也就是说，从这一层开始，运行时把“一个 session 的正式配置盒子”当成统一入口。

### 3.3 `SessionRuntime`

`SessionRuntime` 继续负责：

- facts
- surface
- 决策域解析

但它不再承担“去全局共享 profile registry 找当前前台身份”的职责。

它只认当前 session bundle 里的 `frontstage_agent_id`，并把本次最终使用的 `agent_id` 收进路由结果。

### 3.4 `RuntimeRouter`

`RuntimeRouter` 继续负责把 session runtime 的结果收成 `RouteDecision`。

但它的 `agent_id` 不再表示“命中的共享 profile 名”，而表示“当前 session 目录里的前台 agent”。

### 3.5 `RuntimeApp`

`RuntimeApp` 不再依赖旧的 `profile_loader(decision)` 作为前台正式接缝。

它改成：

- 按当前 session bundle 读取 `frontstage_agent`
- 基于这份对象构造当前 run 使用的 agent 快照

### 3.6 模型解析

模型解析不再默认把前台主线理解成“共享 profile 对应的 `agent:<agent_id>` target”。

第一阶段正式规则是：

- `SessionAgent` 可以显式声明自己的 `model_target`
- run 级模型解析按当前 session-owned agent 取值
- 不再回退到旧的前台 profile 真源

## 四、Computer 默认能力与 Surface 覆盖

第一阶段确认采用两层模型：

- `agent.yaml` 里的 `computer_policy` 是前台 agent 的默认 computer 能力
- `session.yaml` 的 surface `computer` 决策只做场景化覆盖

这里的“覆盖”含义固定为：

- 只影响当前命中 surface 的这一次 run
- 不反向改写 `agent.yaml`
- 不改变前台 agent 的默认真源

这条规则允许表达类似这样的场景：

- 默认前台 agent 允许较强 computer 能力
- 普通群成员消息默认走较弱隔离环境
- 管理员消息或明确触发的 surface 才允许更高权限 backend(host)

## 五、Control Plane 与前台 API

第一阶段 control plane 也同步硬切，不保留旧前台 profile 入口作为正式主入口。

新的正式前台入口是：

- `POST /api/sessions`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `PUT /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/agent`
- `PUT /api/sessions/{session_id}/agent`

推荐返回形状是：

- `GET /api/sessions`
  - 只返回 session 摘要
  - 不内嵌完整 agent 配置
- `GET /api/sessions/{session_id}`
  - 返回 `session`
  - 返回 `agent`
  - 返回当前 session 目录相关路径

这样 control plane 的对象边界和文件真源完全一致。

### 5.1 最小接口示例

`GET /api/sessions/{session_id}` 的最小返回形状建议是：

```json
{
  "session": {
    "session_id": "qq:group:123456",
    "frontstage_agent_id": "frontstage"
  },
  "agent": {
    "agent_id": "frontstage",
    "prompt_ref": "prompt/aca/default",
    "visible_tools": ["read", "write"],
    "visible_skills": ["frontend-design"],
    "visible_subagents": ["excel-worker"]
  },
  "paths": {
    "session_dir": "/abs/sessions/qq/group/123456",
    "session_config_path": "/abs/sessions/qq/group/123456/session.yaml",
    "agent_config_path": "/abs/sessions/qq/group/123456/agent.yaml"
  }
}
```

这里返回的 `frontstage_agent_id / agent_id` 只是内部只读观测字段，不是前台操作者直接编辑的业务输入。

`POST /api/sessions` 的最小输入形状建议是：

```json
{
  "session_id": "qq:group:123456",
  "title": "Aca Group Session"
}
```

`PUT /api/sessions/{session_id}` 只更新 `session.yaml`，最小输入形状建议是：

```json
{
  "title": "Aca Group Session"
}
```

如果请求试图修改 `frontstage_agent_id`，control plane 必须直接拒绝，而不是尝试协调改写 `agent.yaml.agent_id`。

`POST /api/sessions` 是第一阶段唯一正式的 session 创建入口。创建时由 control plane 一次性写出同目录的 `session.yaml + agent.yaml`，并分配内部使用的 `frontstage_agent_id / agent_id`；操作者不在创建或更新接口里显式提供这两个字段。

`PUT /api/sessions/{session_id}/agent` 只更新 `agent.yaml`，最小输入形状建议是：

```json
{
  "prompt_ref": "prompt/aca/default",
  "visible_tools": ["read", "write"],
  "visible_skills": ["frontend-design"],
  "visible_subagents": ["excel-worker"],
  "computer_policy": {
    "backend": "docker",
    "allow_exec": true,
    "allow_sessions": true
  }
}
```

如果请求试图修改或重命名 `agent_id`，control plane 也必须直接拒绝。第一阶段不支持 session-owned agent 重命名。

### 5.2 旧前台接口退场

第一阶段完成时，下面这些不再保留为前台正式配置入口：

- `/api/profiles`
- `list_profiles`
- `get_profile`
- `upsert_profile`
- `delete_profile`

如果后续系统内部还需要临时保留部分 helper，也不再允许它们参与前台主线解析。

## 六、硬切清理策略

第一阶段明确采用“硬切清理”策略，不保留旧前台 profile 模型的任何正式入口、兼容层或双轨状态。

也就是说，第一阶段完成时，系统必须满足：

- 前台正式真源只认 `session.yaml + agent.yaml`
- 前台运行时不再存在旧的共享 profile 解析链
- 前台 control plane 不再暴露 `/api/profiles` 作为正式入口
- 文档、字段名、测试断言里不再继续使用前台语义下的 `profile`、`frontstage_profile`、`profile_id`
- 不允许因为旧 `runtime.profiles` 仍然存在, 就偷偷继续跑旧逻辑
- 搜索关键词, 无旧策略的结果

### 6.1 错误处理原则

第一阶段错误处理采用“显式创建 + 已配置 bundle 硬错误”的策略，不猜测，不回退，不兜旧路：

- 未配置 session 收到事件 -> 不自动创建、不进入前台执行主线、不回复当前消息，并记录带 `session_id` 的可观测告警或限流日志
- session 目录已存在但 `session.yaml` 缺失 -> 直接报 session 真源不完整
- `session.yaml` 存在但 `agent.yaml` 缺失 -> 直接报 session agent 真源不完整
- `frontstage_agent_id` 与 `agent.yaml` 冲突 -> 直接报真源冲突
- `agent.yaml` 引用的 `prompt/tool/skill/subagent` 不存在 -> 直接返回明确错误
- 不允许回退到旧 registry 或旧 config 路径

## 七、测试策略

测试也同步硬切，不做“新旧都能过”的双轨测试。

第一阶段需要新增或重写这些测试：

- session 目录 bundle 加载测试
- `session.yaml + agent.yaml` 缺失、冲突、引用失效的错误测试
- `SessionRuntime -> RuntimeRouter -> RuntimeApp` 使用 session-owned agent 的主线测试
- control plane 的 `/api/sessions` 与 `/api/sessions/{id}/agent` 测试
- 现有 session 真源样例和 fixtures 迁移到 `session.yaml + agent.yaml` 形态的测试

第一阶段需要删除或退出正式主线的测试包括：

- 前台 profile CRUD API 测试
- 围绕 `default_agent_id / runtime.profiles / /api/profiles` 的前台行为断言
- 默认共享 profile 仍作为前台真源的测试前提

## 八、本 Spec 当前不写死的内容

下面这些内容在这份 spec 里不先写死，后续在实现计划中再按当前 runtime 主线单独收束：

- `SessionConfig` 的完整正式字段集合
- WebUI 的具体页面交互和路由落地
- 模板复用产品形态
- 非前台主线的历史遗留对象如何在代码里清理到最终形态

这份 spec 当前只写死这些已经确认的结论：

- `session-owned agent` 是独立真源对象
- 一个 session 一个目录，里面放 `session.yaml + agent.yaml`
- 前台正式语义里不再继续使用 `profile`
- `computer_policy` 属于前台 agent 默认能力，surface `computer` 只做场景化覆盖
- 第一阶段采用硬切清理，不保留旧前台 profile 模型
