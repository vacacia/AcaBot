# Gateway 和渠道适配层

这一层只做两件事：

1. 把外部平台事件翻译成 AcaBot 能处理的 `StandardEvent`
2. 把 AcaBot 要发出去的动作翻回平台 API

这层不要负责：

- 该不该回复
- 该走哪个 agent
- 该用哪个 tool
- 该不该提取长期记忆
- prompt 最后怎么组

这些事情都在 runtime 主线里，不在 gateway。

## 当前正式入口

现在要以这些文件为准：

- `src/acabot/gateway/base.py`
- `src/acabot/gateway/napcat.py`
- `src/acabot/gateway/onebot_message.py`
- `src/acabot/runtime/gateway_protocol.py`
- `src/acabot/types/event.py`
- `src/acabot/types/action.py`

可以把它们简单理解成两层：

### 实现层

- `BaseGateway`
- `NapCatGateway`

这一层是真正和平台协议打交道的代码。

### runtime 依赖层

- `GatewayProtocol`

这一层是 runtime 真正依赖的接口形状。
`RuntimeApp`、`Outbox`、`MessageResolutionService` 这些地方不需要知道具体是不是 `NapCatGateway`，只要对象满足 `GatewayProtocol` 就行。

## `BaseGateway` 和 `GatewayProtocol` 的关系

现在的真实情况不是“只能靠 `BaseGateway` 跑”，而是：

- `BaseGateway` 是实现层常用的抽象基类
- `GatewayProtocol` 是 runtime 接线时真正依赖的协议

所以如果你以后换平台：

- 可以继续按 `BaseGateway` 这套写一个实现
- 也可以只保证这个实现满足 `GatewayProtocol`

关键不是继承关系，关键是：

- 能收事件
- 能发动作
- 能做 `call_api`

## `NapCatGateway` 现在负责什么

`NapCatGateway` 是当前 QQ / OneBot v11 入口。

它做的事情很直接：

- 作为反向 WebSocket 服务端，等 NapCat 主动连进来
- 校验 token
- 接收 OneBot v11 的 JSON
- 把入站 JSON 翻译成 `StandardEvent`
- 把 `Action` 翻译成 OneBot API 请求
- 处理 `call_api()` 的请求-响应匹配

它不是调度器，也不是业务层。

## 入站消息怎么翻译

现在翻译主要分两块：

### 1. `napcat.py`

负责：

- 判断 `post_type`
- 区分 `message` 和 `notice`
- 组装最终的 `StandardEvent`
- 记录网关侧日志

### 2. `onebot_message.py`

负责：

- 解析 reply
- 解析 mention
- 解析附件
- 提取纯文本

也就是说，现在消息段细节不是全堆在 `NapCatGateway` 里了。
如果你发现：

- reply 没提出来
- mention 信息不对
- 图片/文件没有进 `attachments`

先看 `onebot_message.py`，再看 `napcat.py`。

## 当前已经翻译的事件类型

### message

消息事件会整理出这些关键信息：

- `EventSource`
- `segments`
- `reply_reference`
- `mentioned_user_ids`
- `mentioned_everyone`
- `attachments`
- `mentions_self`
- `reply_targets_self`
- `targets_self`

所以 runtime 后面已经能直接拿到：

- 文本段
- reply 引用信息
- 图片/文件附件
- @ 信息
- 这条消息是不是冲着 bot 来的

### notice

当前 `NapCatGateway` 已经能翻这些 notice：

- `poke`
- `recall`
- `member_join`
- `member_leave`
- `admin_change`
- `file_upload`
- `friend_added`
- `mute_change`
- `lucky_king`
- `honor_change`
- `title_change`

如果后面 notice 类型继续增加，这篇文档应该跟着改，不要继续只写旧的那几种。

## gateway 把事件交给谁

现在正式主线是：

`Gateway.on_event(...) -> RuntimeApp.handle_event(...)`

也就是说：

- gateway 负责把平台消息翻成 `StandardEvent`
- `RuntimeApp` 负责接住这个标准事件，送进 runtime 主线

在 `RuntimeApp.handle_event(...)` 里，事件会先经过：

1. 后台入口判断：`_handle_backend_entrypoint(event)`
2. 普通前台主线：`router.route(event)`
3. 再进入 `ThreadPipeline`

