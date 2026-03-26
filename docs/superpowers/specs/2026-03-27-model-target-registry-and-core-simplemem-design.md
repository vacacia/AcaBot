# 统一 Model 真源与 Core SimpleMem 边界正式 Spec

## 目标

这份 spec 只做两件事：

1. 把 AcaBot 全系统的模型真源和模型消费入口收成一套正式契约。
2. 把 Core SimpleMem 和 runtime 的边界、模型接线方式、以及第一版存储实现边界写死。

这份 spec 不是实现计划。它是后面两份实现计划的共同前提。

## 命名决议

后续正式命名统一使用 `model_*` 前缀，避免 `provider / preset / target / binding` 裸词在文档和控制面里过于抽象。

正式词典：

- `model_provider`
  - 表示供应商连接配置。
- `model_preset`
  - 表示一个可复用的具体模型预设。
- `model_target`
  - 表示系统里的一个模型消费位点，也就是“谁在使用模型”。
- `model_binding`
  - 表示某个 `model_target` 当前绑定的主 `model_preset` 和 fallback 链。

其中：

- `model_provider` 管连接，不代表具体模型。
- `model_preset` 管具体模型和调用参数，不代表谁在使用它。
- `model_target` 管职责位点，不直接保存连接细节和模型参数。
- `model_binding` 管“这个位点现在到底用哪条模型链”。

## 一、统一 Model 真源

### 1.1 正式真源对象

AcaBot 的模型正式真源收成四类对象：

- `model_provider`
- `model_preset`
- `model_target`
- `model_binding`

这四类对象共同构成唯一正式模型配置体系。

后续系统里任何模型消费者都只能从这套真源取模型，不再从 profile、session、plugin 私有配置里取模型。

### 1.2 正式解析路径

系统里任何模块要拿模型时，正式路径统一是：

`model_target -> model_binding -> RuntimeModelRequest + fallback_requests`

也就是说：

- 模块先声明自己要哪个 `model_target`
- resolver 再根据当前 `model_binding` 解析出主请求和 fallback 请求链
- 模块只消费解析结果，不再自己管理 `preset_id`、`provider_id`、`default_model`、`summary_model`

### 1.3 不再保留的旁路

下列形态不再是正式模型真源：

- `profile.default_model`
- `profile.config.default_model`
- `profile.config.summary_model`
- `profile.config.summary_model_preset_id`
- Session 或 WebUI 自己保存的 `model_preset_id`
- 各模块内部私有的 `fallback_preset_ids`

这些字段后续可以在迁移过程中短暂存在于代码里，但不再作为正式契约继续演化。

## 二、统一 Model 消费位点

### 2.1 `model_target` 是“谁在用模型”

`model_target` 不表示某个具体模型，而表示系统里一个稳定的模型职责位点。

例如：

- `agent:aca`
- `system:compactor_summary`
- `system:ltm_extract`
- `system:ltm_query_plan`
- `system:ltm_answer`
- `system:ltm_embed`

这些位点是稳定对象，不是散落在模块内部的字符串常量集合。

### 2.2 固定内建 target、动态 agent target 与插件 target

`model_target` 分成三类：

- 固定内建 target
  - 由宿主代码固定维护，例如 `system:*` 这类稳定系统位点。
- 动态 agent target
  - 从 live `AgentProfileRegistry` 派生，正式形态是 `agent:<agent_id>`。
  - profile load、filesystem reload、control plane reload 后，都要同步重建这组 target。
- 插件 target
  - 由插件声明自己的模型槽位后，进入统一 target 清单。

插件 target 的命名空间固定为：

`plugin:<plugin_id>:<slot_id>`

例如：

- `plugin:memory_plugin:extractor`
- `plugin:memory_plugin:embedder`

### 2.3 插件怎样表达“需要模型”

插件不直接声明：

- `model_provider`
- `model_preset`
- `fallback model`

插件只声明自己的模型槽位，也就是声明自己有哪些 `model_target` 会被动态注册进系统。

插件槽位至少要带这些元信息：

- `slot_id`
- `capability`
- `required`
- `allow_fallbacks`
- `description`

宿主加载插件后：

- 把插件槽位转换成正式 `model_target`
- 让这些 target 进入统一 `model_binding` 真源
- 插件运行时只按 target 取模型，不自己解析 preset

这里统一使用 `capability`，不再单独发明 `task_type` 这个词。

### 2.4 插件 target 的生命周期

插件 target 不是 bootstrap 初始时就天然存在的固定对象。

正式语义是：

- persisted `model_binding` 可以先指向 `plugin:<plugin_id>:<slot_id>`
- 在插件还没加载、槽位还没注册之前，这条 binding 处于“未解析完成”的状态
- 它不会因为 target 暂时缺席就让整个 runtime bootstrap 失败
- 插件加载并注册槽位后，registry 再重新校验并激活这条 binding
- 控制面查看 binding 时，要能看到 `binding_state = resolved | unresolved_target`
- 这个 `binding_state` 是派生视图状态，不是第二套持久化真源

