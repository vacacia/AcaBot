# Phase 1: Reference Backend Removal - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Delete the entire Reference Backend subsystem. When done, the codebase should look like Reference Backend never existed — no files, no imports, no config keys, no context fields, no tests.

</domain>

<decisions>
## Implementation Decisions

### Deletion scope
- **D-01:** 彻底删除，不留任何痕迹。不是 deprecate，不是标记废弃，而是当它从来不存在。
- **D-02:** `src/acabot/runtime/references/` 整个目录删除（base.py, local.py, openviking.py, contracts.py, __init__.py）
- **D-03:** `src/acabot/runtime/plugins/reference_tools.py` 删除
- **D-04:** `src/acabot/runtime/control/reference_ops.py` 删除
- **D-05:** `tests/runtime/test_reference_backend.py` 和 `tests/runtime/test_reference_tools_plugin.py` 删除

### BackendBridgeToolPlugin 处理
- **D-06:** BackendBridgeToolPlugin 中对 `reference_backend` 的依赖直接删掉。如果整个插件因此失去意义，连插件一起删（Phase 2 会重做插件体系）。
- **D-07:** 不做"过渡期兼容"，不保留 None 占位——当它从来不存在。

### RuntimePluginContext 字段
- **D-08:** `RuntimePluginContext.reference_backend` 字段直接删掉。Phase 2 会重写整个 Context，不需要过渡。

### Config 处理
- **D-09:** config.yaml / config.example.yaml 中 `reference:` section 直接删除，不标 deprecated。
- **D-10:** `build_reference_backend()` 函数从 builders.py 删除。

### Bootstrap / App 清理
- **D-11:** `bootstrap/__init__.py` 中所有 `reference_backend` 相关构造和注入删除。
- **D-12:** `app.py` 中 `reference_backend` 参数、属性、close() 逻辑删除。
- **D-13:** `components.py` 中 `RuntimeComponents.reference_backend` 字段删除。
- **D-14:** `runtime/__init__.py` 中所有 Reference Backend 相关的 re-export 删除。

### Claude's Discretion
- 删除顺序（先删叶子还是先删根）由 planner 决定
- 是否需要中间提交（每步一个 commit 还是一个大 commit）由 planner 决定

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Reference Backend 现状
- `src/acabot/runtime/references/base.py` — ReferenceBackend ABC 定义
- `src/acabot/runtime/references/local.py` — LocalReferenceBackend 实现
- `src/acabot/runtime/references/openviking.py` — OpenVikingReferenceBackend 实现
- `src/acabot/runtime/plugins/reference_tools.py` — ReferenceToolsPlugin（依赖 reference_backend）
- `src/acabot/runtime/control/reference_ops.py` — Reference CRUD 操作

### 集成点（需要修改的文件）
- `src/acabot/runtime/bootstrap/__init__.py` — 构造 reference_backend 并注入
- `src/acabot/runtime/bootstrap/builders.py` — build_reference_backend() 函数
- `src/acabot/runtime/bootstrap/components.py` — RuntimeComponents.reference_backend 字段
- `src/acabot/runtime/app.py` — reference_backend 参数和 close() 逻辑
- `src/acabot/runtime/plugin_manager.py` — RuntimePluginContext.reference_backend 字段
- `src/acabot/runtime/control/control_plane.py` — 可能的 reference 相关方法
- `src/acabot/runtime/__init__.py` — re-exports
- `src/acabot/runtime/plugins/__init__.py` — ReferenceToolsPlugin 导出
- `config.example.yaml` line 62-63 — reference config section

### 测试文件
- `tests/runtime/test_reference_backend.py` — 直接删除
- `tests/runtime/test_reference_tools_plugin.py` — 直接删除
- `tests/runtime/test_bootstrap.py` — 可能引用 reference_backend
- `tests/runtime/test_app.py` — 可能引用 reference_backend
- `tests/test_main.py` — 可能引用 reference_backend

### 调研参考
- `.planning/research/PITFALLS.md` — Pitfall #11 (dangling imports) 和 #12 (BackendBridge breakage)

</canonical_refs>

<code_context>
## Existing Code Insights

### Affected Files (15 source + 5 test)
- `src/acabot/runtime/references/` — 整个目录删除（5 files）
- `src/acabot/runtime/plugins/reference_tools.py` — 删除
- `src/acabot/runtime/control/reference_ops.py` — 删除
- 8 个文件需要移除 import 和引用
- 5 个测试文件需要删除或修改

### Established Patterns
- `bootstrap/__init__.py` 是所有组件的 DI 组装点——删除 reference_backend 构造即可
- `RuntimePluginContext` 是插件 setup 时的上下文 bag——删字段即可
- `runtime/__init__.py` 的 `__all__` 列表需要同步清理

### Integration Points
- `plugin_manager.py` 的 `RuntimePluginContext` 会在 Phase 2 被重写，但 Phase 1 先删 reference_backend 字段
- `BackendBridgeToolPlugin` 可能引用 reference_backend——需要审计

</code_context>

<specifics>
## Specific Ideas

用户明确说"当它从来不存在"——不是 soft delete，不是 deprecate，是完全擦除。grep 验证零残留。

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-reference-backend-removal*
*Context gathered: 2026-04-03*
