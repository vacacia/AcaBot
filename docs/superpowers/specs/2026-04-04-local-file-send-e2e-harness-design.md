# 本地文件发送 E2E 测试体系设计

**日期：** 2026-04-04  
**状态：** 设计已确认，待进入 planning  
**读者：** runtime / gateway / 测试基础设施开发者  
**目标：** 补齐一套不依赖真实 QQ 客户端、但足够端到端的发送验证链路，用来验证本地文件从 `message` 到 NapCat 的完整发送闭环。

---

## 1. 要解决的问题

当前缺的不是单点单测，而是正式发送链路的闭环验证。

现状里已经有：
- `message` tool 的参数合同测试
- `Outbox` 的物化测试
- `NapCatGateway` 的协议翻译测试

但还缺一条真正能回答下面问题的测试：

> 如果模型调用 `message.send(images=["x.png"])`，AcaBot 能不能把这个本地文件一路送到 NapCat，并且让 NapCat 真的读到文件？

这个问题不能靠真实 QQ 手测做日常回归，也不能只靠某个中间函数的断言来替代。

---

## 2. 最终设计

本次补两层测试能力，而且两层都要正式交付。

### 2.1 主回归层：pytest 端到端测试

新增一条“模拟模型动作”的正式 E2E 测试链。

这里的“模拟模型动作”不是直接调用某个 tool handler，也不是手工拼 `PlannedAction`，而是要从 **真实 runtime 入口** 进入。更具体地说，fake agent 必须在 runtime 中真实执行一次 `tool_executor("message", ...)`，不能只伪造一份“模型返回了 tool call”的审计对象：

1. 在测试环境里创建 workspace 文件
2. 构造一个 fake agent，让它在正式 `ModelAgentRuntime` 执行过程中真实调用一次 `tool_executor("message", ...)`
3. 让动作继续走正式 runtime 主线：
   - `ModelAgentRuntime`
   - `ToolBroker`
   - `message` tool
   - `PlannedAction`
   - `Outbox`
   - `NapCatGateway`

同时必须确保本地文件发送所需的 work world 上下文真实存在：
- 优先方案：让 harness 直接走 `ThreadPipeline` 或等价的 `ComputerRuntime.prepare_run_context()` 注入路径
- 如果不走完整 `ThreadPipeline`，也必须显式准备与正式 run 等价的 `ctx.world_view` / `ctx.workspace_state`
- 不允许省略 work world 注入后再手工补一个路径字符串，因为那会绕过 `/workspace` -> host path 的真实解析逻辑

4. 末端不接真实 NapCat，而是接一个 **OneBot probe**
5. probe 收到 `send_private_msg` / `send_group_msg` 后，必须：
   - 记录最终 payload
   - 遍历 message segments
   - 对 `image/file/record/video` 的 `data.file` 按 scheme 分类验证
   - 只有验证通过时才返回成功 ack
   - 验证失败时不返回成功 ack；默认做法是返回 `no ack` / timeout，让 `NapCatGateway.send()` 与 `Outbox.send_items()` 都明确落入失败路径，而不是返回一个会被当前产品代码误判为成功的 failure ack

pytest 和 smoke 的 PASS 语义也必须写死：
- PASS 只能建立在“成功 ack + 无本地文件读取失败证据”之上
- 任何 timeout / no ack / `ENOENT` / probe 验证失败都算 FAIL

scheme 验证规则必须写死：
- 本地 path / `file://`：必须能被 probe 真实读取
- `http://` / `https://`：不做本地读文件断言，只验证 payload 透传正确
- `data:` / `base64://`：不做本地读文件断言，只验证 payload 透传正确

这层的职责是：
- 提供稳定、可重复、可断言的自动化回归
- 精确判断最终送到 OneBot 边界的 payload 到底是什么
- 证明 NapCat 侧至少具备“能打开这个文件”的必要条件

### 2.2 冒烟层：真实 NapCat 手动脚本

新增一个容器内可执行的 smoke 脚本，直接复用现有 `acabot` + `acabot-napcat` compose 环境。

脚本职责：

1. 在 compose 环境里明确指定一个测试目标会话，并在该会话对应的 workspace 中创建本地文件
2. 模拟一次 `message.send(...)`
3. 走正式发送链路到真实 `acabot-napcat`
4. 输出结构化结果：
   - 输入参数
   - 发送 ack
   - `acabot-napcat` 的关键日志片段
   - 如已有结构化日志可得，再附带 materialized segments / gateway payload 证据
   - PASS / FAIL 结论

真实 NapCat smoke 的执行模型明确为：
- 它是 **对 already-running compose 环境的黑盒冒烟脚本**
- 通过现有运行中的 `acabot` 触发正式发送链路，到现有运行中的 `acabot-napcat`
- 为了给 smoke 提供确定性的黑盒触发入口，本轮允许**窄幅扩展现有 `POST /api/notifications`**，让它接受与高层发送意图一致的 `text / images / render / target` 字段，并沿正式 `Outbox -> Gateway` 主线执行
- 这不是新增独立调试 API，而是把现有主动通知入口提升为可发送结构化内容的正式运维入口
- 该入口如果接收本地图片，必须复用与 `message.send` 一致的本地文件合同：输入仍是 workspace 相对路径，系统内部统一规范化为 `/workspace/...`
- 该入口还必须能根据目标会话解析对应的 work world / workspace 视图，保证本地路径最终能经正式 world 解析进入 Outbox 发布层，而不是直接裸传给 Gateway
- smoke 不要求在同一进程里直接拿到 live runtime 内部对象
- 对 live 进程的观测证据来自发送 ack、现有可获取的结构化日志和 NapCat 日志，而不是进程内对象直读
- 为避免“failure ack 被产品代码误判成功”，该入口返回结果必须暴露足够的发送证据，至少包含原始 ack 的 `status` / `retcode` 或等价结构化发送结果

