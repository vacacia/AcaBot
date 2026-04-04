# Phase 7 Render Readability + Workspace Boundary Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 render 清晰度成为可配置、可在 WebUI 调整、可通过真实 QQ 客户端验收的正式能力，同时把 `/workspace` 系统提醒、QQ 本地文件发送规则、render artifact 例外边界收成一致契约。

**Architecture:** render 默认值收口到 `runtime.render` 全局配置，经 bootstrap 注入 `PlaywrightRenderBackend`，并通过 control plane / HTTP API / SystemView 暴露为可编辑的系统设置。`/workspace` 规则通过 `ContextAssembler` 注入稳定 system reminder；QQ 本地文件发送规则只放在 `message` 工具说明和校验里，工具把相对路径重写成 runtime 内部使用的 `/workspace/...` world path；render 继续走 runtime 内部 artifact 主线。

**Tech Stack:** Python 3.11, pytest + pytest-asyncio, Vue 3 + TypeScript + Vite, Playwright

---

## File Structure

### Read first
- `docs/superpowers/specs/2026-04-04-phase-7-render-workspace-boundary-design.md` — 本次已确认 spec，优先级最高
- `.planning/phases/07-render-readability-workspace-boundary/07-CONTEXT.md` — phase scope 与决策真源
- `docs/2026-04-04-outbound-file-publish-layer.md` — `/workspace` 文件发送与 runtime 发布边界背景

> 注意：`.planning/phases/07-render-readability-workspace-boundary/07-01-PLAN.md` / `07-02-PLAN.md` 是更早的草案。若与已确认 spec 冲突，以 `docs/superpowers/specs/2026-04-04-phase-7-render-workspace-boundary-design.md` 为准。

### Files to modify
- `src/acabot/runtime/render/playwright_backend.py` — render 宽度 / device scale factor 的最终消费点
- `src/acabot/runtime/bootstrap/__init__.py` — 从 config 读取 render 默认值并注入 backend
- `src/acabot/runtime/control/config_control_plane.py` — render 配置读写、保存、热应用
- `src/acabot/runtime/control/control_plane.py` — 暴露 render 配置读写接口与 system snapshot
- `src/acabot/runtime/control/http_api.py` — 新增 render 配置 API
- `src/acabot/runtime/context_assembly/assembler.py` — 注入“所有工作都在 `/workspace` 完成”的稳定 system reminder
- `src/acabot/runtime/builtin_tools/message.py` — QQ 本地文件发送说明与相对路径校验/归一化
- `webui/src/views/SystemView.vue` — render 默认值编辑入口
- `webui/src/lib/api.ts` — render 配置接口缓存失效规则
- `config.example.yaml` — render 配置示例
- `docs/07-gateway-and-channel-layer.md` — render artifact 与手动本地文件发送边界
- `docs/08-webui-and-control-plane.md` — WebUI / API 新入口
- `docs/09-config-and-runtime-files.md` — `runtime.render` 配置说明
- `docs/12-computer.md` — `/workspace` 模型语义与 render artifact 例外

### Files to create
- `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-FIXTURE.md` — 8 类内容的固定验收素材
- `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md` — 真实 QQ 客户端验收记录

### Tests to modify
- `tests/runtime/test_render_service.py` — render 参数注入与截图上下文行为
- `tests/runtime/test_bootstrap.py` — fresh runtime start 是否从持久化 config 读回 render 默认值
- `tests/runtime/test_webui_api.py` — render 配置 API、system page 视图、system page 渲染 smoke test
- `tests/runtime/test_context_assembler.py` — `/workspace` system reminder
- `tests/runtime/test_builtin_tools.py` — message 工具的 QQ 本地文件规则
- `tests/runtime/test_outbox.py` — render 继续走 runtime 内部 artifact 路径，不受 workspace 本地文件规则影响

---

### Task 1: Render runtime 默认值收口到配置与 backend

**Files:**
- Modify: `tests/runtime/test_render_service.py`
- Modify: `tests/runtime/test_bootstrap.py`
- Modify: `src/acabot/runtime/render/playwright_backend.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`
- Modify: `config.example.yaml`

