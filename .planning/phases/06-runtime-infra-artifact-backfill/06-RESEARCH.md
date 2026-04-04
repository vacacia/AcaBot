# Phase 06: Runtime Infra Artifact Backfill - Research

**Researched:** 2026-04-04
**Domain:** GSD phase artifact backfill for scheduler, LTM data safety, and logging / observability
**Confidence:** MEDIUM

<user_constraints>
## User Constraints

No `CONTEXT.md` exists for this phase.

Use only these scope gates:
- `.planning/STATE.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/v1.0-MILESTONE-AUDIT.md`

Locked scope from roadmap + audit:
- This phase is for **artifact / traceability repair**, not new feature design.
- It must close the audit blockers for `3a`, `3b`, and `3c`.
- It is **out of scope** to solve `MSG-08` real-client readability and workspace / `runtime_data` boundary issues. Those belong to Phase 07 or separate gap work.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHED-01 | Cron expression scheduling | Existing scheduler core tests, `croniter` runtime, and `3a-PLAN-01.md` map directly to current code in `src/acabot/runtime/scheduler/`. |
| SCHED-02 | Interval scheduling | Existing scheduler core tests and plan-to-code mapping are intact. |
| SCHED-03 | One-shot scheduling | Existing scheduler core tests and store recovery logic are intact. |
| SCHED-04 | Task persistence and recovery | Existing persistence tests exist; summary backfill must cite store + restart tests. |
| SCHED-05 | Task cancellation by `task_id` | Existing scheduler core tests cover cancel and unregister paths. |
| SCHED-06 | Graceful shutdown | Existing scheduler core tests cover callback drain; phase verification must also record app shutdown ordering evidence. |
| SCHED-07 | Plugin lifecycle binding | Existing unload cleanup test passes; backfill must point to `PluginRuntimeHost` wiring. |
| SCHED-08 | RuntimeApp lifecycle integration | Existing test file exists but two app lifecycle tests are stale after Phase 04 `render_service` wiring; planner must refresh this proof path. |
| LTM-01 | Write serialization | Existing write-lock tests pass; backfill can rely on current code plus test suite. |
| LTM-02 | Periodic backup capability | Existing backup builder, backup store, and app registration tests pass. |
| LTM-03 | Startup integrity check | Fresh-store validation and degraded bootstrap behavior exist, but corruption-proof is only partially automated; planner should decide whether to add a stricter negative test. |
| LTM-04 | Graceful degradation on LTM failure | Existing bootstrap and app degradation tests pass. |
| LOG-01 | Structured tool call logs | Existing tool broker structured logging tests pass. |
| LOG-02 | Per-run token usage with model and cost | Token + model proof exists, but `cost` does not appear in current runtime code or tests; this is a real planning risk. |
| LOG-03 | Error logs auto-associate run context | Existing structlog context propagation tests pass. |
| LOG-04 | WebUI log viewer displays structured fields | Browser path is healthy, but current tests only prove log API + page existence, not `extra` field rendering. |
| LOG-05 | LTM extraction / query logs visible | Query-side structured logs are tested; extraction-side logging exists in code but is not explicitly asserted. |
| LOG-06 | structlog integration with contextvars | Existing `log_setup.py` and structured logging tests pass. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- 所有文档、代码注释、交流过程都使用中文 + 英文标点符号。
- 每次工作前都要读 `docs/00-ai-entry.md`。
- 作为 main agent, 要遵照 GSD 指示, 不做超范围的事。
- 技术栈固定为 Python 3.11+ + `asyncio`, 不引入新的异步框架。
- Gateway 只需要 NapCat / OneBot v11 实现。
- 部署要兼容 Docker Compose 的 Full + Lite 双镜像。
- 插件重构相关兼容性不能破坏 `BackendBridgeToolPlugin` 过渡期可用性。
- 已知全量测试失败: `tests/runtime/backend/test_pi_adapter.py` 依赖真实 `pi` 可执行文件, 全量验证时应显式 `--ignore`。

## Project Conventions (from `docs/00-ai-entry.md`)