所以现在的真实情况不是“所有 gateway 事件都直接进前台 agent”。
有些事件会先被后台入口接走。

## gateway 和 `runtime/inbound/` 的边界

这块很容易看混。

### gateway 负责什么

- 平台 JSON → `StandardEvent`
- 提取 reply / mention / 附件这些原始可用信息
- 提供 `call_api()` 给下游继续查平台数据

### `runtime/inbound/` 负责什么

- 把当前消息真正要用的材料补齐
- 把 reply 里的文字和图片补回来
- 做图片说明
- 把材料整理成：
  - history 版本
  - model 输入版本
  - memory 候选材料

当前这条链主要在这些文件：

- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/inbound/message_resolution.py`
- `src/acabot/runtime/inbound/message_projection.py`
- `src/acabot/runtime/inbound/image_context.py`

可以简单记成：

- gateway 负责“平台翻译”
- inbound 负责“这轮消息怎么真正给 runtime 和模型用”

## reply 和图片现在怎么走

当前 reply / 图片不是在 gateway 里一次做完的。
真正流程是：

1. `NapCatGateway` 把当前消息先翻成 `StandardEvent`
2. 当前消息自带的附件先进入 `event.attachments`
3. `ComputerRuntime.prepare_run_context()` 会先做附件 staging
4. `MessageResolutionService` 需要时再通过 `gateway.call_api("get_msg", ...)` 把 reply 消息拉回来
5. `MessageResolutionService` 再从 reply 里抽文字和图片
6. `MessageProjectionService` 再决定历史文本、模型输入、记忆候选材料怎么组织

所以：

- gateway 不直接负责图片说明
- gateway 不直接负责把 reply 内容塞进 prompt
- gateway 只负责把“能拿到的原始事实”先交出来

## 出站动作怎么走

当前出站主线是：

`PlannedAction -> Outbox -> Gateway.send(Action) -> 平台 API`

边界很清楚：

- runtime 决定“做什么”
- outbox 负责统一发送和消息入库
- gateway 决定“怎么按平台协议发出去”

如果一个改动会碰到：

- `ActionType`
- `Outbox`
- `Gateway.send()`

那三处通常要一起看，不要只改一处。

## `call_api()` 什么时候用

不是所有平台能力都应该抽成通用 `ActionType`。

这些情况更适合 `call_api()`：

- 平台特有查询
- 一次性的原生能力
- 只在某个平台上有意义的接口

当前典型例子：

- `get_msg`
- `get_group_member_info`
- `get_forward_msg`

如果你要加的是“查平台原始数据”，优先想 `call_api()`，不要先急着扩通用动作枚举。

## 现在最容易踩的坑

### 1. 只改 `napcat.py`，忘了 `onebot_message.py`

结果就是：

- 事件看起来进来了
- 但 reply / mention / attachment 还是不对

### 2. 在 gateway 偷偷做业务判断

比如：

- 该不该回复
- 该走哪个 agent
- 遇到图片要不要直接调用模型

这些都不该放这里。

### 3. 只看 gateway，不看 `runtime/inbound/`

很多“图片没生效”“reply 没进模型输入”的问题，不是 gateway 没翻译，而是后面的消息整理链没接住。

### 4. 只改出站动作，不看 `Outbox`

如果 `Action` 结构改了，但 `Outbox` 没同步，runtime 里看着没问题，实际消息还是发不出去。

### 5. 把 `BaseGateway` 当成 runtime 唯一入口

runtime 现在真正依赖的是 `GatewayProtocol`。文档和代码理解都要以这个边界为准。

## 改这层时建议先看哪些源码

建议顺序：

1. `src/acabot/gateway/base.py`
2. `src/acabot/runtime/gateway_protocol.py`
3. `src/acabot/gateway/onebot_message.py`
4. `src/acabot/gateway/napcat.py`
5. `src/acabot/runtime/app.py`
6. `src/acabot/runtime/inbound/message_resolution.py`
7. `src/acabot/runtime/inbound/message_projection.py`
8. `src/acabot/runtime/inbound/message_preparation.py`
9. `src/acabot/runtime/outbox.py`

如果是平台字段翻译问题，先看前四个。  
如果是“进了系统以后怎么被用掉”的问题，再往后看 runtime 这几层。