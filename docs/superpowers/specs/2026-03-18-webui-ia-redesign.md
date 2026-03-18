# AcaBot WebUI IA 与 Self/Sticky Notes 正式 Spec

## 目标

重做 WebUI，不继承旧前端的信息架构。

这一版的目标很直接：

1. 信息隔离清楚：系统、共享资源、Bot、Session 不混。
2. 页面目的直观：每一页都能一句话说明自己在管理什么对象。
3. 配置模型清楚：用户知道自己到底在改什么，而不是在拼底层 rule。
4. 直接做成可用 WebUI，而不是长期停留在静态原型。
5. 把 `self` 和 `sticky_note` 正式纳入信息架构，而不是继续把它们留在实现暗角里。
6. 明确对外交互链路和维护链路的材料边界：对外交互固定装配 `self`，维护链路可见但不装配。

## 本版前提

这份 spec 建立在 [17-project-consensus.md](../../17-project-consensus.md) 上。

当前已确定的前提是：

- `self` 是 Aca 的稳定自我设定真源
- `self` 由系统对外运行这一侧维护
- `/self` 主文件固定进入对外交互上下文
- `task` 并入 `self`
- `sticky_note` 是当前真正暴露给产品和 WebUI 的 memory 形态
- `sticky_note` 对每个 scope 分成只读区和可编辑区
- `sticky_note` 只使用 `user` 和 `channel` 两种 scope
- `readonly` 和 `editable` 都进入上下文
- relationship memory / channel memory 仍是概念层级，当前不做产品化暴露
- 维护链路因为拥有仓库根目录权限，天然可见这些文件
- 但维护链路不装配 `self`
- `MemoryBroker` 只负责检索规则，每类 memory 的来源由自己管理
- `self` 的规则等价于每次 run 永远命中、永远进入上下文

## 顶层页面

顶层只保留四个入口：

1. 首页
2. 配置
3. 会话
4. 系统

其中“配置”在左侧导航中直接展开成具体对象入口，而不是再让用户先点进一个抽象首页。

## 首页

首页只回答一个问题：AcaBot 现在是否正常。

布局：

- 上方状态摘要
- 下方大日志区

日志区是首页主角：

- 默认全显示
- 按等级筛选
- 按关键词过滤
- 后续可补暂停自动跟随，但不是当前阻塞项

## 配置模型

前端只承认六类对象：

### 1. 系统

全局运维级配置，例如：

- Gateway
- Backend
- 日志
- 资源区
- 审批 / 系统动作

### 2. Self

Aca 的稳定自我设定真源，例如：

- `identity.md`
- `soul.md`
- `state.yaml`
- `task.md`
- 围绕 `self` 的附加材料

### 3. Memory

第一版产品层只暴露 sticky notes。

说明：

- sticky note 是零碎但长期有用的笔记
- sticky note 只依附于 `user` 和 `channel` 两种 scope
- sticky note 在产品层最接近“两个文件 / 两个分区”
- relationship memory / channel memory 暂不做独立页面

### 4. 共享资源

被 Bot 和 Session 引用，但不在它们内部定义，例如：

- Providers
- 模型 Presets
- Prompts
- Plugins
- Skills
- Subagents

### 5. 管理员

当前先只保留共享管理员设置，不单独立一个 Bot 默认配置页。

### 6. Session

Session 是独立配置对象，不再只是底层规则拼出来的幻觉页面。

Session 页展示的是当前生效值，不刻意强调“继承中 / 默认中 / override 中”。

## 配置页导航

左侧导航直接露出这些配置入口：

1. Self
2. Memory
3. 管理员
4. Providers
5. 模型
6. Prompts
7. Plugins
8. Skills
9. Subagents

说明：

- `Self` 是独立入口，不并入管理员页。
- `Memory` 是独立入口，不塞进 Session。
- `Providers` 和 `模型` 不再放在同一编辑区混排。
- `Providers` 负责连接配置。
- `模型` 负责 Preset。
- 模型 Preset 通过选择已有 Provider 建立关联。

## Self 页面

`Self` 页面负责编辑 Aca 的稳定自我设定真源。

页面结构：

- 左侧：`/self` 文件列表
- 右侧：当前文件内容编辑区

固定主文件应被明显标记出来：

- `identity.md`
- `soul.md`
- `state.yaml`
- `task.md`

页面要求：

- 默认先展示主文件
- 允许查看和编辑附加文件
- 允许新建附加文件
- 不把 `self` 折叠成一个总 prompt 文本框
- UI 上明确说明：`self` 固定进入对外交互链路，不进入维护链路

## Memory 页面

`Memory` 页面第一版只负责管理 sticky notes。

页面结构：

- 左侧：scope 列表和 note 列表
- 右侧：当前 note 的只读区与可编辑区

页面要求：

