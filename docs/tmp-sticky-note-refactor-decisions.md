# Sticky Note 重构决策

这一页只记录已经拍板的 sticky note 重构决定。

## 命名收束更新

这一页保留了完整的讨论结论，但后续正式实现一律以 [00-ai-entry.md](/home/acacia/AcaBot/docs/00-ai-entry.md) 里的全局命名字典为准。

从这次命名收束开始，sticky note 相关主契约统一改成：

- 正式对象引用统一叫 `entity_ref`
- 派生分类统一叫 `entity_kind = user | conversation`
- 旧写法里的 `channel` 统一读作 `conversation`
- 旧写法里的 `channel note` 统一读作 `conversation note`
- 旧写法里的 `channel_scope` 统一读作 `conversation_id`
- 旧写法里的 `sticky_note_read(scope, entity_id)` 统一读作 `sticky_note_read(entity_ref)`
- 旧写法里的 `sticky_note_append(scope, entity_id, text)` 统一读作 `sticky_note_append(entity_ref, text)`

这也意味着下面早期讨论里关于：

- `scope + entity_id`
- `user/channel`

这些说法，后续都不再作为正式实现契约。

## 已确认决定

1. Sticky note 正式只保留 `user` 和 `conversation` 两种 `entity_kind`。
2. `relationship` 和 `global` 不再属于 sticky note 体系，它们如果还需要存在，应该作为别的记忆层单独表达。
3. Sticky note 的核心边界是“它对应哪个实体”。只要能稳定表达出对应实体，标识就已经足够；后面的数据模型应尽量围绕这个目标收窄，不再引入额外的抽象归属层。
4. Sticky note 的正式对象标识统一收成单个 `entity_ref`。
5. `entity_kind` 只保留为从 `entity_ref` 派生出来的局部分类，用于 WebUI 分组和局部枚举，不再承担主契约职责。
6. Sticky note 默认是一实体一张 note。
7. 第一版不保留 `note_key` 这一层。sticky note 的物理和逻辑形态都围绕“某个实体对应一张便签”来设计。
8. Sticky note 的真源仍然是文件，但正式写入口定为 sticky note 专用 service/tool，不开放 bot 直接把内部 sticky note 文件路径当作普通文件去改。
9. 这样做的目的不是否定文件真源，而是把 `editable/readonly` 规则、实体合法性、以及后续目录结构演进都收在受控入口里，避免 bot 依赖内部物理路径。
10. Sticky note 的读取不区分 `readonly` 和 `editable`。无论是检索还是工具读取，默认都读取整张 note 的完整内容。
11. `readonly/editable` 的区分只存在于写入侧。保留 `readonly` 的目的，是让人工能够写入绝对可靠的基础信息，并防止 bot 在修改时误伤这些内容。
12. 即使第一版 bot 侧写工具只有 `append`，也仍然保留 `readonly/editable` 双区。
13. 保留双区的核心原因不是为了支持复杂编辑，而是为了表达可信度分层：
    - `readonly` 承载人工确认过的高可信、稳定、基础性的事实锚点
    - `editable` 承载 bot 后续追加的观察、印象、提醒和低风险补充
14. 因此，读取时虽然统一读取整张 note，但写入语义上仍然要清楚区分“人工高可信信息”和“bot 累积观察”，避免两类内容混在一起失去责任边界。
15. 第一版正式只给 bot 两个 sticky note 工具：
    - `sticky_note_read(entity_ref)`
    - `sticky_note_append(entity_ref, text)`
16. 第一版不提供 replace、delete、list all notes，也不暴露 sticky note 的内部真实文件路径。
17. `sticky_note_append(...)` 只允许向 `editable` 区追加内容；`sticky_note_read(...)` 默认返回整张 note 的完整视图。
18. 工具提示词里需要明确说明 `entity_ref` 的规则和用途，让 bot 能在聊天过程中根据观察到的发言人或当前对话容器，主动读取或追加任意相关实体的 sticky note。
19. 这意味着 bot 不只能读取“当前自己正在对话的对象”，也应该能在群聊里基于消息中的发言人和当前对话容器，读取某个人或某个对话容器的便签，并把新的观察追加进去。
20. Sticky note 的 retrieval 目标由 `RetrievalPlanner` 直接产出为具体实体 target，而不是只给抽象的分类名字；这个 retrieval 字段的正式 shape 固定为：
    - `sticky_note_targets: list[str]`
    - 其中每个元素都必须是一个合法的 `entity_ref`