- [ ] **Step 1: 先写 render 参数注入的失败测试**

在 `tests/runtime/test_render_service.py` 增加两个测试，并在 `tests/runtime/test_bootstrap.py` 增加一个 fresh-start 配置读取测试：

```python
@pytest.mark.asyncio
async def test_playwright_backend_uses_configured_viewport_and_device_scale_factor(tmp_path: Path) -> None:
    fake_browser = FakeBrowser()

    async def start_playwright() -> FakePlaywright:
        return FakePlaywright(fake_browser)

    backend = PlaywrightRenderBackend(
        start_playwright=start_playwright,
        viewport_width=1280,
        device_scale_factor=2.0,
    )
    service = RenderService(runtime_root=tmp_path / "runtime_data")
    service.register_backend(backend.name, backend)

    result = await service.render_markdown_to_image(
        markdown_text="# Title",
        conversation_id="qq:user:10001",
        run_id="run:render-config",
    )

    context = fake_browser.contexts[0]
    assert result.status == "ok"
    assert context.options["viewport"] == {"width": 1280, "height": 720}
    assert context.options["device_scale_factor"] == 2.0


def test_playwright_html_template_does_not_hardcode_960px_width() -> None:
    assert "width: 960px;" not in HTML_TEMPLATE
```

再在 `tests/runtime/test_bootstrap.py` 增加：

```python
async def test_build_runtime_components_reads_render_defaults_from_config(tmp_path: Path) -> None:
    config = Config(
        {
            "agent": {"system_prompt": "You are Aca."},
            "runtime": {
                "render": {"width": 1280, "device_scale_factor": 2.5},
                "runtime_root": str(tmp_path / "runtime_data"),
            },
        }
    )

    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend = components.render_service.get_backend("playwright")

    assert backend is not None
    assert getattr(backend, "_viewport_width") == 1280
    assert getattr(backend, "_device_scale_factor") == 2.5
```

并补齐 fake browser / fake context 桩：

```python
class FakeContext:
    def __init__(self, options: dict[str, object]) -> None:
        self.options = dict(options)
        self.pages: list[FakePage] = []
        self.closed = 0

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed += 1
```

- [ ] **Step 2: 跑 render 定向测试，确认先失败**

Run:
```bash
uv run pytest tests/runtime/test_render_service.py tests/runtime/test_bootstrap.py -q -k "render or build_runtime_components_reads_render_defaults"
```

Expected:
- FAIL，报 `PlaywrightRenderBackend.__init__()` 不接受新参数，或 fake browser 没有 `new_context()`，或模板仍然硬编码 `960px`，或 bootstrap 还没有把持久化 config 注入 backend

- [ ] **Step 3: 只实现最小 render backend 变更**

在 `src/acabot/runtime/render/playwright_backend.py` 做最小改动：

```python
class PlaywrightRenderBackend:
    def __init__(
        self,
        *,
        start_playwright: StartPlaywright | None = None,
        viewport_width: int = 960,
        device_scale_factor: float = 2.0,
    ) -> None:
        self._start_playwright = start_playwright or _default_start_playwright
        self._viewport_width = max(320, int(viewport_width))
        self._device_scale_factor = max(1.0, float(device_scale_factor))
        ...

    def update_render_defaults(self, *, viewport_width: int, device_scale_factor: float) -> None:
        self._viewport_width = max(320, int(viewport_width))
        self._device_scale_factor = max(1.0, float(device_scale_factor))

    async def render_markdown_to_image(self, request: RenderRequest) -> RenderResult:
        ...
        context = await browser.new_context(
            viewport={"width": self._viewport_width, "height": 720},
            device_scale_factor=self._device_scale_factor,
        )
        page = await context.new_page()
        ...
```

同时把模板里的固定宽度改成依赖 viewport 的布局，例如：

```css
.render-shell {
  box-sizing: border-box;
  width: 100%;
  padding: 40px;
}
```

- [ ] **Step 4: 从 bootstrap 读取 `runtime.render` 默认值并注入 backend**

在 `src/acabot/runtime/bootstrap/__init__.py` 增加读取逻辑：

