# Phase 01: system-runtime-paths - Research

**Researched:** 2026-03-29
**Domain:** Brownfield WebUI control plane for system-level configuration, path resolution, and runtime apply semantics
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

**CRITICAL:** These decisions are locked by Phase 1 context and must be honored during planning.

### Locked Decisions
- `系统` 页只编辑系统级共享配置，其他领域配置继续留在各自页面。
- `系统` 页正文的正式可编辑内容包含 gateway 配置、catalog 扫描根、共享管理员，以及单独的“重新读取配置”维护动作区。
- `系统` 页必须有高级区，用来展示技术细节和实际生效路径，但这些信息必须用人话标签表达，不能直接把内部黑话暴露成主标签。
- 默认交互语义是“保存即尝试生效”；gateway 这类项允许“已保存，需要重启后生效”。
- 共享管理员和扫描根采用“一次填一个”的列表编辑器，不再用多行 textarea 作为主交互。
- 前端只做可靠的轻量输入校验；路径存在/可读等权威判断以后端和 control plane 为准。
- 错误反馈必须采用“人话主结论 + 可展开技术细节”的形式。

### the agent's Discretion
- 高级区的卡片分组、视觉密度和命名细节。
- 批量导入是否在第一轮一起上线，还是先保留为次级入口。
- 结果反馈在现有设计系统中的具体展现方式。

### Deferred Ideas (OUT OF SCOPE)
- 把系统页扩成所有领域配置的总入口。
- 在系统页直接编辑 LTM、模型、提示词或 Session 领域对象。
- 重做首页状态页职责。

</user_constraints>

<research_summary>
## Summary

Phase 1 最稳的做法不是“新做一个系统页”，而是把现有控制面链路正式产品化：`SystemView.vue` 负责呈现，`http_api.py` 继续做薄适配，`RuntimeControlPlane` 聚合系统级视图，`RuntimeConfigControlPlane` 保持配置真源写入与重载语义。现有仓库已经具备 `/api/gateway/config`、`/api/filesystem/config`、`/api/admins`、`/api/runtime/reload-config` 这些基础接缝，所以实现重点不是造新架构，而是统一读写形状、补路径总览、补结果状态语义，并把前端从“状态卡片 / textarea 表单”升级成正式配置面。

从产品边界看，系统页必须同时完成两件事：一是给操作者稳定的系统级共享配置入口；二是让路径和真源足够可解释，帮助排障和建立信任。但它不应越权去管理所有领域对象，也不应把内部 config key 直接当 UI 语言。最合适的结构是“主编辑区 + 高级只读诊断区”，让系统页既能操作，也能解释。

从技术风险看，最容易做坏的地方有三个：前端自己复制一套路径解析规则、HTTP API 继续膨胀成业务层、以及“已保存”与“已生效”语义混乱。研究结论非常明确：**路径解析、存在性和可读性判断都必须以后端权威视图为准；系统页需要统一的 apply result contract；列表输入必须改成单项编辑器。**

**Primary recommendation:** 以“后端先统一系统级配置视图 + 前端按 UI-SPEC 收口”为主线，把 Phase 1 拆成后端契约、前端系统页重构、验证闭环三块可执行计划。
</research_summary>

<standard_stack>
## Standard Stack

