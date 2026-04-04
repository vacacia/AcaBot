# Phase 7: Render Readability + Workspace Boundary - Research

**Researched:** 2026-04-04
**Domain:** Playwright rendering / workspace semantics / runtime contracts
**Confidence:** HIGH

## Summary

Phase 7 的核心任务是将 Playwright render 图片在真实 QQ 客户端中变得清晰可读，，以及把 bot 工作空间语义收窄对 `/workspace` 并写入 system prompt。 两者改进独立但但紧密耦合于现有代码。

**render 可读性** 方面的核心发现是: 当前 `PlaywrightRenderBackend` 使用 `browser.new_page()` 创建页面，然后通过 `page.set_viewport_size()` 设置视口。 但 `device_scale_factor` 忲 `browser.new_context()` 层面设置，而非 `page` 层面。 这这意味着要改动代码需要从 `browser.new_page()` 切换到 `browser.new_context()` + `context.new_page()` 模式。 这一，HTML 模板中的 CSS 宽度 `960px` 是硬编码在 `HTML_TEMPLATE` 和 `render_shell` 的 `width` 中，需要变为可配置。

**workspace 语义** 方面的核心发现是: 现有的 `WorldView`、`WorkspaceManager`、`ComputerRuntime` 已经正确实现了 `/workspace` 语义映射:
host backend 的 `runtime_root/workspaces/threads/{thread_id}/workspace/`。host backend 下 shell 看到真实宿主机路径。当前代码通过 `ExecutionView` 区分了这两层, 但需要在 Phase 7 中收稳和D-add 文prompt 中的工作区指引。

**Primary recommendation:** 改用 `browser.new_context()` + `device_scale_factor` 替代 `browser.new_page()` 来创建 HiDPI 戇 render 页面; 在 WebUI 系统设置页增加 render 配置区。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Render 可读性整改先只做"提高分辨率"，这件事, 不先重做整体视觉风格, 不先重排内容密度, 也不先改成另一套版式语言。
- **D-02:** 当前问题被定义为"像素不够清晰"， 不是"样式方向错误"。 后续 planner 和 researcher 应优先调查截图倍率、输出像素密度、QQ 压缩后的清晰度表现, 而不是先开大范围 UI 重画。
- **D-03:** `deviceScaleFactor` 不能继续写死在代码里, 要变成运行时配置项, 并在 WebUI 里可调。
- **D-04:** render 宽度也不能继续写死在代码里, 要变成运行时配置项, 并在 WebUI 里可调。
- **D-05:** 这两个 render 参数先只做"全局默认值"级别的配置, 不做 session 级覆盖。
- **D-06:** Phase 7 不要求现在就锁死最终默认值。初始默认值可以由 planner 决定, 再通过真实 QQ 验收收敛。
- **D-07:** Render 的人工验收使用"完整验收"范围, 不做最小版。
- **D-08:** 真实 QQ 客户端至少要验证这 8 类内容都可读: 标题、普通段落、列表、行内公式、块公式、代码块、引用块、表格。
- **D-09:** Phase 7 需要把这次人工验收结果正式写入 phase artifacts, 不能继续只停留在口头确认。
- **D-10:** 不要求在 `host` backend 下把 shell 看到的真实路径伪装成 `/workspace`。如果模型通过 shell 观察到真实宿主机路径, 这不算 Phase 7 要解决的问题。
- **D-11:** Phase 7 要收稳的是"模型工作语义", 不是 host shell 虚拟化。system prompt 必须明确告诉模型; 工作区全部在 `/workspace`。
- **D-12:** 模型自己要发送本地文件到 QQ 时, 只应使用 `/workspace` 里的内容, 并通过相对路径引用。这个发送规则当前先只对 QQ 收口, 不要求同时扩展到其他平台。
- **D-13:** `/workspace` 是模型侧正式工作语义; 真实宿主机路径和 `runtime_data` 目录结构属于 runtime 内部实现, 不需要升格成模型工具契约。
- **D-14:** `render` 属于工具驱动的 runtime 内部流程。模型提供的是待渲染内容, 不是"自己挑一个本地路径再发送"。
- **D-15:** 因为 `render` 不是模型手动选路径发送, 所以它不受"模型只能从 `/workspace` 里按相对路径发 QQ 本地文件"这条规则约束。
- **D-16:** Render 产物继续允许留在 runtime 内部 artifact 路径, 由系统自动发送; Phase 7 不因为 workspace 发送规则而强行把 render 产物塞回 Work World。

