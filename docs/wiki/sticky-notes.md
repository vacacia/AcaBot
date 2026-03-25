# Sticky Notes

Sticky Note 是 AcaBot 的实体级便签系统。它是 AcaBot 运行时的内建记忆层，在系统启动时自动激活，并把同一张便签同时用于 bot 工具读取、上下文注入、管理界面中的人工编辑和 HTTP API 管理。

每张便签只对应一个实体。这个实体通过 `entity_ref` 标识，系统会根据 `entity_ref` 自动判断出 `entity_kind`，用于文件目录分组、列表过滤和人类阅读辅助。当前只支持 `user` 和 `conversation` 两类实体。

`entity_ref` 的常见格式是 `<platform>:<type>:<id>`，由具体的平台适配器决定。例如 `qq:user:10001` 表示某个平台上的一个用户，`qq:group:20002` 表示某个平台上的一个群或对话容器。

最常见的例子是：


| `entity_ref`                | `entity_kind`  |
| ----------------------------- | ---------------- |
| `qq:user:10001`             | `user`         |
| `qq:group:20002`            | `conversation` |
| `discord:channel:987654321` | `conversation` |

## 核心对象


| 名称               | 含义                                                                                                                                                    |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `entity_ref`       | sticky note 的正式主键。它指向用户或对话容器。这里的“对话容器”指群组、频道、房间或私聊容器，不包括`thread_id` 和 `session_id` 这类运行时或配置层 id。 |
| `entity_kind`      | 系统根据`entity_ref` 自动判断出来的分类，只允许 `user` 或 `conversation`。                                                                              |
| `StickyNoteRecord` | 一张 sticky note 的正式记录对象，字段为`entity_ref`、`readonly`、`editable`、`updated_at`。                                                             |
| `readonly`         | 由人类直接维护的内容，bot 只读不改。                                                                                                                    |
| `editable`         | bot 可以追加观察的区域。                                                                                                                                |
| `combined_text`    | 每次读取时实时把`readonly` 和 `editable` 合并后生成的完整文本视图，不是持久化字段。                                                                     |

`entity_ref` 的校验和 `entity_kind` 的判断由同一个共享解析函数负责。当前实现允许系统内部标准实体 id 里常见的字符，例如字母、数字、`:`、`-`、`_`、`.`、`@`、`!`，并明确拒绝路径分隔符、`..`、`thread:`、`session:` 这类非法输入。

## 存储模型

每张 sticky note 在逻辑上是一条便签记录，在物理上仍然保留双文件结构。目录按 `entity_kind` 分组，目录名直接使用 `entity_ref`。

```text
.acabot-runtime/sticky-notes/
├── user/
│   └── <entity_ref>/
│       ├── readonly.md
│       └── editable.md
└── conversation/
    └── <entity_ref>/
        ├── readonly.md
        └── editable.md
```

`updated_at` 取 `readonly.md` 和 `editable.md` 两个文件修改时间的最大值。当前没有单独的索引文件，也没有 `note_key` 这一层逻辑寻址。

## 组件结构

Sticky Note 当前的 backend 结构可以概括为下面这条线：

```text
StickyNoteFileStore
    -> StickyNoteService
        -> StickyNoteRenderer
            -> builtin tools / StickyNoteRetriever / control plane / HTTP API
```

各个组件的职责如下。


