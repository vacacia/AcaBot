# Phase 07: Render Readability + Workspace Boundary - Research

**Researched:** 2026-04-04
**Domain:** 运行时渲染可读性、工作区边界语义、真实产品收口
**Confidence:** MEDIUM

<user_constraints>
## User Constraints

### Locked Inputs
- 研究对象是 Phase 07: Render Readability + Workspace Boundary。
- 阶段描述: Close the remaining real-product close-out gaps from Phase 4: render readability in the real QQ client, and the contract mismatch between bot workspace semantics and runtime_data.
- Phase requirement IDs (MUST address): `MSG-08`
- 产物必须写到 `/home/acacia/AcaBot/.planning/phases/07-render-workspace-boundary-closure/07-RESEARCH.md`。
- 必须包含 `## Validation Architecture`，供后续生成 `VALIDATION.md`。
- 本阶段没有 `CONTEXT.md`。研究范围以 roadmap、requirements、audit、state 和最新 runtime docs 为准。

### Claude's Discretion
- 选择最合适的实现方案，用来补齐真实 QQ 客户端里的渲染可读性问题。
- 选择最合适的实现方案，用来收紧 bot workspace semantics 和 `runtime_data` 之间的边界契约。
- 选择对应的测试、文档同步、UAT 收口策略。

### Deferred Ideas (OUT OF SCOPE)
- Phase 05 / 06 的补档和回填工作。
- 与本阶段无关的审计遗留项，例如 group reply policy 的其他缺口。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MSG-08 | 富文本消息在真实产品链路里可稳定落图、回退、投递，并完成可用性收口。 | 本文给出当前 `RenderService -> Outbox -> NapCat` 管线事实、真实 QQ 可读性缺口、建议的几何与像素密度调优方案、测试映射和手工 UAT 闭环。 |
</phase_requirements>

## Summary

Phase 07 不是新功能探索，而是一个很明确的 close-out phase。Phase 04 已经把 `MSG-08` 的主干能力做出来了，代码里也已经有 `RenderService`、Playwright renderer、Outbox materialization、NapCat 文件段落投递这条完整链路；问题卡在最后 10%: 一是图片在真实 QQ 客户端里可读性还不够扎实，二是 bot 对外暴露的 workspace 语义，和当前 runtime 内部真实落盘目录、host execution view 之间还存在契约漂移。

渲染侧的结论很直接: 不需要换栈，不需要重写消息工具，更不该把渲染产物塞进 `/workspace`。现有 Playwright renderer 已经能稳定产图，但默认输出是 `960 x 540` 的 `full_page` 截图，外边距偏大、内容占比偏低。基于本地实测，最有效的两个调节杆是: `device_scale_factor=2` 提升像素密度，以及从 `full_page` 改成对内容容器做 element screenshot，减少空白区。这个方向和 Playwright 官方能力完全一致，风险比引入新 renderer 小得多。

工作区边界侧更要收紧口径。当前代码已经把实体工作区根目录收敛到 `runtime_root/workspaces`，通常就是 `runtime_data/workspaces`；但是 host backend 的 execution view 仍然泄露宿主机绝对路径，和 docs 里想让 agent 认知为 `/workspace /skills /self` 的前台语义不一致。换句话说，真正的 gap 不是“目录放错了”，而是“前台契约和后台落盘没对齐”。计划阶段应该把这件事当成代码、测试、文档一起改的边界修复，而不是提示词小修小补。

**Primary recommendation:** 保留现有 `Playwright + RenderService + Outbox + NapCat` 栈，用 `HiDPI + 内容级截图` 修正真实 QQ 的落图可读性；同时把 host execution view、测试断言、路径文档统一到一个清晰契约: 后台真实目录在 `runtime_root/workspaces`，前台稳定语义是 `/workspace`。

## Project Constraints (from CLAUDE.md)