### Claude's Discretion
- Render 默认配置值的初始建议, 例如默认宽度和默认 `deviceScaleFactor`
- Render 参数在 WebUI 中的具体页面位置、表单文案和保存交互
- system prompt 中关于 `/workspace` 与 QQ 本地文件发送规则的具体措辞
- 真实 QQ 验收素材的具体组织方式, 例如单条长案例还是多条短案例

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MSG-08 | 文转图渲染 (Playwright render_markdown_to_image) | Playwright `browser.new_context(device_scale_factor=...)` API (官方 docs 已确认); HiDPI 戕图方案; 现有测试桩可复用 |
</phase_requirements>

## Standard Stack

### Core (Render Pipeline)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright ( 已在 Dockerfile | Headless Chromium 戁览染 | 项目 Dockerfile 预装 |
| markdown-it-py | 已在 pyproject.toml | Markdown -> HTML | 现有 render 依赖 |
| mdit-py-plugins | 已在 pyproject.toml | dollarmath plugin | LaTeX math 支持 |
| latex2mathml | 已在 pyproject.toml | LaTeX -> MathML | 公式渲染 |

### Supporting (Workspace / Config)

| Component | File | Purpose | When to Use |
|-----------|------|---------|-------------|
| `Config` | `src/acabot/config.py` | YAML 配置读写 | render 参数外置的配置接入点 |
| `RuntimeControlPlane` | `src/acabot/runtime/control/control_plane.py` | runtime 配置管理 | render config API 暴露 |
| `SystemView` | `webui/src/views/SystemView.vue` | 系统设置页 | render 配置 UI |
| `WorkWorldBuilder` | `src/acabot/runtime/computer/world.py` | `/workspace` 语义 | workspace boundary |
| `WorkspaceManager` | `src/acabot/runtime/computer/workspace.py` | 宿主机目录布局 | workspace path 分配 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `browser.new_context()` + context/page | `browser.new_page()` | 必须使用前者才能设置 `device_scale_factor`; 后者不支持该参数 |

**Installation:** 不需要新安装, 所有依赖已在项目中.

## Architecture Patterns

### Render Pipeline 当前架构

```
RenderService.render_markdown_to_image()
    -> PlaywrightRenderBackend.render_markdown_to_image()
        -> _build_document()           # markdown -> HTML
        -> _ensure_browser()          # lazy singleton browser
        -> browser.new_page()         # 创建 page (需要改!)
        -> page.set_viewport_size()   # 设置视口 (硬编码 960x540)
        -> page.set_content()         # 写入 HTML
        -> page.screenshot()          # full_page=True 截图
```

### 推荐改动: HiDPI Render 流程

```python
# 当前 (无法设置 device_scale_factor):
browser = await self._ensure_browser()
page = await browser.new_page()                  # 无 device_scale_factor
await page.set_viewport_size({"width": 960, "height": 540})

# 推荐改为:
browser = await self._ensure_browser()
context = await browser.new_context(
    viewport={"width": viewport_width, "height": 720},
    device_scale_factor=device_scale_factor,
)
page = await context.new_page()
# 不再需要 set_viewport_size (context 级别已设)
```

### Pattern: Render Config 外置到 Runtime Config

**What:** 把 `device_scale_factor` 和 `viewport_width` 从代码中的硬编码值变成可配置的全局默认值。
**When to use:** Phase 7 的 render 清晰度提升。
**Example:**
```python
# config.yaml 新增 render 配置
runtime:
  render:
    device_scale_factor: 2.0
    viewport_width: 960

# PlaywrightRenderBackend 构造函数接收 config
class PlaywrightRenderBackend:
    def __init__(self, *, device_scale_factor: float = 2.0, viewport_width: int = 960):
        self._device_scale_factor = device_scale_factor
        self._viewport_width = viewport_width
```

