# Sticky Note 重构设计

这一篇是 sticky note 重构的正式设计文档。

目标读者是后面继续实现或 review 这块的人。它的任务不是记录讨论过程，而是把已经达成的共识收成一份稳定、可执行、可回读的设计说明。

这一篇会讨论：

- sticky note 在 AcaBot 里的正式定位
- sticky note 和 retrieval、tool、WebUI、control plane、session/profile 配置的关系
- sticky note 的数据模型、组件边界和交互边界
- 这一轮要删除哪些旧抽象，为什么要删
- 哪些点是明确 postpone 的后续 TODO

这一篇不展开：

- WebUI 视觉细节
- XML 模板的最终具体字符串
- session/profile 配置字段名
- 实现步骤和测试清单

这些内容分别留给 implementation plan 和具体代码实现。

---

## 1. 先讲结论

sticky note 在 AcaBot 里，正式被定义为：

- 一个 **runtime 内建的 memory layer**
- 一个围绕 **实体便签** 建模的能力
- 一个同时服务于 **retrieval、bot tools、WebUI、control plane** 的正式产品面

它不是：

- 通用长期记忆项
- `MemoryItem` 的一个变体
- 一个外部 plugin
- 一个只存在于 WebUI 的静态资料页

对应的整体结论是：

- sticky note 的正式主契约是 `entity_ref`
- sticky note 只保留 `user` 和 `conversation` 两种 `entity_kind`
- sticky note 默认是一实体一张 note
- sticky note 的真源是文件系统
- sticky note 的检索是 memory 主线的一部分
- sticky note 的 bot tools 是 builtin tool adapter，但不享受工具特权
- sticky note 的旧 `MemoryItem / MemoryStore / structured_memory` 链路这一轮直接删除，不保留兼容层

---

## 2. Sticky Note 是什么

sticky note 的产品定位不变：

- 它保存零碎但长期有用的稳定笔记
- 它帮助 bot 在后续继续理解某个用户或某个对话容器
- 它几乎每轮都会参与上下文

在实体语义上，它只围绕两类对象展开：

- `user`
- `conversation`

也就是说，sticky note 不是一套泛化记忆容器，而是“针对某个实体的一张便签”。

这里的正式对象引用统一收成：

- `entity_ref`

为了方便 UI 分组和局部枚举，再从 `entity_ref` 派生出：

- `entity_kind = "user" | "conversation"`

这里的派生规则也固定住：

- 指向“人”的 `entity_ref` 派生为 `user`
- 指向“群 / 频道 / 房间 / 私聊容器”这类对话容器的 `entity_ref` 派生为 `conversation`

如果某个 `entity_ref` 不能稳定派生到这两类之一，那它对 sticky note 来说就是无效对象，应该在 sticky note 边界直接拒绝，而不是临时猜测或再长出第三种类型。

这里不再使用 `scope + entity_id` 作为 sticky note 的正式主契约，也不再引入 `note_key`。  
第一版的 sticky note 逻辑和物理形态都收成：

- 一实体
- 一张 note

---

## 3. Sticky Note 不是什么

这次重构最重要的纠偏之一，就是明确 sticky note 不再承担下面这些角色：

- 不再承担 `relationship` memory
- 不再承担 `global` memory
- 不再回落到通用 `MemoryStore`
- 不再借 `MemoryItem` 表达自己
- 不再混入 `author / confidence / memory_type / source_run_id` 这种别的记忆层字段

也就是说，sticky note 这一层的真正边界就是：

> 一张针对某个实体的文件真源便签。

如果后面还需要：

- relationship memory
- global memory
- 其他长期记忆层

它们应该作为别的 memory layer 独立设计，而不是继续躲在 sticky note 名下。

---

## 4. 正式数据模型

sticky note 的正式对象命名为：

- `StickyNoteRecord`

它代表“某个实体的一张便签记录”，最小字段集固定为：