- 所有文档、代码注释、对话输出都必须使用中文 + English punctuation。
- 每次开始都先阅读 `docs/00-ai-entry.md`。
- 主 agent 必须遵循 GSD，不做与当前 phase 无关的额外工作。
- 技术栈固定为 Python 3.11+、`asyncio`。不要引入新的 async framework。
- 网关只支持 NapCat。设计可以平台无关，但实现层面只需要 OneBot v11。
- Docker 部署使用 Docker Compose。镜像层改动必须保持 Full + Lite 兼容。
- `BackendBridgeToolPlugin` 仍处于过渡期，相关能力不能破坏。
- 项目是单运营者场景，不需要多租户隔离。
- 已知全量测试里 `tests/runtime/backend/test_pi_adapter.py` 失败，执行 full suite 时应显式忽略。

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12.3 runtime, project target 3.11+ | 运行时主语言 | 已是项目固定主栈，所有 runtime / gateway / tools 都围绕它构建。 |
| Playwright | 1.58.0 | HTML -> PNG 渲染后端 | 代码已接入，官方支持 viewport、`device_scale_factor`、element screenshot，足够解决当前 close-out 问题。 |
| markdown-it-py | 4.0.0 | Markdown 解析 | 当前 `RenderService` 已使用，和现有 rich message 语义一致。 |
| mdit-py-plugins | 0.5.0 | 数学等扩展语法 | 已在渲染管线里启用，继续沿用即可。 |
| latex2mathml | 3.79.0 | 数学公式转 MathML | 已在现有 markdown -> HTML 流程中接入，避免手写公式渲染。 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.0.2 via `uv run` | 阶段验证主框架 | 所有 runtime close-out 测试都应继续落在 pytest。 |
| pytest-asyncio | 1.3.0 | 异步 runtime 测试 | 涉及 render service、outbox、computer runtime 时使用。 |
| Noto Serif CJK SC | system font present | 中文正文字体 | 当前 renderer 已使用该字体，真实中文落图一致性更好。 |
| Docker | 29.1.2 | 运行环境兼容性 | 只在需要验证容器部署路径时使用，本阶段不是主执行面。 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 继续使用 Playwright renderer | 引入 WeasyPrint / wkhtmltoimage / 新截图链路 | 纯属扩大范围。现有栈已经能稳定产图，close-out 只差参数和裁切策略。 |
| 修正 execution view 边界 | 只改提示词 / 只改文档 | 不能修掉 shell 里实际暴露的 host 路径，属于假修。 |
| 保持 render artifacts 在 runtime 内部 | 把图片先落进 `/workspace/attachments` | 会把内部投递产物和 agent 工作区混在一起，边界更脏。 |

**Installation / verification:**
```bash
PYTHONPATH=src uv run python -c "import playwright, markdown_it, mdit_py_plugins, latex2mathml; print(playwright.__version__)"
PYTHONPATH=src uv run pytest --version
```

**Version verification:** 以上版本来自本机实际环境探测，不是训练记忆。研究日为 2026-04-04。

## Architecture Patterns

### Recommended Project Structure
```text
src/acabot/runtime/
├── render/              # Markdown -> HTML -> image 渲染服务与 artifact 管理
├── builtin_tools/       # message / computer 等工具入口
├── computer/            # workspace、world view、execution view、backend
├── bootstrap/           # runtime 组件装配与 config 解析
└── outbox.py            # 出站消息物化、渲染回退、最终 segment 生成
```

### Pattern 1: Render belongs to Outbox finalization
**What:** 工具层只产出 message intent / rich segment，真正的渲染与回退发生在 Outbox materialization。
**When to use:** 任何需要把 markdown / rich content 变成图片、并在 renderer 不可用时自动降级为文本的场景。
**Example:**
```python
# Source: src/acabot/runtime/outbox.py
if seg.type == "rich_text":
    if self._render_service is None:
        materialized.append({"type": "text", "text": seg.text})
        continue
    rendered = await self._render_service.render(seg.text, workdir=workdir)
    materialized.append({"type": "image", "file": rendered.artifact.uri})
```

### Pattern 2: Render artifacts are internal runtime artifacts, not workspace files
**What:** 渲染图片要落在 `runtime_root/render_artifacts/...`，而不是 bot 对外认知的 `/workspace`。
**When to use:** 任何富文本截图、公式渲染图、临时展示图。
**Example:**
```python
# Source: src/acabot/runtime/render/artifacts.py
artifact_dir = runtime_root / "render_artifacts" / run_id
artifact_dir.mkdir(parents=True, exist_ok=True)
```

### Pattern 3: World Path is the frontstage contract, Host Path is runtime-owned
**What:** agent 与 tool 的稳定文件语义应该围绕 World Path，比如 `/workspace/foo.txt`；host 上真实目录只属于 runtime 内部。
**When to use:** file tools、computer session、UI path 展示、日志与提示。
**Example:**
```python
# Source: src/acabot/runtime/computer/world.py
world_path = PurePosixPath("/workspace") / relative_path
host_path = workspace_root / relative_path
```

