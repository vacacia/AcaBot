# Sticky Note 重构 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 sticky note 从旧 `MemoryItem / MemoryStore / structured_memory / plugin tool` 链路中彻底抽离，重构成 runtime 内建的实体便签 memory layer，并同步落地新的 file store、service、renderer、retriever、builtin tools、control plane。WebUI 页面重构当前由另一条线并行推进，本计划先不执行 WebUI 部分。

**Architecture:** 这一轮把 sticky note 收成一条完全独立的实体便签主线：正式对象引用统一使用 `entity_ref`，`entity_kind = user | conversation` 只作为派生分类。文件真源由 `StickyNoteFileStore` 管，业务动作由 `StickyNoteService` 管，统一文本表达由 `StickyNoteRenderer` 管，retrieval 由 `StickyNoteRetriever` 读取渲染结果后转成 `MemoryBlock`。bot tools 作为 builtin tool adapter 由 bootstrap 直接注册到 `ToolBroker`，但仍然受 `enabled_tools` 控制；人类管理面先收口到 control plane / HTTP API，WebUI 页面实现暂缓，等并行重构稳定后再接。

**Tech Stack:** Python runtime, ToolBroker builtin tools, file-backed storage under `.acabot-runtime/sticky-notes/`, Control Plane + HTTP API, pytest

**Execution constraints:**
- 本轮不做兼容层，不保留旧 `MemoryItem` / `MemoryStore` / `structured_memory` / sticky notes plugin 链路。
- 本轮不要 commit。
- 本轮严格按 TDD 推进：先补/改测试，再实现，再跑对应测试。
- 本轮不展开 target slot 配置化，也不实现“最近 N 个相关人物”的 sticky note retrieval。

---

## 文件结构和职责

### 保留并重命名 / 重写的主文件

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
  - 重写为 `StickyNoteFileStore`
  - 负责 `user/<entity_ref>/readonly.md`、`editable.md` 以及 `conversation/<entity_ref>/readonly.md`、`editable.md` 的文件真源读写与列表
- `src/acabot/runtime/memory/sticky_notes.py`
  - 重写为 `StickyNoteService`
  - 负责 bot `read/append` 和人类控制面的整张 note 读写/删除
- `src/acabot/runtime/memory/file_backed/retrievers.py`
  - 替换 `StickyNotesFileRetriever`
  - 新增 / 改为 `StickyNoteRetriever`
- `src/acabot/runtime/bootstrap/__init__.py`
  - 替换旧 sticky note service/source 注入
  - 改为注入 `StickyNoteFileStore`、`StickyNoteService`、`StickyNoteRenderer`
- `src/acabot/runtime/bootstrap/builders.py`
  - 更新 memory broker 注册逻辑
  - 删除 `structured_memory` 注册
- `src/acabot/runtime/control/control_plane.py`
  - 改为 sticky note 专属人类管理接口
- `src/acabot/runtime/control/http_api.py`
  - 改为 sticky note 专属 HTTP API
### 新建文件

- `src/acabot/runtime/memory/sticky_note_renderer.py`
  - 定义 `StickyNoteRenderer`
  - 把 `StickyNoteRecord` 渲染成统一 XML `combined` 文本
- `src/acabot/runtime/builtin_tools/sticky_notes.py`
  - 注册 `sticky_note_read`
  - 注册 `sticky_note_append`

### 直接删除的旧链路

- `src/acabot/runtime/memory/structured_memory.py`
- `src/acabot/runtime/storage/memory_item_store.py`
- `src/acabot/runtime/plugins/sticky_notes.py`

### 需要显著删改的旧抽象

- `src/acabot/runtime/storage/stores.py`
  - 删除 `MemoryStore`
  - 删除 `MemoryItem` 相关协议依赖
- `src/acabot/runtime/storage/sqlite_stores.py`
  - 删除 `SQLiteMemoryStore`
- `src/acabot/runtime/contracts/records.py`
  - 删除 `MemoryItem`
- `src/acabot/runtime/contracts/__init__.py`
  - 去掉 `MemoryItem` 导出
- `src/acabot/runtime/__init__.py`
  - 去掉 `MemoryItem`、`MemoryStore`、`structured_memory` 相关导出