- `entity_ref`
- `readonly`
- `editable`
- `updated_at`

其中：

- `entity_ref`
  - 是这张 note 的正式主键
  - 它只能指向实体对象或对话容器对象
- `readonly`
  - 承载人工确认过的高可信、稳定、基础性的事实锚点
- `editable`
  - 承载 bot 后续追加的观察、印象、提醒和低风险补充

这里保留双区，不是为了支持复杂编辑能力，而是为了表达**可信度分层**。

### `updated_at` 的定义

`updated_at` 表示整张 note 的最后更新时间。

在当前双文件物理形态下，它取：

- `readonly.md`
- `editable.md`

两个文件修改时间的最大值。

### `combined_text` 不属于 record

`combined_text` 不是 `StickyNoteRecord` 的持久化字段。

它只是输出层的统一渲染结果：根据

- `entity_ref`
- `readonly`
- `editable`

动态生成的一份完整文本视图。

这样可以保证：

- 原始数据保持干净
- 展示/注入格式不会反向污染 record 本身

---

## 5. 物理真源：文件系统

sticky note 的真源是文件系统。

第一版采用最直接的物理映射，不引入额外逻辑寻址结构。物理形态固定为：

- `user/<entity_ref>/readonly.md`
- `user/<entity_ref>/editable.md`
- `conversation/<entity_ref>/readonly.md`
- `conversation/<entity_ref>/editable.md`

这里虽然逻辑上是一实体一张 note，但物理上仍然保留“目录下双文件”，而不是单文件双分区。

这样做的原因是：

- `readonly` 和 `editable` 在物理上天然隔离
- 修改一边时不会误伤另一边
- 不需要依赖标题解析、正则切分之类脆弱逻辑

### `entity_ref` 的落盘规则

`entity_ref` 不做额外编码、转义或哈希，直接作为目录名使用。

之所以可以这样做，是因为：

- `entity_ref` 属于系统内部创建和控制的稳定标识
- 它不是任意外部输入

但即便如此，落盘前仍然要做严格字符白名单校验。

第一版这个白名单至少允许这些会出现在 canonical ref 里的字符：

- 字母和数字
- `:`
- `-`
- `_`
- `.`
- `@`
- `!`

同时明确禁止：

- 路径分隔符
- `..`
- 其他会破坏目录安全边界的字符

`entity_ref` 的合法性校验和 `entity_kind` 的派生，必须复用同一个共享解析 helper。file store、service、retriever、control plane 和 WebUI 不能各自维护一套不一致的判断规则。

---

## 6. 正式组件边界

这轮 sticky note 重构只覆盖四层：

- file store
- service
- bot tools
- retrieval / WebUI / control plane

不顺手扩展到 `/self`、LTM 或其他 memory page。

### 6.1 `StickyNoteFileStore`

底层文件真源层统一改名为：

- `StickyNoteFileStore`

它只负责：

- 文件路径组织
- 文件读写
- 列表读取
- `updated_at` 聚合
- 路径与标识校验

它不负责：

- bot 工具语义
- retrieval target 选择
- XML 渲染
- `MemoryBlock` 组装

它的外部接口只接正式主键 `entity_ref`。  
`entity_kind` 只在文件落盘和 UI 分组这种局部场景里由 `entity_ref` 派生，不作为 file store / service 的并列外部入参。

### 6.2 `StickyNoteService`

旧的 `StickyNotesService` 不再保留，新的受控服务层统一改名为：

- `StickyNoteService`

它负责：

- 面向 bot 的受控动作
- 面向人类控制面的整张 note 读写/删除
- 统一创建语义
- 把文件真源能力收成业务动作

它不负责：

- 自己渲染 `combined_text`
- 自己决定 retrieval target
- 自己决定 target slot

### 6.3 `StickyNoteRenderer`

渲染职责从 service 中单独拆出一个很小的组件：

- `StickyNoteRenderer`