21. 这些 target 直接根据 event 中的来源信息决定：
    - 私聊默认检索当前对话对象对应的 `user` sticky note
    - 群聊默认检索当前对话容器对应的 `conversation` sticky note，以及当前发言人对应的 `user` sticky note
22. Sticky note 的检索不是全文搜索或模糊枚举，而是基于 event 上下文对具体实体进行定址 retrieval，再由后续 memory 层统一装配进上下文。
23. Sticky note source / retriever 直接使用 sticky note 自己的专属数据模型，并直接把它转换成 `MemoryBlock`。
24. Sticky note 这一支中间不再经过 `MemoryItem`。`MemoryItem` 不再承担 sticky note 的中间表示或统一记忆对象角色。
25. 这一轮不保留 `MemoryItem` 及其旧链路的兼容层，也不考虑平滑过渡。
26. 重构目标是直接把 sticky note 从 `MemoryItem` 体系中完全抽离，并同步删除 `MemoryItem` 相关的旧抽象和旧实现，而不是先标记 legacy 再等待第二轮清理。
27. 这一轮直接删除整条 store-backed old memory 链，不保留 `MemoryStore / structured_memory / SQLiteMemoryStore / InMemoryMemoryStore` 这一套旧设计。
28. 删除理由不是单纯“代码没用了”，而是这套抽象已经被判断为错误设计；如果继续保留，会持续误导后续架构判断，并默默把新的 memory 设计往错误方向拉偏。
29. Sticky note 的专属数据对象命名为 `StickyNoteRecord`。
30. 这个对象代表“针对某个实体的一张文件真源便签记录”，后续 service、tool、retriever、WebUI 都围绕这个名字建立一致语义。
31. `StickyNoteRecord` 的最小字段集先定成：
    - `entity_ref`
    - `readonly`
    - `editable`
    - `updated_at`
32. 不再把 `author`、`confidence`、`memory_type`、`source_run_id` 等别的记忆层字段混入 sticky note 对象。
33. `updated_at` 保持为单个时间戳字段，用来表达“这张 note 最近一次被修改的时间”，不做数组。
34. Sticky note 的文件真源布局直接按 `entity_kind` 分目录，并以实体作为唯一寻址单元，不再额外引入 `note_key`、嵌套层级或别的逻辑映射结构。
36. 虽然逻辑上是一实体一张 sticky note，但物理上继续采用“目录下双文件”的结构，而不是单文件双分区。
37. 采用双文件的原因是让 `readonly` 和 `editable` 在物理上天然隔离，避免修改一边时误伤另一边，也避免为了分区解析去引入标题约定、正则切分等脆弱逻辑。
38. 因此，重构后的文件布局进一步收敛为：
    - `user/<entity_ref>/readonly.md`
    - `user/<entity_ref>/editable.md`
    - `conversation/<entity_ref>/readonly.md`
    - `conversation/<entity_ref>/editable.md`