| 组件                 | 文件                                                    | 责任                                                                                   |
| ---------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| entity 解析          | `src/acabot/runtime/memory/sticky_note_entities.py`     | 校验`entity_ref`，派生 `entity_kind`，统一 sticky note 的命名边界。                    |
| 文件存储层           | `src/acabot/runtime/memory/file_backed/sticky_notes.py` | 定义`StickyNoteRecord`，管理文件布局，读取、保存、追加、删除和列表查询。               |
| 渲染器               | `src/acabot/runtime/memory/sticky_note_renderer.py`     | 把`StickyNoteRecord` 渲染成统一 XML 风格文本。                                         |
| 服务层               | `src/acabot/runtime/memory/sticky_notes.py`             | 提供 bot 面和人类控制面的稳定业务接口。                                                |
| 上下文检索适配层     | `src/acabot/runtime/memory/file_backed/retrievers.py`   | 根据`sticky_note_targets` 里给出的实体，精确读取 sticky note，并转换成 `MemoryBlock`。 |
| 内建工具             | `src/acabot/runtime/builtin_tools/sticky_notes.py`      | 注册`sticky_note_read` 和 `sticky_note_append`，把服务层结果转成工具返回对象。         |
| 控制面               | `src/acabot/runtime/control/control_plane.py`           | 暴露人类控制面使用的 sticky note 管理动作。                                            |
| HTTP API             | `src/acabot/runtime/control/http_api.py`                | 把控制面的 sticky note 动作暴露成本地 API。                                            |
| runtime 启动时的接线 | `src/acabot/runtime/bootstrap/__init__.py`              | 创建 store 和 service，并把它们接进 runtime。                                          |
| memory broker 接线   | `src/acabot/runtime/bootstrap/builders.py`              | 在`MemoryBroker` 中注册 `StickyNoteRetriever`。                                        |
| runtime 组件导出     | `src/acabot/runtime/bootstrap/components.py`            | 把`sticky_notes_source` 和 `sticky_notes` 暴露给其他组件。                             |

## 代码位置

### 实体解析

文件：

- `src/acabot/runtime/memory/sticky_note_entities.py`

这一层定义了 sticky note 的统一边界，负责校验 `entity_ref`、判断 `entity_kind`，并拒绝不合法的输入。关键函数包括：

- `parse_sticky_note_entity_ref(entity_ref)`
- `derive_sticky_note_entity_kind(entity_ref)`
- `normalize_sticky_note_entity_kind(entity_kind)`

`entity_ref` 的校验和 `entity_kind` 的判断都集中在这里。其他层只复用这里的结果，不自己再实现一套规则。

### 文件读写

文件：

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`

这一层定义了 `StickyNoteRecord`，并负责 sticky note 的文件布局、读取、保存、追加、删除和列表查询。关键对象和方法包括：

- `StickyNoteRecord`
- `StickyNoteFileStore.load_record(entity_ref)`
- `StickyNoteFileStore.save_record(record)`
- `StickyNoteFileStore.create_record(entity_ref)`
- `StickyNoteFileStore.append_editable_text(entity_ref, text)`
- `StickyNoteFileStore.delete_record(entity_ref)`
- `StickyNoteFileStore.list_records(entity_kind=...)`

当前 `create_record(...)` 可以重复调用。如果 note 已存在，它会直接返回现有内容，不会覆盖 `readonly` 或 `editable`。

### 完整文本模板

文件：

- `src/acabot/runtime/memory/sticky_note_renderer.py`

这一层把一张 `StickyNoteRecord` 渲染成稳定的完整文本。核心方法是：

- `StickyNoteRenderer.render_combined_text(record)`

工具读取和上下文注入复用的就是这份完整文本。

### 服务层

文件：

- `src/acabot/runtime/memory/sticky_notes.py`

这一层把文件存储层收成稳定的业务接口。bot 使用的接口是：

- `read_note(entity_ref)`
- `append_note(entity_ref, text)`

人类控制面使用的接口是：

- `load_record(entity_ref)`
- `save_record(record)`
- `create_record(entity_ref)`
- `delete_record(entity_ref)`
- `list_records(entity_kind=...)`

`append_note(...)` 只接受单行文本，空白文本会直接拒绝，写入只发生在 `editable`。

### 上下文注入

相关文件：

- `src/acabot/runtime/control/session_runtime.py`
- `src/acabot/runtime/memory/retrieval_planner.py`
- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/file_backed/retrievers.py`

默认“要读取哪些便签”是在 `SessionRuntime._default_sticky_note_targets(facts)` 中决定的。群聊默认会选择当前发言人的 user note 和当前对话容器的 conversation note；私聊默认只选择当前发言人的 user note。这样做是因为群聊里通常需要同时记住“这个人是谁”和“这个群在聊什么”。

`RetrievalPlanner` 会把最终目标收成 `sticky_note_targets: list[str]`，`MemoryBroker` 再把这组目标放进本轮检索请求里，`StickyNoteRetriever` 只读取这些明确给出的目标，不做全文搜索，也不做目录全量扫描。