```python
runtime_conf = config.get("runtime", {}) or {}
render_conf = dict(runtime_conf.get("render", {}) or {})
viewport_width = int(render_conf.get("width", 960) or 960)
device_scale_factor = float(render_conf.get("device_scale_factor", 2.0) or 2.0)

runtime_playwright_render_backend = PlaywrightRenderBackend(
    viewport_width=viewport_width,
    device_scale_factor=device_scale_factor,
)
```

- [ ] **Step 5: 给 `config.example.yaml` 加最小 render 配置示例**

在 `runtime:` 下新增：

```yaml
  render:
    width: 960
    device_scale_factor: 2.0
```

- [ ] **Step 6: 回跑 render 测试确认通过**

Run:
```bash
uv run pytest tests/runtime/test_render_service.py tests/runtime/test_bootstrap.py -q -k "render or build_runtime_components_reads_render_defaults"
```

Expected:
- PASS，新的 viewport / device scale factor 测试通过
- PASS，fresh runtime start 会从持久化 config 读回 render 默认值
- 旧 render pipeline 测试仍通过

- [ ] **Step 7: 提交这一小段**

```bash
git add tests/runtime/test_render_service.py tests/runtime/test_bootstrap.py src/acabot/runtime/render/playwright_backend.py src/acabot/runtime/bootstrap/__init__.py config.example.yaml
git commit -m "feat(render): externalize render defaults"
```

---

### Task 2: 暴露 render 配置 API，并在保存后热应用到现有 backend

**Files:**
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `src/acabot/runtime/control/config_control_plane.py`
- Modify: `src/acabot/runtime/control/control_plane.py`
- Modify: `src/acabot/runtime/control/http_api.py`
- Modify: `src/acabot/runtime/bootstrap/__init__.py`

- [ ] **Step 1: 先写 render 配置 API 的失败测试**

在 `tests/runtime/test_webui_api.py` 增加两个测试：一个验证 API + snapshot，另一个显式验证“保存后热应用到当前 QQ / OneBot 主 runtime backend”；再补一个热应用失败分支测试。

```python
async def test_runtime_http_api_server_serves_and_updates_render_config(tmp_path: Path) -> None:
    ...
    assert initial["data"]["width"] == 960
    assert updated["data"]["width"] == 1280
    assert updated["data"]["device_scale_factor"] == 2.5
    assert updated["data"]["apply_status"] == "applied"
    assert system_snapshot["data"]["render"]["width"] == 1280


async def test_render_config_put_hot_applies_to_existing_playwright_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend = components.render_service.get_backend("playwright")
    assert backend is not None

    result = await components.control_plane.upsert_render_config(
        {"width": 1280, "device_scale_factor": 2.5}
    )

    assert result["apply_status"] == "applied"
    assert getattr(backend, "_viewport_width") == 1280
    assert getattr(backend, "_device_scale_factor") == 2.5


async def test_render_config_put_reports_apply_failed_when_hot_apply_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, webui_enabled=True, port=0)
    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    backend = components.render_service.get_backend("playwright")
    assert backend is not None

    def _explode(*, viewport_width: int, device_scale_factor: float) -> None:
        raise RuntimeError("render hot apply exploded")

    monkeypatch.setattr(backend, "update_render_defaults", _explode)

    result = await components.control_plane.upsert_render_config(
        {"width": 1280, "device_scale_factor": 2.5}
    )

    assert result["apply_status"] == "apply_failed"
    assert result["restart_required"] is True
    assert "render hot apply exploded" in result["technical_detail"]
```

- [ ] **Step 2: 跑 WebUI API 定向测试，确认新路由还不存在**

Run:
```bash
uv run pytest tests/runtime/test_webui_api.py -q -k "render_config"
```

Expected:
- FAIL，报 `/api/render/config` 404、snapshot 缺少 `render`，或 control plane 还没有 hot-apply / apply_failed 行为

- [ ] **Step 3: 在 config control plane 中实现 render 配置读写与热应用**

在 `src/acabot/runtime/control/config_control_plane.py` 增加：

