# Phase 7: Render Readability + Workspace Boundary - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 7 只收两件还没闭环的事：

1. 让 `message.send.render` 生成的图片在真实 QQ 客户端里可读，并留下正式人工验收记录。
2. 把 bot 的 workspace 语义和真实 `runtime_data` 落盘边界讲清楚，让模型工作规则、QQ 本地文件发送规则、runtime 内部 artifact 规则不再打架。

这不是新功能扩展阶段，不加新消息能力，不重做消息工具结构，也不重做 render 整体架构。Phase 4 已经交付的 `message -> Outbox -> Gateway` 主线继续保留。

</domain>

<decisions>
## Implementation Decisions

### Render 可读性整改范围
- **D-01:** Phase 7 的 render 可读性整改，先只做"提高分辨率"这件事，不先重做整体视觉风格，不先重排内容密度，也不先改成另一套版式语言。
- **D-02:** 当前问题被定义为"像素不够清晰"，不是"样式方向错误"。后续 planner 和 researcher 应优先调查截图倍率、输出像素密度、QQ 压缩后的清晰度表现，而不是先开大范围 UI 重画。

### Render 参数外置
- **D-03:** `deviceScaleFactor` 不能继续写死在代码里，要变成运行时配置项，并在 WebUI 里可调。
- **D-04:** render 宽度也不能继续写死在代码里，要变成运行时配置项，并在 WebUI 里可调。
- **D-05:** 这两个 render 参数先只做"全局默认值"级别的配置，不做 session 级覆盖。
- **D-06:** Phase 7 不要求现在就锁死最终默认值。初始默认值可以由 planner 决定，再通过真实 QQ 验收收敛。

### 真实客户端验收范围
- **D-07:** Render 的人工验收使用"完整验收"范围，不做最小版。
- **D-08:** 真实 QQ 客户端至少要验证这 8 类内容都可读：标题、普通段落、列表、行内公式、块公式、代码块、引用块、表格。
- **D-09:** Phase 7 需要把这次人工验收结果正式写入 phase artifacts，不能继续只停留在口头确认。

### Workspace 语义
- **D-10:** 不要求在 `host` backend 下把 shell 看到的真实路径伪装成 `/workspace`。如果模型通过 shell 观察到真实宿主机路径，这不算 Phase 7 要解决的问题。
- **D-11:** Phase 7 要收稳的是"模型工作语义"，不是 host shell 虚拟化。system prompt 必须明确告诉模型：工作区全部在 `/workspace`。
- **D-12:** 模型自己要发送本地文件到 QQ 时，只应使用 `/workspace` 里的内容，并通过相对路径引用。这个发送规则当前先只对 QQ 收口，不要求同时扩展到其他平台。
- **D-13:** `/workspace` 是模型侧正式工作语义；真实宿主机路径和 `runtime_data` 目录结构属于 runtime 内部实现，不需要升格成模型工具契约。

### Render 与本地文件发送的边界
- **D-14:** `render` 属于工具驱动的 runtime 内部流程。模型提供的是待渲染内容，不是"自己挑一个本地路径再发送"。
- **D-15:** 因为 `render` 不是模型手动选路径发送，所以它不受"模型只能从 `/workspace` 里按相对路径发 QQ 本地文件"这条规则约束。
- **D-16:** Render 产物继续允许留在 runtime 内部 artifact 路径，由系统自动发送；Phase 7 不因为 workspace 发送规则而强行把 render 产物塞回 Work World。

### the agent's Discretion
- Render 默认配置值的初始建议，例如默认宽度和默认 `deviceScaleFactor`
- Render 参数在 WebUI 中的具体页面位置、表单文案和保存交互
- system prompt 中关于 `/workspace` 与 QQ 本地文件发送规则的具体措辞
- 真实 QQ 验收素材的具体组织方式，例如单条长案例还是多条短案例

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and audit gap
- `.planning/ROADMAP.md` — Phase 7 的正式目标、成功标准、3 个 plan 切分
- `.planning/REQUIREMENTS.md` — `MSG-08` 当前仍挂在 Phase 7，必须闭环
- `.planning/STATE.md` — 当前 milestone 路由已经明确把下一步指向 Phase 7
- `.planning/v1.0-MILESTONE-AUDIT.md` — 本轮真正要关掉的 2 个 blocker：真实 QQ 可读性 + workspace / `runtime_data` contract gap

