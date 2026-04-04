# Phase 05: Foundation Artifact Backfill - Research

**Researched:** 2026-04-04
**Domain:** GSD artifact backfill, requirement traceability repair, Nyquist validation reconstruction for already-landed Phase 1 / Phase 2 work
**Confidence:** HIGH

<user_constraints>
## User Constraints

No `05-CONTEXT.md` exists for this phase.

Use these locked inputs from the prompt, roadmap, requirements, state, and milestone audit:

- Only backfill GSD evidence for the already-delivered foundation refactors in Phase 1 and Phase 2.
- Must address `REF-01`, `REF-02`, `REF-03`, `PLUG-01`, `PLUG-02`, `PLUG-03`, `PLUG-04`, `PLUG-05`, `PLUG-06`, `PLUG-07`, `PLUG-08`, `PLUG-09`, `PLUG-10`, `PLUG-11`, `PLUG-12`, `PLUG-13`.
- The outcome is evidence-chain repair, not new product behavior.
- Re-running milestone audit must stop reporting foundation requirements as orphaned.
- `## Validation Architecture` must be present so downstream tooling can create `VALIDATION.md`.

Out of scope:

- New Phase 1 / Phase 2 product features.
- Phase 3+ runtime gaps except where they directly affect artifact reconstruction tooling.
- Inventing new planning metadata formats outside existing GSD artifact conventions.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-01 | Reference Backend subsystem completely deleted, no residual imports | Use git deletion commits + current zero-hit grep + robust no-source-files check that ignores generated `__pycache__` |
| REF-02 | BackendBridgeToolPlugin decoupled from Reference Backend, transition-period usable | Use current `backend_bridge_tool.py` + focused backend-bridge pytest smoke, not full backend / `pi` runtime tests |
| REF-03 | `config.yaml` reference-related config items cleaned or marked deprecated | Use current `config.example.yaml` zero-hit check for `reference:` keys and no `reference_backend` wiring in bootstrap / app |
| PLUG-01 | Plugin identity migrated from import path to `plugin_id` | Use `plugin_protocol.py`, `plugin_package.py`, `plugin_spec.py`, `plugin_runtime_host.py`, and related tests |
| PLUG-02 | `PluginPackage` scans `extensions/plugins/` for `plugin.yaml` manifests | Use `PackageCatalog` implementation, `sample_tool/plugin.yaml`, and `test_plugin_package.py` |
| PLUG-03 | `PluginSpec` persisted to `runtime_config/plugins/` | Use `SpecStore` implementation + `test_plugin_spec.py` |
| PLUG-04 | `PluginStatus` persisted to `runtime_data/plugins/` | Use `StatusStore` implementation + `test_plugin_status.py` |
| PLUG-05 | `PluginReconciler` implements desired-state convergence | Use `plugin_reconciler.py` + `test_plugin_reconciler.py` |
| PLUG-06 | `PluginRuntimeHost` executes load / unload / teardown / `run_hooks` | Use `plugin_runtime_host.py` + `test_plugin_runtime_host.py` |
| PLUG-07 | Single-plugin exception does not affect runtime | Use reconciler / host isolation tests and current code paths that catch per-plugin failures |
| PLUG-08 | Old `plugin_manager.py` fully replaced and deleted | Use current file absence + `git show --stat --summary 1dfe340` |
| PLUG-09 | Legacy plugins deleted | Use current file absence for `ops_control.py` / `napcat_tools.py` + preserved transitional `BackendBridgeToolPlugin` |
| PLUG-10 | REST API 5 new endpoints replace old 4 endpoints | Use current `http_api.py` / `control_plane.py`, API smoke, and note thin direct endpoint coverage where applicable |
| PLUG-11 | WebUI plugin management page | Use current `PluginsView.vue`, `npm run build`, and reconciler API usage |
| PLUG-12 | Bootstrap integration constructs catalog / spec_store / status_store / host / reconciler | Use `build_runtime_components()` wiring + targeted bootstrap tests |
| PLUG-13 | Pipeline integration switches `plugin_manager.run_hooks` to `host.run_hooks` | Use `pipeline.py`, `app.py`, and targeted runtime tests / code inspection |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- 所有文档, 代码注释, 交流过程都使用中文 + English punctuation.
- 开始前要读 `docs/00-ai-entry.md`.
- 作为 main agent, 必须遵照 GSD 指示, 不做不该做的事情.
- Python 技术栈锁定为 Python 3.11+ + asyncio, 不引入新的异步框架.
- Gateway 只需要支持 NapCat / OneBot v11.
- 部署约束是 Docker Compose, 且 Full + Lite 镜像都要兼容.
- `BackendBridgeToolPlugin` 在过渡期必须保持可用.
- 场景是单操作者系统, 不需要多租户隔离.
- 已知全量测试例外是 `tests/runtime/backend/test_pi_adapter.py`, 没有真实 `pi` 可执行文件时可忽略.

