# reference_backend

这一篇讲的是 `reference / notebook` 这条线。

它和长期记忆有关，但不是一回事。

关键文件:

- `src/acabot/runtime/references/`
- `src/acabot/runtime/plugins/reference_tools.py`
- `src/acabot/runtime/bootstrap/`
- `src/acabot/runtime/control/control_plane.py`

## 先讲边界

`reference_backend` 负责的是高精度、可追溯、按需检索的资料库。

它和别的“记忆”边界是这样的:

- working memory: 当前 thread 上下文
- sticky notes: 本地结构化记忆
- `semantic / relationship / episodic`: 走 `MemoryBroker`
- `reference / notebook`: 走 `ReferenceBackend`

最重要的一条原则是:

reference 默认不是每轮自动注入 prompt，而是 on-demand lookup。

## 这层的核心对象

### `ReferenceDocumentInput`

写入时的输入对象。

### `ReferenceDocumentRef`

轻量引用，适合列表和写入结果。

### `ReferenceHit`

检索命中结果，带 score 和可选 body。

### `ReferenceDocument`

文档详情。

### `ReferenceSpace`

space 元信息。

## `ReferenceBackend` 协议

统一接口主要有:

- `add_documents()`
- `search()`
- `get_document()`
- `list_spaces()`
- `start()`
- `close()`

如果你以后要换 provider，实现这套协议就行。

## 现在有哪些 backend

### `NullReferenceBackend`

空实现，表示 reference 不可用。

### `LocalReferenceBackend`

本地 SQLite 版，当前最容易理解，也最适合作为默认参考实现。

它会做:

- 本地存储 reference 文档
- 自动生成 `overview / abstract`
- 本地简单打分检索
- 返回可追溯的 `ref_id / uri`

### `OpenVikingReferenceBackend`

接 OpenViking 生态的 provider。

支持的方向是:

- `embedded`
- 未来可扩的 `http`

这一层更像真正的 provider 适配器，不是简单本地表。

## `LocalReferenceBackend` 的实际风格

它不是向量数据库，也不是很重的检索系统。

现在更像:

- 一个轻量 SQLite 文档库
- 带摘要和 overview
- 带简单 local score
- 支持 tenant / space / mode

如果你要的是“本地 reference notebook”，这个实现已经够用。

如果你要的是更强的语义检索，再考虑往 provider 方向扩。

## tenant / space / mode 是怎么分的

reference 这套东西不是一个全局平面表。

它至少有三维:

- `tenant_id`
- `space_id`
- `mode`

`mode` 目前主要是:

- `readonly_reference`
- `appendable_reference`

这意味着如果你做 WebUI、工具或权限控制，不要只看 `ref_id`，还要看它属于哪个 tenant / space / mode。

## `ReferenceToolsPlugin` 是怎么接上的

bot 现在主要通过 plugin 暴露这套能力。

已有工具包括:

- `reference_add_document`
- `reference_search`
- `reference_read`

这也说明 reference 现在更像:

- 一个可调用的知识库能力
- 而不是每轮自动塞给模型的 memory layer

## 什么时候该用 reference，不该用 memory

### 更适合 reference

- 文档类资料
- 需要 provenance
- 想按需搜
- 希望可读原文 / overview / abstract

### 更适合 memory

- 用户关系记忆
- 对话里的情节记忆
- sticky note
- 小而稳定的结构化事实

简单说:

reference 更像资料库，memory 更像运行时记忆系统。

## OpenViking 这层怎么理解

如果接 OpenViking，不要把它当成“一个更大的本地表”。

它更像 provider：

- 要 `start()`
- 要维护 service
- 有自己的 ctx
- 通过 provider 原生 URI 来定位资源

如果你未来做真正外部 reference provider，这个类就是主要参考。

## 哪些改动会碰这里

- 给 bot 增加资料库读写能力
- 做 notebook / reference 管理页面
- 把外部文档导入本地 reference
- 切换 reference provider
- 想给模型一个可追溯知识库，而不是把东西塞进长期记忆

## 常见误区

### 1. 把 reference 当长期记忆替代品

两者边界不一样。reference 更强调资料检索和 provenance。

### 2. 想当然地每轮自动注入 reference

这会把 reference 和 memory 的边界冲掉，也会让 prompt 失控。

### 3. 只改 plugin，不看 backend

reference 工具只是入口，真正行为大多在 backend。

### 4. 不看 tenant / space / mode

这样做出来的 UI 和权限行为会很怪。

## 当前已知实现特点

这块目前更像 provider-style 资料库，不像自动注入式 memory。

所以如果以后你改成:

- 默认自动注入
- 更重的语义检索
- 更强的 notebook 工作流

就要同步这篇文档里关于边界的描述，不然后面的 AI 会继续按“按需 lookup”来理解它。

## 如果改这里，通常同步哪些文档

- `14-reference-backend.md`
- `06-tools-plugins-and-subagents.md`
- 如果影响 WebUI / control plane，再看 `08-webui-and-control-plane.md`

## 读源码顺序建议

1. `src/acabot/runtime/references/contracts.py`
2. `src/acabot/runtime/references/base.py`
3. `src/acabot/runtime/references/local.py`
4. `src/acabot/runtime/references/openviking.py`
5. `src/acabot/runtime/plugins/reference_tools.py`
6. `src/acabot/runtime/bootstrap/`
7. `src/acabot/runtime/control/control_plane.py`