```python
def get_render_config(self) -> dict[str, Any]:
    runtime_conf = dict(self.config.get("runtime", {}) or {})
    render_conf = dict(runtime_conf.get("render", {}) or {})
    return {
        "width": max(320, int(render_conf.get("width", 960) or 960)),
        "device_scale_factor": max(1.0, float(render_conf.get("device_scale_factor", 2.0) or 2.0)),
    }

async def upsert_render_config(self, payload: dict[str, Any]) -> dict[str, Any]:
    current = self.get_render_config()
    next_conf = {
        "width": max(320, int(payload.get("width", current["width"]) or current["width"])),
        "device_scale_factor": max(1.0, float(payload.get("device_scale_factor", current["device_scale_factor"]) or current["device_scale_factor"])),
    }
    data = self.config.to_dict()
    runtime_conf = dict(data.get("runtime", {}) or {})
    runtime_conf["render"] = next_conf
    data["runtime"] = runtime_conf
    self.config.replace(data)
    self.config.save()
    backend = self.render_service.get_backend("playwright") if self.render_service is not None else None
    update_defaults = getattr(backend, "update_render_defaults", None)
    if not callable(update_defaults):
        return self.with_apply_result(
            self.get_render_config(),
            apply_status="apply_failed",
            restart_required=True,
            message="已保存，但热应用失败，需要重启",
            technical_detail="playwright render backend does not support hot apply",
        )
    try:
        update_defaults(viewport_width=next_conf["width"], device_scale_factor=next_conf["device_scale_factor"])
    except Exception as exc:
        return self.with_apply_result(
            self.get_render_config(),
            apply_status="apply_failed",
            restart_required=True,
            message="已保存，但热应用失败，需要重启",
            technical_detail=str(exc),
        )
    return self.with_apply_result(self.get_render_config(), apply_status="applied", restart_required=False, message="已保存并已生效")
```

为此需要给 `RuntimeConfigControlPlane.__init__` 增加 `render_service` 参数，并在 bootstrap 传入 `runtime_render_service`。

- [ ] **Step 4: 把 render 配置接到 control plane / HTTP API / system snapshot**

在 `src/acabot/runtime/control/control_plane.py` 增加：

```python
async def get_render_config(self) -> dict[str, object]: ...
async def upsert_render_config(self, payload: dict[str, object]) -> dict[str, object]: ...
```

在 `get_system_configuration_view()` 里新增：

```python
"render": await self.get_render_config(),
```

在 `src/acabot/runtime/control/http_api.py` 新增：

```python
if segments == ["render", "config"] and method == "GET":
    return self._ok(self._await(self.control_plane.get_render_config()))
if segments == ["render", "config"] and method == "PUT":
    return self._ok(self._await(self.control_plane.upsert_render_config(payload)))
```

- [ ] **Step 5: 回跑 API 定向测试确认通过**

Run:
```bash
uv run pytest tests/runtime/test_webui_api.py -q -k "render_config or system_configuration or hot_apply"
```

Expected:
- PASS，`/api/render/config` 可读可写
- PASS，`system/configuration` 快照带 `render` 字段
- PASS，PUT 后现有 playwright backend 默认值立即变化
- PASS，热应用异常时返回 `apply_failed` + `restart_required=True`，而不是伪装成已生效

- [ ] **Step 6: 提交这一小段**

```bash
git add tests/runtime/test_webui_api.py src/acabot/runtime/control/config_control_plane.py src/acabot/runtime/control/control_plane.py src/acabot/runtime/control/http_api.py src/acabot/runtime/bootstrap/__init__.py
git commit -m "feat(control-plane): add render config api"
```

---

### Task 3: 在 SystemView 中提供 render 默认值编辑入口

**Files:**
- Modify: `tests/runtime/test_webui_api.py`
- Modify: `webui/src/views/SystemView.vue`
- Modify: `webui/src/lib/api.ts`

- [ ] **Step 1: 先写 system view 的静态断言和页面 smoke test**

在 `tests/runtime/test_webui_api.py` 的前端源码断言里补充：