也就是说：

- 固定内建 target 和动态 agent target 必须在 registry reload 时就可见
- 插件 target 允许延迟出现
- 但延迟出现只影响这条 plugin binding 的可用性，不影响宿主整体启动

### 2.5 宿主和插件的责任边界

宿主负责：

- 提供统一 `model_provider / model_preset / model_target / model_binding` 真源
- 提供统一 resolver
- 提供统一能力校验
- 提供统一控制面配置入口

插件负责：

- 声明自己需要哪些模型槽位
- 在运行时按 target 请求模型
- 自己决定未配置或解析失败时的具体失败语义

如果插件声明了必填槽位但用户没有绑定模型：

- 宿主可以返回明确的未配置状态
- 但宿主不替插件决定生命周期策略
- 插件作者自己决定是在启动时检查、在调用前检查、还是在运行到该位点时报错

## 三、能力约束

### 3.1 `model_preset` 不是无类型对象

`model_preset` 必须携带能力语义，不能只是一组松散参数。

第一版至少区分：

- `chat`
- `embedding`

后续如果需要，再扩成：

- `rerank`
- `vision`
- `moderation`

### 3.2 `model_target` 与 `model_preset` 必须做能力匹配

`model_target` 也要声明自己需要什么能力类型。

正式约束是：

- `chat` target 不能绑定 `embedding` preset
- `embedding` target 不能绑定 `chat` preset
- fallback 链中的所有 `model_preset` 也必须满足同一种能力约束

这条规则由后端统一校验，不交给各模块自己兜底。

## 四、Profile、Session、Plugin 的职责边界

### 4.1 Session 不再决定模型

`SessionConfig` 继续只负责：

- routing
- admission
- persistence
- extraction
- context
- computer

Session 不再是模型真源，不再直接保存主模型或摘要模型选择。

### 4.2 Profile 不再承担模型真源职责

`AgentProfile` 只表达：

- agent 身份
- prompt
- tools
- skills
- computer policy 默认值

Profile 不再承担“默认模型”这类正式真源职责。

### 4.3 Plugin 不再拥有私有模型配置系统

插件只声明“我要哪些槽位”，不声明“我要哪条 provider/preset 链”。

这条边界的目标是：

- 插件和内建模块共享同一套模型真源
- 插件生态不长成第二套模型配置系统

## 五、统一 Fallback 语义

### 5.1 fallback 只由 `model_binding` 声明

主模型和回退链只存在于 `model_binding`：

- 第一项是主 `model_preset`
- 后续项是 fallback `model_preset` 链

后续所有模块共享同一套 fallback 语义，不再允许：

- agent 自己一套
- compactor 自己一套
- LTM 自己一套
- plugin 再自己一套

### 5.2 fallback 的失败边界

resolver 负责：

- 按顺序展开主请求和 fallback 请求链

具体调用失败后的行为由当前模块决定，但模块不再配置自己的私有 fallback 链。

如果一条 fallback 链耗尽：

- 这就是该 target 当前模型链的正式失败结果
- 模块自己处理错误，不再偷偷回落到 legacy 字段

## 六、Core SimpleMem 与 Runtime 的正式边界

### 6.1 对 runtime 来说，LTM 后端必须透明

runtime 只通过两条线和 Core SimpleMem 交互：

- 写入线：`LongTermMemoryWritePort`
- 检索线：`MemorySource`

runtime 不理解：

- LanceDB 表结构
- `MemoryEntry` 持久化细节
- LTM 内部窗口状态实现
- LTM 内部检索实现细节

### 6.2 对 Core SimpleMem 内部来说，第一版采用 LanceDB-first

第一版 Core SimpleMem 只有一个正式存储实现：

- `LanceDB`

但这里的含义不是“以后绝不可能换库”，而是：

- 第一版不承诺通用可插拔数据库后端契约
- 第一版不为了假想的多后端未来，先发明最低公分母抽象

正式边界写成：

`LanceDB-first, storage-layer-contained`

### 6.3 “外部透明”和“内部可替换”不是一回事

对 runtime 来说，LTM 后端可以是透明的。

但对 Core SimpleMem 内部来说：

- `MemoryEntry` 结构字段检索
- 向量检索
- FTS
- provenance 查询
- cursor / failed window 状态
- 三路召回与合流

都会天然吃到具体存储能力差异。

因此第一版不把“数据库完全无感、任意热插拔”写成正式目标。

### 6.4 内部仍然要分层

虽然第一版只实现 LanceDB，但 Core SimpleMem 内部仍然要分层。

这层分层的目标是：

- 把 LanceDB 接口集中收口在 storage/repository 层
- 不让提取逻辑、检索规划、renderer、状态机到处直接操作 LanceDB API
- 以后如果真的要换库，影响面集中在存储层，而不是炸穿整个 LTM