## Summary

Phase 05 不是重新实现 Phase 1 / 2, 而是把已经落地的历史事实补成 GSD 真正看得懂的证据链。当前 milestone audit 的硬规则不是看 `STATE.md` 写得像不像, 而是做三向交叉核对: `REQUIREMENTS.md` traceability, 各 phase `VERIFICATION.md` requirements table, 以及各 plan `*-SUMMARY.md` frontmatter 里的 `requirements-completed`。只补一份 Phase 05 自己的总结, 或者只改 `STATE.md`, 都不够。

这次研究里最关键的实现细节有两个。第一, 旧 phase 的 plan basename 必须原样保留给 summary 配对。工具是直接拿 `PLAN` 文件名去掉 `-PLAN.md` 后的 basename 找 matching summary, 所以 Phase 1 / 2 这种老命名必须生成 `01-PLAN-01-SUMMARY.md`、`01-PLAN-02-SUMMARY.md`、`02-PLAN-01-SUMMARY.md` 这类文件, 不是 `01-01-SUMMARY.md` 这种“看起来更整齐”的新样式。第二, `REF-01` 的验证不能再写成粗暴的 `test ! -d src/acabot/runtime/references/`, 因为当前仓库里那个目录只剩 ignored 的 `__pycache__` `.pyc` 文件, 源码已经删光了, 但目录本身会被运行时重新生成。

当前仓库已经给够了 backfill 所需证据。`git show` 能回放 Phase 1 / 2 的关键提交: `d09413c`, `8183ad7`, `ba16ed1`, `1dfe340`, `b454029`。2026-04-04 的 live checks 也能证明现状: foundation plugin pytest 子集 `95 passed in 5.82s`, `/api/system/plugins` 相关 HTTP smoke `1 passed in 3.32s`, backend bridge 过渡 smoke `2 passed in 2.72s`, `webui` 的 `npm run build` 通过。但是也有两个不能装看不见的坑: `tests/test_main.py` 现在有 2 个现成失败, 原因是 `RuntimeComponents` 新增了必填 `render_service` 字段而旧 fixture 没跟上; 另外 `tests/runtime/test_tool_broker_backend_bridge.py` 里那两条依赖真实 backend `pi` 路径的用例现在也不能拿来当 Phase 05 硬门槛。

**Primary recommendation:** 把 Phase 05 规划成一个 traceability-reconstruction phase: 在 Phase 01 / 02 原目录里补齐 plan-matching `*-SUMMARY.md`、phase-level `*-VERIFICATION.md`、phase-level `*-VALIDATION.md`, 再同步 `.planning/REQUIREMENTS.md` / `.planning/STATE.md` / `.planning/ROADMAP.md`, 最后重跑 milestone audit 收口。

## Standard Stack

### Core

| Library / Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| GSD phase artifact schema (`*-SUMMARY.md`, `*-VERIFICATION.md`, `*-VALIDATION.md`) | GSD `1.30.0` | 给 audit / verify / transition / milestone summary 提供机器可读证据 | 本地 workflow 明确只读取这些约定文件 |
| `git` | `2.43.0` | 证明历史删除 / 重构已经发生 | 已落地工作最可靠的真源不是记忆, 是提交历史 |
| `node` + `gsd-tools.cjs` | `v22.22.1` + `1.30.0` | 提取 summary frontmatter, phase state, audit compatibility | 本地 GSD 工具链已经内置匹配逻辑 |
| `uv` + `pytest` | `0.9.15` + `9.0.2` | 重跑 foundation 相关回归命令 | 这是仓库现有测试标准链路 |

### Supporting