```python
def test_webui_real_pages_system_view_includes_render_settings_entrypoint() -> None:
    system_view_source = Path("webui/src/views/SystemView.vue").read_text(encoding="utf-8")
    assert "Render 默认配置" in system_view_source
    assert "/api/render/config" in system_view_source
    assert "device_scale_factor" in system_view_source
    assert "width" in system_view_source
```

并在现有 `test_system_page_renders_when_filesystem_configured_dirs_are_null` 风格上增加一个 smoke test，确认 `/system` 页面能看到 “Render 默认配置”。

- [ ] **Step 2: 跑前端相关测试，确认页面还没有这个入口**

Run:
```bash
uv run pytest tests/runtime/test_webui_api.py -q -k "system_view_includes_render or system_page_renders"
```

Expected:
- FAIL，SystemView 源码里还没有 render 配置 UI

- [ ] **Step 3: 在 `SystemView.vue` 增加 render 表单与保存逻辑**

在 `webui/src/views/SystemView.vue` 增加类型：

```ts
type RenderConfig = {
  width: number
  device_scale_factor: number
}

type SystemConfigurationSnapshot = {
  ...
  render: RenderConfig
}

type SystemDraft = {
  ...
  render: RenderConfig
}
```

增加保存函数：

```ts
async function saveRender(): Promise<void> {
  if (!draft.value) {
    return
  }
  activeAction.value = "render"
  feedback.value = null
  try {
    const saved = await apiPut<RenderConfig & ApplyResult>("/api/render/config", {
      width: draft.value.render.width,
      device_scale_factor: draft.value.render.device_scale_factor,
    })
    setApplyFeedback("Render 默认配置", saved)
    await refreshAfterMutation()
  } catch (error) {
    setFeedback("is-error", "Render 默认配置保存失败。", normalizeErrorMessage(error))
  } finally {
    activeAction.value = ""
  }
}
```

在模板中新增一个 panel，至少包含：
- Render 宽度输入框
- Device scale factor 输入框
- “保存并尝试生效”按钮
- 简短 helper：最终是否清晰以真实 QQ 客户端为准

- [ ] **Step 4: 在 `api.ts` 加 render 接口缓存失效规则**

补充：

```ts
if (path.startsWith("/api/render/config")) {
  return ["/api/render/config", "/api/system/configuration"]
}
```

- [ ] **Step 5: 跑 WebUI 测试和 build**

Run:
```bash
uv run pytest tests/runtime/test_webui_api.py -q -k "system_view_includes_render or system_page_renders"
cd webui && npm run build
```

Expected:
- PASS，系统页源码断言和页面 smoke test 通过
- PASS，Vite build 成功

- [ ] **Step 6: 提交这一小段**

```bash
git add tests/runtime/test_webui_api.py webui/src/views/SystemView.vue webui/src/lib/api.ts
git commit -m "feat(webui): expose render defaults in system view"
```

---

### Task 4: 收口 `/workspace` system reminder 与 message 工具本地文件契约

**Files:**
- Modify: `tests/runtime/test_context_assembler.py`
- Modify: `tests/runtime/test_builtin_tools.py`
- Modify: `tests/runtime/test_outbox.py`
- Modify: `src/acabot/runtime/context_assembly/assembler.py`
- Modify: `src/acabot/runtime/builtin_tools/message.py`

- [ ] **Step 1: 先写 `/workspace` system reminder 的失败测试**

在 `tests/runtime/test_context_assembler.py` 增加：

```python
def test_context_assembler_always_adds_workspace_system_reminder() -> None:
    assembler = ContextAssembler()
    ctx = _assembler_ctx(
        retrieval_plan=RetrievalPlan(retained_history=[]),
        message_projection=MessageProjection(history_text="hello", model_content="hello"),
    )

    assembled = assembler.assemble(ctx, base_prompt="base", tool_runtime=ToolRuntime())

    assert "所有工作都在 /workspace 中完成" in assembled.system_prompt
    assert "QQ 本地文件" not in assembled.system_prompt
```

- [ ] **Step 2: 先写 message 工具路径规则的失败测试**