### Pattern: System Prompt Workspace 规则注入

**What:** 在 system prompt 中加入关于 `/workspace` 的明确指引。
**When to use:** 修改 `runtime_config/prompts/aca.md` (或对应 agent 的 prompt 文件).
**Example:**
```markdown
## 工作区规则

- 你的所有工作文件都在 `/workspace` 目录下。
- 需要发送 QQ 本地文件时, 使用相对路径引用 `/workspace` 中的内容。
- 不要使用 `tmp/` 或其他临时目录存放工作产物。
```

### Anti-Patterns to Avoid

- **在 `page` 级别设置 `device_scale_factor`:** Playwright API 中 `device_scale_factor` 只在 `browser.new_context()` 级别生效, `page` 层面无法设置。用 `browser.new_page()` 跳过了 context, 无法控制 DPI。
- **在 HTML/CSS 中通过 `transform: scale(2)` 模拟 HiDPI:** 这只会放大 CSS 布局而不增加像素密度, 截图仍然是 1x 的物理分辨率。正确做法是设置 `device_scale_factor`。
- **把 render 产物路径改到 `/workspace/attachments/`:** 这违反了 D-14/D-15/D-16 的设计决策。render 产物属于 runtime 内部 artifact, 不属于 Work World。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HiDPI 渲染 | CSS `transform: scale(2)` 或手动放大 | `browser.new_context(device_scale_factor=2)` | CSS 放大只改变布局不增加像素; `device_scale_factor` 让 Playwright 在截图时生成真正的 2x 物理像素 |
| 配置管理 | 在 backend 内部解析配置文件 | 传入 config 参数 / Config 对象 | 已有 `Config` 类和 `control_plane` 配置链路, 不要自己读文件 |
| WebUI render 设置 | 新建独立页面 | 在 SystemView 中新增一个 section | 系统设置页已有完整的配置编辑 UI 模式, 新增 section 符合现有交互模式 |

**Key insight:** Playwright 的 `device_scale_factor` 是浏览器层面的原生 HiDPI 支持, 不是 CSS hack。它让截图的物理像素数翻倍, 同时保持 CSS 布局不变。

## Common Pitfalls

### Pitfall 1: `browser.new_page()` 无法设置 device_scale_factor

**What goes wrong:** 在 `browser.new_page()` 上创建的 page 无法控制 `device_scale_factor`, 因为这个参数只在 `browser.new_context()` 级别生效。
**Why it happens:** Playwright 文档明确说明 `browser.new_page()` 是便捷 API, 生产代码应该用 `browser.new_context()` + `context.new_page()`。
**How to avoid:** 改为 `browser.new_context(device_scale_factor=...)` + `context.new_page()`。
**Warning signs:** 设置了 `device_scale_factor` 但截图分辨率没有变化。

### Pitfall 2: context 泄漏

**What goes wrong:** 每次调用 `browser.new_context()` 都会创建一个新的 BrowserContext, 如果不在 `finally` 中关闭 context, 会导致浏览器内存泄漏。
**Why it happens:** 当前代码用 `browser.new_page()` 会自动创建和销毁 context; 改用显式 context 管理后, 必须手动关闭 context。
**How to avoid:** 在 `finally` 块中同时关闭 page 和 context。
**Warning signs:** 多次 render 后 Chromium 内存使用持续增长。

### Pitfall 3: QQ 图片压缩导致模糊

**What goes wrong:** 即使 render 产出了高分辨率图片, QQ 客户端仍可能压缩图片导致模糊。
**Why it happens:** QQ 客户端对发送的图片有自动压缩, 这不在 AcaBot 控制范围内。
**How to avoid:** 精确来说无法完全避免。但提高初始分辨率可以减少压缩后的模糊程度。建议 `device_scale_factor` 设为 2 或 3。
**Warning signs:** 在 PC 上看起来清晰但在手机 QQ 上模糊。

### Pitfall 4: viewport_width 改变后 HTML 布局断裂