| Library / Tool | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ripgrep` | `14.1.0` | 零残留 grep 和文件审计 | 验证 REF / PLUG 删除类 requirement |
| `npm` + `vite build` | `10.9.4` + `vite v7.3.1` | `PLUG-11` 的 WebUI 编译级 smoke | 验证插件管理页至少仍可构建 |
| `docs/gsd-guide.md` + local workflow docs | repo current | 还原 GSD 工件语义和消费者行为 | 规划 summary / verification / validation 结构时 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 在 Phase 05 目录里单独写一份大总结 | 直接把缺失工件补回 Phase 01 / 02 原目录 | audit 读取 phase-local `VERIFICATION.md` 和 matching `SUMMARY.md`; 只写 05 自己的文档会继续 orphan |
| 只靠 `STATE.md` / `MILESTONE_SUMMARY` 叙述补证明 | 用 `git show` + current code/test/build + plan-matching summary frontmatter | narrative 不能通过 audit 的三向交叉核对 |
| 用“目录必须不存在”验证删除 | 用“源码文件不存在 + zero symbol grep + tolerate ignored `__pycache__`” | 当前仓库已经证明目录级断言会误报 |

**Installation:**

```bash
uv sync --dev
cd webui && npm ci
```

**Version verification:**

```bash
cat "$HOME/.codex/get-shit-done/VERSION"   # 1.30.0
python3 --version                          # 3.12.3
uv --version                               # 0.9.15
PYTHONPATH=src uv run pytest --version     # 9.0.2
node --version                             # v22.22.1
npm --version                              # 10.9.4
git --version                              # 2.43.0
cd webui && npm run build                  # vite v7.3.1
```

## Architecture Patterns

### Recommended Project Structure

```text
.planning/phases/01-reference-backend-removal/
├── 01-CONTEXT.md
├── 01-PLAN-01.md
├── 01-PLAN-02.md
├── 01-PLAN-01-SUMMARY.md
├── 01-PLAN-02-SUMMARY.md
├── 01-VERIFICATION.md
└── 01-VALIDATION.md

.planning/phases/02-plugin-reconciler/
├── 02-CONTEXT.md
├── 02-PLAN-01.md
├── 02-PLAN-02.md
├── 02-PLAN-03.md
├── 02-PLAN-01-SUMMARY.md
├── 02-PLAN-02-SUMMARY.md
├── 02-PLAN-03-SUMMARY.md
├── 02-VERIFICATION.md
└── 02-VALIDATION.md

.planning/phases/05-foundation-artifact-backfill/
├── 05-RESEARCH.md
├── 05-01-PLAN.md
├── 05-01-SUMMARY.md
├── 05-VERIFICATION.md
└── 05-VALIDATION.md
```

### Pattern 1: Keep Legacy Plan Basenames When Backfilling Summaries

**What:** summary basename 必须和现有 plan basename 一模一样, 只把尾巴从 `-PLAN.md` 换成 `-SUMMARY.md`.

**When to use:** 任何早期 phase 的 plan 文件命名不符合今天的新样式时。

**Why:** GSD 本地工具是 literal basename match, 不是“智能理解你大概想表达什么”。

**Example:**

```bash
# Source: ~/.codex/get-shit-done/bin/lib/phase.cjs + verify.cjs
# 这会把 01-PLAN-01.md 的完成态匹配到 01-PLAN-01-SUMMARY.md
plan_base="${plan_file%-PLAN.md}"
summary_file="${plan_base}-SUMMARY.md"
```

### Pattern 2: Split Evidence into Historical Truth and Current Truth

**What:** 对已经交付过的 phase, 证据要拆成两类:

- historical truth: 用 `git show` / `git log` 证明当时删了什么, 建了什么, 哪些 commit 属于哪个 plan
- current truth: 用今天的源码, targeted pytest, API smoke, build, grep 证明这些结果现在仍然成立

**When to use:** 任何 “代码早就合并了, 现在只是补文档和验证” 的 phase。

**Example:**

```bash
# Source: current repo + git history
git show --stat --summary d09413c -- src/acabot/runtime
git show --stat --summary 1dfe340 -- src/acabot/runtime

PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_plugin_package.py \
  tests/runtime/test_plugin_spec.py \
  tests/runtime/test_plugin_status.py \
  tests/runtime/test_plugin_runtime_host.py \
  tests/runtime/test_plugin_reconciler.py \
  tests/runtime/test_plugin_integration.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_app.py