- 先支持现有 sticky note scope
- 每个 scope 下的 sticky note 明确分成两块：
  - 只读区：人工真源，bot 不可改
  - 可编辑区：bot 可写
- 当前主打 `user` 和 `channel` 两种 scope
- 这一页不假装自己是在编辑 relationship memory / channel memory 整个体系
- 这一页操作的是 sticky notes，不是抽象记忆层级名
- `readonly` 和 `editable` 都属于会进入上下文的内容

## 管理员页面

当前页面只负责维护共享管理员列表。

字段包括：

- 共享管理员 actor 列表

说明：

- 管理员 actor 使用跨平台唯一标识，例如 `qq:private:123456`
- 这份列表同时用于 WebUI 管理和 backend 权限判断
- 暂时不在这里混入 Prompt、模型、工具、Skills、默认输入处理

## Providers 页面

Providers 页面只负责连接配置。

字段包括：

- 名称
- Provider ID
- 类型
- Base URL
- API Key / 认证相关字段

设计要求：

- 不把模型 Preset 和 Provider 放在同一编辑面板里
- 这一页只讲“连接到哪里”
- 名称和 ID 必须分开
- 用户主要看到名称
- ID 负责稳定引用和排重

## 模型页面

模型页面只负责模型 Preset。

字段包括：

- Preset ID
- Provider
- 模型名
- 上下文窗口
- 其他模型能力字段（如需要）

设计要求：

- Preset 必须选择一个已存在的 Provider
- 这一页只讲“用哪个 Provider 的哪个模型”

## Prompts 页面

Prompt 页面只保留两个核心字段：

- 名字
- 内容

约束：

- UI 不强调 `prompt/` 前缀
- 不展示“主默认 Prompt”之类解释
- Prompt 在用户视角里就是“名字 + 内容”

内部可继续映射到 `prompt/<name>`，但这不是主界面概念。

## Plugins 页面

Plugins 页面负责插件配置与启停。

当前要求：

- 每个插件有明确开启 / 关闭开关
- 保存后写回配置
- 可执行 reload

用户视角里，插件首先是“开还是关”，其次才是更细的配置。

## Skills 页面

Skills 页面展示当前已安装的 skill 列表。

当前目标：

- 先把列表和可选性讲清楚
- 供 Bot / Session 配置引用

不再把它们塞进“能力”这类抽象层。

## Subagents 页面

Subagents 页面第一版先只做 executor registry 可视化，不承诺真实 enable / disable。

当前要求：

- 展示当前已注册 executor
- 展示 `agent_id`
- 展示来源和基础元数据
- 明确标注：这一页当前是只读观察页，不是完整配置页

说明：

- 真实 enable / disable 需要单独定义真源和运行时约束
- 这一轮先不把它和 `Self + Sticky Notes + Session 输入处理` 混在一起实现

## 会话页

会话页负责查看和编辑某个具体 Session。

这一页遵循一个硬约束：

- 前端只暴露产品概念，不暴露底层规则概念
- Session 前端只出现三类设置：`AI`、`消息响应`、`其他`
- 底层 `binding / inbound / event policy` 只作为后端映射细节存在

### 左侧

简单会话列表：

- 备注名
- Session ID

不分组，不做复杂排序，靠备注和搜索找。

### 右侧

Session 顶部显示基础信息：

- 备注名
- Session ID

下方使用标签页：

1. 基础信息
2. AI
3. 消息响应
4. 其他

要求：

- 标签页切换必须真实可用
- `基础信息 / AI / 消息响应 / 其他` 点击后应切换到对应面板

## Session / 基础信息

这一页回答：这个会话自身有哪些基础设置。

字段包括：

- display name
- `thread_id`
- `channel_scope`
- 渠道模板

约束：

- Session 页不强调“当前 agent”这个概念
- Session 只管自己的设置，底层映射细节不外露
- 渠道模板用于收口这类会话真正会遇到的输入类型
- 第一版至少支持 `QQ 私聊` 和 `QQ群聊`

## Session / AI

这一页回答：这个 Session 的 AI 能力配置是什么。

字段包括：

- Prompt
- 主模型
- 摘要模型
- 上下文管理策略
- Tools
- Skills

当前目标：

- 用户只看到“这个 Session 的 AI 设置”
- 前端不显示 profile / binding 等实现术语
- 后端负责把这一组设置映射到当前 runtime 的真实配置结构

## Session / 消息响应

这一页回答：不同输入类型进入这个会话时，怎么处理、怎么存。

这里不是把所有底层事件平铺给用户。

消息响应必须受“渠道模板”约束：

- `QQ 私聊` 只展示私聊真正会遇到的输入类型
- `QQ群聊` 只展示群聊真正会遇到的输入类型
- 不要把私聊里根本不存在的群事件硬塞进前端