**What goes wrong:** `viewport_width` 从 960 改成其他值后, `HTML_TEMPLATE` 中 `.render-shell` 的 `width: 960px` 是硬编码的, 可能导致布局不一致。
**Why it happens:** CSS 固定宽度和 viewport 宽度是两个独立值。
**How to avoid:** 让 `.render-shell` 的宽度从 CSS 硬编码改为由 viewport_width 参数驱动, 或者直接去掉固定宽度让 viewport 决定布局宽度。
**Warning signs:** 改了 viewport_width 后截图出现裁切或多余空白。

### Pitfall 5: workspace 规则写进 prompt 后模型仍用 tmp/

**What goes wrong:** 即使 system prompt 写了"工作区在 /workspace", 模型仍然可能使用 `tmp/` 因为旧习惯或工具实现细节。
**Why it happens:** prompt 指引是软约束, 不是硬限制。模型可能忽略或误解。
**How to avoid:** prompt 措辞要非常明确具体。同时在 tool 的 description 中也可以再次提醒。但最终需要通过真实 UAT 确认。
**Warning signs:** 模型生成的代码或文件路径仍包含 `tmp/`。

### Pitfall 6: render 配置值设置过大

**What goes wrong:** `device_scale_factor` 设成 3 或 4 后, render 产物文件体积急剧增大, 导致发送变慢甚至超时。
**Why it happens:** 物理像素数是平方增长的 (2x = 4 倍像素, 3x = 9 倍像素).
**How to avoid:** 默认值建议用 2, 最大不超过 3。WebUI 配置中加范围提示。
**Warning signs:** render 产物 PNG 超过 5MB, QQ 发送超时。

## Code Examples

### Playwright HiDPI Render (推荐模式)

```python
# Source: Playwright official docs - browser.new_context()
# 在 PlaywrightRenderBackend.render_markdown_to_image() 中

async def render_markdown_to_image(self, request: RenderRequest) -> RenderResult:
    document_html = self._build_document(request.source_markdown)
    request.artifacts.html_path.write_text(document_html, encoding="utf-8")
    page = None
    context = None
    try:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            viewport={"width": self._viewport_width, "height": 720},
            device_scale_factor=self._device_scale_factor,
        )
        page = await context.new_page()
        await page.set_content(document_html, wait_until="load")
        await page.screenshot(
            path=str(request.artifacts.image_path),
            full_page=True,
            type="png",
        )
        return RenderResult.ok(
            backend_name=self.name,
            artifact_path=request.artifacts.image_path,
            html=document_html,
            metadata={
                "html_path": str(request.artifacts.html_path),
                "device_scale_factor": self._device_scale_factor,
                "viewport_width": self._viewport_width,
            },
        )
    except Exception as exc:
        return RenderResult.error_result(
            backend_name=self.name,
            artifact_path=request.artifacts.image_path,
            html=document_html,
            error=str(exc),
            metadata={"html_path": str(request.artifacts.html_path)},
        )
    finally:
            await page.close()
        if context is not None:
            await context.close()
```

### Config 接入 render 参数

```python
# Source: 已有 bootstrap 模式
# src/acabot/runtime/bootstrap/__init__.py 中

# config.yaml 中:
# runtime:
#   render:
#     device_scale_factor: 2.0
#     viewport_width: 960

# bootstrap 读取:
render_config = config.get("runtime", {}).get("render", {})
runtime_playwright_render_backend = PlaywrightRenderBackend(
    device_scale_factor=float(render_config.get("device_scale_factor", 2.0)),
    viewport_width=int(render_config.get("viewport_width", 960)),
)
```

### System Prompt Workspace 规则 (建议措辞)

