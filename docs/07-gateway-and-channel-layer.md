# Gateway 和渠道适配层

Gateway 只做两件事：把外部平台事件翻译成 `StandardEvent`，把系统要发出去的 `Action` 翻回平台 API。路由决策、agent 选择、工具调度、长期记忆提取、prompt 组装都在 runtime 主线里，不在 gateway。

## 关键文件

| 文件 | 职责 |
|------|------|
| `src/acabot/gateway/base.py` | `BaseGateway` 抽象基类 |
| `src/acabot/gateway/napcat.py` | NapCat / OneBot v11 实现 |
| `src/acabot/gateway/onebot_message.py` | 消息段解析（reply、mention、附件、纯文本提取） |
| `src/acabot/runtime/gateway_protocol.py` | `GatewayProtocol`——runtime 真正依赖的接口 |
| `src/acabot/types/event.py` | `StandardEvent` 定义 |
| `src/acabot/types/action.py` | `Action` 定义 |

## BaseGateway 与 GatewayProtocol

`BaseGateway` 是实现层的抽象基类，`GatewayProtocol` 是 runtime 接线时真正依赖的协议。RuntimeApp、Outbox、MessageResolutionService 不需要知道具体是不是 NapCatGateway，只要满足 GatewayProtocol（能收事件、能发动作、能 `call_api`）。换平台时可以继续按 BaseGateway 写实现，也可以只保证满足 GatewayProtocol。

## NapCatGateway

当前 QQ / OneBot v11 入口。作为反向 WebSocket 服务端等 NapCat 主动连进来，校验 token，接收 OneBot v11 JSON，把入站 JSON 翻译成 StandardEvent，把 Action 翻译成 OneBot API 请求，处理 `call_api()` 的请求-响应匹配。

## 入站消息翻译

翻译分两层：

**`napcat.py`**：判断 `post_type`，区分 message 和 notice，组装最终 StandardEvent，记录网关侧日志。

**`onebot_message.py`**：解析 reply、mention、附件，提取纯文本。如果 reply 没提出来、mention 信息不对、图片/文件没进 attachments，先看 `onebot_message.py` 再看 `napcat.py`。

### 已翻译的事件类型

**message** 事件整理出：EventSource、segments、reply_reference、mentioned_user_ids、mentioned_everyone、attachments、mentions_self、reply_targets_self、targets_self。runtime 后面能直接拿到文本段、reply 引用、图片/文件附件、@ 信息和"是否冲着 bot 来的"。

**notice** 事件当前支持：poke、recall、member_join、member_leave、admin_change、file_upload、friend_added、mute_change、lucky_king、honor_change、title_change。

## Gateway → Runtime 的交接

```
Gateway.on_event(...) → RuntimeApp.handle_event(...)
```

RuntimeApp 里事件先经过后台入口判断（`_handle_backend_entrypoint`），再进普通前台主线（`router.route`），最后进入 ThreadPipeline。不是所有 gateway 事件都直接进前台 agent，有些会先被后台入口接走。

## Gateway 与 runtime/inbound/ 的边界

**Gateway** 负责：平台 JSON → StandardEvent、提取 reply/mention/附件原始信息、提供 `call_api()` 给下游查平台数据。

**`runtime/inbound/`** 负责：把当前消息真正要用的材料补齐（reply 文字和图片补回、图片说明），整理成 history 版本、model 输入版本和 memory 候选材料。

关键文件：`message_preparation.py`、`message_resolution.py`、`message_projection.py`、`image_context.py`。

简单记：gateway 负责"平台翻译"，inbound 负责"这轮消息怎么给 runtime 和模型用"。

## Reply 和图片的完整链路

1. NapCatGateway 把当前消息翻成 StandardEvent
2. 当前消息自带的附件先进入 `event.attachments`
3. `ComputerRuntime.prepare_run_context()` 做附件 staging
4. `MessageResolutionService` 需要时通过 `gateway.call_api("get_msg", ...)` 把 reply 消息拉回来，再抽文字和图片
5. `MessageProjectionService` 决定历史文本、模型输入、记忆候选材料怎么组织

Gateway 不直接负责图片说明和把 reply 内容塞进 prompt，只负责把能拿到的原始事实先交出来。

## 出站动作

```
PlannedAction → Outbox → Gateway.send(Action) → 平台 API
```

runtime 决定"做什么"，outbox 统一发送和消息入库，gateway 按平台协议发出去。改动涉及 ActionType、Outbox、Gateway.send() 时三处要一起看。

NapCat 当前出站映射如下：
- `SEND_TEXT` / `SEND_SEGMENTS` → `send_private_msg` 或 `send_group_msg`
- `RECALL` → `delete_msg`
- `REACTION` → `set_msg_emoji_like`

`REACTION` 的 payload 约定为 `{"message_id": ..., "emoji_id": ...}`。gateway 只负责把这个底层动作翻成 NapCat 扩展 API, 不负责 emoji 名称解析。emoji alias / Unicode → `emoji_id` 的映射在统一 `message` builtin tool 里完成。

## call_api()

不是所有平台能力都该抽成通用 ActionType。平台特有查询、一次性原生能力、只在某个平台上有意义的接口更适合 `call_api()`。当前典型例子：`get_msg`、`get_group_member_info`、`get_forward_msg`。要加"查平台原始数据"的功能时优先用 `call_api()`。

## 常见问题

1. **只改 `napcat.py` 忘了 `onebot_message.py`**：事件进来了但 reply/mention/attachment 不对。
2. **在 gateway 做业务判断**：该不该回复、该走哪个 agent、遇到图片要不要调模型——都不该放这里。
3. **只看 gateway 不看 `runtime/inbound/`**：很多"图片没生效""reply 没进模型输入"不是 gateway 没翻译，而是消息整理链没接住。
4. **只改出站动作不看 Outbox**：Action 结构改了但 Outbox 没同步，消息发不出去。

## 源码阅读顺序

平台字段翻译问题先看前四个，进了系统后怎么被用的问题看后面几个：

1. `src/acabot/gateway/base.py`
2. `src/acabot/runtime/gateway_protocol.py`
3. `src/acabot/gateway/onebot_message.py`
4. `src/acabot/gateway/napcat.py`
5. `src/acabot/runtime/app.py`
6. `src/acabot/runtime/inbound/message_resolution.py`
7. `src/acabot/runtime/inbound/message_projection.py`
8. `src/acabot/runtime/inbound/message_preparation.py`
9. `src/acabot/runtime/outbox.py`