在 `tests/runtime/test_builtin_tools.py` 增加三个测试。注意：当前 unified `message` tool 的发送目标与 `at_user` 语义都已经收口在 QQ，因此这里的本地文件规则也是 **QQ local-file send** 规则；当前 schema 里，只有 `images` 是“模型主动发送本地文件”的输入面，所以本期规则只在 `images` 上落实现与测试。如果未来 schema 新增其他本地文件字段，应在 QQ 发送分支下复用同一套相对路径规则，而不是默认推广到所有平台。

```python
async def test_message_tool_rewrites_relative_local_file_paths_into_workspace_world_paths() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    result = await broker.execute(
        tool_name="message",
        arguments={"action": "send", "images": ["reports/out.png"]},
        ctx=ctx,
    )

    plan = result.user_actions[0]
    assert plan.action.payload["images"] == ["/workspace/reports/out.png"]


async def test_message_tool_rejects_absolute_local_file_paths_for_qq_send() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    with pytest.raises(ValueError, match="relative path"):
        await broker.execute(
            tool_name="message",
            arguments={"action": "send", "images": ["/tmp/out.png"]},
            ctx=ctx,
        )


async def test_message_tool_rejects_parent_traversal_local_file_paths_for_qq_send() -> None:
    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    surface.register(broker)
    ctx = _tool_execution_context(enabled_tools=["message"])

    with pytest.raises(ValueError, match="relative path|safe relative path"):
        await broker.execute(
            tool_name="message",
            arguments={"action": "send", "images": ["../secret/out.png"]},
            ctx=ctx,
        )

    with pytest.raises(ValueError, match="relative path|safe relative path"):
        await broker.execute(
            tool_name="message",
            arguments={"action": "send", "images": ["./../secret/out.png"]},
            ctx=ctx,
        )
```

- [ ] **Step 3: 跑这两组定向测试，确认先失败**

Run:
```bash
uv run pytest tests/runtime/test_context_assembler.py tests/runtime/test_builtin_tools.py -q -k "workspace or message_tool"
```

Expected:
- FAIL，assembler 还没有稳定的 `/workspace` reminder
- FAIL，message 工具还接受绝对路径或 `../` 越界路径

- [ ] **Step 4: 在 assembler 里增加稳定 workspace reminder**

在 `src/acabot/runtime/context_assembly/assembler.py` 增加一个 system contribution builder，只写用户确认过的那一句核心规则，并把它视为稳定合同、默认每轮都注入：

```python
SYSTEM_PROMPT_PRIORITY = {
    "base_prompt": 1000,
    "workspace_reminder": 950,
    "skill_reminder": 900,
    "subagent_reminder": 850,
}


def _build_workspace_reminder_contribution(self) -> list[ContextContribution]:
    return [
        ContextContribution(
            source_kind="workspace_reminder",
            target_slot="system_prompt",
            priority=self.SYSTEM_PROMPT_PRIORITY["workspace_reminder"],
            role="system",
            content="所有工作都在 /workspace 中完成。",
        )
    ]
```

并在 `_collect_contributions()` 中把它插到 skill/subagent reminder 之前。不要把它做成依赖某个 runtime 条件的可选提醒，否则会让合同在部分 run 中消失。

- [ ] **Step 5: 在 message 工具里增加说明与本地路径归一化 / 拒绝逻辑**

更新 `src/acabot/runtime/builtin_tools/message.py`：

1. 把 `images` 参数说明改成：

```python
"description": (
    "Optional remote URLs, inline data URLs, or QQ local file refs for action=send. "
    "QQ local files must be given as relative paths under the workspace. "
    "The tool rewrites those relative paths to internal /workspace/... refs before delivery. "
    "If you want to send a file from another visible path, copy or move it into the workspace first."
)
```

2. 新增本地文件归一化 helper：

```python
from pathlib import PurePosixPath

_REMOTE_PREFIXES = ("http://", "https://", "data:", "base64://")

@classmethod
def _normalize_images(cls, value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("images must be a list of strings")
    return [cls._normalize_send_image_ref(str(item or "").strip()) for item in value if str(item or "").strip()]

@classmethod
def _normalize_send_image_ref(cls, file_ref: str) -> str:
    if file_ref.startswith(_REMOTE_PREFIXES):
        return file_ref
    raw = str(file_ref or "").strip()
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError("QQ local file sends require a relative path under /workspace")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("QQ local file sends require a safe relative path under /workspace")
    normalized = PurePosixPath(*parts).as_posix()
    return f"/workspace/{normalized}"
```