```markdown
## 工作区

- 你的所有工作文件都在 `/workspace` 目录下。使用 `computer_read`、`computer_write` 工具操作文件时, 路径以 `/workspace/` 开头。
- 如需发送 `/workspace` 中的文件到 QQ, 使用相对路径。例如: `/workspace/screenshot.png` 在发送时引用为 `screenshot.png`。
- 不要使用系统临时目录 (如 `/tmp/`) 存放工作产物。
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `browser.new_page()` | `browser.new_context()` + `context.new_page()` | Playwright 始终支持 | 生产代码推荐显式 context 管理, 可以设置 device_scale_factor |
| 硬编码 viewport | 可配置 viewport | Phase 7 改进 | render 参数可调, 不需改代码 |
| 1x 截图 | HiDPI (2x-3x) 截图 | Phase 7 改进 | QQ 客户端可读性提升 |

**Deprecated/outdated:**
- `browser.new_page()` 用于生产 render: Playwright 文档明确说明这只是便捷 API, 生产代码应使用显式 context 管理。

## Open Questions

1. **QQ 客户端压缩阈值**
   - What we know: QQ 对发送图片有自动压缩, 但具体压缩算法和阈值不公开。
   - What's unclear: 多大的初始分辨率能在 QQ 压缩后保持可读。
   - Recommendation: 使用 `device_scale_factor=2` 作为初始默认值, 通过真实 QQ 验收确认是否需要提高到 3。

2. **render 配置热更新机制**
   - What we know: 当前其他 runtime 配置 (model、session、plugin) 支持热更新。
   - What's unclear: render 参数修改后是否需要重启 Playwright browser 才能生效。
   - Recommendation: `device_scale_factor` 和 `viewport_width` 影响的是每次 render 时创建的新 context, 所以改配置后下一个 render 自动生效, 不需要重启 browser。这是比其他配置更轻量的热更新。

3. **出站文件发布层**
   - What we know: `docs/2026-04-04-outbound-file-publish-layer.md` 已经有完整设计。
   - What's unclear: 这份设计是否在 Phase 7 scope 内, 还是后续才做。
   - Recommendation: 根据 D-12 和 D-15 的决策, render 产物继续留在 `runtime_data/render_artifacts/`, 出站发布层的设计可以后续再落地。但 workspace 文件发送到 QQ 的场景 (非 render) 确实需要出站发布层。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest >= 8.0 + pytest-asyncio >= 0.23 |
| Config file | pyproject.toml (`[tool.pytest.ini_options]`) |
| Quick run command | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` |
| Full suite command | `python -m pytest tests/ -x --ignore=tests/runtime/backend/test_pi_adapter.py` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MSG-08 | Playwright render produces HiDPI image | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | Yes (需扩展) |
| MSG-08 | device_scale_factor 可配置 | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | No (Wave 0) |
| MSG-08 | viewport_width 可配置 | unit | `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py` | No (Wave 0) |
| MSG-08 | 真实 QQ 客户端可读性 | manual-only | N/A | N/A |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/runtime/test_render_service.py -x --ignore=tests/runtime/backend/test_pi_adapter.py`
- **Per wave merge:** `python -m pytest tests/ -x --ignore=tests/runtime/backend/test_pi_adapter.py`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/runtime/test_render_service.py` -- 需新增: device_scale_factor 传参测试、viewport_width 传参测试、context 正确关闭测试
- [ ] WebUI render 配置 API 测试 (如果添加了新 API 端点)

## Sources

### Primary (HIGH confidence)
- [Playwright Python API - browser.new_context()](https://playwright.dev/python/docs/api/class-browser#browser-new-context) - `device_scale_factor`, `viewport` 参数文档
- [Playwright Emulation docs](https://playwright.dev/python/docs/emulation) - device scale factor 使用说明
- [Playwright Screenshots docs](https://playwright.dev/python/docs/screenshots) - 截图 API

### Secondary (MEDIUM confidence)
- `src/acabot/runtime/render/playwright_backend.py` - 当前实现, 已直接阅读确认
- `src/acabot/runtime/outbox.py` - render 物化流程, 已直接阅读确认
- `src/acabot/runtime/computer/world.py` - `/workspace` 语义, 已直接阅读确认
- `docs/2026-04-04-outbound-file-publish-layer.md` - 出站文件发布层设计

### Tertiary (LOW confidence)
- QQ 客户端图片压缩行为 - 未经验证的社区观察, 需要通过真实 UAT 确认

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - 所有库和 API 直接从源码和官方文档确认
- Architecture: HIGH - 现有代码已直接阅读, 改动方案明确
- Pitfalls: MEDIUM - Playwright 陷阱从官方文档确认, QQ 行为需 UAT 验证

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (render/workspace 语义稳定, 不太可能快速变化)