- 不要为了保留旧审计层再发明兼容层。
- 文档和注释写“现在是什么”, 不写“不要怎么做”。
- 如果这 phase 最终需要补测试或补少量验证代码, 改到 runtime / WebUI / config / tool / docs 对应层时要同步相关文档真源。
- 全局正式命名继续沿用 `actor_id` / `conversation_id` / `thread_id` / `session_id` / `entity_ref`。

## Summary

这 phase 的本质不是补功能, 是把已经落地的 `3a-scheduler`、`3b-ltm-data-safety`、`3c-logging-observability` 重新挂回 GSD 证据链。milestone audit 真正看的不是“代码应该在”, 而是原 phase 目录里有没有被工具识别的 `*-SUMMARY.md`、`*-VERIFICATION.md`、`*-VALIDATION.md`, 再加上 `REQUIREMENTS.md` 和 summary frontmatter 的三向对齐。所以 planning 时最重要的决策不是“还要不要重做 scheduler”, 而是“哪些东西补到原 phase 目录里, 哪些验证命令在当前代码库还站得住”。

我实际复跑后, 大多数运行时能力都还在, 而且有不少测试能直接拿来做 backfill 证据: scheduler core 23 个用例现在仍能稳定通过, LTM 安全相关 14 个用例通过, logging / token / LTM query / tool broker 相关 36 个用例通过, WebUI logs API + logs page 的浏览器路径也能通过。但别自欺欺人, 这里有 4 个会直接影响 plan 的硬坑: `SCHED-08` 的旧 integration tests 因为 Phase 04 后续给 `RuntimeApp` 加了 `render_service` 推断而失效; `LOG-04` 现有测试只证明日志页活着, 没直接锁住 `extra` 字段渲染; `LOG-02` 的 requirement 写了 `cost`, 当前代码和测试里基本没有; `LTM-03` 有 fresh validation 和 degraded bootstrap 证明, 但没有真坏表 schema 的负向测试。

**Primary recommendation:** 把 Phase 06 规划成“原 phase 目录原地补 summary + current-code re-verification + Nyquist validation repair”, 并预留最少量的 verification-only 测试修复 / closeout 修复来补 `SCHED-08`、`LOG-04`、`LOG-02(cost)` 这些真实缺口。

## Standard Stack

### Core