它只负责一件事：

- 把一张 `StickyNoteRecord` 渲染成统一的完整文本视图

这份完整文本视图既用于：

- `sticky_note_read(...)`
- retrieval 注入

也就是说，同一张 note 的工具读取和上下文注入，使用同一套输出模板。

### 6.4 `StickyNoteRetriever`

retrieval 适配层统一改名为：

- `StickyNoteRetriever`

它负责：

- 接住 planner 给出的 sticky note targets
- 读取对应的 `StickyNoteRecord`
- 调用 `StickyNoteRenderer`
- 把结果转换成 `MemoryBlock`

它不负责理解 sticky note 的内部文件结构，也不负责生成 `combined_text` 的细节。

---

## 7. Bot 工具面

bot 侧正式只保留两个工具：

- `sticky_note_read`
- `sticky_note_append`

旧的：

- `sticky_note_put`
- `sticky_note_get`
- `sticky_note_list`
- `sticky_note_delete`

这一轮直接删除，不保留兼容入口。

### 7.1 `sticky_note_read`

`sticky_note_read(entity_ref)` 的语义是：

- 读取一个实体的完整 sticky note 视图

它返回给 bot 的不是原始分区结构，而是渲染后的完整文本块。

也就是说：

- bot 不直接看见 `readonly`
- bot 不直接看见 `editable`
- bot 只看见统一的 `combined` 完整表达

如果目标 note 不存在：

- 不抛错
- 只返回明确的空结果，例如 `exists = false`
- 不回显 bot 自己刚传入的参数

### 7.2 `sticky_note_append`

`sticky_note_append(entity_ref, text)` 的语义是：

- 向该实体 note 的 `editable` 区追加一条 bot 观察

它的边界很窄：

- `text` 必须是单行文本
- 工具层拒绝包含换行符的输入
- `text` 为空串或纯空白时直接拒绝
- 工具本身不做自动去重
- 服务端负责自动补换行和空行分隔

如果目标 note 不存在：

- `append` 允许自动创建

这里的逻辑是：

- retrieval/read 不产生副作用
- bot 明确决定“值得记一笔”时，才允许创建

`append` 的返回值只需要表达成功，不返回完整 record。  
如果 bot 真的想核对结果，再显式调用 `sticky_note_read(...)`。

---

## 8. 人类控制面

sticky note 的人类控制面和 bot 工具面是明确分层的。

### 人类控制面保留的能力

WebUI / control plane 保留：

- 新建便签
- 读取完整 `StickyNoteRecord`
- 保存整张 `StickyNoteRecord`
- 删除整张便签

也就是说，人类控制面继续能看到并编辑：

- `readonly`
- `editable`
- `updated_at`

### 为什么人类和 bot 的权限不一样

这是故意设计出来的：

- bot 只负责**读完整视图**和**追加一条观察**
- 人类负责**整理、迁移、提炼、重写整个实体档案**

因此：

- `readonly` 的限制只针对 bot
- 人类在 WebUI 里两块都可以编辑
- 人类可以把 bot 以前追加在 `editable` 里的内容整理后迁到 `readonly`

### 创建与删除

WebUI 需要显式提供“新建便签”入口，因为：

- 并不是每一张值得维护的便签都会先被 bot 读写

新建时只要求人类提供稳定的：

- `entity_ref`

系统再从 `entity_ref` 派生 `entity_kind`，并对这个主键做严格校验。

删除时：

- 保留人类删除能力
- 做二次确认

### 编辑体验

便签页第一版采用：

- 手动保存
- 不做自动保存

只要内容发生修改，就持续显示一个固定位置的“尚未保存”提示，但不遮挡主要内容。

### 页面形态

外层入口是“记忆”。

进入后，各个记忆层级是独立页面；sticky note 这一层在产品命名上直接叫：

- `便签`

便签页的核心形态参考文件系统浏览：