```

### Pattern 3: Backfill Where Audit Actually Reads

**What:** 证据要落在 audit 的消费者路径上:

- `*-SUMMARY.md` frontmatter 里的 `requirements-completed`
- phase-level `*-VERIFICATION.md` 的 requirements table
- `REQUIREMENTS.md` 的 checkbox / traceability

**When to use:** requirement 当前被 audit 标成 orphaned, 但产品代码其实已经在。

**Example:**

```bash
# Source: ~/.codex/get-shit-done/workflows/audit-milestone.md
for summary in .planning/phases/*-*/*-SUMMARY.md; do
  [ -e "$summary" ] || continue
  node "$HOME/.codex/get-shit-done/bin/gsd-tools.cjs" \
    summary-extract "$summary" \
    --fields requirements_completed \
    --pick requirements_completed
done
```

### Pattern 4: Create VALIDATION Only After Summary Backfill Exists

**What:** Phase 01 / 02 的 `VALIDATION.md` 应该在 summary backfill 之后补, 不能倒着来。

**When to use:** retroactive Nyquist reconstruction.

**Why:** `validate-phase` workflow 的 State C 是 “没有 summary files 就直接退出”。

**Example:**

```text
1. Backfill matching plan summaries
2. Backfill phase verification
3. Generate phase validation from reconstructed evidence map
4. Sync top-level planning docs
5. Re-run milestone audit
```

### Anti-Patterns to Avoid

- **只写 Phase 05 自己的验证报告:** audit 还会继续把 Phase 01 / 02 看成缺工件。
- **把 legacy summary 命名成新风格:** `01-01-SUMMARY.md` 对 `01-PLAN-01.md` 不会被工具识别为 completed plan。
- **拿当前 dirty worktree 当历史证据:** 现在仓库有大量未提交修改, provenance 必须回到具体 commit。
- **把 `__pycache__` 当源码残留:** 当前 `src/acabot/runtime/references/` 目录只剩 `.pyc`, 不是 REF-01 真回归。
- **把 broad full-suite fail 当 foundation blocker:** `tests/test_main.py` 的 `render_service` fixture drift 和 Phase 05 目标无关。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plan completion detection | 自己猜 “哪个 summary 对应哪个 plan” | GSD 现有 basename 规则: `plan.replace('-PLAN.md', '') == summary.replace('-SUMMARY.md', '')` | 本地工具就是这么判 completed plan 的 |
| Requirement status logic | 自定义 spreadsheet 或文字说明 | `audit-milestone.md` 的三向矩阵: REQUIREMENTS + VERIFICATION + SUMMARY frontmatter | milestone audit 明确按这个矩阵算 satisfied / partial / orphaned |
| Retro validation contract | 随手列一个 checklist | `VALIDATION.md` template + `validate-phase.md` State B / C 规则 | planner / verifier / validate-phase 都期待固定 section |
| Historical proof | 靠 `STATE.md` 或人脑回忆 | `git show --stat --summary` + current repo checks | 已落地工作最容易被“现在的改动”污染, commit history 才稳 |

**Key insight:** 这个 phase 成功的标准不是“文档写得感人”, 而是“现有 GSD 消费者能机械地读懂并认账”。

## Common Pitfalls

### Pitfall 1: `__pycache__` 让删除目录看起来像没删干净

**What goes wrong:** 你用 `test ! -d src/acabot/runtime/references/` 当 REF-01 gate, 结果今天直接 fail。

**Why it happens:** 当前目录只剩 ignored 的 `.pyc` 文件, Python import / test 过程会自动再生目录。

**How to avoid:** 验证“没有 tracked / source files + 没有 residual imports”, 不验证目录 inode 本身。

**Warning signs:** `find src/acabot/runtime/references -type f` 只列出 `__pycache__/*.pyc`, `git status` 对这个目录是干净的。

### Pitfall 2: Summary 文件名一旦不配对, audit 继续认为 plan 没执行

**What goes wrong:** 你补了 summary, 但 `completed_by_plans` 还是空。

**Why it happens:** 工具用 literal basename 做 plan-summary matching。

**How to avoid:** 对 legacy plan 保持 legacy basename, 例如 `01-PLAN-01.md` -> `01-PLAN-01-SUMMARY.md`。

**Warning signs:** `phase.cjs` / `verify.cjs` 里 `planBase` 和 `summaryBase` 对不上。

### Pitfall 3: 只写 narrative, 不写 `requirements-completed`

**What goes wrong:** summary 正文说 requirement 完成了, 但 audit 还是 partial / orphaned。

**Why it happens:** milestone audit 会显式提取 summary frontmatter 里的 `requirements-completed`, 不会靠正文意会。

**How to avoid:** 每个 backfilled summary frontmatter 都要把该 plan 的 `requirements:` 原样复制到 `requirements-completed`。

**Warning signs:** `node ... summary-extract ... --fields requirements_completed` 返回空数组。

### Pitfall 4: dirty worktree 污染 provenance

**What goes wrong:** 你拿当前 `git diff` 或工作区现状去解释 Phase 1 / 2 当时做了什么, 然后被别的修改带偏。

**Why it happens:** 当前仓库不是干净树, 有不少无关变更。

**How to avoid:** provenance 只看明确 commit 和 plan 关联, 现状只用来做 “今天仍然成立吗” 的验证。

**Warning signs:** `git status --short` 出现一长串和 foundation backfill 不直接相关的文件。

### Pitfall 5: 拿不相关的 broad suite fail 当 phase blocker

**What goes wrong:** 你跑一大把测试, `tests/test_main.py` 因 `render_service` fixture drift 挂了, 然后误判 Phase 05 不可验证。

**Why it happens:** broad suite 包含后续 phase 引入的结构变化, 不等于 foundation requirement 回归。

**How to avoid:** 用 phase-scoped evidence suite, 并把无关 suite drift 明确写进 residual risk。

**Warning signs:** 报错点在 `RuntimeComponents.__init__()` 缺少 `render_service`, 而不是 REF / PLUG 行为本身。

### Pitfall 6: 把已 skip 的旧 plugin config API 测试当成新 API 证据

**What goes wrong:** 你以为 `test_webui_api.py` 已经覆盖插件 API 全链路, 实际上旧 `/api/system/plugins/config` 测试是 `pytest.skip(...)`。

**Why it happens:** Phase 2 替换了 API 设计, 老测试留作历史残骸。

**How to avoid:** `PLUG-10` 证据要回到当前 `http_api.py` / `control_plane.py`, 再加当前还有效的 HTTP smoke 和 reconciler tests。

**Warning signs:** 测试正文一开头就是 “旧 plugin config API 已删除”。

## Code Examples

Verified patterns from local workflow sources and current repo:

### Matching Legacy Plan Summaries

```bash
# Source: ~/.codex/get-shit-done/bin/lib/phase.cjs
plan_file=".planning/phases/01-reference-backend-removal/01-PLAN-01.md"
plan_base="${plan_file##*/}"
plan_base="${plan_base%-PLAN.md}"     # 01-PLAN-01
summary_file="${plan_base}-SUMMARY.md" # 01-PLAN-01-SUMMARY.md
```

### Robust REF-01 Verification

```bash
# Source: current repo state on 2026-04-04
test -z "$(find src/acabot/runtime/references -type f ! -path '*/__pycache__/*' -print -quit 2>/dev/null)"
test ! -f src/acabot/runtime/plugins/reference_tools.py
test ! -f src/acabot/runtime/control/reference_ops.py
! rg -n 'reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops' \
  src tests config.example.yaml