这里不要使用 `lstrip("./")` 这类会吞掉前缀的写法，否则像 `./../secret.png` 这种越界路径会被错误洗成合法路径。

3. `render` 字段说明里补一句：render 是 runtime 内部流程，不走本地路径选择。

4. 在 `tests/runtime/test_outbox.py` 补一个显式锁边界测试，确保 render 仍然走 runtime 内部 artifact 路径，而不是被 message 工具本地文件规则改写到 `/workspace/...`：

```python
async def test_outbox_render_artifact_path_remains_runtime_internal(tmp_path: Path) -> None:
    gateway = FakeGateway()
    store = FakeMessageStore()
    artifact_path = tmp_path / "runtime_data" / "render.png"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    render_service = FakeRenderService(
        RenderResult.ok(
            backend_name="playwright",
            artifact_path=artifact_path,
            html="<p>rendered</p>",
        )
    )
    outbox = Outbox(gateway=gateway, store=store, render_service=render_service)
    ctx = _send_intent_context(render="# Title")

    report = await outbox.dispatch(ctx)

    sent_action = gateway.sent[0]
    assert report.has_failures is False
    assert sent_action.payload["segments"] == [{"type": "image", "data": {"file": str(artifact_path)}}]
    assert str(artifact_path).startswith(str(tmp_path / "runtime_data"))
    assert not str(artifact_path).startswith("/workspace/")
```

- [ ] **Step 6: 回跑定向测试确认通过**

Run:
```bash
uv run pytest tests/runtime/test_context_assembler.py tests/runtime/test_builtin_tools.py tests/runtime/test_outbox.py -q -k "workspace or message_tool or render_artifact_path_remains_runtime_internal"
```

Expected:
- PASS，system prompt 只新增 `/workspace` 工作提醒，不提 QQ 细则
- PASS，message 工具接受相对路径并重写到 `/workspace/...`
- PASS，message 工具拒绝绝对本地路径和 `../` 越界路径
- PASS，render 继续输出 runtime 内部 artifact 路径，不被重写到 `/workspace/...`

- [ ] **Step 7: 提交这一小段**

```bash
git add tests/runtime/test_context_assembler.py tests/runtime/test_builtin_tools.py tests/runtime/test_outbox.py src/acabot/runtime/context_assembly/assembler.py src/acabot/runtime/builtin_tools/message.py
git commit -m "feat(message): enforce workspace local file contract"
```

---

### Task 5: 同步文档并落真实 QQ 验收 artifacts

**Files:**
- Modify: `docs/07-gateway-and-channel-layer.md`
- Modify: `docs/08-webui-and-control-plane.md`
- Modify: `docs/09-config-and-runtime-files.md`
- Modify: `docs/12-computer.md`
- Create: `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-FIXTURE.md`
- Create: `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md`

- [ ] **Step 1: 先写固定验收素材文件**

创建 `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-FIXTURE.md`，内容必须同时覆盖 8 类项目：

```md
# Render 可读性验收素材

# 一级标题

这是一段普通正文，用来确认 QQ 客户端里的常规中文文本是否清晰可读。

- 列表项一
- 列表项二
- 列表项三

行内公式：$E = mc^2$

$$
\int_0^1 x^2 dx = \frac{1}{3}
$$

```python
for i in range(3):
    print(i)
```

> 这是一段引用块，用来确认引用文字边界和底色是否仍然可读。

| 列 1 | 列 2 | 列 3 |
| --- | --- | --- |
| A | B | C |
| 1 | 2 | 3 |
```

- [ ] **Step 2: 更新 4 份正式文档**

文档改动目标：

- `docs/07-gateway-and-channel-layer.md`
  - 明确 render artifact 是 runtime 内部发送路径
  - 明确它不属于“模型手动选本地文件发 QQ”