The established libraries/tools for this domain are already in the repo:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vue 3 + TypeScript | repo current | WebUI 页面状态、表单和交互 | 已是正式前端主栈，SystemView / AdminsView / LogsView 都基于它 |
| Vite | repo current | WebUI 构建到 `src/acabot/webui` | 与 Python 静态托管链路已打通，不需要更换 |
| `ThreadingHTTPServer` + `RuntimeHttpApiServer` | repo current | 本地 API 与静态资源托管 | 已是正式 control plane 入口，适合继续加系统级 API |
| `RuntimeControlPlane` + `RuntimeConfigControlPlane` | repo current | 系统状态聚合、配置真源写入、reload 语义 | 已经体现清晰边界，符合本 phase 的需求 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `webui/src/styles/design-system.css` | repo current | 面板、字段、按钮、状态消息统一样式 | 所有系统页新增 UI 都应直接复用 |
| `tests/runtime/test_webui_api.py` | repo current | Phase 1 后端契约测试主落点 | 新系统级 API 和结果语义优先在这里补 |
| `Config` (`src/acabot/config.py`) | repo current | config 路径解析、保存、base_dir/resolve_path | 任何路径统一都应围绕它而不是前端重算 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 现有 control plane 分层 | 直接把逻辑塞进 `http_api.py` | 短期快，长期会把路径解析、写回、reload 和响应结构糊成一层 |
| 单项列表编辑器 | 继续使用 multiline textarea | 初期实现简单，但校验、去重、错误定位和后续批量扩展都会更差 |
| 后端权威路径视图 | 前端复制路径解析规则 | 会重复 `base_dir` / `resolve_path` 逻辑，极易与真实运行态漂移 |

**Installation:**
```bash
# Preferred approach expects no new third-party dependencies.
# Reuse existing repo stack and test/build commands.
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```text
webui/src/views/
  SystemView.vue            # Phase 1 主前端落点
  AdminsView.vue            # 迁移参考或并入来源

src/acabot/runtime/control/
  http_api.py               # 薄 HTTP 适配层
  control_plane.py          # 系统级聚合视图与结果形状
  config_control_plane.py   # 真源写入、路径解析、reload/apply

tests/runtime/
  test_webui_api.py         # 系统级 API 与配置语义主验证文件
```

### Pattern 1: Backend-Authoritative System Snapshot
**What:** 用单一的系统级 payload 把“当前在用的配置文件、base_dir、解析后的扫描根、关键运行时路径、保存/应用结果语义”汇总给前端。  
**When to use:** 当前端需要展示“实际生效位置”和“写入后状态”时。  
**Example:**
```python
# control_plane.py
async def get_system_configuration_view(self) -> dict[str, object]:
    return {
        "gateway": self.config_control_plane.get_gateway_config(),
        "filesystem": self.config_control_plane.get_filesystem_scan_config(),
        "admins": await self.get_admins(),
        "paths": self.config_control_plane.get_runtime_path_overview(),
    }
```

### Pattern 2: Thin API, Rich Control Plane
**What:** `http_api.py` 只做 URL → method → payload 的转发，业务规则和 reload 语义落在 control/config 层。  
**When to use:** 新增系统页 API、apply result contract、diagnostics endpoint。  
**Example:**
```python
# http_api.py
if segments == ["system", "configuration"] and method == "GET":
    return self._ok(self._await(self.control_plane.get_system_configuration_view()))