39. `entity_ref` 不做额外编码、转义或哈希，直接作为目录名使用。
40. 之所以可以保持原样，是因为 `entity_ref` 属于系统内部创建和控制的稳定标识，不是任意外部输入。
41. 即便如此，落盘前仍然要经过严格字符白名单校验；第一版至少允许字母、数字、`:`、`-`、`_`、`.`、`@`、`!` 这些会出现在 canonical ref 里的字符，并明确禁止路径分隔符、`..` 和其他会破坏目录安全边界的内容。
42. `entity_ref` 的合法性校验和 `entity_kind` 的派生必须复用同一个共享解析 helper，不让 file store、service、retriever、control plane、WebUI 各自写一套判断。
42. Sticky note 的 retrieval 是纯读取路径，不产生副作用。
43. 当 planner/broker 依据 event 上下文检索某个实体的 sticky note 时，如果目标文件不存在，就视为“当前没有这张 note”，直接返回空结果，不自动创建。
44. 检索阶段不负责补档或预建空文件，避免 bot 仅仅因为看到了某个实体，就把文件系统污染出大量空 sticky note。
45. `sticky_note_append(entity_ref, text)` 在目标 note 不存在时自动创建。
46. 自动创建的前提是 bot 已经明确做出了“这条内容值得记下来”的写入决策；因此它属于受控写副作用，而不是检索阶段的隐式产物。
47. 第一版 `sticky_note_append(...)` 采用最简单的文本追加语义：总是在 `editable` 末尾追加一段文本，不做结构化 merge、去重或智能重排。
48. bot 侧只传入一段单段文本，不要求也不鼓励自己携带换行、分节或复杂格式。
49. 分隔规则由服务端统一处理：在追加时自动补必要的换行和空行，让 `editable` 保持稳定、可读的逐段累积形态。
50. 第一版 `sticky_note_append(...)` 的 `text` 参数明确限制为单行文本；工具层直接拒绝包含换行符的输入。
51. 这一限制要直接写进工具描述（tool description / prompt hint）里，让 bot 从使用层面就形成稳定预期：每次只追加一条短观察，而不是提交多段大块文本。
52. `sticky_note_read(entity_ref)` 返回给 bot 的是这个实体的完整 sticky note 视图。
53. 这份完整视图统一叫 `combined_text`，它的语义应与 retrieval 注入给模型的 sticky note 内容保持一致。
54. 检索默认会根据 event 带上当前相关实体的完整 note；因此 bot 主动调用 `sticky_note_read(...)` 查看其他实体信息时，也应该看到同样意义上的完整 note，而不是被裁开的局部片段。
55. Sticky note 在 retrieval 阶段转换为 `MemoryBlock` 时，第一版只注入一个完整文本块，不把 `readonly` 和 `editable` 拆成两个独立 block。
56. 可信度分层不通过 block 数量表达，而是在这个完整文本块内部通过 Markdown 或 XML 风格的结构提示明确告诉 bot：
    - `readonly` 是人工维护的高可信信息
    - `editable` 是 bot 累积观察的可追加区
57. Sticky note 的注入位置后续要支持配置化，每一类记忆都可以声明自己的 target slot。
58. 这一能力当前只记录为 TODO，本轮不展开设计和实现。
59. 当前阶段 sticky note 统一先注入到靠近当前 `user message` 的位置，后续再根据场景细分 `conversation note`、`user note` 在不同会话类型下的 target slot 策略。
60. WebUI / control plane 的外层入口应表达为“记忆”，点开后再进入各个记忆层级的独立页面；sticky note 这一层在产品命名上直接叫“便签”。
61. “便签”页面本身只围绕 sticky note 的专属对象工作，不再复用 `MemoryItem` 的概念或展示方式。
62. 便签页的交互形态参考文件系统浏览：
    - 左侧/主区域展示 `user`、`conversation` 下的实体目录
    - 点进某个实体后，在右侧展示对应 note 的两个编辑区
63. `readonly` 的限制只针对 bot 写入语义；在人类使用的 WebUI 中，两块内容都允许直接编辑。
64. 人类可以随时把 bot 之前追加在 `editable` 里的内容整理、提炼并迁移到 `readonly`，把高可信信息沉淀成更稳定的实体档案。
65. 便签页中的实体浏览仍然按 `user` 和 `conversation` 两类分组。
66. 但由于只有两类，不单独占用一个永久侧栏做复杂层级导航；而是在页面顶部提供一个轻量的二选一切换控件，让用户在 `user` / `conversation` 两种实体视图之间切换。
67. 实体列表项需要显示 `updated_at`，让人能快速看出哪些便签最近发生过变化，方便整理和回看。
68. 实体列表提供排序切换按钮，至少支持：
    - 按时间
    - 按名称
