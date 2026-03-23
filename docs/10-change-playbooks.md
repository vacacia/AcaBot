# 常见改动的落点手册

这一篇不讲大原理，只讲一件事：

> 你要改某类功能时，先看哪些文件，最不容易走偏。

当前代码已经不是旧的 rule 主线了，所以这篇手册也要完全按现在的代码来。

## 先做这四步

无论你改哪一块，先把这四步做了：

1. 用一句话说清楚你想改出什么结果
2. 先找主入口文件，不要全文搜索到哪改哪
3. 列出会被连带影响的层
4. 先说清楚这次不碰什么

很多失控改动，不是因为代码太复杂，而是第一步就没定边界。

## 场景一：平台事件翻译

这种需求通常长这样：

- NapCat 传来的字段没接住
- 新 notice 类型没翻进系统
- reply / mention / attachment 信息不完整
- 平台原始消息和 `StandardEvent` 对不上

### 先看哪些文件

- `src/acabot/gateway/base.py`
- `src/acabot/runtime/gateway_protocol.py`
- `src/acabot/gateway/onebot_message.py`
- `src/acabot/gateway/napcat.py`
- `src/acabot/types/event.py`
- `src/acabot/types/action.py`

### 先判断你改的是哪一层

#### 只改平台 JSON 到标准事件的翻译

重点看：

- `onebot_message.py`
- `napcat.py`

#### 需要给 runtime 多一个标准字段

除了 gateway，还要一起看：

- `types/event.py`
- 后面真正消费这个字段的 runtime 模块

### 最容易踩的坑

- 只改 `napcat.py`，忘了 `onebot_message.py`
- 上游字段有了，但没进 `StandardEvent`
- 在 gateway 偷偷做业务判断

## 场景二：消息进来后该怎么决定

这种需求通常长这样：

- 为什么这条消息走这个 profile
- 为什么这条消息被 silent drop
- 为什么这条消息能 respond / record_only
- 为什么当前 run 的 computer backend / skill 可见性 / context labels 是这样

### 先看哪些文件

- `src/acabot/runtime/router.py`
- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/control/session_loader.py`
- `src/acabot/runtime/contracts/session_config.py`
- `src/acabot/runtime/contracts/routing.py`

### 先记住当前主线

现在真正的决策主线是：

`StandardEvent -> SessionRuntime -> RouteDecision`

不是：

- binding rule
- inbound rule
- event policy

这些旧名字已经不是现行主线了。

### 最容易踩的坑

- 看到“路由问题”就先去 gateway 改
- 看到“行为不对”就先改 profile，而不是先看 `SessionRuntime`
- 在多个地方重复发明消息决策逻辑

## 场景三：前台 builtin tools / computer / Work World

这种需求通常长这样：

- `read / write / edit / bash` 行为不对
- `/workspace /skills /self` 路径不对
- 图片读取不对
- `/skills/...` 看不见或写完不刷新
- shell 行为和当前 world 对不上

### 先看哪些文件

- `src/acabot/runtime/builtin_tools/computer.py`
- `src/acabot/runtime/computer/runtime.py`
- `src/acabot/runtime/computer/contracts.py`
- `src/acabot/runtime/computer/backends.py`
- `src/acabot/runtime/computer/world.py`
- `src/acabot/runtime/computer/workspace.py`
- `src/acabot/runtime/tool_broker/broker.py`

### 先记住现在前台工具面

前台 builtin tools 现在是：

- `read`
- `write`
- `edit`
- `bash`

不要再去找这些旧工具：

- `ls`
- `grep`
- `exec`
- `bash_open`
- `bash_write`
- `bash_read`
- `bash_close`

### 先判断你改的是哪一层

#### 只是模型看到的工具 schema 或返回文案

先看：

- `builtin_tools/computer.py`

#### 真正的读写、编辑、bash 行为

先看：

- `computer/runtime.py`

#### 真正宿主机 / docker 怎么执行

先看：

- `computer/backends.py`

### 最容易踩的坑

- 把 builtin tool 当本体改
- 只改 backend，不看 `ComputerRuntime`
- 把 `/skills` 的准备逻辑又塞回 builtin surface

## 场景四：当前轮消息整理、reply 图片、模型输入

这种需求通常长这样：

- reply 文字没进上下文
- 图片说明没出来
- 当前模型支持 vision，但最后 user message 没带图
- memory 候选材料不对

### 先看哪些文件

- `src/acabot/runtime/inbound/message_preparation.py`
- `src/acabot/runtime/inbound/message_resolution.py`
- `src/acabot/runtime/inbound/message_projection.py`
- `src/acabot/runtime/inbound/image_context.py`
- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/computer/runtime.py`

### 先记住边界

- gateway 只负责平台翻译
- `runtime/inbound/` 负责把这轮消息真正要用的材料补齐
- `computer` 负责附件 staging
- `pipeline` 负责把这些东西接到当前 run 上