### Pattern 4: Execution View must not leak host assumptions by accident
**What:** shell / computer runtime 暴露给 agent 的 cwd 与可见根，应和前台契约一致，而不是顺手把宿主机绝对路径透出去。
**When to use:** host backend、sandbox backend、session bootstrap、tool return payload。
**Example:**
```python
# Desired direction, supported by docs/22-work-world-computer-and-sandbox.md
execution_view.workspace_path == "/workspace"
session.cwd_visible == "/workspace"
```

### Anti-Patterns to Avoid
- **在 `message` tool 里硬塞截图逻辑:** 这会绕过 outbox fallback，破坏统一投递路径。
- **把 render artifact 当工作区文件暴露给 agent:** 内部投递产物和 agent 编辑区是两码事，混在一起会污染记忆与路径语义。
- **只改文档不改 execution view:** 计划里看着干净，运行时还是会把 host path 甩到 agent 脸上。
- **为了 QQ 可读性重启一套新 renderer:** 现在的问题是参数和裁切，不是架构失效。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown 富文本落图 | 自己拼 HTML parser / 自写截图器 | 现有 `RenderService + PlaywrightRenderBackend` | 已打通，可回退，有测试，只差可读性调优。 |
| 高清截图 | 手写图像放大 / 二次插值逻辑 | Playwright `device_scale_factor` | 浏览器原生 HiDPI 输出更稳，少一层失真。 |
| 内容裁切 | 自己算 DOM 高度后裁图 | Playwright element screenshot / locator screenshot | 官方能力现成，边界情况更少。 |
| Workspace 边界修复 | 用 prompt 或 regex 替换路径字符串 | 修正 `execution_view`、session bootstrap、相关测试与 docs | 真实泄漏点在 runtime，不在文本表面。 |
| 图片投递临时目录 | 额外造一套 `/tmp` 路由协议 | 继续走 runtime render artifacts + outbox materialization | 现有网关已能消费本地文件 URI，不必另造状态机。 |

**Key insight:** 这个阶段最容易翻车的地方，就是把“最后一公里收口”误判成“需要换栈”。其实完全没必要。当前代码已经离完成很近，真正该做的是把边界和参数调干净。

## Common Pitfalls

### Pitfall 1: 只改 CSS，不改截图几何
**What goes wrong:** HTML 在浏览器里看起来变漂亮了，但发到 QQ 后文字还是小、白边还是大。
**Why it happens:** 当前默认是固定 `960 x 540` 的 `full_page=True` 截图，问题不只在样式，还在像素密度和裁切范围。
**How to avoid:** 把 `device_scale_factor` 和 screenshot target 一起纳入方案，至少验证 `HiDPI + 内容容器截图` 这一组。
**Warning signs:** 生成图片文件变了，但外层空白、内容占比几乎没变。

### Pitfall 2: 把 host path 泄漏当成文案问题
**What goes wrong:** 文档写 `/workspace`，实际 shell session 返回 `/home/.../runtime_data/workspaces/...`，agent 还是会学到错误心智模型。
**Why it happens:** `ComputerRuntime.open_session()` 和 `WorkWorldBuilder._execution_view()` 当前直接沿用了 host path。
**How to avoid:** 计划里必须包含 runtime 代码改动、测试重写、文档同步，三件一起做。
**Warning signs:** `test_computer.py` 还在断言 `execution_view.workspace_path == workspace_host_path`。

### Pitfall 3: 把 render artifact 混进 `/workspace`
**What goes wrong:** agent 看到一堆内部截图文件，路径语义混乱，还可能把投递产物误当用户工作文件。
**Why it happens:** 为了“统一路径”偷懒，把内部 artifact 和 agent workspace 合并。
**How to avoid:** 坚持 render artifacts 留在 runtime 内部目录，只通过 outbox / gateway 消费。
**Warning signs:** 计划里出现 `/workspace/attachments/rendered-*.png` 之类路径。

### Pitfall 4: 文档只修一半
**What goes wrong:** 一部分文档说 `runtime_data/workspaces`，另一部分还写 `~/.acabot/workspaces` 或 `.acabot-runtime`，后续 planner 和执行者继续踩坑。
**Why it happens:** 这个项目已有多轮演进，路径话术存在历史残留。
**How to avoid:** 把 `docs/09`、`docs/12`、`docs/16`、`docs/22` 当成一个同步集合来审。
**Warning signs:** 控制面 API、runtime docs、computer docs 描述不一致。

## Code Examples

Verified patterns from official sources and current code:

### HiDPI browser context
```python
# Source: https://playwright.dev/docs/emulation
page = await browser.new_page(
    viewport={"width": 960, "height": 540},
    device_scale_factor=2,
)
```