69. 默认排序为按时间倒序，也就是最近更新的实体排在最前面。
70. `sticky_note_append(...)` 第一版不做自动去重，包括“完全相同文本的连续追加”也不拦截。
71. 重复内容的清理和整理交给人类在便签页面中处理，不把这层复杂性前置到 bot 写入路径里。
72. 群聊场景下，sticky note 的 `user` target 第一版只取当前触发这条 event 的发言人。
73. 第一版不扩展到“最近 N 条消息里出现过的人”、被提及的人、或更复杂的人物集合推断。
74. 这一点作为后续 TODO 留在文档里：未来可以考虑根据消息流中的多个相关人物批量拉取 user sticky notes，但不在当前重构范围内展开。
75. 私聊场景下，第一版只拉当前对话对象对应的 `user` sticky note。
76. 第一版不额外引入 `private conversation note` 这一层概念，避免在 `user/conversation` 之外重新长出第三种半重叠实体语义。
77. `sticky_note_read(entity_ref)` 在目标 note 不存在时，不抛错。
78. 工具返回明确的空结果语义，例如 `exists = false` 或同等可判定结构，让 bot 能稳定区分“读取失败”和“当前没有这张 note”。
79. `sticky_note_append(entity_ref, text)` 在 `text` 为空串或纯空白时直接拒绝。
80. 这种输入既不创建 note，也不写入任何内容，避免 bot 因为空操作制造空文件或无意义噪音。
81. 人类在 WebUI 里编辑 sticky note 时，第一版采用手动保存，不做自动保存。
82. 只要页面内容发生修改，就持续显示一个固定位置的“尚未保存”提示；这个提示要稳定可见，但不能遮挡主要编辑内容。
83. 便签页第一版提供搜索框，至少支持按 `entity_ref` 做列表过滤。
84. control plane / HTTP API 第一版只暴露 sticky note 专属接口。
85. 这些接口直接围绕 `StickyNoteRecord` 和 sticky note 专属动作设计，不再保留或复用通用 `MemoryItem` 风格的接口形状。
86. bot 侧正式工具面收敛为：
    - `sticky_note_read`
    - `sticky_note_append`
87. 旧的 `sticky_note_put/get/list/delete` 视为错误设计的一部分，这一轮直接删除，不保留兼容入口。
88. control plane / WebUI 这边保留“完整保存整张 `StickyNoteRecord`”的接口。
89. 这个接口允许人类一次性提交和覆盖 `readonly + editable` 两块内容，用于整理、迁移、提炼和重写整个实体档案。
90. 因此，bot 工具面和人类控制面明确分层：
    - bot 只有 `read + append`
    - 人类拥有整张 note 的完整编辑权
91. WebUI 提供显式的“新建便签”入口，让人类可以主动为一个尚未被 bot 读写过的实体先建立档案。
92. 新建时需要严格校验 `entity_ref` 的格式，避免无效实体进入文件系统。
93. 读取路径仍然保持纯读：note 不存在就返回空，不创建。
94. bot 的 `append` 在目标不存在时可自动创建；人类通过 WebUI 保存整张 note 时，如果目标不存在，也允许直接创建。
95. WebUI / control plane 为人类保留“删除整张便签”的能力。
96. bot 不具备 delete 能力；删除属于人类档案管理动作的一部分。
97. 人类在 WebUI 删除便签时，第一版需要二次确认，避免误触造成实体档案被直接移除。
98. `StickyNoteRecord.updated_at` 定义为“整张 note 的最后更新时间”。
99. 在当前双文件物理形态下，它取 `readonly.md` 和 `editable.md` 两个文件修改时间的最大值。
100. 重构后不再保留 `StickyNotesService` 这个旧名字。
101. 新的受控服务层统一改名为 `StickyNoteService`，以明确它处理的是“一张实体便签”的新模型，而不是旧 `MemoryItem` 时代的混合职责延续。
102. 底层文件真源层也同步改名，不再保留 `StickyNotesSource` 这个旧名字。
103. 文件真源层统一改名为 `StickyNoteFileStore`，明确它的职责是 sticky note 的文件存取，而不是泛化的 source 概念。
104. retrieval 适配层也同步改名，不再保留 `StickyNotesFileRetriever` 这个旧名字。
105. retrieval 适配层统一改名为 `StickyNoteRetriever`，表达它是“按实体 target 读取 sticky note 并转换成 `MemoryBlock`”的专属适配器。
106. 这一轮 sticky note 重构明确只覆盖以下四层：
    - file store
    - service
    - bot tools
    - retrieval / WebUI / control plane