### 测试文件

- 新建：`tests/runtime/test_sticky_note_file_store.py`
- 新建：`tests/runtime/test_sticky_note_renderer.py`
- 新建：`tests/runtime/test_sticky_note_service.py`
- 新建：`tests/runtime/test_sticky_note_retriever.py`
- 新建：`tests/runtime/test_sticky_note_builtin_tools.py`
- 新建：`tests/runtime/test_http_api_sticky_notes.py`
- 修改：`tests/runtime/test_control_plane.py`
- 修改：`tests/runtime/test_builtin_tools.py`
- 删除或重写：`tests/runtime/test_sticky_notes_plugin.py`
- 删除或重写：`tests/runtime/test_structured_memory.py`
- 删除或重写：`tests/runtime/test_sqlite_memory_store.py`

---

## Task 1: 删除旧抽象的入口面，先把错误设计从公共契约中拔掉

**Files:**
- Modify: `src/acabot/runtime/contracts/records.py`
- Modify: `src/acabot/runtime/contracts/__init__.py`
- Modify: `src/acabot/runtime/storage/stores.py`
- Modify: `src/acabot/runtime/storage/sqlite_stores.py`
- Modify: `src/acabot/runtime/__init__.py`
- Delete: `src/acabot/runtime/storage/memory_item_store.py`
- Delete: `src/acabot/runtime/memory/structured_memory.py`
- Test: `tests/runtime/test_sqlite_memory_store.py`
- Test: `tests/runtime/test_structured_memory.py`

- [ ] 写一条删除面测试 / 导出测试，证明 `MemoryItem`、`MemoryStore`、`StoreBackedMemoryRetriever` 不再是公开契约的一部分。
- [ ] 跑旧测试，确认当前仍然有 `MemoryItem / MemoryStore / structured_memory` 依赖。
- [ ] 不要误删 `tests/runtime/test_memory_store.py`；这个文件实际测的是 `InMemoryMessageStore`，不属于 `MemoryStore` 旧链路清理范围。
- [ ] 删除 `MemoryItem` dataclass 及其导出；删除 `MemoryStore` 抽象和 `SQLiteMemoryStore / InMemoryMemoryStore`。
- [ ] 删除 `structured_memory.py` 以及 bootstrap 中对它的引用。
- [ ] 删除或重写不再成立的旧测试文件，不保留 legacy 断言。
- [ ] 运行：
  - `PYTHONPATH=src pytest tests/runtime/test_sqlite_memory_store.py tests/runtime/test_structured_memory.py -q`
  - 目标：旧链路测试不再存在，或已经被重写为“确认旧链路已删除”的新断言。

---

## Task 2: 落 `StickyNoteRecord` 和 `StickyNoteFileStore`

**Files:**
- Modify: `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- Test: `tests/runtime/test_sticky_note_file_store.py`

- [ ] 先写 `StickyNoteFileStore` 的失败测试，覆盖这些行为：
  - 只接受能稳定派生出 `entity_kind = user | conversation` 的 `entity_ref`
  - 一实体一张 note
  - 文件布局固定为 `<entity_kind>/<entity_ref>/readonly.md|editable.md`
  - `entity_kind` 只从 `entity_ref` 派生, 不作为 file store / service 的外部并列入参
  - `entity_ref` 白名单校验
  - `thread:...` 这种 `entity_ref` 直接拒绝
  - `session:...` 这种 `entity_ref` 直接拒绝
  - `updated_at = max(readonly, editable)`
  - retrieval/read 不存在时返回空
  - append/save 时支持缺失自动创建
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_file_store.py -q`
  - 目标：先红。
- [ ] 在 `src/acabot/runtime/memory/file_backed/sticky_notes.py` 中重写为新的 `StickyNoteRecord` + `StickyNoteFileStore`。
- [ ] 删除旧的 `scope_key / note_key / list_notes(scope_key=...) / read_pair(key=...)` 这套多级结构。
- [ ] 确认 docstring 和命名全部换成新模型。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_file_store.py -q`
  - 目标：转绿。

---

## Task 3: 落 `StickyNoteRenderer`

**Files:**
- Create: `src/acabot/runtime/memory/sticky_note_renderer.py`
- Test: `tests/runtime/test_sticky_note_renderer.py`

- [ ] 先写失败测试，覆盖：
  - 输出为固定 XML 风格模板
  - 模板显式携带 `entity_ref`
  - 如有派生分类，只使用从 `entity_ref` 派生出的 `entity_kind = user | conversation`
  - 文案强调“高可信内容 / 可追加观察”，不直露 `readonly` 这个实现词
  - 空 `readonly` 或空 `editable` 时仍能稳定渲染
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_renderer.py -q`
  - 目标：先红。
