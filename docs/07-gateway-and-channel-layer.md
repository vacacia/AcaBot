# Gateway 和渠道适配层

这一层的职责很朴素:

把外部平台说的话翻译成系统能懂的对象，再把系统要做的动作翻回平台 API。

别给它加太多戏。

## 当前正式入口

相关文件:

- `src/acabot/gateway/base.py`
- `src/acabot/gateway/napcat.py`
- `src/acabot/types/event.py`
- `src/acabot/types/action.py`

现在的抽象还是 `BaseGateway`，不是 `agent-first/` 里设想的新名字。

## `BaseGateway` 契约

核心方法:

- `start()`
- `stop()`
- `send(action)`
- `on_event(handler)`
- `call_api(action, params)`

从职责上看，这已经很接近一个 channel adapter 了。

## `NapCatGateway` 现在做了什么

它是 OneBot v11 反向 WebSocket 服务端。

职责包括:

- 等 NapCat 反连进来
- 校验 token
- 接收事件 payload
- 翻译成 `StandardEvent`
- 把 `Action` 翻译成 OneBot API 调用
- 处理 `call_api` 请求响应匹配

## 事件翻译

现在正式支持两大类:

- `message`
- 部分 `notice`

notice 里已经处理了好几种常见事件，比如:

- `poke`
- `recall`
- `member_join`
- `member_leave`
- `admin_change`
- `file_upload`

### message 翻译时会做的事

- 生成 `EventSource`
- 转 `segments`
- 抽 `reply_reference`
- 抽 mention 信息
- 抽 `attachments`
- 计算 `targets_self`

所以如果你发现上游 OneBot payload 里明明有图片，但 runtime 里没法拿到，多半先查这里。

## 出站动作

出站不是直接在 pipeline 里调平台 API，而是:

`PlannedAction -> Outbox -> Gateway.send(Action) -> OneBot API`

这层的边界非常重要:

- runtime 负责决定“要做什么”
- gateway 负责决定“怎么用平台协议做出来”

## 哪些逻辑不要写进 Gateway

不要写:

- 该不该响应
- 用哪个 agent
- 记忆提取策略
- tool 审批
- prompt 组装

判断标准很简单:

如果未来换 Telegram、Discord 之后，这段逻辑还应该保留，那它大概率就不该写在 gateway。

## 图片和附件功能怎么接比较稳

这类需求通常会先碰 gateway。

建议顺序:

1. 先确认平台 payload 里有没有足够的原始信息
2. 确认 `StandardEvent.attachments` 能不能表达
3. 再决定下游是:
   - 直接吃远程 URL / file_id
   - 先拉成本地文件
   - 交给 computer runtime 做 staging

别在 gateway 里直接做复杂业务，比如“一收到图片就调用 VLM 并塞回复”。这层不适合。

## `call_api` 的意义

不是所有平台能力都值得抽成 `ActionType`。

查询类、平台特殊能力一般走 `call_api()`。

例子:

- `get_msg`
- `get_group_member_info`
- `get_forward_msg`

如果你要加的是平台特有查询，优先想 `call_api` 或现有 plugin，不要硬塞通用动作枚举。

## 当前这层和 `agent-first` 草稿的关系

`agent-first/01-channel-adapter.md` 提出的方向基本合理:

- 适配层只做协议翻译
- 不做业务调度

但当前真实实现还是 `BaseGateway + NapCatGateway`。写文档和改代码时要以现状为准。

## 改这层时最常见的问题

### 1. 加了新字段，但没同步到 `StandardEvent`

结果就是上游明明有数据，下游根本用不到。

### 2. 出站动作改了，但 Outbox 和 Gateway 没一起改

这会导致 action 在 runtime 里看着对，实际发不出去。

### 3. 在 Gateway 偷偷做业务过滤

这种改法短期看省事，后面排查 routing 和 policy 时会非常痛苦。

## 读源码顺序建议

1. `src/acabot/gateway/base.py`
2. `src/acabot/gateway/napcat.py`
3. `src/acabot/types/event.py`
4. `src/acabot/types/action.py`
5. `src/acabot/runtime/outbox.py`