### bot 工具

相关文件：

- `src/acabot/runtime/builtin_tools/sticky_notes.py`
- `src/acabot/runtime/builtin_tools/__init__.py`

当前正式工具只有两个：

- `sticky_note_read(entity_ref)`
- `sticky_note_append(entity_ref, text)`

它们由 bootstrap 直接注册进 `ToolBroker`，但仍然受 `enabled_tools` 控制。

### 控制面和 HTTP API

相关文件：

- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

control plane 提供的 sticky note 动作是：

- `list_sticky_notes(entity_kind)`
- `get_sticky_note_record(entity_ref)`
- `save_sticky_note_record(entity_ref, readonly, editable)`
- `create_sticky_note(entity_ref)`
- `delete_sticky_note(entity_ref)`

HTTP API 对应的接口是：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/memory/sticky-notes?entity_kind=...` | 列出某类实体的 sticky notes，`entity_kind` 只允许 `user` 或 `conversation` |
| `GET` | `/api/memory/sticky-notes/item?entity_ref=...` | 读取一张完整便签 |
| `POST` | `/api/memory/sticky-notes/item` | 创建一张空 note |
| `PUT` | `/api/memory/sticky-notes/item` | 保存整张 note |
| `DELETE` | `/api/memory/sticky-notes/item?entity_ref=...` | 删除一张 note |

这层只接受 `entity_kind = user | conversation`。非法分类会直接报错，HTTP API 会返回 `400`。

### runtime 装配

相关文件：

- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/bootstrap/builders.py`
- `src/acabot/runtime/bootstrap/components.py`

`bootstrap/__init__.py` 负责创建 `StickyNoteFileStore` 和 `StickyNoteService`，并在 runtime 启动时把它们接到 builtin tool 注册、memory broker、control plane 和 runtime components。

`bootstrap/builders.py` 里的 `build_memory_broker(...)` 会把 `StickyNoteRetriever` 注册到 `MemoryBroker`。`bootstrap/components.py` 则把 `sticky_notes_source` 和 `sticky_notes` 作为 runtime components 的一部分暴露出去。

## 调用路径

### bot 主动读取 sticky note

```text
ToolBroker
  -> BuiltinStickyNoteToolSurface.sticky_note_read
    -> StickyNoteService.read_note
      -> StickyNoteFileStore.load_record
      -> StickyNoteRenderer.render_combined_text
```

### bot 追加一条观察

```text
ToolBroker
  -> BuiltinStickyNoteToolSurface.sticky_note_append
    -> StickyNoteService.append_note
      -> StickyNoteFileStore.append_editable_text
      -> StickyNoteFileStore.save_record
```

### sticky note 自动注入上下文

```text
SessionRuntime._default_sticky_note_targets
  -> RetrievalPlanner.prepare
  -> MemoryBroker._build_retrieval_request
  -> StickyNoteRetriever
  -> StickyNoteRenderer
  -> ContextAssembler
```

## 测试文件

sticky note 相关测试主要覆盖文件操作、文本渲染、服务层边界、上下文注入、工具行为和 HTTP/API 管理接口，当前分布在这些文件里：


| 主题                         | 测试文件                                                                                                                                                     |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 文件真源                     | `tests/runtime/test_sticky_note_file_store.py`                                                                                                               |
| 渲染                         | `tests/runtime/test_sticky_note_renderer.py`                                                                                                                 |
| 服务层                       | `tests/runtime/test_sticky_note_service.py`                                                                                                                  |
| retrieval                    | `tests/runtime/test_sticky_note_retriever.py`, `tests/runtime/test_file_backed_memory_retrievers.py`                                                         |
| builtin tools                | `tests/runtime/test_sticky_note_builtin_tools.py`, `tests/runtime/test_builtin_tools.py`                                                                     |
| control plane / HTTP API     | `tests/runtime/test_control_plane.py`, `tests/runtime/test_http_api_sticky_notes.py`, `tests/runtime/test_webui_api.py`                                      |
| planner / broker / bootstrap | `tests/runtime/test_retrieval_planner.py`, `tests/runtime/test_memory_broker.py`, `tests/runtime/test_bootstrap.py`, `tests/runtime/test_session_runtime.py` |