107. 本轮不顺手扩展到别的记忆层设计，也不借机重做 `/self`、LTM、或其他未来 memory page 的抽象。
108. 人类在 WebUI / control plane 中编辑 sticky note 内容时，不对 `readonly` / `editable` 的正文格式施加额外限制；人可以自由整理、重写、搬运和排版内容。
109. bot 侧写入语义仍然保持窄边界：一次只追加一句单行文本，由服务端自动补换行和分隔。
110. 这里放开的只是“note 正文内容”的编辑自由，不包括 `entity_ref` 这类标识字段；这些标识字段仍然要经过前面已确定的严格校验规则。
111. `sticky_note_append(...)` 的返回值不回传完整 `StickyNoteRecord`。
112. 第一版只返回简洁成功结果即可；如果 bot 需要核对当前完整状态，应显式再调用 `sticky_note_read(...)`。
113. `sticky_note_read(...)` 在目标不存在时，空结果只需要表达“当前不存在这张 note”，例如 `exists = false`。
114. 空结果不需要回显 `entity_ref` 等调用参数；这些参数本来就是 bot 自己输入的，重复返回只会让结构更啰嗦。
115. Sticky note 注入给模型时，第一版使用固定的 XML 风格模板，而不是 Markdown 标题模板。
116. 采用 XML 风格的原因是让 sticky note 在混合上下文中拥有更稳定的块边界，并更清楚地区分元信息、可信内容和可追加观察等内部部分。
117. 面向 bot 的注入文本不强调 `readonly` 这个实现术语，而是直接表达语义：
    - 一部分是高可信、稳定的内容
    - 一部分是 bot 累积的可追加观察
118. `readonly/editable` 仍然保留为系统内部和人类编辑界面的结构边界，但在 prompt 注入层优先突出“可信度分层”而不是实现字段名。
119. 注入给模型的 sticky note XML 需要显式携带 `entity_ref`。
120. 如果模板需要更强的人类可读性，可以再派生出 `entity_kind`；但主身份字段始终是 `entity_ref`，避免在多块上下文混合时丢失归属。
121. 第一版 sticky note 在注入上下文时一律完整注入，不做额外摘要、裁剪、压缩或选择性截断。
122. sticky note 作为高频、小而稳的记忆层，当前优先保证语义完整和行为直接，不提前为了 token 预算引入额外复杂性。
123. `sticky_note_read(...)` 返回给 bot 的 `combined_text` 与 retrieval 注入给模型的完整 sticky note 视图，统一复用同一套 XML 模板。
124. 这种模板统一不是“第一版权宜之计”，而是长期边界：同一个 sticky note 在工具读取和上下文注入中应保持同一种完整表达。
125. sticky note 层不负责裁剪、压缩或发送前截断；如果未来需要控制 prompt 体积，这属于更后面的发送前阶段职责，不应把责任分摊回 sticky note 自身。
126. `StickyNoteRecord` 本身不包含 `combined_text` 这一字段。
127. `combined_text` 只是输出层的渲染结果：在 `sticky_note_read(...)` 或 retrieval 注入时，根据 `entity_ref + readonly + editable` 动态生成。
128. 这样可以保持原始数据和展示/注入格式分离，避免把 presentation 层格式固化进 record 本身。
129. 渲染职责从 service 中单独拆出一个很小的 `StickyNoteRenderer`。
130. `StickyNoteRenderer` 只负责把一张 `StickyNoteRecord` 的两块内容渲染成统一的完整文本视图（XML 模板）。
131. 检索层不承担 sticky note 内部格式知识；retrieval 只拿若干已经渲染好的完整文本块拼接进上下文，不关心里面是不是 `combined_text`、也不关心 `readonly/editable` 的内部渲染细节。
132. bot 侧的 `sticky_note_read(...)` 也只返回渲染后的完整视图，不暴露 `readonly` / `editable` 两个原始分区。
133. `readonly` / `editable` 这两个分区只属于文件系统、人类使用的 WebUI / control plane、以及系统内部服务层；一旦进入 bot 工具或模型上下文，就统一表现为一个 `combined` 完整文本块。
134. 这样可以明确划清边界：bot 只消费“这个实体的完整便签表达”，而不接触人类维护结构和文件分区细节。
135. WebUI / control plane 的读接口继续返回完整的 `StickyNoteRecord`。
136. 这意味着人类控制面仍然能看到并编辑 `readonly + editable + updated_at` 这套原始结构，因为这本来就是人类档案整理和维护所需要的视图。
137. Sticky note retrieval 中的每个 target 都独立命中、独立注入。
138. 例如群聊场景下，如果当前发言人的 `user` note 不存在，但 `conversation` note 存在，就只注入 `conversation` note；反之亦然。
139. 对不存在的 target，不做补偿、不报错、也不引入替代逻辑，直接安静跳过。
140. Sticky note 整体被定义为 runtime 内建能力，而不是外部 plugin。
141. 这套内建能力包含：
    - `StickyNoteFileStore`
    - `StickyNoteService`
    - `StickyNoteRenderer`
    - `StickyNoteRetriever`
    - control plane / HTTP API
    - bot tools