- `docs/08-webui-and-control-plane.md`
  - 记录 SystemView 新增 render 默认配置入口
  - 记录 `/api/render/config` 的 GET / PUT
- `docs/09-config-and-runtime-files.md`
  - 记录 `runtime.render.width`
  - 记录 `runtime.render.device_scale_factor`
- `docs/12-computer.md`
  - 明确 `/workspace` 是模型侧语义
  - 明确 host shell 看到真实路径不在本期处理
  - 明确 render artifact 仍落在 `runtime_data/render_artifacts/`

- [ ] **Step 3: 跑回归测试和前端 build**

Run:
```bash
uv run pytest tests/runtime/test_render_service.py tests/runtime/test_webui_api.py tests/runtime/test_context_assembler.py tests/runtime/test_builtin_tools.py tests/runtime/test_outbox.py -q
cd webui && npm run build
```

Expected:
- PASS，所有本期新增测试通过
- PASS，WebUI build 成功

- [ ] **Step 4: 用真实 QQ 客户端做人工验收**

手工步骤：
1. 在 WebUI 的系统页把 render 默认值调到待验收值
2. 使用固定素材通过正式 `message.send.render` 链路发送到真实 QQ 会话
3. 在真实 QQ 客户端逐项确认以下 8 类内容可读：
   - 标题
   - 普通段落
   - 列表
   - 行内公式
   - 块公式
   - 代码块
   - 引用块
   - 表格
4. 如不可读，只调整 `width` / `device_scale_factor`，重新发送，直到通过

- [ ] **Step 5: 写正式验收记录**

创建 `.planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md`，格式至少包含：

```md
# Phase 7 Render 可读性真实 QQ 验收记录

- 验收日期：2026-04-04
- 验收时间：
- 客户端 / 环境：
- render width：
- render device_scale_factor：

## 可读性检查
- [ ] 标题
- [ ] 普通段落
- [ ] 列表
- [ ] 行内公式
- [ ] 块公式
- [ ] 代码块
- [ ] 引用块
- [ ] 表格

## 证据
- 截图：
- 备注：

## 结论
- [ ] 通过
- [ ] 不通过
```

如果有截图，把文件放在同目录下并在记录里引用相对路径。

- [ ] **Step 6: 提交文档与 artifacts**

```bash
git add docs/07-gateway-and-channel-layer.md docs/08-webui-and-control-plane.md docs/09-config-and-runtime-files.md docs/12-computer.md .planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-FIXTURE.md .planning/phases/07-render-readability-workspace-boundary/07-QQ-READABILITY-ACCEPTANCE.md
git commit -m "docs(07): close phase 7 contract and acceptance artifacts"
```

---

## Final Verification

- [ ] **Step 1: 跑本期完整 Python 回归**

```bash
uv run pytest
```

Expected:
- PASS，全量 Python 测试通过

- [ ] **Step 2: 跑前端 build**

```bash
cd webui && npm run build
```

Expected:
- PASS，构建成功

- [ ] **Step 3: 检查最终文件面是否齐全**

Run:
```bash
rg -n "device_scale_factor|/api/render/config|所有工作都在 /workspace 中完成|relative path under /workspace|render_artifacts" src webui docs .planning/phases/07-render-readability-workspace-boundary
```

Expected:
- render 配置、API、system reminder、message 工具说明、render artifact 文档、QQ 验收 artifact 都能被 grep 到

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat(07): close render readability and workspace boundary"
```

---

## Notes for the Implementer

- 不要把 QQ 本地文件发送规则写进 system prompt；system prompt 只保留“所有工作都在 `/workspace` 中完成”。
- `message.send.render` 是 runtime 内部流程，不要为了满足 QQ 本地文件规则把 render artifact 塞进 `/workspace`。
- 对模型暴露的本地文件发送输入应是**相对路径**；runtime 内部可以把它重写成 `/workspace/...` world path，再交给后续出站链路。
- 如果实现过程中发现旧草案要求直接改某个 prompt 文件，请停下并回到已确认 spec：这里优先用稳定的 assembler reminder，而不是修改某一个具体 prompt 文件。