- 顶部用一个轻量的 `user/conversation` 二选一切换控件
- 主列表展示该类实体
- 点进某个实体后，在右侧展示两个编辑区

列表项需要显示：

- `entity_ref`
- `updated_at`

并提供：

- 搜索框
  - 第一版至少支持按 `entity_ref` 过滤
- 排序切换
  - `按时间`
  - `按名称`

默认排序是：

- 按时间倒序

---

## 9. Retrieval 主线怎么接

sticky note 是 memory 主线的一部分，所以它的 retrieval 不再靠硬编码拼 prompt，而是继续走：

- `RetrievalPlanner`
- `MemoryBroker`
- `StickyNoteRetriever`
- `ContextAssembler`

### 9.1 Planner 产出的是具体 `entity_ref` targets

planner 不再给抽象的 `sticky_note_scopes`。

它应该直接产出具体 retrieval target。这里的正式字段形状固定为：

- `sticky_note_targets: list[str]`
- 其中每个元素都必须是一个合法的 `entity_ref`

这条语义链必须在下面几层保持一致：

- `RetrievalPlan`
- `ThreadPipeline` 的 fallback retrieval plan
- `MemoryBroker` 构建出的 shared retrieval request
- `StickyNoteRetriever`

也就是说，这几层都应该围绕 `sticky_note_targets` 和其中的 `entity_ref` 工作，不能再出现 planner 说 target、contract 还说 scope、broker 还在转发旧字段、retriever 还读旧字段的半重构状态。

例如：

- 私聊：
  - 当前对话对象的 `user` `entity_ref`
- 群聊：
  - 当前对话容器的 `conversation` `entity_ref`
  - 当前发言人的 `user` `entity_ref`

sticky note 的 retrieval 不是全文搜索，也不是枚举所有 note，而是按 event 上下文对具体实体定址读取。

### 9.2 私聊与群聊的第一版策略

私聊：

- 只拉当前对话对象的 `user` note
- 不引入“私聊容器自己也有一张单独便签”这条线

也就是说，私聊第一版只把当前对话对象当成 sticky note 的主题对象，不再额外把私聊容器本身也做成第二张 note。

群聊：

- 拉当前对话容器的 `conversation` note
- 拉当前发言人的 `user` note

第一版不扩展到：

- 最近 N 个相关人物
- 被提及的人
- 更复杂的人物集合推断

### 9.3 不存在就安静跳过

sticky note retrieval 是纯读取路径，不产生副作用。

如果 target 不存在：

- 不自动创建
- 不报错
- 不做补偿
- 直接跳过

每个 target 都独立命中、独立注入。  
例如群聊里：

- `conversation` note 有
- 当前发言人 `user` note 没有

那就只注入 `conversation` note。

### 9.4 注入形态

sticky note 被转成 `MemoryBlock` 时：

- 每张 note 对应一个完整文本块
- 不把 `readonly` / `editable` 拆成两个独立 block

也就是说，可信度分层通过文本内部结构表达，而不是通过 block 数量表达。

### 9.5 文本模板

sticky note 注入给模型时使用固定的 XML 风格模板。

这样做的目的不是好看，而是：

- 在混合上下文里有稳定块边界
- 清楚区分元信息和内容部分
- 避免与普通自然语言上下文混淆

注入文本中至少需要显式携带：

- `entity_ref`

如果模板需要更强的人类可读性，可以再派生出：

- `entity_kind`

但不直接强调内部实现词 `readonly`。  
对 bot 更重要的是直接表达：

- 一部分是高可信、稳定的内容
- 一部分是 bot 累积的可追加观察

第一版 sticky note 一律完整注入，不在 sticky note 层做额外摘要、裁剪或压缩。  
如果未来需要控制 prompt 体积，那是发送前阶段的职责，不往 sticky note 层回摊责任。

---

## 10. 配置与开关

sticky note 的行为策略支持两层配置：