- [ ] 实现 `StickyNoteRenderer`，只接收 `StickyNoteRecord` 并输出统一 `combined` 文本。
- [ ] 不在 renderer 里做摘要、裁剪、slot 选择或 `MemoryBlock` 组装。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_renderer.py -q`
  - 目标：转绿。

---

## Task 4: 重写 `StickyNoteService`

**Files:**
- Modify: `src/acabot/runtime/memory/sticky_notes.py`
- Test: `tests/runtime/test_sticky_note_service.py`

- [ ] 先写失败测试，覆盖：
  - bot 读接口：只返回 `combined` 或 `exists=false`
  - bot append：单行文本约束、空白拒绝、自动创建、只写 `editable`
  - `thread:...` 这种 `entity_ref` 直接拒绝
  - `session:...` 这种 `entity_ref` 直接拒绝
  - 人类控制面：读完整 `StickyNoteRecord`
  - 人类控制面：整张保存可同时覆盖 `readonly + editable`
  - 人类控制面：删除整张 note
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_service.py -q`
  - 目标：先红。
- [ ] 把旧 `StickyNotesService` 改成 `StickyNoteService`。
- [ ] 删除旧的 `put_note/get_note/list_notes/delete_note` 围绕 `MemoryItem` 的行为。
- [ ] 明确拆出两类接口：
  - bot-facing：`read_note(...)`、`append_note(...)`
  - human-facing：`load_record(...)`、`save_record(...)`、`delete_record(...)`、`list_records(...)`
- [ ] 注入 `StickyNoteRenderer`，由 service 负责在 bot read 时调用 renderer。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_service.py -q`
  - 目标：转绿。

---

## Task 5: 重写 retrieval，替换成 `StickyNoteRetriever`

**Files:**
- Modify: `src/acabot/runtime/memory/file_backed/retrievers.py`
- Modify: `src/acabot/runtime/bootstrap/builders.py`
- Test: `tests/runtime/test_sticky_note_retriever.py`

- [ ] 先写失败测试，覆盖：
  - planner 提供具体 `entity_ref` targets 时 retriever 只读取这些实体
  - 私聊只拉当前 user note
  - 群聊拉 conversation note + 当前发言人 user note
  - target 不存在时安静跳过
  - 每张 note 生成一个完整 `MemoryBlock`
  - block 内容来自 renderer，而不是 retriever 内联拼字符串
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_retriever.py -q`
  - 目标：先红。
- [ ] 把 `StickyNotesFileRetriever` 改成 `StickyNoteRetriever`。
- [ ] 删掉旧的 `scope_key + note_key + list_notes()` 全量扫描逻辑。
- [ ] 改成基于 planner target 的定址 retrieval。
- [ ] 确认 block 仍然先统一走靠近 `user message` 的 slot，不展开 slot 配置化。
- [ ] 更新 bootstrap 的 memory source 注册，移除 `store_memory` 旧注册。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_retriever.py -q`
  - 目标：转绿。

---

## Task 6: 把 sticky note tools 从 plugin 改成 builtin tool adapter

**Files:**
- Create: `src/acabot/runtime/builtin_tools/sticky_notes.py`
- Modify: `src/acabot/runtime/builtin_tools/__init__.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Delete: `src/acabot/runtime/plugins/sticky_notes.py`
- Test: `tests/runtime/test_sticky_note_builtin_tools.py`
- Test: `tests/runtime/test_builtin_tools.py`
- Test: `tests/runtime/test_tool_broker.py`
- Test: `tests/runtime/test_sticky_notes_plugin.py`