```

### Phase-Scoped Foundation Evidence Suite

```bash
# Source: live command results on 2026-04-04
PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_plugin_package.py \
  tests/runtime/test_plugin_spec.py \
  tests/runtime/test_plugin_status.py \
  tests/runtime/test_plugin_runtime_host.py \
  tests/runtime/test_plugin_reconciler.py \
  tests/runtime/test_plugin_integration.py \
  tests/runtime/test_bootstrap.py \
  tests/runtime/test_app.py

PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud \
  tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent \
  tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable

cd webui && npm run build
```

### Audit-Visible Requirement Extraction

```bash
# Source: ~/.codex/get-shit-done/workflows/audit-milestone.md
for summary in .planning/phases/*-*/*-SUMMARY.md; do
  [ -e "$summary" ] || continue
  node "$HOME/.codex/get-shit-done/bin/gsd-tools.cjs" \
    summary-extract "$summary" \
    --fields requirements_completed \
    --pick requirements_completed
done
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `STATE.md` / milestone summary 代替 phase evidence | `*-SUMMARY.md` frontmatter + phase `*-VERIFICATION.md` + `REQUIREMENTS.md` checkbox 三向交叉 | 当前 GSD `audit-milestone` workflow | 没这三件套就会被判 orphaned / partial |
| 目录不存在 = 删除完成 | 源码文件不存在 + zero-hit grep, 容忍 ignored `__pycache__` | 2026-04-04 当前仓库实测 | 避免 REF-01 被 pycache 假阳性卡死 |
| 旧 `/api/system/plugins/config` 视为插件管理证据 | 新 reconciler API: `/api/system/plugins`, `/{id}`, `/{id}/spec`, `/reconcile` + current WebUI | Phase 2 delivered on 2026-04-03 | 旧 skip 测试不能再拿来背书 PLUG-10 |