```

### Pattern 3: Single-Item List Editor
**What:** 前端对扫描根和管理员采用“一次输入一个值”的局部编辑器。  
**When to use:** 列表项需要即时去重、单项错误提示、删除确认、未来批量导入扩展时。  
**Example:**
```ts
function addItem(value: string): void {
  const normalized = value.trim()
  if (!normalized) return
  if (draftItems.value.includes(normalized)) return
  draftItems.value = [...draftItems.value, normalized]
}
```

### Anti-Patterns to Avoid
- **前端重算真实路径：** 会复制 `Config.resolve_path()` 和 filesystem 规则，最终展示不可信。
- **把“已保存”和“已生效”混成一个布尔：** 会让 gateway、reload failure、partial apply 都无法正确解释。
- **系统页继续拆散到多个孤立接口却没有统一视图：** 会导致页面交互碎片化，难以表达高级区总览。
- **沿用 textarea 列表输入：** 错误定位和后续交互扩展都会变糟。
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 路径解析 | 前端自己实现 `base_dir + relative path` 解析 | `Config.base_dir()` + `Config.resolve_path()` + config/control plane 统一视图 | 真实 config path 不一定在 repo 根，前端无法权威判断 |
| 系统页状态消息 | 每个保存按钮自己拼不同文案和错误格式 | 统一 apply result payload + `ds-status` 状态组件语义 | 否则无法稳定区分已保存/已生效/需重启/应用失败 |
| 扫描目录校验 | 浏览器端做宿主机存在性和可读性探测 | 后端写入前后校验 + resolved preview | 权限、容器、backend cwd、真实运行上下文都在服务端 |
| 系统页新样式 | 单独做一套 admin 主题 | 现有 glass console + `ds-*` 设计系统 | Phase 1 目标是产品化，不是重做视觉体系 |

**Key insight:** Phase 1 最大价值来自“收敛已有接缝”，不是“额外造一层智能前端”。
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: 路径说明和真实运行态漂移
**What goes wrong:** 页面显示的“当前目录”与 runtime 实际使用路径不一致。  
**Why it happens:** 直接用前端字符串拼接、默认假设 repo 根就是 config 根、忽略 `ACABOT_CONFIG`。  
**How to avoid:** 统一让后端返回权威的 resolved path overview。  
**Warning signs:** 页面显示路径与 `/api/meta` 的 `config_path`、filesystem resolved roots 或 backend session path 对不上。

### Pitfall 2: HTTP API 继续膨胀
**What goes wrong:** `http_api.py` 同时承担请求解析、配置写入、路径解析、错误整形和 reload 策略。  
**Why it happens:** 看起来“只加一个 endpoint 很快”。  
**How to avoid:** 新逻辑先落 `control_plane.py` 或 `config_control_plane.py`，HTTP 层只负责转发。  
**Warning signs:** 同一 endpoint 分支里出现大量 config 读写、路径处理和条件语义。

### Pitfall 3: 结果状态语义模糊
**What goes wrong:** 用户只看到“保存成功”，却不知道是否真正生效。  
**Why it happens:** 没有统一 apply result contract，或者仅靠异常区分成功失败。  
**How to avoid:** 结果形状显式区分 `applied | restart_required | write_failed | apply_failed`。  
**Warning signs:** 文案里频繁出现“可能需要重启”“视情况而定”这种模糊话。

### Pitfall 4: 列表编辑交互做成文本框
**What goes wrong:** 管理员和扫描目录变成一大段文本，重复项、空项、错误定位都很差。  
**Why it happens:** 觉得 textarea 最省事。  
**How to avoid:** Phase 1 直接切到单项列表编辑器。  
**Warning signs:** 保存函数里出现大量 `split("\n")/trim/filter(Boolean)`。
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from project sources:

### Existing Filesystem Config Contract
```python
# Source: src/acabot/runtime/control/http_api.py + config_control_plane.py
GET  /api/filesystem/config
PUT  /api/filesystem/config

# returned fields already include:
# - enabled
# - base_dir
# - configured_*_catalog_dirs
# - default_*_catalog_dirs
# - resolved_*_catalog_dirs
```

### Existing Shared Admin Contract
```python
# Source: src/acabot/runtime/control/control_plane.py
GET /api/admins
PUT /api/admins

# current persistence target:
# default bot profile.admin_actor_ids
```

### Existing Frontend Status Feedback Pattern
```ts
// Source: webui/src/views/AdminsView.vue
const saveMessage = ref("")
const errorMessage = ref("")

