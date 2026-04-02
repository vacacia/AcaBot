# Reference Backend

> ⚠️ **待删除**：该模块设计不合理，计划整体移除。删除时需一并清理：`src/acabot/runtime/references/`、`runtime/plugins/reference_tools.py`、`runtime/control/reference_ops.py`、`runtime/control/http_api.py` 中的 `/api/reference/*`、`runtime/bootstrap/` 中的接线。

Reference / notebook 是高精度、可追溯、按需检索的资料库。它和长期记忆相关但不是一回事：reference 默认不是每轮自动注入 prompt，而是 on-demand lookup。

| 记忆类型 | 走哪条线 |
|---------|---------|
| working memory | 当前 thread 上下文 |
| sticky notes | file-backed 实体便签 |
| /self、长期记忆 | MemoryBroker |
| reference / notebook | ReferenceBackend |

## 核心对象

- `ReferenceDocumentInput` — 写入时的输入
- `ReferenceDocumentRef` — 轻量引用（列表和写入结果）
- `ReferenceHit` — 检索命中（带 score 和可选 body）
- `ReferenceDocument` — 文档详情
- `ReferenceSpace` — space 元信息

## ReferenceBackend 协议

统一接口：`add_documents()`、`search()`、`get_document()`、`list_spaces()`、`start()`、`close()`。

## Backend 实现

**NullReferenceBackend**：空实现，表示 reference 不可用。

**LocalReferenceBackend**：本地 SQLite 版。本地存储 reference 文档、自动生成 overview/abstract、本地简单打分检索、返回可追溯的 ref_id/uri。支持 tenant/space/mode 维度。

**OpenVikingReferenceBackend**：接 OpenViking 生态的 provider 适配器，支持 `embedded` 方向。

## tenant / space / mode

三个维度：`tenant_id`、`space_id`、`mode`（`readonly_reference` / `appendable_reference`）。

## 两条正式入口

1. **模型侧**：`ReferenceToolsPlugin` 暴露 `reference_add_document`、`reference_search`、`reference_read`
2. **控制面侧**：`RuntimeReferenceControlOps` + `RuntimeControlPlane` + `/api/reference/*`

## 关键文件

| 文件 | 职责 |
|------|------|
| `runtime/references/contracts.py` | 核心对象定义 |
| `runtime/references/base.py` | ReferenceBackend 协议 |
| `runtime/references/local.py` | LocalReferenceBackend |
| `runtime/references/openviking.py` | OpenVikingReferenceBackend |
| `runtime/plugins/reference_tools.py` | 模型侧工具 |
| `runtime/control/reference_ops.py` | 控制面操作 |
