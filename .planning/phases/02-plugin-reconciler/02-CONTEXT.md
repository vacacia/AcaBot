# Phase 2: Plugin Reconciler - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the 959-line `plugin_manager.py` monolith with six focused modules implementing a desired-state reconciler pattern (Package / Spec / Status / Reconciler / RuntimeHost / Protocol). Deliver declarative plugin management via REST API (5 endpoints) and WebUI management page. Delete legacy plugins (OpsControl/NapCatTools). Preserve BackendBridgeToolPlugin as transitional code outside the new system.

</domain>

<decisions>
## Implementation Decisions

### Config migration & compatibility
- **D-01:** No config migration. Treat old config as non-existent — same philosophy as Phase 1 ("当它从来不存在"). All old data/config is irrelevant.

### ADR correction
- **D-02:** Fix `docs/29-plugin-control-plane.md` first — remove `reference_backend` from `RuntimePluginContext` (deleted in Phase 1). This correction happens before implementation begins.

### WebUI interaction feedback
- **D-03:** Use inline state changes (loading spinner, disabled controls) + toast notifications for success/error on all plugin operations (toggle, config save, rescan).

### WebUI error display
- **D-04:** Plugin load failures shown as 'failed' badge on list item. Full error details (traceback, load_error) displayed in a modal dialog on click — not inline in the expand panel.

### WebUI rescan experience
- **D-05:** Progressive feedback for `POST /api/system/plugins/reconcile`:
  - 前端点击 "重新扫描" 后, 列表中所有插件临时显示 'reconciling' 过渡状态 (纯前端状态)
  - `POST /api/system/plugins/reconcile` 单次调用, 返回完整最终结果
  - 前端用返回值替换整个列表, 清除过渡状态
  - 相比原始两阶段方案 (先返回 package 列表 + 再 GET 最终状态), 简化为单调用 + 前端过渡态, 避免不必要的 API 往返.

### Sample plugin
- **D-06:** Ship a sample plugin in `extensions/plugins/` that serves as both SC#1 verification and developer template. Should be a small but real utility (not just echo), with `plugin.yaml` including `config_schema` to demonstrate schema-driven config form. Stays in repo as a reference for future plugin authors.

### Plugin capability audit (research directive)
- **D-07:** Research phase MUST audit plugin infrastructure needs beyond what's already in the ADR. The ADR documents four "本轮不实现" gaps (LLM calls, scheduled tasks, rich messaging, platform adapter API). Research should check if there are additional undiscovered infrastructure needs that plugins might require — focusing on whether the RuntimePlugin protocol and RuntimePluginContext provide sufficient hooks for future extension. This is an audit of completeness, not implementation.

### Claude's Discretion
- Sample plugin's specific functionality (what tool it provides) — as long as it's useful and demonstrates config_schema
- Internal implementation patterns (e.g., how to structure the two-phase refresh API response)
- Test structure and organization for the new plugin modules

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plugin system ADR (PRIMARY)
- `docs/29-plugin-control-plane.md` — Master design document covering all 6 modules, data models, reconciler logic, API endpoints, WebUI page, bootstrap integration, and edge cases. **Must be corrected first** (remove reference_backend from RuntimePluginContext per D-02).

### Current implementation (to be replaced)
- `src/acabot/runtime/plugin_manager.py` — The 959-line monolith being replaced. Read to understand current hook/tool registration, load ordering, and RuntimePluginContext shape.
- `src/acabot/runtime/plugins/ops_control.py` — Legacy plugin to delete
- `src/acabot/runtime/plugins/napcat_tools.py` — Legacy plugin to delete
- `src/acabot/runtime/plugins/backend_bridge_tool.py` — Transitional plugin to preserve with import updates

### Bootstrap & integration points
- `src/acabot/runtime/bootstrap/__init__.py` — DI assembly point, needs rewiring
- `src/acabot/runtime/bootstrap/components.py` — RuntimeComponents dataclass
- `src/acabot/runtime/bootstrap/builders.py` — build_builtin_runtime_plugins() to delete
- `src/acabot/runtime/app.py` — start()/stop() lifecycle integration
- `src/acabot/runtime/pipeline.py` — run_hooks() call sites

### Control plane & API
- `src/acabot/runtime/control/control_plane.py` — Add new plugin resource methods
- `src/acabot/runtime/control/config_control_plane.py` — Delete old plugin config methods
- `src/acabot/runtime/control/http_api.py` — Replace 4 old endpoints with 5 new ones

### WebUI
- `webui/src/` — Vue 3 + TypeScript frontend
- `webui/src/api.ts` — API client (old plugin interfaces to replace)

### Directory layout ADR
- `docs/todo/28-directory-restructure.md` — Referenced by ADR for extensions path resolution

### Phase 1 context
- `.planning/phases/01-reference-backend-removal/01-CONTEXT.md` — Confirms reference_backend fully deleted

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ToolBroker` (`src/acabot/runtime/tool_broker/broker.py`) — Tool registration/unregistration by source, already used by current plugin system
- `MutableModelTargetCatalog` — Model target registration with revalidation, existing integration in plugin_manager
- `RuntimeHookPoint` enum and `RuntimeHookResult` — Can be extracted directly from plugin_manager.py
- `RuntimePlugin` ABC — Current contract in plugin_manager.py, to be moved to plugin_protocol.py
- Atomic write pattern — Used in config_control_plane.py and model_registry.py (NamedTemporaryFile + Path.replace)

### Established Patterns
- DI via constructor injection with factory functions in bootstrap/
- Protocol-based abstractions at boundaries (GatewayProtocol, ToolExecutor, etc.)
- Config paths resolved via `config.resolve_path()`, not hardcoded
- YAML for config, JSON for runtime state
- `logging.getLogger("acabot.<subsystem>")` per module

### Integration Points
- `bootstrap/__init__.py` — Construct all new objects (catalog, spec_store, status_store, host, reconciler)
- `app.py` start/stop — reconcile_all() on start, host.teardown_all() on stop
- `pipeline.py` — Replace plugin_manager.run_hooks() calls with host.run_hooks()
- `runtime/__init__.py` — Update massive re-export facade (~300 symbols)
- `extensions/plugins/` — Currently has empty dirs (napcat_tools/, notepad/), will host sample plugin

</code_context>

<specifics>
## Specific Ideas

- 用户明确："不需要考虑配置迁移/兼容，同样当旧设计不存在" — 和 Phase 1 一样的彻底替换哲学
- ADR 中 reference_backend 相关内容需要先修正，因为 Phase 1 已经删除了整个子系统
- Research 阶段特别关注：插件基建需求是否有遗漏（ADR 记录了 LLM/定时/富消息/平台API 四个空缺，是否还有其他？）
- Sample plugin 要有实际用途，不是纯 echo — 同时展示 config_schema 驱动的配置表单

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-plugin-reconciler*
*Context gathered: 2026-04-03*