| Library / Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uv` | `0.9.15` | Canonical runner for repo-local Python env | `uv run` 环境里的 `pytest` / deps 才和项目真实执行环境一致。 |
| `pytest` | `9.0.2` | Automated verification runner | 当前 repo 的 phase proof 命令都应该围绕 `uv run pytest` 写。 |
| `pytest-asyncio` | `1.3.0` | Async test support | runtime 代码是 `asyncio` 原生, 不需要新测试框架。 |
| `git` | `2.43.0` | Commit archaeology for summary reconstruction | `3a/3b/3c` 的 missing summaries 需要从真实提交链回填, 不能靠记忆瞎编。 |
| `gsd-tools` local workflow | local | Canonical audit / summary / validation contract | audit 识别的是固定命名、frontmatter 和 report 结构, 不认自定义格式。 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `croniter` | `6.2.2` | Evidence source for scheduler cron support | 只用于复核 `SCHED-01`, 不建议 Phase 06 再改依赖策略。 |
| `lancedb` | `0.30.1` | Evidence source for LTM store / backup / validate behavior | 复核 `LTM-01..04` 时引用当前实现和测试。 |
| `structlog` | `25.5.0` | Evidence source for run context propagation and structured logging | 复核 `LOG-01..06` 时直接看当前 emit sites 和 tests。 |
| `playwright` | `1.58.0` | Browser proof path for `LOG-04` if planner adds a UI regression | 现有浏览器测试链能跑, 所以可以继续用。 |
| `node` | `v22.22.1` | Runs `gsd-tools` CLI and summary extraction helpers | backfill 过程要频繁用 `summary-extract`、`init`、`find-phase`。 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 在 `06-runtime-infra-artifact-backfill/` 里写一份总说明 | 把 artifacts 补回 `3a` / `3b` / `3c` 原目录 | audit 读的是原 phase 目录; 只写 06 目录会继续 orphan。 |
| 直接复述旧 plan 里的验证命令 | 用当前代码库重新跑当前还能过的命令, 并修补 stale tests | 后续 phase 已经改过 app / render wiring, 旧命令会撒谎。 |
| 把 `LOG-02` / `LOG-04` 直接标成已满足 | 先承认 gap, 再补最小测试或 closeout 修复 | 这是 milestone honesty 的底线, 不然 audit 只是被糊弄过去。 |

**Installation:**
```bash
cd /home/acacia/AcaBot
uv sync --extra dev
```

**Version verification:** 以上版本在 2026-04-04 通过本机 CLI 和 `uv run python` 的 `importlib.metadata` 实测确认, 不是凭训练记忆写的。

## Architecture Patterns

### Recommended Project Structure

```text
.planning/phases/
├── 3a-scheduler/
│   ├── 3a-PLAN-01.md
│   ├── 3a-PLAN-02.md
│   ├── 3a-01-SUMMARY.md      # Phase 06 要补
│   ├── 3a-02-SUMMARY.md      # Phase 06 要补
│   ├── 3a-VERIFICATION.md    # Phase 06 要补
│   └── 3a-VALIDATION.md      # Phase 06 要补
├── 3b-ltm-data-safety/
│   ├── 3b-PLAN-01.md
│   ├── 3b-PLAN-02.md
│   ├── 3b-01-SUMMARY.md      # Phase 06 要补
│   ├── 3b-02-SUMMARY.md      # Phase 06 要补
│   ├── 3b-VERIFICATION.md    # Phase 06 要补
│   └── 3b-VALIDATION.md      # Phase 06 要补
├── 3c-logging-observability/
│   ├── 3c-PLAN-01.md
│   ├── 3c-PLAN-02.md
│   ├── 3c-PLAN-03.md
│   ├── 3c-01-SUMMARY.md      # Phase 06 要补
│   ├── 3c-02-SUMMARY.md      # Phase 06 要补
│   ├── 3c-03-SUMMARY.md      # Phase 06 要补
│   ├── 3c-VERIFICATION.md    # Phase 06 要补
│   └── 3c-VALIDATION.md      # Phase 06 要补
└── 06-runtime-infra-artifact-backfill/
    ├── 06-RESEARCH.md
    ├── 06-PLAN-*.md
    └── 06-SUMMARY.md
```

### Pattern 1: Backfill Into The Source Phase Directories

**What:** 缺的 `SUMMARY/VERIFICATION/VALIDATION` 要写回 `3a`、`3b`、`3c` 原目录, 不是只在 `06` 目录写 umbrella 文档。

**When to use:** 任何 milestone audit 报 “orphaned by missing phase artifacts” 的情况。

**Example:**
```bash
# audit 交叉校验 summary frontmatter 的 requirement 列表
node "$HOME/.codex/get-shit-done/bin/gsd-tools.cjs" summary-extract \
  ".planning/phases/04-unified-message-tool-playwright/04-01-SUMMARY.md" \
  --fields requirements_completed \
  --pick requirements_completed
# -> MSG-04,MSG-05,MSG-07,MSG-10
```
Source: `/home/acacia/.codex/get-shit-done/workflows/audit-milestone.md`, `/home/acacia/.codex/get-shit-done/templates/summary.md`

### Pattern 2: Reconstruct Per-Plan Summaries, Not One Big Retro Note

**What:** `3a` 有 2 个 plan, `3b` 有 2 个, `3c` 有 3 个。summary 应该按原 plan 粒度回填, frontmatter 里的 `requirements-completed` 也按各 plan 的 requirement 覆盖来写。

**When to use:** phase 当时真的拆 plan 执行过, 但 summary 丢了。

**Example:**
```markdown
---
phase: 3a-scheduler
plan: 01
requirements-completed: [SCHED-01, SCHED-02, SCHED-03, SCHED-04, SCHED-05, SCHED-06]
---
```
Source: `/home/acacia/.codex/get-shit-done/templates/summary.md`, `/home/acacia/AcaBot/.planning/phases/3a-scheduler/3a-PLAN-01.md`

### Pattern 3: Verify Against Today's Codebase, Not Yesterday's Plan Text

**What:** verification report 要围绕当前真实代码和当前还能跑的测试来写。原 plan 的 verify block 只能当线索, 不能原样照抄。

**When to use:** 后续 phase 改过 constructor、DI、fixture 依赖或者 UI shell。

**Example:**
```bash
# 2026-04-04 实测当前还能过的 scheduler 子集
PYTHONPATH=src uv run pytest -q tests/test_scheduler.py tests/test_scheduler_integration.py \
  -k 'not test_app_start_starts_scheduler and not test_app_stop_order'