### Screenshot the content container instead of the entire page
```python
# Source: https://playwright.dev/python/docs/api/class-locator
card = page.locator(".render-shell")
await card.screenshot(path=str(output_path), type="png")
```

### Runtime-owned render artifact storage
```python
# Source: src/acabot/runtime/render/artifacts.py
artifact_dir = runtime_root / "render_artifacts" / run_id
artifact_path = artifact_dir / f"{request_id}.png"
```

### Runtime computer root resolves under runtime_data by default
```python
# Source: src/acabot/runtime/bootstrap/builders.py
root_dir = resolve_runtime_path(config, computer_conf.get("root_dir", "workspaces"))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| “渲染能出图就算完成” | 真实 QQ 客户端可读性要单独收口 | 2026-03 milestone audit 明确提出 | 自动化通过不代表产品 close-out 完成。 |
| `full_page=True` + 1x 固定截图 | 推荐 `device_scale_factor=2` + 内容容器截图 | 本次研究实测确认 | 内容占比更高，中文正文更清晰。 |
| 文档里混用 `~/.acabot/...`、`.acabot-runtime/...` | 当前代码主线已收敛到 `runtime_root` / `runtime_data` | 近几轮 runtime 重构后形成 | 需要把旧文档残留清干净，否则 planner 会拿错契约。 |
| host execution view 直接暴露 host path | 设计目标应是前台稳定 `/workspace` 语义 | docs/22 已明确目标，但代码未完全跟上 | 这是本阶段 workspace boundary 的核心修复点。 |

**Deprecated / outdated:**
- `docs/12-computer.md` 里关于 `~/.acabot/workspaces/...` 的描述，和当前主线实现不一致。
- `docs/16-front-back-agents-and-self-evolution.md` 里关于 `.acabot-runtime` 的描述，和当前 runtime path 口径不一致。
- 把 Phase 04 的自动化通过当作 MSG-08 最终完成态，已经被 milestone audit 否掉。

## Open Questions

1. **真实 QQ 客户端最终接受的最佳几何参数是多少?**
   - What we know: `device_scale_factor=2` 明显提升清晰度，`.render-shell` / `.render-card` 裁切能显著减少白边。
   - What's unclear: 最终应截 `.render-shell`、`.render-card` 还是继续全页但调 viewport，需要真人在 QQ 客户端里看。
   - Recommendation: 计划里保留 1 次手工 UAT 任务，用固定 markdown 样本比较 2 到 3 组参数。

2. **host backend 的 execution view 是否要硬性改成 `/workspace`?**
   - What we know: docs/22 的目标很明确，当前代码和测试却还在锁定 host absolute path。
   - What's unclear: 是否存在少量内部逻辑依赖“可见 cwd == host path”这一旧行为。
   - Recommendation: 规划时默认按 `/workspace` 收口；实施前先 grep 依赖点，并同步调整测试。

3. **控制面 path overview 是否也要暴露 render artifacts 路径?**
   - What we know: 当前 overview 已暴露 `computer_root_dir`、sticky notes、LTM、backend session，但没有 render artifacts。
   - What's unclear: 本阶段是否需要给运维 / UAT 更强可观察性。
   - Recommendation: 作为可选任务，不阻塞主修复。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime / tests | ✓ | 3.12.3 | — |
| uv | 项目内一致的执行环境 | ✓ | 0.9.15 | 可用系统 python，但不建议 |
| Playwright Python package | render backend | ✓ | 1.58.0 | 无。缺失会直接降级成文本，但无法完成真实渲染 close-out |
| Node.js | Playwright runtime 依赖 | ✓ | v22.22.1 | — |
| npm | 前置环境 | ✓ | 10.9.4 | — |
| pytest | automated validation | ✓ | 9.0.2 via `uv run` | 系统 `pytest 7.4.4` 仅作兜底，不应用于正式验证 |
| pytest-asyncio | async tests | ✓ | 1.3.0 | 无 |
| Noto Serif CJK SC | 中文渲染字体 | ✓ | system font present | 若缺失会退回 serif，中文视觉可能变差 |
| Docker | 容器兼容性抽查 | ✓ | 29.1.2 | 非主路径，可不作为本阶段 blocker |
| 真实 QQ 客户端 + NapCat 真实链路 | 最终可读性 UAT | ✗ in this environment | — | 无自动化替代，必须人工验收 |

**Missing dependencies with no fallback:**
- 真实 QQ 客户端 UAT 环境。没有它，就不能宣称“真实产品 close-out”完成。

**Missing dependencies with fallback:**
- 无。其余依赖都已可用。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | `pyproject.toml` |
| Quick run command | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py tests/runtime/test_outbox.py tests/runtime/test_work_world.py tests/runtime/test_computer.py tests/runtime/test_bootstrap.py` |
| Full suite command | `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MSG-08 | rich text 可走 `RenderService` 成功落图，renderer 不可用时能文本回退 | unit / integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py tests/runtime/test_outbox.py` | ✅ |
| MSG-08 | bootstrap 正确注册默认 Playwright renderer，并把同一个 render service 注入 outbox | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_bootstrap.py` | ✅ |
| MSG-08 | NapCat / outbox 最终消费本地图片文件路径而不是未物化 rich segment | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py` | ✅ |
| MSG-08 | 真实 QQ 客户端里的最终可读性达到收口标准 | manual UAT | 无自动化替代 | ❌ manual-only |