// Pattern to preserve:
// - load current draft
// - submit via apiPut
// - show concise success/error feedback in-page
```
</code_examples>

<sota_updates>
## State of the Art (Project, 2026-Q1)

What changed recently inside this repo:

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 旧式零散静态 WebUI 壳 | Vue 3 + Vite + shared design system | 2026-03 | Phase 1 应继续扩这套 shell，不要回到零散页面 |
| profile/session 私有模型字段 | model target registry + bindings | 2026-03 | 系统页不应重新引入旧式“万能配置页”思路 |
| plugin / subagent 注册依赖旧来源 | filesystem-backed catalog and control plane surfaces | 2026-03 | 扫描根已经是正式系统级配置，不是边角功能 |

**New tools/patterns to consider:**
- Unified system configuration payload: reduces page fragmentation and strengthens diagnostics.
- Single-item list editor: better fit for admin IDs and scan roots than multiline text.

**Deprecated/outdated:**
- 把系统页当状态卡片页使用。
- 用 raw config key 直接当界面语言。
- 让用户靠“保存之后自己猜有没有生效”。
</sota_updates>

## Validation Architecture

### Recommended Validation Layers

1. **Backend contract tests**
   - Extend `tests/runtime/test_webui_api.py`
   - Cover unified system configuration view, apply-result semantics, restart-required semantics, and path overview payload

2. **Frontend structure assertions**
   - Keep lightweight source assertions for `webui/src/views/SystemView.vue`
   - Verify `ds-*` design-system usage, advanced section presence, and list-editor structure markers

3. **Build safety**
   - `npm --prefix webui run build`
   - Ensures the refactored system page still emits a valid static bundle

### Recommended Command Strategy

- **Quick loop:** targeted `pytest` for system/webui API behavior
- **Wave completion:** frontend build + targeted backend tests
- **Before execution sign-off:** full relevant backend test file green

### Nyquist Guidance

- Every plan task must map to at least one concrete verification command or grep-check.
- No task should end with only manual confidence.
- The highest-risk gaps are:
  - resolved path overview shape
  - save/apply result contract
  - system page structure regression after moving admins into system page flow

<open_questions>
## Open Questions

1. **系统页总览是走一个聚合 endpoint，还是前端拼多个已有接口？**
   - What we know: 现有接口已经分散存在于 `/api/meta`、`/api/filesystem/config`、`/api/admins`、`/api/backend/status`。
   - What's unclear: 是否要在 Phase 1 引入一个新的聚合系统配置视图。
   - Recommendation: **要。** 统一系统页视图更利于高级区、人话标签和 apply result contract，不建议让前端拼装长期契约。

2. **批量导入是否第一轮一起做？**
   - What we know: 用户明确主交互要是单项列表编辑，批量导入只是次级入口。
   - What's unclear: 第一轮是否必须上线。
   - Recommendation: 规划时可把批量导入作为同 phase 的后半任务，前提是不拖慢主链路。
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- `.planning/phases/01-system-runtime-paths/01-CONTEXT.md` — locked decisions and user intent
- `.planning/phases/01-system-runtime-paths/01-UI-SPEC.md` — visual/interaction contract for Phase 1
- `webui-pages-draft.md` — page boundary and product semantics
- `docs/08-webui-and-control-plane.md` — control plane layering and config/state separation
- `docs/09-config-and-runtime-files.md` — config lookup order, filesystem-backed truth, apply semantics
- `src/acabot/runtime/control/http_api.py` — current API surface
- `src/acabot/runtime/control/control_plane.py` — current system/admin/backend aggregations
- `src/acabot/runtime/control/config_control_plane.py` — gateway/filesystem config write and reload behavior
- `webui/src/views/SystemView.vue` — current system page shell
- `webui/src/views/AdminsView.vue` — current shared admin editing flow
- `tests/runtime/test_webui_api.py` — current backend contract coverage

### Secondary (MEDIUM confidence)
- `docs/01-system-map.md` — runtime/webui/control-plane boundary overview
- `.planning/codebase/ARCHITECTURE.md` — codebase-level architecture summary
- `.planning/codebase/CONCERNS.md` — risks around hardcoded paths and operability

### Tertiary (LOW confidence - needs validation)
- None — this research is grounded in local source and current project docs.
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Vue 3 system page + Python control plane
- Ecosystem: existing repo stack only
- Patterns: config/state separation, path authority, list editing, apply-result semantics
- Pitfalls: duplicated path logic, silent save semantics, UI drift from current shell

**Confidence breakdown:**
- Standard stack: HIGH - current repo stack is explicit and already deployed
- Architecture: HIGH - current control plane boundaries are visible in code and docs
- Pitfalls: HIGH - risks are directly observable in current page/API split
- Code examples: HIGH - taken from repo code and tests

**Research date:** 2026-03-29
**Valid until:** 2026-04-28
</metadata>

---

*Phase: 01-system-runtime-paths*
*Research completed: 2026-03-29*
*Ready for planning: yes*