# -> 23 passed, 2 deselected in 4.35s
```
Source: local test run on 2026-04-04

### Pattern 4: Validation Is Per Original Phase, Not Per Umbrella Phase

**What:** `workflow.nyquist_validation` 现在是启用状态, 所以 `3a-VALIDATION.md`、`3b-VALIDATION.md`、`3c-VALIDATION.md` 都要有。它们可以由 Phase 06 规划 / 执行补出来, 但文件归属仍然属于原 phase。

**When to use:** audit 把 `3a/3b/3c` 列进 `nyquist.missing_phases`。

**Example:**
```bash
test -f ".planning/phases/3a-scheduler/3a-VALIDATION.md"
test -f ".planning/phases/3b-ltm-data-safety/3b-VALIDATION.md"
test -f ".planning/phases/3c-logging-observability/3c-VALIDATION.md"
```
Source: `/home/acacia/AcaBot/.planning/config.json`, `/home/acacia/.codex/get-shit-done/workflows/validate-phase.md`

### Anti-Patterns to Avoid

- **只补 `06-VERIFICATION.md`:** milestone audit 还是会把 `3a/3b/3c` 当 missing phase。
- **照搬 2026-04-03 的 verify blocks:** 现在 `RuntimeApp` 构造约束已经变了, 老命令会给你假安全感。
- **猜 commit hash 填 summary:** `3b/3c` 很多实现被压进 `2a202ac feat: complete phase 3`, 没证据就别造原子 task hash。
- **先把 REQUIREMENTS.md 打勾再补证据:** audit 会用三向交叉校验把这种假完成直接抓出来。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Audit-recognized artifact naming | 自定义“retro report”文件名 | `*-SUMMARY.md`, `*-VERIFICATION.md`, `*-VALIDATION.md` | GSD workflow 和 audit 只认固定命名。 |
| Requirement extraction from summaries | 手写 grep / 脚本乱解析 frontmatter | `gsd-tools summary-extract` | 跟 audit 用同一个解析器, 不会解析歪。 |
| Phase verification contract | 自定义 checklist | `/home/acacia/.codex/get-shit-done/workflows/verify-phase.md` 的结构 | 产出的 status、requirements table、human verification 才能被后续工具消费。 |
| Validation coverage bookkeeping | 人脑记哪些 requirement 有测试 | `/home/acacia/.codex/get-shit-done/workflows/validate-phase.md` 风格的 requirement-to-test map | Nyquist frontmatter 和 Wave 0 gap 格式有固定消费方。 |
| Commit archaeology | 凭印象补 task commit | `git log -- <files>`, `git show --stat` | Phase 3 实现混有 umbrella commit, 只能看真 history。 |

**Key insight:** 这个领域最容易翻车的不是技术实现, 而是“证据格式看起来像对, 实际工具不认”。Phase 06 计划必须完全贴着 GSD workflow 的消费方式来写。

## Common Pitfalls

### Pitfall 1: 把补档文件全堆到 06 目录

**What goes wrong:** `06` 自己很漂亮, 但 `3a/3b/3c` 还是被 audit 记成 missing / orphaned。

**Why it happens:** milestone audit 扫的是原 phase 目录, 还会从 summary frontmatter 提 requirement。

**How to avoid:** 先列出每个原 phase 缺哪些文件, 然后按原目录原文件名回填。

**Warning signs:** `find .planning/phases/3a-scheduler -maxdepth 1 -name '*SUMMARY.md'` 仍然空。

### Pitfall 2: 直接照搬 scheduler 的旧 integration verify 命令

**What goes wrong:** `SCHED-08` 两个旧测试直接炸, 看起来像 scheduler 回归了。

**Why it happens:** `RuntimeApp.__init__()` 现在会从 `pipeline.outbox` 推断 `render_service`, 但 `tests/test_scheduler_integration.py` 还在传 `pipeline=None`。

**How to avoid:** 在 Phase 06 里把这 2 个测试修成当前 fixture, 或把同等断言迁到 `tests/runtime/test_app.py`。

**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'outbox'` 出现在 `tests/test_scheduler_integration.py`。