补充说明: workspace boundary close-out 没有单独 requirement ID，但它是本 phase 描述的一半，planner 仍应显式创建相关测试任务，至少覆盖 `tests/runtime/test_computer.py`、`tests/runtime/test_work_world.py`，必要时补 `tests/runtime/test_webui_api.py`。

### Sampling Rate
- **Per task commit:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py tests/runtime/test_outbox.py tests/runtime/test_work_world.py tests/runtime/test_computer.py`
- **Per wave merge:** `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py tests/runtime/test_outbox.py tests/runtime/test_work_world.py tests/runtime/test_computer.py tests/runtime/test_bootstrap.py tests/runtime/test_webui_api.py`
- **Phase gate:** `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` 全绿，然后执行一次真实 QQ 客户端手工 UAT

### Wave 0 Gaps
- [ ] `tests/runtime/test_render_service.py` 目前没有像素密度、裁切范围、内容占比相关断言。
- [ ] `tests/runtime/test_computer.py` 当前锁定 host path execution view；如果 Phase 07 把前台契约收口到 `/workspace`，这些断言必须先改。
- [ ] 缺少固定 markdown 样本 + 人工 UAT checklist，无法稳定比较 QQ 客户端真实可读性。
- [ ] `tests/runtime/test_work_world.py` 还没把“frontstage path contract”和“host storage path”明确拆开验证。

## Sources

### Primary (HIGH confidence)
- Local docs: `docs/02-runtime-mainline.md`, `docs/03-data-contracts.md`, `docs/05-memory-and-context.md`, `docs/07-gateway-and-channel-layer.md`, `docs/12-computer.md`, `docs/22-work-world-computer-and-sandbox.md`
- Local planning docs: `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/v1.0-MILESTONE-AUDIT.md`, `.planning/phases/04-unified-message-tool-playwright/04-VALIDATION.md`, `.planning/phases/04-unified-message-tool-playwright/04-VERIFICATION.md`
- Local code: `src/acabot/runtime/render/service.py`, `src/acabot/runtime/render/playwright_backend.py`, `src/acabot/runtime/render/artifacts.py`, `src/acabot/runtime/outbox.py`, `src/acabot/runtime/computer/*.py`, `src/acabot/runtime/bootstrap/*.py`, `src/acabot/runtime/control/config_control_plane.py`, `src/acabot/gateway/napcat.py`
- Local tests: `tests/runtime/test_render_service.py`, `tests/runtime/test_outbox.py`, `tests/runtime/test_computer.py`, `tests/runtime/test_work_world.py`, `tests/runtime/test_bootstrap.py`, `tests/runtime/test_webui_api.py`
- Playwright official docs: https://playwright.dev/docs/emulation
- Playwright Python locator screenshot docs: https://playwright.dev/python/docs/api/class-locator
- Local runtime experiments run on 2026-04-04:
  - current backend output: PNG `960 x 540`
  - HiDPI output with `device_scale_factor=2`: PNG `1920 x 1080`
  - element screenshot sizes: `.render-shell` `1920 x 740`, `.render-card` `1760 x 580`

### Secondary (MEDIUM confidence)
- 无。关键结论都能由本地代码、测试、文档或官方 Playwright 文档直接验证。

### Tertiary (LOW confidence)
- 无。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 版本与能力都由本机环境和当前代码直接验证。
- Architecture: MEDIUM - render 路线很清楚，但 workspace execution view 仍存在 docs / code 漂移，需要计划阶段锁定最终契约。
- Pitfalls: HIGH - 都来自现有代码断言、milestone audit 和本地实测，不是空想风险。

**Research date:** 2026-04-04
**Valid until:** 2026-04-11