- [ ] 先写失败测试，覆盖：
  - bootstrap 直接注册 `sticky_note_read` / `sticky_note_append`
  - 两个工具仍然受 `enabled_tools` 控制
  - subagent 不会自动看到未启用的 sticky note tools
  - 旧 `sticky_note_put/get/list/delete` 不再出现
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_builtin_tools.py tests/runtime/test_builtin_tools.py tests/runtime/test_tool_broker.py -q`
  - 目标：先红。
- [ ] 新建 builtin tool surface，注册 `sticky_note_read` / `sticky_note_append`。
- [ ] 在 `register_core_builtin_tools(...)` 中接入 sticky note builtin surface。
- [ ] 删除 `StickyNotesPlugin` 及其测试。
- [ ] 重写 / 删除旧插件测试，不再保留 plugin 生命周期断言。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_builtin_tools.py tests/runtime/test_builtin_tools.py tests/runtime/test_tool_broker.py -q`
  - 目标：转绿。

---

## Task 7: 收口 control plane / HTTP API

**Files:**
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `src/acabot/runtime/bootstrap/components.py`
- Test: `tests/runtime/test_control_plane.py`
- Test: `tests/runtime/test_http_api_sticky_notes.py`

- [ ] 先写失败测试，覆盖：
  - 人类控制面读取返回完整 `StickyNoteRecord`
  - 新建时严格校验 `entity_ref`
  - 保存整张 note 支持创建和覆盖
  - 删除整张 note 需要专用接口
  - API 不再复用 `MemoryItem` 风格 payload
  - HTTP API 至少覆盖 sticky note 的 `GET/PUT/POST/DELETE`
  - HTTP API 的 payload shape 和返回 shape 都围绕 `StickyNoteRecord / entity_ref`
  - 不再走旧 `/readonly` 旧语义
- [ ] 跑：
  - `PYTHONPATH=src pytest tests/runtime/test_control_plane.py tests/runtime/test_http_api_sticky_notes.py -q`
  - 目标：先红。
- [ ] 把 sticky note 相关 control plane 接口改成围绕 `StickyNoteRecord`。
- [ ] 删除旧的 `/api/memory/sticky-notes/readonly` 这类残留旧结构接口，或重写成新语义。
- [ ] 确保人类管理面不受 `enabled_tools` 影响。
- [ ] 再跑：
  - `PYTHONPATH=src pytest tests/runtime/test_control_plane.py tests/runtime/test_http_api_sticky_notes.py -q`
  - 目标：转绿。

---

## Task 8: WebUI 页面暂缓

WebUI 这部分当前正在并行重构，本计划先不执行页面侧改动。

- [ ] 本轮只保证 sticky note 的 backend 契约、tool、retrieval 和文档对齐，不主动改 `webui/src/`。
- [ ] 等并行的 WebUI 重构稳定后，再单独写一份页面实现 plan，把 `user/conversation` 切换、搜索、排序、双编辑区和未保存横幅接进去。

---

## Task 9: 把 planner / retrieval 配置语义对齐到 sticky note 新设计

**Files:**
- Modify: `src/acabot/runtime/contracts/context.py`
- Modify: `src/acabot/runtime/memory/memory_broker.py`
- Modify: `src/acabot/runtime/pipeline.py`
- Modify: `src/acabot/runtime/memory/retrieval_planner.py`
- Modify: `src/acabot/runtime/contracts/session_config.py`（仅当现有 retrieval 配置承载不下新 sticky note target 语义时）
- Modify: `src/acabot/runtime/control/profile_loader.py`（仅当 profile 配置解析需要补 sticky note retrieval 选项时）
- Test: `tests/runtime/test_retrieval_planner.py`
- Test: `tests/runtime/test_memory_broker.py`
- Test: `tests/runtime/test_bootstrap.py`

- [ ] 先补失败测试，覆盖：
  - planner 产出 sticky note 具体 `entity_ref` targets，而不是抽象分类名字
  - 私聊只产出当前 user target
  - 群聊产出 conversation target + 当前发言人 user target
  - sticky note retrieval 开关与 tools 开关无关
