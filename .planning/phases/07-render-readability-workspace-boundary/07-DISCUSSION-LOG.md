# Phase 7: Render Readability + Workspace Boundary - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `07-CONTEXT.md` — this log preserves the alternatives considered and the user's corrections.

**Date:** 2026-04-04
**Phase:** 07-render-readability-workspace-boundary
**Areas discussed:** Render readability strategy, acceptance coverage, render config externalization, workspace guidance, render vs local-file-send boundary

---

## 1. Render 可读性整改范围

| Option | Description | Selected |
|--------|-------------|----------|
| 改整体视觉方向 | 重做版式、风格、信息密度 | |
| 清晰度优先 vs 内容量优先 | 先定阅读策略，再推版式 | |
| 只提高分辨率 | 不先重做设计，先解决像素清晰度 | ✓ |

**User's choice:** 只提高分辨率。

**Notes:** 用户直接纠正了提问方向，明确说当前不想先聊视觉语言和内容密度，只想先把分辨率提上去。

---

## 2. 真实 QQ 验收覆盖范围

| Option | Description | Selected |
|--------|-------------|----------|
| 最小验收 | 标题、正文、行内公式、块公式 | |
| 标准验收 | 最小验收 + 列表 + 代码块 | |
| 完整验收 | 标题、正文、列表、行内公式、块公式、代码块、引用块、表格 | ✓ |

**User's choice:** 完整验收。

---

## 3. Render 参数如何暴露

| Option | Description | Selected |
|--------|-------------|----------|
| 写死在代码里 | 直接在 backend 常量里调默认值 | |
| 只把分辨率外置 | 宽度继续写死 | |
| 分辨率和宽度都外置到 WebUI | 两个参数都做成配置项 | ✓ |

**User's choice:** `deviceScaleFactor` 和宽度都要外置到 WebUI。

### 配置层级

| Option | Description | Selected |
|--------|-------------|----------|
| 全局默认值 | 整个 bot 共用一套 render 配置 | ✓ |
| 按 session 配置 | 不同会话独立调参 | |
| 两层都有 | 全局默认 + session override | |

**User's choice:** 先做全局默认值。

---

## 4. Workspace 语义

最初候选方向：

| Option | Description | Selected |
|--------|-------------|----------|
| 强制 host shell 也表现成 `/workspace` | 连真实宿主机路径都尽量不暴露 | |
| 只收模型工作语义 | system prompt 讲清 `/workspace` 规则，不强求 shell 虚拟化 | ✓ |

**User's choice:** 只收模型工作语义，不强求 host shell 路径伪装。

**User correction:** 用户明确指出，在 `host` backend 下，模型本来就可能通过 shell 看见自己真实所在位置、workspace、skills、配置路径。所以 Phase 7 不该把问题误定义成"模型完全看不到真实路径"。

**Locked rule from discussion:**
- system prompt 里明确告诉模型，工作区全部在 `/workspace`
- 模型自己要发 QQ 本地文件时，只使用 `/workspace` 里的内容，并按相对路径引用
- 这条规则当前先只针对 QQ

---

## 5. Render 和本地文件发送规则的关系

最初存在一个潜在混淆：如果"只有 `/workspace` 里的文件能发 QQ"，那 render 产物是不是也要塞回 `/workspace`。

**User correction:** 不需要纠结这个。`render` 是工具自动渲染、自动发送的内部流程，不是模型自己找一个路径去发文件。

**Locked boundary:**
- `/workspace` 发送规则只约束模型自己挑本地文件发送
- `render` 不属于这条规则
- render 继续作为 runtime 内部 artifact 流程处理

---

## the agent's Discretion

- Render 默认宽度和默认 `deviceScaleFactor` 的初始值
- WebUI 中这两个配置项的具体落点和文案
- system prompt 里关于 `/workspace` 和 QQ 本地文件发送规则的具体措辞

## Deferred Ideas

- host shell 完整虚拟化
- 其他平台的本地文件发送语义
- render 样式大改版
