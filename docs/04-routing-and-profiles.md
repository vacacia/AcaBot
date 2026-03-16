# 路由、Profile 和配置装配

这一篇回答三个问题:

1. 一条消息为什么落到这个 agent
2. 为什么这条消息会回复 / 只记录 / 直接丢弃
3. profile、prompt、rule 是从哪里来的

## 先看路由的输入和输出

输入是 `StandardEvent`。

输出是 `RouteDecision`。

中间会把三类东西一起算出来:

- thread / actor / channel 这些稳定 ID
- agent 绑定
- `run_mode` 和 event policy

## `RuntimeRouter` 真正做了什么

在 `src/acabot/runtime/router.py`。

它先算三个基础 ID:

- `actor_id`
- `channel_scope`
- `thread_id`

当前默认规则很直接:

- 私聊: `qq:user:{user_id}`
- 群聊: `qq:group:{group_id}`
- `thread_id` 现在默认直接等于 `channel_scope`

这意味着当前线程切分是按会话范围做的，不是按 message_id 或更细粒度做的。

## agent 绑定

agent 绑定不是硬编码在 router 里的，而是通过 profile registry 和 binding rule 解析出来。

相关文件:

- `runtime/profile_loader.py`
- `runtime/config_control_plane.py`
- `runtime/bootstrap.py`

### binding rule 解决什么问题

它回答的是:

“当前这条消息应该交给哪个 agent”

它可以按这些条件匹配:

- `thread_id`
- `event_type`
- `message_subtype`
- `notice_type / notice_subtype`
- `actor_id`
- `channel_scope`
- `targets_self`
- `mentioned_everyone`
- `sender_roles`

### 实际影响

你如果做:

- 某个群固定用某个 agent
- 某个用户在某个群走特殊 agent
- 某类事件走专门 agent

一般都落在 binding rule，不该写死在 pipeline。

## inbound rule 和 `run_mode`

inbound rule 回答的是:

“这条消息该不该进入完整主线”

它最后会给出:

- `respond`
- `record_only`
- `silent_drop`

### 典型用途

- 群消息只有 at bot 才回复
- 某些通知事件只记日志不回消息
- 某些事件直接忽略

### 注意

inbound rule 决定的是“跑不跑完整主线”，不是“用哪个 agent”。这两个经常被混。

## event policy

event policy 是第三条线。

它回答的是:

1. 这条 event 要不要持久化进 `ChannelEventStore`
2. 这条 event 要不要参与 memory extraction
3. 提取时带哪些 `memory_scopes` 和 `tags`

相关文件:

- `runtime/event_policy.py`
- `runtime/models.py`
- `runtime/config_control_plane.py`

### 这个点很重要

如果你做长期记忆相关改动，不要只看 `structured_memory.py`，还要看 event policy 有没有把事件放进 extraction。

## profile 从哪里来

两种来源:

### 1. 配置内嵌

来自 `runtime.profiles` 或默认 runtime / agent 配置。

### 2. 文件系统配置

如果 `runtime.filesystem.enabled = true`，会从运行时目录加载:

- profiles
- prompts
- bindings
- inbound rules
- event policies

这条线主要在:

- `runtime/profile_loader.py`
- `runtime/config_control_plane.py`

## prompt 怎么解析

`prompt_ref` 最后由 `PromptLoader` 解析。

现在支持:

- 内存静态 prompt
- 文件系统 prompt
- chained fallback

所以 AI 改 prompt 相关功能时，要先确认改的是:

- profile 里对 prompt 的引用
- prompt 文件本体
- loader 解析规则

而不是只盯某一个地方。

## WebUI 和配置热刷新是怎么接上的

WebUI 并不是直接改运行中对象。

大致路径是:

`WebUI -> HTTP API -> RuntimeControlPlane -> RuntimeConfigControlPlane -> 配置真源 / 注册表 reload`

这意味着:

- 有些配置改完就能热刷新
- 有些配置只是写回文件，下次重启才完全生效

具体要不要热刷新，不能拍脑袋，要看 `config_control_plane.py` 的实际实现。

## 什么时候该改哪一层

### 想改“谁处理这条消息”

先看 binding rule / profile loader。

### 想改“这条消息回不回复”

先看 inbound rule。

### 想改“这条消息记不记事件 / 记不记长期记忆”

先看 event policy。

### 想改“这个 agent 默认用什么模型、prompt、tools、skills”

先看 profile。

## 常见误区

### 1. 在 pipeline 里重新判断 agent

不对。agent 绑定应该尽量在路由阶段做完。

### 2. 用 prompt 内容来偷偷实现路由

这是最容易把系统变脏的做法。路由归路由，prompt 归 prompt。

### 3. 改 profile 但忘了文件系统模式

如果 runtime 开了 filesystem 配置，很多值不是从内嵌 config 读的。你只改默认 config，很可能线上不生效。

## 读源码时优先看哪些文件

1. `src/acabot/runtime/router.py`
2. `src/acabot/runtime/profile_loader.py`
3. `src/acabot/runtime/event_policy.py`
4. `src/acabot/runtime/config_control_plane.py`
5. `src/acabot/runtime/bootstrap.py`