每条规则默认折叠。

每条规则至少包含：

- 是否启用
- 响应方式
- 是否保存
- 记忆范围

其中 `message` 还要支持会话类型相关的触发条件：

- 私聊可配置“全部回复”
- 群聊可配置“全部回复 / 仅被艾特 / 仅被引用 / 被艾特或被引用”

前端展示的是当前生效值，不暴露 `inbound rule / event policy` 等底层概念。

## Session / 其他

这一页放 Session 的补充配置。

第一版先保留轻量字段，例如：

- 预留扩展区（后续新增而不破坏前三块结构）

## Session 映射责任

必须明确：

- 前端负责收集 `AI / 消息响应 / 其他` 三块设置
- 后端负责把这三块设置映射到当前可持久化的真实真源
- 映射是后端契约，不是前端概念
- 前端不得直接展示 `binding_rule_id / inbound_rule_id / event_policy_id` 等实现字段
- 群聊里的“仅被艾特 / 仅被引用 / 被艾特或被引用”由后端展开成真实规则

## 运行时真源与装配规则

这一版不是只改 UI，而是要把 UI 后面的真源和装配边界一起立起来。

建议真源路径：

- `.acabot-runtime/self/identity.md`
- `.acabot-runtime/self/soul.md`
- `.acabot-runtime/self/state.yaml`
- `.acabot-runtime/self/task.md`
- `.acabot-runtime/self/attachments/...`
- `.acabot-runtime/sticky-notes/<scope>/<scope-key>/<note-key>/readonly.md`
- `.acabot-runtime/sticky-notes/<scope>/<scope-key>/<note-key>/editable.md`

装配规则：

- 对外交互每轮固定读取 `/self` 主文件并装配
- `task` 跟随 `self` 一起进入上下文
- sticky note 从文件真源读取，并在需要时按对应 scope 进入上下文
- 维护链路不装配 `/self`
- 维护链路如果需要读取这些材料，只把它们当项目文件查看

说明：

- `self` 解决的是系统对外交互时的稳定自我问题，不是维护链路的执行问题
- sticky note 解决的是零碎但长期有用的信息沉淀
- `MemoryBroker` 只负责检索规则；`self` 是否物理经过 `MemoryBroker` 不是这里关心的问题，只要行为等价于“每次 run 永远命中”即可
- 维护链路的工作目标是工程执行，装配 `self` 只会干扰维护工作

## 维护链路边界

这份 spec 明确要求：

- 维护链路保持仓库根目录和运行时目录可见
- 维护链路不自动获得 `self` 装配
- 不把 `self` 主文件混进维护链路自己的工作设定
- 不把“维护链路能看到 `/self`”误解成“维护链路应该带着 `/self` 工作”

## 不直接暴露的内部实现

以下内容不作为主配置概念暴露给用户：

- binding_rule_id
- inbound_rule_id
- event_policy_id
- 其他底层实现细节

说明：

- Provider 的连接字段属于 Provider 对象本身，因此应在 Provider 页面可见。
- Prompt 内容属于 Prompt 对象本身，因此应在 Prompt 页面可见。
- “不直接暴露”指的是不把底层实现 id 和内部拼装逻辑当成主界面概念。

## 原型 / 实现策略

当前策略不再是长期维护独立原型，而是直接把新 IA 推进成可用 WebUI。

WebUI 技术路线改为：

- 前端使用 Vue
- 构建产物继续由当前 HTTP server 静态托管
- 后端继续复用 `RuntimeHttpApiServer + RuntimeControlPlane + RuntimeConfigControlPlane`
- 对 `Self / sticky notes` 增补真实可编辑 API，而不是只做静态页面

## 前端架构

Vue 前端不应继续沿用单文件脚本堆状态的方式，而应拆成明确模块：

- App shell
  - 顶层导航、全局状态摘要、路由容器
- 页面级 view
  - 首页
  - Self
  - Memory
  - 管理员
  - Providers
  - 模型
  - Prompts
  - Plugins
  - Skills
  - Subagents
  - 会话
  - 系统
- 通用组件
  - 侧边导航
  - 对象列表
  - 文件列表
  - 编辑器面板
  - note 双区面板
  - 表单区块
  - 保存状态条
  - 日志流视图

状态管理要求：

- 页面数据和编辑草稿分离
- 切换对象时保留未保存提示
- `Self` 页面使用“文件列表 + 编辑器 + 保存状态”模式
- `Memory` 页面使用“scope / note 列表 + 只读区 + 可编辑区 + 保存状态”模式
- 日志流视图不应只依赖整页手动刷新；需要支持“首次快照 + 增量刷新”的稳定契约
- 不把底层实现 id 直接暴露成主 UI 结构

## 后端 API

为支撑 Vue WebUI，本轮需要新增或补齐以下 API 族：