脚本必须明确前置条件和失败归因：
- `acabot` / `acabot-napcat` 容器必须正在运行
- `acabot-napcat` 必须已建立 OneBot 连接
- smoke 默认只验证“NapCat 边界是否成功接收并读取本地文件”，不要求真实 QQ 客户端在线
- 如果环境前置条件不满足，脚本必须输出 `SKIP/ENV-FAIL`，不能冒充业务失败

这层的职责是：
- 作为真实第三方组件兼容性的冒烟验证
- 作为开发者本地排障手段
- 让“修完以后再打一枪确认”不再依赖真实 QQ 客户端

如果 smoke 需要展示 `materialized segments` 与 `gateway 最终发送 payload`，只能走已有日志证据或未来专门的内部测试 harness；本轮不通过新增产品 API 获取，也不强制要求 live script 直接拿到运行中进程的内部对象。也就是说，smoke 是运维脚本，不是新的对外调试接口。

---

## 3. 成功标准

### 3.1 pytest E2E 必须证明

- 从 fake model response 进入正式 `ModelAgentRuntime -> ToolBroker -> message` 链路，而不是直接跳进 `Outbox`
- 最终 OneBot payload 已经不是 `/workspace/...`
- 对本地 path / `file://`，probe 真的能读到最终文件
- 对 remote URL / `data:` / `base64://`，probe 证明 payload shape 与 scheme 透传正确
- 发送链路拿到成功 ack

### 3.2 smoke 脚本必须证明

- 在当前 docker compose 环境下，workspace 文件发送不会再触发 `ENOENT`
- 可以直接观察到真实 NapCat 的接收结果
- 成功证据不是“接口返回了一个非空对象”，而是原始 ack 语义明确成功，且没有对应的本地文件读取失败证据
- 输出结果足够清楚，便于人工判断是哪一层失败

---

## 4. 架构边界

### 4.1 OneBot probe 的定位

probe 不是为了替代真实 NapCat，而是为了提供：
- 稳定自动化
- 精确可观测性
- 文件可读性的硬性断言

probe 协议契约至少要明确：
- 支持 OneBot 风格 `echo` 回传，保证 `NapCatGateway.send()` 能正常完成 request/ack 匹配
- 本地文件引用需要同时支持裸路径和 `file://` URI 解析
- 如需鉴权，支持最小 token / auth 头验证，但默认测试可使用最简配置

它应该只模拟本次测试需要的最小 OneBot 行为：
- 反向 WS client 连接到 `NapCatGateway`
- 接收发送请求
- 做文件读取验证
- 返回 OneBot 风格 ack

不需要模拟完整 NapCat 功能，不需要承担消息翻译或 QQ 行为。

### 4.2 可扩展性要求

这套 harness 不能只为“workspace 图片发送”写死。

设计上必须允许后续继续补这些场景：
- `file` / `record` / `video` 发送
- render 发送
- remote URL / `data:` / `base64://` 发送
- group / private 两类会话
- 未来其他主动发送入口

因此测试辅助设施应拆成可复用组件，而不是把逻辑硬编码进单个测试函数里。

推荐的复用边界：
- OneBot probe：负责接收 payload + 按 scheme 验证 file-like ref + 回 ack
- 通用 send-path harness：负责组装最小 runtime / fake model response / gateway 驱动
- 入口 driver：当前先提供 `message.send` driver，后续可继续补其他发送入口 driver
- smoke 脚本：负责现场跑一条真实 compose 环境的验证

---

## 5. 最小实现范围

本轮只先覆盖最关键的本地文件发送回归，不扩成泛化测试平台。

### pytest 必测
- workspace 相对路径图片发送成功
- remote URL 图片发送仍然透传
- `data:` / `base64://` 图片发送仍然透传
- render 发送仍然可用
- 非法路径在 tool 层失败

### smoke 脚本必测
- 真实 `acabot-napcat` 环境中的 workspace 本地图片发送
- 输出 NapCat 关键日志和发送结果

---

## 6. 非目标

本次不做：
- 不接真实 QQ 客户端做自动化
- 不接真实模型供应商
- 不新增独立的测试专用产品 API
- 不把黑盒日志当成唯一断言来源
- 不一次性把所有消息类型都做满

---

## 7. 验收标准

这次设计只有在下面几项都存在时才算闭环：

1. 有正式 pytest E2E，用“模拟模型动作”跑通 `message -> ... -> OneBot 边界`
2. 有 OneBot probe，能按 scheme 对 file-like segment 做真实可读性/透传验证，并以“成功 ack / no ack”语义稳定驱动发送链路成败
3. 有真实 `acabot-napcat` smoke 脚本，不依赖真实 QQ 客户端
4. 至少能稳定验证 workspace 本地图片发送不会再次回退成 `/workspace/...` 直传
5. 测试辅助设施具备继续扩展到更多发送场景的结构基础
