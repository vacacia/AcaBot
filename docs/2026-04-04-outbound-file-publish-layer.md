# Outbound File Publish Layer Plan

**Goal:** 解决 bot 把 `/workspace/...` 这种内部 world path 直接发给 NapCat，导致 NapCat 在自己的容器里找不到文件的问题。

**Core Idea:** 模型、tool、render 继续使用 `/workspace/...`。真正发消息前，由 `Outbox` 统一把 file-like 引用发布到共享目录 `runtime_data/outbound/...`，再把发布后的路径交给 gateway。`NapCatGateway` 只做协议包装，不负责理解 `/workspace`。

---

## 1. 问题边界

当前报错不是“图片没生成”，而是“路径语义穿层”：

- `/workspace/...` 是 AcaBot 内部逻辑路径
- NapCat 只能读取自己容器里可见的真实文件
- 当前代码把内部路径直接塞进出站 segment
- gateway 不知道这个路径属于哪个 thread，也不该知道

这件事不该在 NapCat 层补丁式修，也不该让模型知道外部发布路径。

## 2. 最终设计

新增一层正式的出站文件发布层，位置在 `Outbox -> Gateway` 之间。

发送链路改成：

1. 上游继续产出 `/workspace/...`、remote URL、`data:`、`base64://`
2. `Outbox` 在真正 `gateway.send()` 前扫描所有 file-like segment
3. 如果是 `/workspace/...`，用当前 run 的 `world_view.resolve()` 解成真实文件
4. 把文件复制到共享发布目录 `runtime_data/outbound/<conversation_id>/<run_id>/...`
5. 把 `segment.data.file` 改写成 gateway 可直接消费的路径
6. gateway 继续只负责构建 OneBot/NapCat payload

结果是：

- 模型一直只认识 `/workspace/...`
- gateway 一直只认识“已经可发送的文件引用”
- NapCat 一直只读取共享目录里的真实文件

## 3. 实现范围

这次只做出站发布层，不改入站附件链路，不让 gateway 学会 `/workspace` 语义。

优先修改这些位置：

- `src/acabot/runtime/outbox.py`
- `src/acabot/runtime/model/model_agent_runtime.py`
- `src/acabot/runtime/builtin_tools/message.py`
- `src/acabot/gateway/napcat.py`
- `tests/runtime/test_outbox.py`
- `tests/test_gateway.py`
- `deploy/compose.yaml`

其中真正的主改动点应该在 `Outbox`。`model_agent_runtime` 和 `message` 只需要继续表达“逻辑引用”，不需要自己做发布。

## 4. 任务拆分

- [ ] Task 1: 定义出站文件发布器

  目标：新增一个专门组件，输入是 file-like ref，输出是已发布的可投递路径。

  最少要支持：

  - world path：`/workspace/...`
  - remote URL：`http://` / `https://`
  - inline data：`data:` / `base64://`

- [ ] Task 2: 把发布器接进 `Outbox`

  目标：所有真正进入 `gateway.send()` 的 file-like segment 都先经过发布器。

  需要覆盖：

  - `SEND_MESSAGE_INTENT.images`
  - render 产出的图片
  - model attachment 转成的 `SEND_SEGMENTS`
  - 直接构造的 `SEND_SEGMENTS`

- [ ] Task 3: 定义共享发布目录

  默认目录：

  - host 写入目录：`runtime_data/outbound/`
  - gateway 可见目录：`/app/runtime_data/outbound/`

  这两个路径现在在当前 compose 部署下碰巧一致，但设计上要允许以后拆开。

- [ ] Task 4: 加安全边界

  默认只允许发布：

  - `/workspace/...`
  - render service 产物
  - runtime 自己生成的安全目录

  默认拒绝任意宿主机绝对路径，避免把运行环境里的其他文件意外发出去。

- [ ] Task 5: 加测试

  至少覆盖：

  - `/workspace/...` 会被发布到共享目录
  - remote URL 不改写
  - `data:` / `base64://` 不改写
  - 非白名单本地绝对路径会失败
  - gateway 收到的永远不是 `/workspace/...`

## 5. 非目标

这份计划现在不做这些事：

- 不改 NapCat 协议层去理解 `/workspace`
- 不把模型可见路径改成共享目录路径
- 不重写入站附件 staging
- 不顺手引入复杂的对象存储或 HTTP 文件服务

## 6. 验收标准

做到下面这些，就算这次设计闭环：

- 模型通过 tool 选中 `/workspace/x_screenshot.png`
- 最终发给 NapCat 的不是 `/workspace/...`
- NapCat 可以直接读取该文件并成功发送
- gateway 不需要知道 `/workspace` 属于哪个 thread
- 模型后续还能继续用原来的 `/workspace/...` 路径工作