142. bot 侧的 `sticky_note_read` / `sticky_note_append` 只是这套内建能力暴露出来的 builtin tool adapter，不作为可选 plugin 独立存在。
143. `sticky_note_read` / `sticky_note_append` 这两个 builtin tools 由 runtime bootstrap 直接注册进 tool broker。
144. 这两个工具不经过 plugin manager 生命周期，不再作为 runtime plugin 动态挂载。
145. 尽管 sticky note tools 属于 builtin tool adapter，但它们不享受任何工具可见性特权。
146. `sticky_note_read` / `sticky_note_append` 仍然和其他普通工具一样，按 profile 的 `enabled_tools` 机制控制是否暴露。
147. 这一点对 subagent 同样成立：subagent 只会看见当前 profile / run 明确启用的工具，不因为 sticky note 是 memory layer 就自动获得使用权。
148. 因此 sticky note tools 的原则是“谁用谁显式装上”，而不是默认向所有 agent / subagent 强行开放。
149. Sticky note 的 retrieval 能力和 bot tools 的开关彼此独立。
150. retrieval 是否参与主线，由 retrieval / memory 自己的配置决定；`sticky_note_read` / `sticky_note_append` 是否可见，则继续由 profile 的 `enabled_tools` 决定。
151. 两者不能绑死在同一个开关上：关闭 bot tools 不应自动关闭 sticky note retrieval；关闭 sticky note retrieval 也不应反向影响 bot tools 的可见性。
152. 这份临时决策文档需要单独整理一个“未决 / 后续 TODO”小节。
153. 所有已经明确 postpone、但又不该丢失的点，都集中沉淀到这一节里，方便后续写正式设计文档和 implementation plan 时直接引用。
154. “sticky note target slot 后续可配置”这一点明确归入后续 TODO。
155. 本轮实现中，sticky note 统一先走靠近 `user message` 的位置；未来再根据记忆类型和会话场景细分不同 target slot 策略。
156. “群聊未来可按消息流扩展到最近 N 个相关人物的 user sticky notes” 这一点明确归入后续 TODO。
157. 本轮实现里，群聊场景仍然只拉当前发言人的 `user` note，不扩展到更大的相关人物集合。
158. Sticky note 的行为策略支持两层配置：
    - 全局默认配置
    - session / profile 级覆盖
159. 不支持 per-note 配置。单张 `StickyNoteRecord` 只承载内容和基础元数据，不承担行为策略。
160. 因此像 retrieval 开关、target 选择、未来的 slot 策略等，都属于系统级或 session/profile 级决策，而不是单张 note 自己携带的属性。
161. Sticky note retrieval 及相关策略配置直接走现有的 session / profile 配置体系。
162. 不为 sticky note 单独发明一套平行的配置入口或配置系统，避免重复治理和配置语义分裂。
163. WebUI / control plane 中的人类 sticky note 管理能力，不受 `enabled_tools` 影响。
164. `enabled_tools` 只控制模型 / agent / subagent 是否能看见并使用 `sticky_note_read` / `sticky_note_append` 这类 bot 工具；人类控制面仍然独立存在。

---