**Deprecated / outdated:**

- `01-01-SUMMARY.md` 这种 summary 命名, 对当前 `01-PLAN-01.md` legacy plan 不适用。
- `test ! -d src/acabot/runtime/references/` 作为 REF-01 的硬断言, 在当前仓库已经过时。
- 把 skip 的 `/api/system/plugins/config` 测试当作新插件 API 自动化覆盖, 也是过时证据。

## Open Questions

1. **`REQUIREMENTS.md` 里的 REF / PLUG phase 归属, backfill 完成后要不要继续留在 Phase 05?**
   - What we know: 当前 `REQUIREMENTS.md` 把 `REF-*` / `PLUG-*` 映射到 Phase 05 `Pending`, 但 roadmap success criteria 又要求 Phase 01 / 02 自己补齐 artifact chain。
   - What's unclear: milestone close-out 更希望保留 gap-closure ownership, 还是把 phase column 改回原始 01 / 02。
   - Recommendation: 先保证 01 / 02 工件链真实存在, 再在一次完整 audit 之后决定是否重映射 phase column。不要先拍脑袋改 traceability。

2. **`PLUG-10` 是否需要补 dedicated HTTP tests 才算证据足够硬?**
   - What we know: 当前有效自动化里, 有 `/api/system/plugins` 通用 HTTP smoke, 也有 reconciler / control-plane / bootstrap 单测, 但旧 `/api/system/plugins/config` 测试已经 skip。
   - What's unclear: 只靠现有 smoke + code inspection, verifier 会不会觉得 detail / spec / reconcile 三个新端点证据偏薄。
   - Recommendation: 在 plan 里预留一个“小而准”的补测选项。如果验证阶段觉得 PLUG-10 证据薄, 就加 focused HTTP smoke; 不要一开始就重写整套 WebUI API 测试。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `gsd-tools.cjs` | summary extraction, init, audit compatibility | ✓ | `1.30.0` | — |
| `python3` | repo runtime / shell helpers | ✓ | `3.12.3` | — |
| `uv` | phase-scoped pytest runs | ✓ | `0.9.15` | — |
| `pytest` | automated regression evidence | ✓ | `9.0.2` | `python -m pytest` if env stays synced |
| `node` | local GSD tooling and frontend build | ✓ | `v22.22.1` | — |
| `npm` | `PLUG-11` build smoke | ✓ | `10.9.4` | — |
| `vite` | current WebUI build | ✓ | `v7.3.1` via `npm run build` | — |
| `git` | historical commit proof | ✓ | `2.43.0` | — |
| `rg` | zero-hit deletion verification | ✓ | `14.1.0` | `grep -R` if necessary |

**Missing dependencies with no fallback:**

- None.

**Missing dependencies with fallback:**