- 全局默认配置
- session / profile 级覆盖

不支持：

- per-note 配置

原因很简单：

- note 是内容对象，不是策略对象

像 retrieval 开关、target 选择、未来的 target slot 策略，都属于：

- 系统级决策
- 或 session/profile 级决策

### retrieval 配置归属

sticky note retrieval 的策略，直接走现有的 session/profile 配置体系。  
不为 sticky note 单独发明一套平行配置系统。

### tool 可见性与 retrieval 分离

bot 工具和 retrieval 开关彼此独立：

- retrieval 是否参与主线
  - 由 retrieval / memory 自己的配置决定
- `sticky_note_read` / `sticky_note_append` 是否可见
  - 由 profile 的 `enabled_tools` 决定

两者不能绑死在同一个开关上。

---

## 11. builtin capability，但 tool 不享受特权

sticky note 整体是 runtime 内建能力。

它包含：

- `StickyNoteFileStore`
- `StickyNoteService`
- `StickyNoteRenderer`
- `StickyNoteRetriever`
- control plane / HTTP API
- bot tools

其中 bot 侧工具只是：

- builtin tool adapter

它们由 runtime bootstrap 直接注册进 `ToolBroker`，不再经过 plugin manager 生命周期。

但它们**不享受任何工具特权**。

也就是说：

- `sticky_note_read`
- `sticky_note_append`

仍然和普通工具一样，按 profile 的 `enabled_tools` 控制是否暴露。

这一点对 subagent 也成立：

- subagent 只看见当前 profile/run 明确启用的工具
- 不会因为 sticky note 是 memory layer 就自动获得访问权

而 WebUI / control plane 的人类管理能力：

- 不受 `enabled_tools` 影响

因为它属于人类控制面，不属于模型工具暴露面。

---

## 12. 旧设计要删除什么

这轮重构不做平滑过渡，也不保留 legacy 兼容层。

删除目标包括：

- `MemoryItem`
- `MemoryStore`
- `structured_memory`
- `SQLiteMemoryStore`
- `InMemoryMemoryStore`
- sticky note 对这整条旧链路的任何依赖

这么做不是为了“代码更少”，而是因为这套抽象已经被判断为错误设计：

- 它会把 sticky note 误导成“统一记忆项”的一个变体
- 它会继续污染后续的 memory 架构判断
- 它会默默把新设计往错误方向拖回去

所以这轮的原则不是“先兼容一下”，而是：

> 直接删干净，别让错误抽象继续影响后面的设计。

---

## 13. 后续 TODO

下面这些点是明确保留到后续的，不在本轮展开：

### 13.1 target slot 策略

后续 sticky note 的 target slot 可以配置化。  
但本轮实现先统一放到靠近 `user message` 的位置。

### 13.2 群聊多人物扩展

未来可以考虑根据消息流扩展到：

- 最近 N 个相关人物的 `user` sticky notes

但本轮群聊只拉：

- 当前对话容器的 `conversation` note
- 当前发言人的 `user` note

### 13.3 更复杂的配置细节

全局默认和 session/profile 覆盖这两层已经定下来了。  
但具体字段名、配置文件形状和 UI 暴露方式，留给实现计划和代码阶段细化。

---

## 14. 推荐阅读顺序

如果后面新开会话，要先理解 sticky note 重构，不建议直接跳进代码。

建议按这个顺序读：

1. 本文档
2. [tmp-sticky-note-refactor-decisions.md](/home/acacia/AcaBot/docs/tmp-sticky-note-refactor-decisions.md)
3. [17-2-memory-stickynotes.md](/home/acacia/AcaBot/docs/17-2-memory-stickynotes.md)

其中：

- 本文档负责讲正式设计
- `tmp-sticky-note-refactor-decisions.md` 保留完整拍板过程和细粒度共识
- `17-2-memory-stickynotes.md` 继续承担“当前代码现状”说明