### 最容易踩的坑

- 只改 gateway，以为图片已经“进系统了”
- 只改 prompt，不改消息整理链
- 直接把图片说明伪装成原始消息事实

## 场景五：长期记忆、working memory、sticky notes、self

这种需求通常长这样：

- 当前线程上下文不对
- 长期记忆取回不对
- sticky notes 不生效
- `/self` 的内容没进入当前轮

### 先看哪些文件

- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/memory/sticky_notes.py`
- `src/acabot/runtime/memory/file_backed/`
- `src/acabot/runtime/soul.py`
- `src/acabot/runtime/soul/source.py`
- `src/acabot/runtime/storage/stores.py`
- `src/acabot/runtime/storage/sqlite_stores.py`

### 先分清四件事

- `ThreadState.working_messages / working_summary`：当前线程上下文
- `ChannelEventStore`：外部事件事实
- `MessageStore`：已经发出去的消息事实
- `MemoryStore`：长期记忆

### 最容易踩的坑

- 把 working memory 和长期记忆混起来
- 只管写记忆，不管 retrieval
- 直接在消息整理层写死长期记忆正文

## 场景六：控制面、WebUI、配置真源

这种需求通常长这样：

- 本地管理页面看不到最新状态
- 改了 profile / prompt / plugin 配置但没生效
- workspace 页面数据不对
- HTTP API 和页面显示不一致

### 先看哪些文件

- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/config_control_plane.py`
- `src/acabot/runtime/control/workspace_ops.py`
- `src/acabot/runtime/control/snapshots.py`
- `src/acabot/runtime/control/ui_catalog.py`
- `src/acabot/webui/index.html`
- `src/acabot/webui/assets/`

### 先记住当前事实

- `src/acabot/webui/` 里现在是已经生成好的静态文件
- 当前仓库里没有旧文档常写的 `src/acabot/webui/app.js`
- `/api/sessions` 现在是 `501`
- `/api/bot` 现在也是 `501`

所以如果你要改的是这两块，不是去补旧壳，而是要先重设计当前壳应该长什么样。

### 先判断你改的是哪一类

#### 运行时状态

先看：

- `RuntimeControlPlane`
- `snapshots.py`

#### 持久配置

先看：

- `RuntimeConfigControlPlane`

#### workspace / computer 管理

先看：

- `workspace_ops.py`
- `computer/runtime.py`

### 最容易踩的坑

- 只改 HTTP API，不看 control plane
- 只改静态页面，不改配置真源
- 继续按旧 `/api/sessions` / `/api/bot` 心智做补丁

## 场景七：后台入口、`ask_backend`、后台维护模式

这种需求通常长这样：

- 前台想把问题转给后台维护者
- 后台入口消息怎么接住
- backend session binding / backend status 为什么不对

### 先看哪些文件

- `src/acabot/runtime/plugins/backend_bridge_tool.py`
- `src/acabot/runtime/backend/`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

### 先记住边界

- `ask_backend` 不是 `builtin:computer`
- 它是单独的后台桥接工具
- `RuntimeApp.handle_event()` 里还有后台入口分流

### 最容易踩的坑

- 把后台维护逻辑塞进前台 builtin tool
- 把 `ask_backend` 当成普通文件工具来改
- 只改 backend bridge，不看 app 入口分流

## 场景八：启动装配和默认真相

这种需求通常长这样：

- 为什么这个组件启动时就有
- builtin tools 是在哪里注册的
- plugin manager 为什么拿到这些依赖
- pipeline、tool broker、computer runtime 是怎么连起来的

### 先看哪些文件

- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/app.py`

### 最容易踩的坑

- 只看某个子模块，不看 bootstrap
- 误把 builtin tool 当 plugin
- 改了 builder，忘了默认装配链

## 最后给自己一个快速判断

如果你的需求像下面这样，可以这样起手：

### “平台消息长什么样？”

先看：

- `gateway/`
- `types/event.py`

### “系统为什么这么决定？”

先看：

- `router.py`
- `control/session_runtime.py`
- `contracts/session_config.py`

### “模型这轮到底能看到什么？”

先看：

- `pipeline.py`
- `runtime/inbound/`
- `memory/`

### “模型能调什么能力？”

先看：

- `tool_broker/broker.py`
- `builtin_tools/`
- `computer/`
- `plugins/backend_bridge_tool.py`

### “用户在本地页面上能改什么、看到什么？”

先看：

- `control/http_api.py`
- `control/control_plane.py`
- `control/config_control_plane.py`
- `src/acabot/webui/`

如果还是拿不准，就回到：

- `docs/00-ai-entry.md`
- `docs/01-system-map.md`
- `docs/02-runtime-mainline.md`
- `docs/12-computer.md`

先把主线看清楚，再下手。