- None.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio` auto mode, plus `npm run build` for WebUI compile smoke |
| Config file | `pyproject.toml`, `webui/package.json` |
| Quick run command | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py tests/runtime/test_plugin_runtime_host.py tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_integration.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py` |
| Full suite command | `bash -lc 'PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_status.py tests/runtime/test_plugin_runtime_host.py tests/runtime/test_plugin_reconciler.py tests/runtime/test_plugin_integration.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py && PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable && cd webui && npm run build'` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-01 | Reference backend source files are gone and no residual imports remain | static + git | `bash -lc 'test -z "$(find src/acabot/runtime/references -type f ! -path '\''*/__pycache__/*'\'' -print -quit 2>/dev/null)" && test ! -f src/acabot/runtime/plugins/reference_tools.py && test ! -f src/acabot/runtime/control/reference_ops.py && ! rg -n "reference_backend|ReferenceBackend|ReferenceToolsPlugin|reference_tools|reference_ops" src tests config.example.yaml'` | ✅ |
| REF-02 | BackendBridge transitional plugin no longer depends on reference backend and still registers cleanly | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | ✅ |
| REF-03 | Config example no longer exposes reference config | static | `bash -lc '! rg -n "^[[:space:]]*reference:" config.example.yaml && ! rg -n "reference_backend|ReferenceBackend" src/acabot/runtime/bootstrap src/acabot/runtime/app.py'` | ✅ |
| PLUG-01 | Plugin identity is `plugin_id`, not import path | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py tests/runtime/test_plugin_spec.py tests/runtime/test_plugin_runtime_host.py` | ✅ |
| PLUG-02 | Package catalog scans `extensions/plugins/*/plugin.yaml` | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py` | ✅ |
| PLUG-03 | Spec store persists to `runtime_config/plugins/` | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_spec.py` | ✅ |
| PLUG-04 | Status store persists to `runtime_data/plugins/` | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_status.py` | ✅ |
| PLUG-05 | Reconciler converges package + spec + status into runtime state | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_reconciler.py` | ✅ |
| PLUG-06 | Runtime host loads, unloads, tears down, and runs hooks | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_runtime_host.py` | ✅ |
| PLUG-07 | Single-plugin failures stay isolated | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_reconciler.py::TestPluginReconciler::test_catches_load_failure tests/runtime/test_plugin_runtime_host.py::TestPluginRuntimeHost::test_hook_exception_isolation` | ✅ |
| PLUG-08 | Legacy `plugin_manager.py` is deleted | static + git | `bash -lc 'test ! -f src/acabot/runtime/plugin_manager.py && git show --stat --summary 1dfe340 -- src/acabot/runtime/plugin_manager.py | rg "delete mode 100644"'` | ✅ |
| PLUG-09 | Legacy `ops_control.py` and `napcat_tools.py` are deleted, BackendBridge stays as transition code | static + unit | `bash -lc 'test ! -f src/acabot/runtime/plugins/ops_control.py && test ! -f src/acabot/runtime/plugins/napcat_tools.py' && PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` | ✅ |
| PLUG-10 | New plugin API surface exists and generic HTTP smoke still works | API smoke + static | `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud && rg -n 'segments == \\["system", "plugins"\\]|segments == \\["system", "plugins", "reconcile"\\]|segments\\[:2\\] == \\["system", "plugins"\\]' src/acabot/runtime/control/http_api.py` | ✅ |
| PLUG-11 | WebUI plugin management page builds against current API surface | build + static | `cd webui && npm run build && rg -n '/api/system/plugins|plugin_id|/spec|reconcile' src/views/PluginsView.vue` | ✅ |
| PLUG-12 | Bootstrap constructs catalog / spec store / status store / host / reconciler | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_bootstrap.py::test_build_runtime_components_creates_plugin_reconciler` | ✅ |
| PLUG-13 | Runtime app / pipeline integrate reconciler startup and host hook execution | unit + static | `PYTHONPATH=src uv run pytest -q tests/runtime/test_app.py::test_runtime_app_plugin_host_available_on_event && rg -n 'plugin_reconciler\\.reconcile_all|plugin_runtime_host\\.run_hooks' src/acabot/runtime/app.py src/acabot/runtime/pipeline.py` | ✅ |

### Sampling Rate

- **Per task commit:** run the smallest command from the table that matches the requirement cluster touched by that task.
- **Per wave merge:** run the quick run command, then rerun the specific REF shell checks if the wave touched Phase 01 artifacts.
- **Phase gate:** run the full suite command, then regenerate milestone audit so orphan detection is checked against the new artifacts rather than guessed.
- **Max feedback latency:** keep single-command feedback under 10s when possible; the full phase evidence suite is about 15-20s on this machine.

### Wave 0 Gaps

- None for pytest infrastructure. The repo already has the needed framework, config, and target test files.
- **Evidence gap to watch:** direct HTTP coverage for `GET /api/system/plugins/{id}`, `PUT /api/system/plugins/{id}/spec`, `DELETE /api/system/plugins/{id}/spec`, and `POST /api/system/plugins/reconcile` is thinner than the rest of the plugin stack. Add focused smoke tests only if verifier says PLUG-10 evidence is too thin.
- **Residual unrelated suite drift:** `tests/test_main.py` currently fails because its `RuntimeComponents` fixture does not provide required `render_service`. Do not use repo-wide full pytest as the Phase 05 gate until that unrelated drift is fixed elsewhere.

## Sources

### Primary (HIGH confidence)

- `.planning/STATE.md` - current phase routing, historical commit IDs, aggregated prior verification signals.
- `.planning/ROADMAP.md` - Phase 05 goal, success criteria, and dependency framing.
- `.planning/REQUIREMENTS.md` - exact `REF-*` / `PLUG-*` descriptions and current traceability state.
- `.planning/v1.0-MILESTONE-AUDIT.md` - concrete orphan evidence and gap taxonomy.
- `.planning/phases/01-reference-backend-removal/01-CONTEXT.md` - original Phase 1 locked decisions.
- `.planning/phases/01-reference-backend-removal/01-PLAN-01.md`
- `.planning/phases/01-reference-backend-removal/01-PLAN-02.md`
- `.planning/phases/02-plugin-reconciler/02-CONTEXT.md`
- `.planning/phases/02-plugin-reconciler/02-PLAN-01.md`
- `.planning/phases/02-plugin-reconciler/02-PLAN-02.md`
- `.planning/phases/02-plugin-reconciler/02-PLAN-03.md`
- `.planning/phases/02-plugin-reconciler/RESEARCH.md`
- `.planning/phases/04-unified-message-tool-playwright/04-VERIFICATION.md`
- `.planning/phases/04-unified-message-tool-playwright/04-VALIDATION.md`
- `.planning/phases/04-unified-message-tool-playwright/04-01-SUMMARY.md`
- `docs/00-ai-entry.md` - project conventions relevant to “write current state, not fantasy history”.
- `docs/gsd-guide.md` - canonical artifact roles and naming examples.
- `~/.codex/get-shit-done/workflows/audit-milestone.md` - orphan detection and tri-source requirement logic.
- `~/.codex/get-shit-done/workflows/verify-phase.md` - phase verifier inputs and expected summary / plan discovery.
- `~/.codex/get-shit-done/workflows/validate-phase.md` - retro validation reconstruction states.
- `~/.codex/get-shit-done/bin/lib/phase.cjs` - exact plan / summary basename matching.
- `~/.codex/get-shit-done/bin/lib/verify.cjs` - phase health warning for missing matching summaries.
- `~/.codex/get-shit-done/templates/summary.md`
- `~/.codex/get-shit-done/templates/verification-report.md`
- `~/.codex/get-shit-done/templates/VALIDATION.md`
- Current implementation files: `src/acabot/runtime/plugin_protocol.py`, `plugin_package.py`, `plugin_spec.py`, `plugin_status.py`, `plugin_runtime_host.py`, `plugin_reconciler.py`, `bootstrap/__init__.py`, `app.py`, `pipeline.py`, `control/http_api.py`, `control/control_plane.py`, `plugins/backend_bridge_tool.py`, `webui/src/views/PluginsView.vue`, `extensions/plugins/sample_tool/*`.

### Secondary (MEDIUM confidence)

- `git show --stat --summary d09413c` - Reference Backend deletions.
- `git show --stat --summary 8183ad7` - reference integration-point removals.
- `git show --stat --summary ba16ed1` - plugin reconciler foundation modules.
- `git show --stat --summary 1dfe340` - new plugin system wiring + legacy deletions.
- `git show --stat --summary b454029` - plugin management WebUI rewrite.
- 2026-04-04 live checks:
  - `PYTHONPATH=src uv run pytest -q tests/runtime/test_plugin_package.py ... tests/runtime/test_app.py` -> `95 passed in 5.82s`
  - `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py::test_runtime_http_api_server_serves_status_and_session_crud` -> `1 passed in 3.32s`
  - `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py::test_tool_broker_only_exposes_backend_bridge_tool_to_default_agent tests/runtime/test_plugin_integration.py::test_backend_bridge_tool_plugin_still_importable` -> `2 passed in 2.72s`
  - `cd webui && npm run build` -> passed, `vite v7.3.1`

### Tertiary (LOW confidence)

- None. The remaining uncertainty is not about missing sources; it is about policy choice on final traceability ownership (`Phase 05` vs back-to-`Phase 01/02` mapping).

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - verified from local toolchain versions and workflow consumers.
- Architecture: HIGH - based on actual local GSD scripts, current repo layout, and live command results.
- Pitfalls: HIGH - reproduced directly from current repo state (`__pycache__`, skipped old API tests, `tests/test_main.py` drift).

**Research date:** 2026-04-04
**Valid until:** 2026-04-11
