## Sticky Note

### 设计理念(不准修改)

定位：
    - 零碎但长期有用的笔记
    - 让 bot 以后还能继续理解某个用户或某个群
    - 每次都会注入上下文, 每次几乎都能用上
    - user: 人名/生日/重大经历/...稳定事实
    - channel: 群聊信息, 群内黑话, 风格...

- 当前主要挂在 `user` 和 `channel` 两个 scope
- 每个 scope 分成两块：
    - `readonly`
    - `editable`
- 两块都会注入上下文
- `readonly` 由人工维护
- `editable` 允许 bot 更新

### 当前代码现状

#### 1. 文件真源已经收成实体便签

代码在：

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- `src/acabot/runtime/memory/sticky_note_entities.py`

当前 sticky note 的正式主键已经统一成：

- `entity_ref`

当前 sticky note 的正式分类只保留：

- `entity_kind = user | conversation`

`entity_kind` 只从 `entity_ref` 派生，不再作为并列主入参传来传去。

当前物理形态已经收成：

- `.acabot-runtime/sticky-notes/user/<entity_ref>/readonly.md`
- `.acabot-runtime/sticky-notes/user/<entity_ref>/editable.md`
- `.acabot-runtime/sticky-notes/conversation/<entity_ref>/readonly.md`
- `.acabot-runtime/sticky-notes/conversation/<entity_ref>/editable.md`

文件真源现在负责：

- `entity_ref` 白名单校验
- 从 `entity_ref` 派生 `entity_kind`
- 拒绝 `thread:` / `session:` 这类非法对象引用
- 双区读写
- `editable` 追加
- 记录列表
- `updated_at = max(readonly, editable)`

#### 2. 服务层已经改成新模型

代码在：

- `src/acabot/runtime/memory/sticky_notes.py`
- `src/acabot/runtime/memory/sticky_note_renderer.py`

当前正式服务层已经收成：

- `StickyNoteService`
- `StickyNoteRenderer`

当前 bot 面只保留两种动作：

- `read_note(entity_ref)`
- `append_note(entity_ref, text)`

其中：

- `read_note(...)` 返回完整 XML 视图，目标不存在时返回 `exists = false`
- `append_note(...)` 只允许追加单行文本，只写 `editable`，目标不存在时自动创建

当前人类控制面动作已经收成：

- `load_record(entity_ref)`
- `save_record(StickyNoteRecord)`
- `create_record(entity_ref)`
- `delete_record(entity_ref)`
- `list_records(entity_kind)`

#### 3. bot 工具已经改成 builtin tool

代码在：

- `src/acabot/runtime/builtin_tools/sticky_notes.py`
- `src/acabot/runtime/builtin_tools/__init__.py`

当前 bot 侧正式工具面已经只剩：

- `sticky_note_read(entity_ref)`
- `sticky_note_append(entity_ref, text)`

这两个工具现在属于 runtime builtin tool surface：

- 直接由 bootstrap 注册
- 仍然受 `enabled_tools` 控制
- 不再经过 sticky notes plugin 生命周期

#### 4. control plane / HTTP API 已经围绕 `StickyNoteRecord`

代码在：

- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

当前 sticky note 的 backend 接口已经围绕：

- `StickyNoteRecord`
- `entity_ref`

当前 HTTP API 形状是：

- `GET /api/memory/sticky-notes?entity_kind=user|conversation`
- `GET /api/memory/sticky-notes/item?entity_ref=...`
- `POST /api/memory/sticky-notes/item`
- `PUT /api/memory/sticky-notes/item`
- `DELETE /api/memory/sticky-notes/item?entity_ref=...`

这里已经不再使用：

- `/api/memory/sticky-notes/scopes`
- `/api/memory/sticky-notes/readonly`
- `scope + scope_key + key`

#### 5. retrieval 已经接到 `sticky_note_targets`

代码在：

- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/file_backed/retrievers.py`

当前 retrieval 主线已经统一围绕：

- `sticky_note_targets: list[str]`

默认策略是：

- 群聊：`[actor_id, conversation_id]` 在现代码里暂时由 `facts.actor_id` 和 `facts.channel_scope` 表达
- 私聊：`[actor_id]`

当前 sticky note retriever 只会：

- 读取 planner 直接给出的 `entity_ref`
- 不做全量扫描
- 不存在就安静跳过
- 每张 note 产出一个完整 `MemoryBlock`
- 统一复用 `StickyNoteRenderer`

#### 6. 旧链路已经退出主线

这一轮 sticky note 已经不再依赖：

- `MemoryItem`
- `MemoryStore`
- `structured_memory`
- sticky note plugin
- `sticky_note_put/get/list/delete`

现在 sticky note backend 的真实主线可以直接记成：

> `StickyNoteFileStore -> StickyNoteService / StickyNoteRenderer -> StickyNoteRetriever / builtin sticky note tools / control plane / HTTP API`