- [ ] 跑对应测试，确认先红。
- [ ] 把 planner 的 sticky note 语义改成“产出 `sticky_note_targets`”，并明确这个字段的正式 shape 是 `list[str]`，其中每个元素都是合法的 `entity_ref`。
- [ ] 把 `RetrievalPlan`、`ThreadPipeline` fallback plan、`MemoryBroker` shared request 构建、retriever 消费端一起统一到同一条字段语义链上。
- [ ] 明确删除旧的 `sticky_note_scopes` 字段和任何只传 scope 不传实体的旧语义，避免出现 planner 说 target、contract 还说 scope、broker 还在转发旧字段、retriever 还读旧字段的半重构状态。
- [ ] 至少跑这三组回归：
  - `PYTHONPATH=src pytest tests/runtime/test_retrieval_planner.py -q`
  - `PYTHONPATH=src pytest tests/runtime/test_memory_broker.py -q`
  - `PYTHONPATH=src pytest tests/runtime/test_bootstrap.py -q`
- [ ] 不实现“最近 N 个相关人物”。
- [ ] 不实现 slot 配置化，只保留后续 TODO 注释和文档。
- [ ] 再跑对应测试，确认转绿。

---

## Task 10: 文档同步与清理

**Files:**
- Modify: `docs/00-ai-entry.md`
- Modify: `docs/17-2-memory-stickynotes.md`
- Modify: `docs/17-2-memory-stickynotes-refactor.md`
- Modify: `docs/tmp-sticky-note-refactor-decisions.md`
- Modify: `docs/HANDOFF.md`

- [ ] 更新 `docs/17-2-memory-stickynotes.md` 的“当前代码现状”，明确它描述的是重构前还是重构后现状，避免和正式设计打架。
- [ ] 回读正式设计文档，确保实现中的命名没有偏离：
  - `entity_ref`
  - `entity_kind`
  - `sticky_note_targets`
  - `StickyNoteFileStore`
  - `StickyNoteService`
  - `StickyNoteRenderer`
  - `StickyNoteRetriever`
  - `StickyNoteRecord`
- [ ] 把实际实现中确认 postpone 的项重新同步到“后续 TODO”小节。
- [ ] 更新 `HANDOFF.md`，写明：
  - 新主线
  - 已删除旧链路
  - 先看哪几篇文档

---

## Task 11: 全量验证本轮 sticky note 重构

**Files:**
- Test only

- [ ] 运行 sticky note 直接相关测试：
  - `PYTHONPATH=src pytest tests/runtime/test_sticky_note_file_store.py tests/runtime/test_sticky_note_renderer.py tests/runtime/test_sticky_note_service.py tests/runtime/test_sticky_note_retriever.py tests/runtime/test_sticky_note_builtin_tools.py tests/runtime/test_control_plane.py tests/runtime/test_http_api_sticky_notes.py -q`
- [ ] 运行工具与 bootstrap 回归：
  - `PYTHONPATH=src pytest tests/runtime/test_builtin_tools.py tests/runtime/test_tool_broker.py tests/runtime/test_bootstrap.py -q`
- [ ] 运行 memory/context 主线回归：
  - `PYTHONPATH=src pytest tests/runtime -q -k 'sticky or tool_broker or control_plane or bootstrap'`
- [ ] 记录任何因为本轮删除 `MemoryItem / structured_memory / MemoryStore` 导致的非 sticky note 连锁失败，并在执行总结里明确列出。
- [ ] 不要 commit；把剩余风险和未动的 TODO 在执行总结里写清楚。

---

## 后续明确不做的事

- 不做 per-note 配置
- 不做 sticky note 自己的裁剪/摘要
- 不做 “最近 N 个相关人物” retrieval
- 不做 target slot 配置化实现
- 不做本轮 WebUI 页面实现
- 不做 plugin 兼容层
- 不保留 `MemoryItem / MemoryStore / structured_memory` 旧链路
- 不在本轮处理别的 memory layer

---

Plan 完成后，执行 agent 应先回读：

- [17-2-memory-stickynotes-refactor.md](/home/acacia/AcaBot/docs/17-2-memory-stickynotes-refactor.md)
- [tmp-sticky-note-refactor-decisions.md](/home/acacia/AcaBot/docs/tmp-sticky-note-refactor-decisions.md)
- [17-2-memory-stickynotes.md](/home/acacia/AcaBot/docs/17-2-memory-stickynotes.md)

再开始落代码。