### Pitfall 3: 把 `LOG-02` 当成已经完整满足

**What goes wrong:** verification 报告写成“token + model + cost 全都有”, 但代码里根本没有成本字段。

**Why it happens:** requirement 和 3c context 写了 `cost`, 当前实现只稳定记录 token 数和 model。

**How to avoid:** planning 时明确二选一: 要么补 `cost` 实现 / 测试, 要么把 `LOG-02` 标成 partial 并承认还需要 closeout。

**Warning signs:** `rg -n "response_cost|completion_cost|cost\\b" src tests` 几乎只命中 planning 文档。

### Pitfall 4: 把 logs 页存在当成 `LOG-04` 自动化闭环

**What goes wrong:** WebUI 其实没被证明真的把 `extra` 字段渲染成 chips, 只是页面打开了。

**Why it happens:** 现有 `tests/runtime/test_webui_api.py` 只断言 logs API 增量拉取和页面标题。

**How to avoid:** 加一个直接喂 `LogEntry.extra` 的浏览器断言, 或在 validation 里老实标 manual-only。

**Warning signs:** 测试里没有任何 `tool_name` / `duration_ms` / `item.extra` 的 DOM 断言。

### Pitfall 5: 只补 phase-level verification / validation, 不补 plan-level summaries

**What goes wrong:** audit 依然可能把 requirement 判成 partial, 因为缺 `requirements-completed` frontmatter 交叉证据。

**Why it happens:** audit 的第三条证据源就是 summary frontmatter。

**How to avoid:** `3a` 补 2 份 summary, `3b` 补 2 份, `3c` 补 3 份, 不偷懒。

**Warning signs:** `summary-extract ... --pick requirements_completed` 对 `3a/3b/3c` 什么都提不出来。

### Pitfall 6: 把 LTM-03 和 LOG-05 的“代码存在”误当成“自动化证据足够”

**What goes wrong:** verification 写得很满, 但其实负向 corruption proof 和 extraction-log proof 都没硬断言。

**Why it happens:** 当前 repo 里有 fresh validation、degrade 测试、query logs 测试, 但没有每个 requirement 的满覆盖自动化。

**How to avoid:** 在 VALIDATION.md 里把这些列成 partial / Wave 0 gap, 再决定补不补测试。

**Warning signs:** 没有真实坏表 schema 的测试; 没有 `LTM extraction completed` 的断言。

## Code Examples

Verified local patterns and commands:

### 1. 用 `gsd-tools` 读取 summary frontmatter

```bash
node "$HOME/.codex/get-shit-done/bin/gsd-tools.cjs" summary-extract \
  ".planning/phases/04-unified-message-tool-playwright/04-01-SUMMARY.md" \
  --fields requirements_completed \
  --pick requirements_completed
# MSG-04,MSG-05,MSG-07,MSG-10
```
Source: `/home/acacia/.codex/get-shit-done/workflows/audit-milestone.md`

### 2. 当前还能直接当证据的 scheduler 子集

```bash
PYTHONPATH=src uv run pytest -q tests/test_scheduler.py tests/test_scheduler_integration.py \
  -k 'not test_app_start_starts_scheduler and not test_app_stop_order'
# 23 passed, 2 deselected in 4.35s
```
Source: local test run on 2026-04-04

### 3. 当前还能直接当证据的 LTM 安全子集

```bash
PYTHONPATH=src uv run pytest -q \
  tests/runtime/test_ltm_write_lock.py \
  tests/runtime/test_ltm_backup.py \
  tests/runtime/test_ltm_data_safety.py \
  tests/runtime/test_bootstrap.py \
  -k 'ltm or long_term_memory or backup or degrade'
# 14 passed, 31 deselected in 10.48s
```
Source: local test run on 2026-04-04