- `GET /api/self/files`
  - 返回 `/self` 文件列表和主文件标记
- `GET /api/self/file?path=...`
  - 返回单个 `self` 文件内容
- `PUT /api/self/file`
  - 保存单个 `self` 文件内容
- `POST /api/self/files`
  - 新建 `self` 附加文件
- `GET /api/memory/sticky-notes/scopes`
  - 通过文件系统枚举当前可浏览的 sticky note scope 列表
- `GET /api/memory/sticky-notes?scope=...&scope_key=...`
  - 返回指定 scope 下的 sticky note 列表
- `GET /api/memory/sticky-notes/item?scope=...&scope_key=...&key=...`
  - 从文件真源返回单个 sticky note 的只读区和可编辑区
- `PUT /api/memory/sticky-notes/item`
  - 保存单个 sticky note 的可编辑区
- `PUT /api/memory/sticky-notes/readonly`
  - 保存单个 sticky note 的只读区
- `POST /api/memory/sticky-notes/item`
  - 新建 sticky note

这些 API 的风格要求：

- 响应格式沿用现有 `ok / data / error`
- 保存接口要返回标准化后的对象标识和最后修改时间
- 非法路径必须被拒绝，不能让 WebUI 任意写宿主文件
- sticky note 保存要带回 scope、scope_key、note_key 等关键信息
- `/self` 的路径约束和 sticky note 的 scope 约束要在后端硬编码

## 数据流

关键数据流分三条：

1. WebUI 编辑流
   - Vue 页面读取文件列表
   - 用户在 `Self` 页面选择文件，或在 `Memory` 页面选择 scope 和 note
   - 前端加载内容到编辑草稿
   - 保存时调用对应 API
   - 保存成功后刷新当前对象视图
2. 对外交互装配流
   - 运行时读取 `/self` 主文件
   - 运行时按需要从 sticky note 文件真源读取对应 scope 的 notes
   - 和 thread working memory 一起组装上下文
   - 再进入模型执行
3. 维护查看流
   - 维护链路可直接查看 `.acabot-runtime/` 下的相关文件
   - 后台消息在更早入口分流，不进入 `self` 装配主线

## 错误处理

本轮需要提前定义几类错误：

- 文件不存在
  - WebUI 显示明确提示，不把空字符串当成功加载
- 路径非法
  - 后端直接拒绝并返回错误
- 并发写入冲突
  - 第一版至少返回最后修改时间，允许前端提示“内容可能已变化”
- YAML 格式错误
  - `state.yaml` 保存前需要后端校验基本可解析性
- sticky note scope 或 note 不存在
  - 返回空列表或明确错误，不返回伪造对象
- 只读区误写
  - bot 不能通过普通写入路径覆盖只读区

## 验证要求

这份 spec 对后续实现提出最低验证标准：

- API 测试
  - `self` 文件列出、读取、保存、新建
  - sticky note scope 列表、note 列表、单条读取、单条保存、新建
  - sticky note 只读区和可编辑区的区分
  - 非法路径拒绝
  - `state.yaml` 基本格式校验
- 运行时测试
  - 对外交互链路会固定装配 `/self` 主文件
  - `task` 会跟随 `self` 一起进入上下文
  - sticky note 在需要时按对应 scope 从文件真源进入上下文
  - 维护链路不装配 `self`
- 前端测试
  - 顶层导航和关键页面能进入
  - `Self / Memory` 页面能加载、编辑、保存
  - Session 的 `基础信息 / AI / 消息响应 / 其他` 标签页切换正常
  - Providers / 模型 / Plugins / Prompts 等关键页面仍能工作
- 手工验证
  - 打开 WebUI，修改 `identity.md`
  - 刷新页面后仍能看到更新
  - 打开 `Memory` 页面，修改一条 sticky note 的可编辑区
  - 刷新页面后仍能看到更新
  - 运行一次对外交互并确认 `self` 生效
  - 运行一次维护链路并确认未装配 `self`

实现上分三层推进：

1. 先立真源和 API
2. 再立 Vue 外壳和 IA
3. 最后把运行时装配和选择性检索接进系统

实现顺序：

1. 先保证 `self` 真源和 sticky note 基础模型存在
2. 再保证 `sticky_note` 的读写 API 和保存链路可用
3. 再用 Vue 替换旧 WebUI 壳
4. 再把 `self` 固定装配与 sticky note 读取接进运行时
5. 最后修正 IA 细节与运行时语义

当前优先项：

1. `Self` 真源与编辑页面
2. `Memory(sticky notes)` 页面
3. Vue WebUI 主壳替换
4. Providers / 模型拆页保留
5. Subagents 只读 registry 页面
6. Session 的 `AI / 消息响应 / 其他` 页面
7. 运行时装配与 sticky note 接线
