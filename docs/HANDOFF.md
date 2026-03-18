# 当前进展 Handoff

## 这轮已经完成了什么

- 已把 `soul` 和 `sticky_note` 接进 runtime 与 WebUI 所需的控制面接口。
- 已补一层真正的 Session 产品壳后端映射:
  - `GET /api/sessions`
  - `GET /api/sessions/<channel_scope>`
  - `PUT /api/sessions/<channel_scope>`
- 这层映射只对前端暴露:
  - `基础信息`
  - `AI`
  - `消息响应`
  - `其他`
- 前端不再需要直接碰 `binding rule / inbound rule / event policy`。
- WebUI 已从旧静态壳切到 Vue + Vite。
- `webui/src/views/` 已补齐，`Soul / Memory / Sessions` 是真实接接口的页面，其余页面先做到可浏览。
- Vite 产物已经写进 `src/acabot/webui/`，旧的静态入口已被替换。

## 这轮的关键设计决策

### 1. `soul` 单独放文件夹

实际落地路径不是早期计划里的扁平文件:

- `src/acabot/runtime/soul/source.py`
- `src/acabot/runtime/soul/__init__.py`

原因很直接:

- 用户明确要求 `soul` 单独一个文件夹
- 这样比把 `soul_source.py` 塞在 `runtime/` 根下更清楚
- 后续如果还要扩展 `soul` 相关能力，不会继续堆在大根目录

### 2. sticky notes 放到 memory 子域

实际落地路径:

- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- `src/acabot/runtime/memory/file_backed/__init__.py`

原因:

- sticky note 本质上是 memory 真源
- 不应该在 `runtime/` 根目录继续散文件
- 文件布局和概念边界一致

### 3. Session 壳映射放回后端

新增:

- `src/acabot/runtime/control/session_shell.py`

原因:

- 文档一直要求前端只讲产品概念
- 旧静态前端的 `app.js` 里其实偷偷做了很多 rule 拼装
- 这次把那套映射收回后端，前端只拿 `AI / 消息响应 / 其他`

## 当前确认过的文档/代码冲突

### Session 文档 vs 旧代码

冲突点:

- 文档要求 Session 前端不能出现后端规则术语
- 旧代码只有 raw rule 接口，没有 Session 壳接口

这次采用的最小可行路径:

- 不改文档方向
- 不把 raw rule 概念搬进 Vue
- 在后端补 `session_shell.py` 做映射

### 计划文档里的旧路径

旧计划里还写着:

- `src/acabot/runtime/self_source.py`
- `src/acabot/runtime/sticky_notes_source.py`
- `webui/src/views/SelfView.vue`

这些和真实落地路径不一致。

这次已经把计划文档里最明显的路径改到当前真实结构，但计划文档仍然是“实施计划”，不是源码真源。真正继续工作时，优先看当前源码。

## 什么有效，什么没用

### 有效

- 先把 Session 壳测试写出来，再补后端映射。
- 先跑 `test_webui_api.py`，确认问题只剩旧静态壳，再切前端。
- 用 `control/session_shell.py` 单独承接 Session 映射，而不是继续往 `control_plane.py` 里堆大块逻辑。
- 先让 Vue 构建落地到 `src/acabot/webui/`，再跑 Python 接口测试，定位更清楚。

### 没用 / 容易踩坑

- 直接在前端拼 `binding / inbound / event policy` 会再次偏离文档口径。
- `tests/runtime/test_sticky_notes_plugin.py` 如果不用临时 `runtime_root`，会读到仓库根目录的 `.acabot-runtime/` 旧数据，导致假失败。
- 当前最小测试环境里没有稳定可写的 model registry，所以 `Session / AI` 里的 `model_preset_id` 不能在所有测试场景下都当作已持久化真源来断言。


## 现在代码里最值得继续看的入口

- `src/acabot/runtime/control/session_shell.py`
- `src/acabot/runtime/control/control_plane.py`
- `src/acabot/runtime/control/http_api.py`
- `src/acabot/runtime/soul/source.py`
- `src/acabot/runtime/memory/file_backed/sticky_notes.py`
- `webui/src/views/SoulView.vue`
- `webui/src/views/MemoryView.vue`
- `webui/src/views/SessionsView.vue`

## 下一步最合理的继续方式

### 1. 补全非核心页面的真实编辑能力

当前 `Bot / Models / Prompts / Plugins / Skills / Subagents / System` 页面已经能看，但很多还是轻编辑或只读态。

### 2. 再把 Session 页的模型配置做深

现在 Session 壳已经有模型字段入口，但在“没有完整 model registry 的最小环境”下，这块还不能保证处处都落到稳定 preset 真源。继续做这块时，要和 model registry 真实生效链一起看。

### 3. 再决定是否继续改文档里的 `self` 命名

代码里已经统一往 `soul` 走，但产品和共识文档仍大量使用 `self`。这不是当前阻塞项，不过后面如果继续推进，可以单独做一次“文档口径统一”。