### 4. 当前还能直接当证据的 logging / token / LTM query 子集

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_structured_logging.py \
  tests/test_agent.py \
  tests/runtime/test_pipeline_runtime.py \
  tests/runtime/test_long_term_memory_source.py \
  tests/runtime/test_tool_broker.py \
  -k 'log or token or LTM or tool or context'
# 36 passed, 25 deselected in 9.93s
```
Source: local test run on 2026-04-04

### 5. WebUI logs path is alive, but not yet enough for `LOG-04`

```bash
PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py \
  -k 'serves_incremental_logs or logs_page_exists'
# 2 passed, 49 deselected in 6.96s
```
Source: local test run on 2026-04-04

### 6. 快速抓 `LOG-02(cost)` 的真实缺口

```bash
rg -n "response_cost|completion_cost|cost\\b" \
  src tests .planning/phases/3c-logging-observability \
  -g '*.py' -g '*.md'
```
Source: local grep on 2026-04-04

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `REQUIREMENTS.md` 打勾就算完成 | audit 用 `VERIFICATION.md` + summary frontmatter + `REQUIREMENTS.md` 三向交叉校验 | Current local GSD audit workflow | 没 artifacts 的 requirement 会被直接记成 orphaned / unsatisfied。 |
| 只要 phase 目录里有 PLAN 就能回溯 | plan execution 还必须留下 `*-SUMMARY.md` | Current `execute-plan.md` + `summary.md` contract | `3a/3b/3c` 现在卡的就是 summary 缺失。 |
| 只要有 VERIFICATION 就算够 | `workflow.nyquist_validation` 开启时还要 `*-VALIDATION.md` | `.planning/config.json` current state | `3a/3b/3c` 现在也会被算进 Nyquist missing phases。 |
| 可以继续沿用 3a 原始 integration tests | `RuntimeApp` 现在有 `render_service` 推断, fixture 也必须跟着升级 | Phase 04 commits `387c67a` + `3592138` | `SCHED-08` 的旧 tests 在今天会假红。 |

**Deprecated / outdated:**
- “把 `STATE.md` 里的汇总验证摘要当 phase-level evidence” 已经不够了。milestone audit 明确说这不能替代原 phase 目录里的独立 artifacts。
- “有 logs page 就算 `LOG-04` 自动化已覆盖” 也是过期认知。现在只能证明页面存在, 不能证明 structured extras 可视化。

## Open Questions

1. **`SCHED-08` 要不要在 Phase 06 里顺手修测试?**
   - What we know: `tests/test_scheduler_integration.py::test_app_start_starts_scheduler` 和 `::test_app_stop_order` 现在因为 `pipeline=None` 而失败。
   - What's unclear: 只靠现有 `tests/runtime/test_app.py` 是否足够替代这两个旧断言。
   - Recommendation: 默认把它当 Phase 06 的 Wave 0 validation gap, 修测试或迁移断言, 不要简单排除。

2. **`LOG-02` 的 `cost` 是补实现, 还是承认 partial?**
   - What we know: 当前代码和测试只稳定证明了 token 数与 model。
   - What's unclear: litellm 的成本数据在当前 provider 组合里是否可靠可取, 以及是否需要持久化。
   - Recommendation: planning 时明确给出决策。若 milestone 必须“honestly pass”, 更稳的做法是补最小实现 + 测试。

3. **`LOG-04` 要不要补真实 DOM 断言?**
   - What we know: logs API 增量拉取和 logs 页面加载都能过, 但没有 test 断言 `extra` chips。
   - What's unclear: audit 对这类 UI requirement 是否接受 code inspection + page existence。
   - Recommendation: 默认补一个浏览器级断言, 因为 Playwright 路径已可用, 成本不高, 证据更硬。

4. **`LTM-03` 要不要补“坏表 schema / corrupt store”负向测试?**
   - What we know: fresh `validate()` 测试有, corrupted store 的 degrade 现在靠 monkeypatch builder 抛错模拟。
   - What's unclear: milestone close-out 是否要求证明真实 `validate()` 失败路径。
   - Recommendation: 如果 Phase 06 还有预算, 加一个最小的 invalid table / missing column fixture 会让 `LTM-03` 更硬。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | `uv run` tests, local tooling | ✓ | `3.12.3` | Repo requires `>=3.11`, so current env is acceptable |
| `uv` | Canonical test / import runner | ✓ | `0.9.15` | None |
| `pytest` via `uv` | All automated verification | ✓ | `9.0.2` | None |
| `pytest-asyncio` via `uv` | Async runtime tests | ✓ | `1.3.0` | None |
| `git` | Summary reconstruction from real history | ✓ | `2.43.0` | None |
| `node` | `gsd-tools` CLI | ✓ | `v22.22.1` | None |
| `npm` | Optional if planner decides to touch WebUI build flow | ✓ | `10.9.4` | Not needed for current proof paths |
| `playwright` CLI | Browser proof for `LOG-04` | ✓ | `1.58.0` | Manual-only verification if browser assertions are skipped |

**Missing dependencies with no fallback:**
- None found.

**Missing dependencies with fallback:**
- None found.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | `pyproject.toml` |
| Quick run command | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py tests/runtime/test_ltm_write_lock.py tests/runtime/test_ltm_backup.py tests/runtime/test_ltm_data_safety.py tests/test_structured_logging.py tests/test_agent.py tests/runtime/test_pipeline_runtime.py tests/runtime/test_long_term_memory_source.py tests/runtime/test_tool_broker.py` |
| Full suite command | `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHED-01 | Cron 解析与触发 | unit | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k 'cron_validates_expression or cron_fires_callback'` | ✅ |
| SCHED-02 | Interval 调度与参数校验 | unit | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k 'interval_fires_callback or interval_validates_positive'` | ✅ |
| SCHED-03 | One-shot 单次触发 | unit | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k one_shot_fires_once` | ✅ |
| SCHED-04 | 持久化恢复与 misfire 策略 | integration | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k 'persist_task_survives_restart or misfire_skip_advances_next_fire or misfire_fire_once_triggers_immediately'` | ✅ |
| SCHED-05 | `task_id` 取消与 owner 批量注销 | unit | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k 'cancel_returns_true_for_existing or cancel_returns_false_for_nonexistent or unregister_by_owner'` | ✅ |
| SCHED-06 | Graceful shutdown 与 callback drain | integration | `PYTHONPATH=src uv run pytest -q tests/test_scheduler.py -k 'graceful_shutdown_waits_callbacks or callback_error_does_not_stop_scheduler'` | ✅ |
| SCHED-07 | Plugin unload 自动清理 scheduler tasks | integration | `PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k unload_plugin_cancels_scheduled_tasks` | ✅ |
| SCHED-08 | RuntimeApp start/stop 生命周期接通 scheduler | integration | `PYTHONPATH=src uv run pytest -q tests/test_scheduler_integration.py -k 'app_start_starts_scheduler or app_stop_order'` | ✅ stale/failing |
| LTM-01 | 写序列化 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_write_lock.py -k 'serialize or concurrent'` | ✅ |
| LTM-02 | 周期性备份 + app 注册 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_backup.py tests/runtime/test_ltm_data_safety.py tests/runtime/test_app.py -k 'backup or registers_ltm_backup_task_when_enabled'` | ✅ |
| LTM-03 | 启动完整性校验 + 损坏时降级 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_ltm_write_lock.py -k validate_passes tests/runtime/test_bootstrap.py -k degrades_when_ltm_init_fails` | ✅ partial |
| LTM-04 | LTM 初始化 / 启动失败不阻断 runtime | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_bootstrap.py tests/runtime/test_app.py tests/runtime/test_long_term_memory_source.py -k 'degrades_when_ltm_init_fails or degrades_when_ltm_start_fails or retrieval_fails'` | ✅ |
| LOG-01 | Tool call structured logs | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_tool_broker.py -k 'structured_success_log or structured_rejection_log or structured_failure_log'` | ✅ |
| LOG-02 | Per-run token usage, model, and cost | integration | `PYTHONPATH=src uv run pytest -q tests/test_agent.py tests/runtime/test_pipeline_runtime.py -k 'LLM run completed or complete finished or token_usage'` | ✅ partial |
| LOG-03 | Error / stdlib logs auto carry run context | unit | `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py -k 'bind_run_context or preserves_context or clear_run_context'` | ✅ |
| LOG-04 | WebUI logs viewer renders structured `extra` fields | browser/integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_webui_api.py -k 'serves_incremental_logs or logs_page_exists'` | ❌ Wave 0 |
| LOG-05 | LTM extraction / query structured logs visible | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_long_term_memory_source.py -k 'query_planner_client_emits_structured_log or embedding_client_emits_structured_log or long_term_memory_source_emits_structured_logs'` | ✅ partial |
| LOG-06 | structlog + contextvars integration | unit | `PYTHONPATH=src uv run pytest -q tests/test_structured_logging.py -k 'extracts_structured_fields or bind_run_context or preserves_context'` | ✅ |

### Sampling Rate

- **Per task commit:** Run the smallest relevant requirement slice from the table above.
- **Per wave merge:** Run the three cluster commands actually re-verified on 2026-04-04: scheduler safe subset, LTM safety subset, logging subset.
- **Phase gate:** After any Wave 0 fixes, full suite should be green with `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py`.

### Wave 0 Gaps

- [ ] `tests/test_scheduler_integration.py` — refresh `RuntimeApp` test fixture for `render_service`-aware construction, or migrate `SCHED-08` assertions into `tests/runtime/test_app.py`.
- [ ] `tests/runtime/test_webui_api.py` — add a direct browser assertion that structured log `extra` fields render as chips and remain filterable.
- [ ] `tests/test_agent.py` or `tests/runtime/test_pipeline_runtime.py` — add `cost` assertions if `LOG-02` remains a must-pass requirement in this phase.
- [ ] `tests/runtime/test_long_term_memory_source.py` or `tests/runtime/test_long_term_memory_write_port.py` — add explicit extraction-log proof if `LOG-05` is interpreted strictly as extraction + query.
- [ ] `tests/runtime/test_ltm_data_safety.py` or a new `tests/runtime/test_ltm_validation.py` — add a true invalid-schema / corrupted-store negative test if Phase 06 must prove `LTM-03` beyond builder-level failure simulation.

## Sources

### Primary (HIGH confidence)

- `/home/acacia/AcaBot/.planning/ROADMAP.md` - Phase 06 scope, original requirement text, success criteria.
- `/home/acacia/AcaBot/.planning/REQUIREMENTS.md` - authoritative requirement wording and current traceability state.
- `/home/acacia/AcaBot/.planning/v1.0-MILESTONE-AUDIT.md` - exact blocker classification for `3a` / `3b` / `3c`.
- `/home/acacia/AcaBot/.planning/STATE.md` - executed-phase history and current routing.
- `/home/acacia/AcaBot/src/acabot/runtime/scheduler/` - current scheduler implementation.
- `/home/acacia/AcaBot/src/acabot/runtime/memory/long_term_memory/storage.py` - current LTM write-lock / validate / backup implementation.
- `/home/acacia/AcaBot/src/acabot/runtime/control/log_setup.py` and `/home/acacia/AcaBot/src/acabot/runtime/control/log_buffer.py` - current structlog / log buffer implementation.
- `/home/acacia/.codex/get-shit-done/workflows/audit-milestone.md` - exact audit evidence contract.
- `/home/acacia/.codex/get-shit-done/workflows/verify-phase.md` - exact verification report contract.
- `/home/acacia/.codex/get-shit-done/workflows/validate-phase.md` - exact Nyquist validation contract.
- `/home/acacia/.codex/get-shit-done/templates/summary.md` - required summary frontmatter and naming.

### Secondary (MEDIUM confidence)

- `git show --stat --summary --oneline 2a202ac` - umbrella commit that bundled much of Phase 3.
- `git log -- <phase files>` on scheduler / LTM / logging paths - used to distinguish plan-specific commits from later cross-phase drift.
- Local test runs on 2026-04-04 - used to confirm current proof paths and reveal stale tests / partial coverage.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified from local env, `uv run`, and repo manifests.
- Architecture: HIGH - derived from current GSD workflow consumers and actual phase directory layout.
- Pitfalls: MEDIUM - based on real audit rules and real failing / partial tests, but final Phase 06 plan still needs to decide whether to fix or defer some gaps.

**Research date:** 2026-04-04
**Valid until:** 2026-04-11
