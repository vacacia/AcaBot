
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

#### 1. 文件

代码在：

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`

当前 sticky note 的物理形态是：

- `.acabot-runtime/sticky-notes/<scope>/<scope_key>/<note_key>/readonly.md`
- `.acabot-runtime/sticky-notes/<scope>/<scope_key>/<note_key>/editable.md`

这个文件真源已经负责：

- scope 和 key 校验
- 双区读写
- scope 浏览
- note 列表
- 路径安全

当前产品化 scope 只有：

- `user`
- `channel`

#### 2. 受控服务层已经存在

代码在：

- `src/acabot/runtime/memory/sticky_notes.py`

`StickyNotesService` 现在已经把 sticky note 收成受控操作：

- `put_note`
- `get_note`
- `list_notes`
- `delete_note`

这里有一个很关键的现状：

- `user` / `channel` scope 优先走文件真源
- `relationship` / `global` scope 仍然可以回落到通用 `MemoryStore`

所以 sticky note 在当前代码里其实是“两套后端并存”的形态：

- 产品主线：file-backed `user` / `channel`
- 通用兜底：`MemoryStore` 上的 `sticky_note` item

#### 3. 插件工具已经存在

代码在：

- `src/acabot/runtime/plugins/sticky_notes.py`

当前已经暴露的工具有：

- `sticky_note_put`
- `sticky_note_get`
- `sticky_note_list`
- `sticky_note_delete`

也就是说，sticky note 现在不只是 WebUI 能编辑，模型本身也已经能通过受控工具读写它。

#### 4. WebUI 已经有第一版页面

代码在：

- `webui/src/views/MemoryView.vue`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`

当前 Memory 页面只暴露 sticky note，不是完整记忆总览页。现在能用的接口主要是：

- `/api/memory/sticky-notes/scopes`
- `/api/memory/sticky-notes`
- `/api/memory/sticky-notes/item`
- `/api/memory/sticky-notes/readonly`

#### 5. prompt 注入已经接通

代码在：

- `src/acabot/runtime/pipeline.py`
- `src/acabot/runtime/memory/retrieval_planner.py`

当前 pipeline 会直接从文件真源读取：

- 当前用户的 sticky notes
- 当前 channel 的 sticky notes

然后转成 `MemoryBlock`，再交给 `RetrievalPlanner` 组装成 `sticky_notes` prompt slot。

这意味着 sticky note 现在已经是主线的一部分，不是只存在于 WebUI 的静态资料。

所以这层的真实现状可以概括成一句话：

> Sticky note 已经是当前代码里最完整的长期记忆产品形态，尤其是 `user/channel + readonly/editable + WebUI + tool + prompt 注入` 这一套已经成形。