### Prior phase decisions
- `.planning/phases/04-unified-message-tool-playwright/04-CONTEXT.md` — Phase 4 已锁定的消息工具、render、Outbox 边界
- `.planning/phases/06-runtime-infra-artifact-backfill/06-CONTEXT.md` — 明确把 render readability 和 workspace / `runtime_data` gap 留给 Phase 7

### Runtime render implementation
- `src/acabot/runtime/render/playwright_backend.py` — 当前 Playwright render backend，现有 viewport / screenshot 行为就在这里
- `src/acabot/runtime/render/service.py` — render service 入口，后续全局配置接入点
- `src/acabot/runtime/render/artifacts.py` — 当前 render artifact 路径分配逻辑，说明 render 产物仍在 `runtime_data/render_artifacts/`
- `src/acabot/runtime/outbox.py` — `message.send.render` 在发送前被物化成图片 segment 的位置

### Workspace and boundary semantics
- `src/acabot/runtime/computer/world.py` — `/workspace` 作为 world path 的正式解析语义
- `src/acabot/runtime/computer/workspace.py` — thread workspace 在宿主机上的真实目录布局
- `src/acabot/runtime/computer/runtime.py` — `workspace_visible_root="/workspace"`、run context workspace state 的真实来源
- `docs/12-computer.md` — 现有 Work World / workspace / render artifact 边界的正式文档
- `docs/07-gateway-and-channel-layer.md` — 出站 file-like segment 和 NapCat 文件发送的当前边界说明

### Follow-up design note
- `docs/superpowers/plans/2026-04-04-outbound-file-publish-layer.md` — 本轮已经整理出的出站文件发布层小计划，后续如果 Phase 7 要收 QQ 本地文件发送边界，可以直接拿来做研究输入

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RenderService` 已经是独立入口，render 相关运行时配置最自然的接入点就在这里或它的 bootstrap 注入层。
- `PlaywrightRenderBackend` 已经有稳定测试桩，后续提高清晰度时可以直接复用 `tests/runtime/test_render_service.py` 的 fake browser / fake page。
- `Outbox._build_render_segments()` 已经把 render 视为发送物化阶段的一部分，不需要重新设计消息主线。
- `WorkspaceManager`、`WorldView`、`workspace_state.workspace_visible_root` 已经把模型侧工作语义指向 `/workspace`，说明 Phase 7 更像收边界和提示，不是从零做 world path。

### Established Patterns
- runtime 内部 artifact 和 Work World 是分开的。render 现在明确落到 `runtime_data/render_artifacts/`，不是 `/workspace/attachments/`。
- 前台 file tools 使用 world path，shell 在 host backend 下看到真实宿主机路径。这套双层语义已经存在，Phase 7 不能假装当前实现是全虚拟化的。
- WebUI / control plane 已经承担运行时配置编辑职责，所以 render 分辨率和宽度外置到 WebUI 符合现有系统方向。

### Integration Points
- Render 配置项大概率会落到 runtime config / control plane / WebUI system settings 这一组链路。
- system prompt 中新增 workspace 发送规则，需要经过 prompt 组装链，而不是写死进 gateway 或 message tool。
- QQ 本地文件发送边界如果要进一步收口，会碰到 Outbox 出站物化和 NapCat file-like segment 的交接点。

</code_context>

<specifics>
## Specific Ideas

- 用户明确说当前 render 问题"只是提高分辨率"，不是重做设计。
- 用户明确要求把 render 的清晰度参数和宽度参数做成外部 UI 可调配置，而不是继续写死在代码里。
- 用户明确要求 workspace 规则写进 system prompt：工作区全部在 `/workspace`，模型自己从本地发 QQ 文件时，只从 `/workspace` 里按相对路径引用。
- 用户明确指出 `render` 是工具自动渲染、自动发送的内部流程，不应该和"模型自己选路径发送文件"混为一谈。

</specifics>

<deferred>
## Deferred Ideas

- Phase 7 不做 host shell 完全虚拟化，不要求把 shell 里的真实宿主机路径也伪装成 `/workspace`
- render 视觉风格重做、内容密度重排、全新版式语言，不属于本轮主目标
- QQ 之外其他平台的本地文件发送语义，后续再谈

</deferred>

---

*Phase: 07-render-readability-workspace-boundary*
*Context gathered: 2026-04-04*