也就是说：

- 第一版不做公开多后端抽象契约
- 但第一版内部实现要把存储耦合收口，而不是散开

## 七、Core SimpleMem 的正式模型接线

Core SimpleMem 内部凡是要调用模型的地方，都必须走统一 `model_target` 路线。

第一版至少保留这些内建 target：

- `system:ltm_extract`
- `system:ltm_query_plan`
- `system:ltm_answer`
- `system:ltm_embed`

这意味着：

- LTM 不拥有私有模型配置系统
- LTM 不自己保存 `preset_id`
- LTM 不自己保存 fallback 链
- LTM 也是统一 model registry 的消费者

## 八、Core SimpleMem 与旧长期记忆路线的关系

Core SimpleMem 第一版不沿用旧通用长期记忆路线继续演化。

明确边界：

- 不把 `structured_memory.py` 作为正式 LTM 主线继续扩展
- 不复用旧 `MemoryStore` 作为 Core SimpleMem 正式 backend
- 不在 runtime 层额外发明一个“长期记忆数据库抽象层”

runtime 和 LTM 的交接边界继续稳定，但 LTM 内部从这一版开始明确进入新的正式实现路线。

## 九、迁移顺序

### 9.1 固定顺序

后续实现顺序固定成：

1. 先完成统一模型真源与 `model_target / model_binding` 唯一路径
2. 再实现 Core SimpleMem

不允许反过来一边做 LTM，一边继续借：

- `default_model`
- `summary_model`
- 私有 `preset_id`

做过渡实现。

### 9.2 第一份改造完成后的目标状态

第一份改造完成后，系统应该满足：

- runtime 内所有模型消费者都走统一 resolver
- `profile.default_model` 和相关 legacy 字段退出正式解析链
- Session / WebUI 的私有模型字段退出正式契约
- 插件 target 和内建 target 进入同一套真源
- `agent:<agent_id>` target 会随着 profile registry load/reload 同步重建
- persisted plugin binding 可以在插件尚未注册 slot 时保持 unresolved，但不阻断 bootstrap
- 旧旁路直接删，不保留兼容桥

### 9.3 第二份改造完成后的目标状态

第二份改造完成后，系统应该满足：

- Core SimpleMem 正式接上写入线和检索线
- LTM 内部模型位点全部走统一 `model_target`
- LTM 内部存储实现是 `LanceDB-first, storage-layer-contained`
- 旧长期记忆路线不再作为正式主线继续演化

## 十、失败语义

### 10.1 target 未绑定

如果某个 `model_target` 当前没有可用 `model_binding`：

- resolver 可以返回明确的未配置状态
- 但宿主不替插件或模块决定生命周期策略
- `record_only` run 继续是特例，不要求解析 run model target

内建模块和插件各自处理自己的失败语义。

如果某条 binding 指向的 `plugin:*` target 当前尚未注册：

- resolver 可以返回明确的 unresolved target 状态
- 这条 unresolved binding 不应阻断宿主 bootstrap
- 插件加载并注册 slot 后，registry 再重新校验并激活它

### 10.2 不再偷偷回落到 legacy 字段

如果某个内建模块拿不到 target：

- 不再偷偷回落到 `default_model`
- 不再偷偷回落到 `summary_model`
- 不再偷偷回落到 session 私有模型字段

统一 target 路线一旦成为正式主线，就不再保留这些旁路兜底。

### 10.3 LTM 写入失败

LTM 写入失败继续沿用写入线既定边界：

- dirty / reconcile 由 `LongTermMemoryIngestor` worker 编排
- `LongTermMemoryWritePort` 负责窗口处理、failed window 记录和 cursor storage 读写
- cursor 只在 `ingest_thread_delta()` 成功后由 `LongTermMemoryIngestor` 保存

runtime 只负责通过正式接口交接，不承担 LTM 内部失败恢复逻辑。

## 十一、验证口径

### 11.1 模型系统验证

模型系统的实现验证至少覆盖：

- `model_target` 解析
- `model_binding` 主链和 fallback 链顺序
- `model_preset` 能力类型校验
- 插件 target 注册与解析
- impact / 删除阻断
- legacy 字段已退出正式解析链

### 11.2 Core SimpleMem 验证

Core SimpleMem 的实现验证至少覆盖：

- 写侧窗口 ingest
- provenance 和 `entry_id` 幂等
- LanceDB 存储读写
- 三路检索行为
- `MemorySource` 输出稳定
- LTM 内部模型位点走统一 `model_target`

## 十二、需要同步的文档方向

这一版落地后，需要同步更新这些文档方向：

- 模型 registry 文档升级成 `model_provider / model_preset / model_target / model_binding`
- routing / profile / session 文档里把模型职责彻底移出
- LTM 文档里明确：
  - 外部接口稳定
  - 内部第一版只实现 LanceDB
  - 以后如果换库，影响面应集中在 storage 层，而不是 runtime 契约层
