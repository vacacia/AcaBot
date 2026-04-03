# Phase 4: Unified Message Tool + Playwright - Research

**Researched:** 2026-04-04  
**Domain:** 统一消息工具、Outbox materialization、Playwright 文转图渲染  
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 单一 `message` 工具，`action` 参数枚举所有操作，`action` 默认值为 `"send"`
- **D-02:** v1 支持 3 个 action：`send` / `react` / `recall`
- **D-03:** `send` action 包含以下可选字段，字段存在即代表该能力被启用：
  - `text`: `str | None` — 普通文本内容
  - `images`: `list[str] | None` — 图片本地路径或 URL 列表
  - `render`: `str | None` — 一整段待渲染源内容
  - `reply_to`: `str | None` — 被引用消息的 `message_id`
  - `at_user`: `str | None` — 要 @ 的 `user_id`
  - `target`: `str | None` — 跨会话目标，使用完整 canonical `conversation_id`
- **D-04:** `render` 不暴露 `format` 字段。v1 固定解释为 `Markdown + LaTeX math`，也就是 markdown 正文中允许 inline / block math，不承诺完整 TeX 文档编译流程
- **D-05:** `text`、`images`、`render` 可共存于同一条消息。需要组合发送说明文字时，必须使用工具自带字段表达，不能依赖最终 assistant 普通文本自动补发
- **D-06:** 如果 `message` 工具的 `send` action 已经发出了内容型消息，runtime 自动抑制本轮默认 assistant 文本回复，避免重复发送
- **D-07:** `react` / `recall` 这类非内容型动作不会触发默认回复抑制
- **D-08:** 工具参数说明里必须明确写清这条规则，告诉后续 agent：如果想“图片 + 说明文字”一起发，直接在 `message.action="send"` 的参数里组合 `text` / `images` / `render`
- **D-09:** `react` action 字段：`message_id` + `emoji`
- **D-10:** `emoji` 字段接受直观名称或 Unicode emoji 字符。工具内部维护名称 / Unicode → QQ `emoji_id` 的映射
- **D-11:** 如果 `emoji` 无法映射到 QQ `emoji_id`，本次 `react` 严格失败，不做静默 fallback，也不自动改发说明文本
- **D-12:** `recall` action 字段：`message_id`
- **D-13:** `images` 字段同时支持本地文件路径和远程 URL，由 runtime 在发送编译阶段统一物化为可发送图片消息
- **D-14:** 渲染是 optional runtime capability，不是 runtime 硬前提，也不是 `message` 工具内部实现
- **D-15:** 渲染发生在 `Outbox materialization layer`，不是 ToolBroker、Gateway 或 Work World
- **D-16:** runtime 只依赖抽象 render service，不依赖 `Playwright` 这个具体名字。Playwright 最多只是一个 backend / adapter
- **D-17:** render backend 采用 capability-based registry + lazy init。没有可用 backend 时，runtime 仍可正常启动
- **D-18:** 渲染产物放在 internal runtime artifacts，不进入 Work World，也不复用 `/workspace/attachments/...`
- **D-19:** 如果渲染失败，`render` 内容按原样降级成普通文本发送，不做 markdown 清洗或 prettify
- **D-20:** `target` 的正式语义是 `conversation_id`，不是 `session_id`
- **D-21:** `target` 只接受完整 canonical 形式，例如 `qq:group:123456`、`qq:user:789`。不接受 `group:123456` 这类缩写
- **D-22:** `message` 工具对外保持统一 surface，但 runtime 内部不把所有动作都抬成同一层
- **D-23:** v1 只有 `send` 进入高层消息意图 Action，由 Outbox 在 materialization 阶段编译成底层发送动作
- **D-24:** `react` 和 `recall` 继续映射到现有 direct low-level Action，不经过高层内容编译链
- **D-25:** 后续如果继续扩展更多动作，只有需要内容编排、能力探测、fallback、artifact 生成的动作才进入高层 intent family。统一的是 tool surface，分层的是 runtime internals

### Claude's Discretion
- `message.send` 高层 Action 的最终命名，例如 `SEND_MESSAGE`、`MESSAGE_SEND_INTENT` 或等价抽象
- render service 的具体模块拆分、构造注入点和 artifact 目录命名
- emoji 映射表的初始覆盖范围，只要能满足常见 reaction 即可
- `message` 工具在 builtin tool surface 中的具体注册方式

### Deferred Ideas (OUT OF SCOPE)
- MSG-V2-01: 合并转发消息
- MSG-V2-02: 富文本编辑
- MSG-V2-03: Interactive components（按钮、卡片）
- MSG-V2-04: 完整 LaTeX 文档编译与模板化排版
- MSG-V2-05: 通过工具列出可用 `conversation_id` 供 agent 选择
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MSG-01 | 文本回复 | `message.send` 高层 intent 在 Outbox 物化为单条 `SEND_SEGMENTS` / `SEND_TEXT`，保留现有发送语义 |
| MSG-02 | 引用回复 | 继续复用 `Action.reply_to`，由 NapCat `_build_msg_payload()` 生成 reply segment |
| MSG-03 | @mention | 在 materialization 阶段把 `at_user` 编译成 OneBot `at` segment |
| MSG-04 | Emoji reaction | `message.react` 直接产出低层 `REACTION` Action，Gateway 映射 NapCat 扩展 API |
| MSG-05 | 撤回消息 | 直接复用现有 `RECALL -> delete_msg` 路径 |
| MSG-06 | 媒体/附件发送 | `images` 在 Outbox 编译成 image segments，本地路径与 URL 统一在这里处理 |
| MSG-07 | 工具层只表达意图 | builtin `message` tool 只返回 `ToolResult.user_actions`，不直接调 Gateway / Outbox |
| MSG-08 | 文转图渲染 | render service 放在 Outbox materialization，推荐 `markdown-it-py + mdit-py-plugins + latex2mathml + Playwright` |
| MSG-09 | 跨会话消息发送 | `target` 解析为 canonical `conversation_id`，并单独处理 destination persistence / thread update 语义 |
| MSG-10 | schema / 字段设计已敲定 | 本研究只说明这些字段的实现后果与测试点，不重新讨论 schema 选择 |
| PW-01 | `render_markdown_to_image()` 在 Outbox 层 | 推荐作为 render service 对外能力，由 Outbox 在 materialization 调用 |
| PW-02 | Singleton browser 实例管理 | 推荐 backend 对象单例 + browser lazy init + `RuntimeApp.stop()` 统一关闭 |
| PW-03 | markdown-it-py -> HTML -> Playwright screenshot | 推荐离线安全栈：MarkdownIt 渲染 HTML，Math 转 MathML，再由 Playwright 截图 |
</phase_requirements>

## Summary

这一 phase 真正要规划清楚的，不是“再加一个 message tool”这么简单，而是把三层边界一次性收干净：`builtin tool surface` 只表达消息意图、`Outbox` 负责把高层 send intent 物化成可发送的低层动作、`Gateway` 继续只做 OneBot / NapCat 协议翻译。只要这三层边界没糊，后面继续扩更多消息动作也不会回头返工。

本地代码审计后，最关键的实现后果有 3 个。第一，默认回复抑制不该在 Gateway 或 Outbox 尾部“猜”，而应该在 `ModelAgentRuntime._to_runtime_result()` 这里决定“还要不要追加默认 assistant text action”，因为现在默认文本回复就是在这里拼进去的。第二，`MSG-09` 比表面更大：当前 `Outbox` 和 `ThreadPipeline` 默认都把已发送消息挂回“当前 thread”，如果直接支持 cross-session send 而不分离“来源 thread”和“投递目标 conversation”，`MessageStore`、working memory、长期记忆写入线都会记错地方。第三，render 虽然是 optional capability，但它的依赖现在只装在 Dockerfile，不在 `pyproject.toml`，这会继续制造“容器能跑、本地测试不能跑”的漂移。

**Primary recommendation:** 把 Phase 4 拆成“统一 tool surface + 低层 direct actions”、“send intent materialization + cross-session/persistence 语义”、“render service + Playwright backend + docs/tests”三段连续计划，不要把它混成一个大 patch。

## Project Constraints (from CLAUDE.md)

- 所有文档、代码注释、交流过程统一使用 中文 + English 标点。
- Phase 相关研究必须以 `docs/00-ai-entry.md` 的命名契约和主线边界为准，尤其是 `conversation_id`、`thread_id`、`session_id` 语义不能混。
- 技术栈固定在 Python 3.11+ / asyncio，不引入新的异步框架。
- Gateway 当前只有 NapCat；消息工具要平台无关设计，但 v1 只需要落 OneBot v11 / NapCat 实现。
- 部署走 Docker Compose；镜像和依赖变更必须同时兼容 `Dockerfile` 和 `Dockerfile.lite`。
- 需要保留 BackendBridgeToolPlugin 过渡期可用性，不要破坏现有 builtin / plugin 装配。
- AcaBot 是单操作者场景，不需要多租户隔离。
- 已知全量测试失败项：`tests/runtime/backend/test_pi_adapter.py` 依赖真实 `pi`，全量 pytest 需要显式 `--ignore=tests/runtime/backend/test_pi_adapter.py`。

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `playwright` | `1.58.0`，PyPI 发布于 `2026-01-30` | Headless browser screenshot backend | 官方 Python API 完整、浏览器生命周期和截图能力成熟，最适合做 singleton render backend |
| `markdown-it-py` | `4.0.0`，PyPI 发布于 `2025-08-11` | Markdown -> HTML | Python 侧最稳的 markdown-it 实现，插件生态直接覆盖表格、强调、数学扩展入口 |
| `mdit-py-plugins` | `0.5.0`，PyPI 发布于 `2025-08-11` | Dollar math / markdown extensions | `dollarmath_plugin` 明确支持 `$...$` / `$$...$$` 场景，比自己写 regex 稳得多 |
| `latex2mathml` | `3.79.0`，PyPI 发布于 `2026-03-12` | LaTeX math -> MathML | 纯 Python、离线、无浏览器端 JS 依赖；和 Chromium 原生 MathML 能力配合后，最适合这个 phase |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Chromium bundled by Playwright | 跟随 `playwright` | Render backend browser | 默认首选，避免依赖系统 Chrome 版本碰撞 |
| 系统 Chrome / Chromium | 本机可用：Chrome `146.0.7680.164`，Chromium `146.0.7680.80` | Playwright fallback channel / executable | 只在 bundled browser 缺失或安装失败时作为 fallback，不作为默认 planning 目标 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `latex2mathml + Chromium MathML` | `KaTeX` / `MathJax` | 显示效果更强，但引入额外 JS/CSS 资产、离线与 sanitization 复杂度更高 |
| 单一 `message` tool + `action` 枚举 | 分开的 `send` / `react` / `recall` tools | 分开更直白，但和已锁定 surface 冲突，也会把默认回复抑制规则拆散 |
| 高层 `send` intent 进 Outbox 物化 | tool 直接吐 `SEND_SEGMENTS` | 短期代码少，但 render capability、fallback、cross-session persistence 以后都要返工 |

**Installation:**

```bash
cd /home/acacia/AcaBot
uv add playwright markdown-it-py mdit-py-plugins latex2mathml
python -m playwright install --with-deps chromium
```

**Version verification:**

```bash
python3 - <<'PY'
import json, urllib.request
for name in ["playwright", "markdown-it-py", "mdit-py-plugins", "latex2mathml"]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=20) as r:
        data = json.load(r)
    version = data["info"]["version"]
    latest_upload = max(
        item["upload_time_iso_8601"][:10]
        for item in data["releases"][version]
    )
    print(name, version, latest_upload)
PY
```

**Planning consequence:** 这 4 个包都应该进入 `pyproject.toml` + `uv.lock`，不要继续只装在 Dockerfile。当前宿主机上 `playwright`、`mdit_py_plugins`、`latex2mathml` 都没装，render 功能实际上不可用。

## Suggested Plan Breakdown

### Plan A: Tool Surface + 低层动作补齐

- 新增 `src/acabot/runtime/builtin_tools/message.py`，实现 `BuiltinMessageToolSurface`。
- `send` 返回高层 intent `PlannedAction`，`react` / `recall` 返回 direct low-level `PlannedAction`。
- 扩展 `src/acabot/types/action.py`，新增一个只给 `send` 用的高层 action type，推荐命名 `SEND_MESSAGE_INTENT`。
- 扩展 `src/acabot/runtime/builtin_tools/__init__.py` 与 `src/acabot/runtime/bootstrap/__init__.py`，把 message surface 注册进 core builtin tools。
- 扩展 `src/acabot/gateway/napcat.py` 支持 `REACTION` 对应的 NapCat API payload。

### Plan B: Outbox Materialization + Cross-Session Semantics

- 在 `src/acabot/runtime/outbox.py` 增加 high-level send intent 的 materialization 入口。
- 统一处理 `text` / `images` / `render` / `at_user` / `reply_to` / `target`，编译成单条低层发送动作。
- 明确区分 “origin thread” 和 “destination conversation”，修正 cross-session send 的 `MessageStore` 落点与 working memory 更新。
- 在 `src/acabot/runtime/model/model_agent_runtime.py` 实现默认回复抑制，只对 `message.send` 内容型动作生效。

### Plan C: Render Service + Playwright Backend + Docs/Tests

- 新增 render service 抽象与 Playwright backend，bootstrap 注入到 Outbox，`RuntimeApp.stop()` 负责回收。
- 使用 `markdown-it-py + mdit-py-plugins + latex2mathml` 生成安全 HTML，再用 Playwright 截图。
- 新增 render / message tool / cross-session 相关测试和 docs 同步。

## Architecture Patterns

### Recommended Project Structure

```text
src/acabot/runtime/
├── builtin_tools/
│   ├── __init__.py
│   └── message.py                  # 统一 message tool surface
├── render/
│   ├── __init__.py
│   ├── protocol.py                # RenderBackend / RenderService protocol
│   ├── service.py                 # capability registry + backend selection
│   ├── artifacts.py               # internal runtime artifact path helpers
│   └── playwright_backend.py      # lazy singleton browser backend
├── outbox.py                      # send intent materialization
└── ids.py                         # canonical conversation_id parser/helper
```

### Pattern 1: Tool Surface 只返回 `user_actions`

**What:** `message` builtin tool 不直接调 Gateway，不直接写 MessageStore，也不直接碰 render backend；它只生成 `ToolResult.user_actions`。

**When to use:** 所有需要“让模型表达一个出站意图”的 builtin tool，都应该走这条路。

**Integration points:**

- `src/acabot/runtime/builtin_tools/message.py`
- `src/acabot/runtime/tool_broker/contracts.py`
- `src/acabot/runtime/model/model_agent_runtime.py`

**Example:**

```python
# Source: repo pattern + ToolBroker contracts
return ToolResult(
    llm_content="",
    user_actions=[
        PlannedAction(
            action_id=f"action:{ctx.run_id}:message:send",
            action=Action(
                action_type=ActionType.SEND_MESSAGE_INTENT,
                target=resolved_target,
                payload={
                    "text": text,
                    "images": images,
                    "render": render,
                    "at_user": at_user,
                },
                reply_to=reply_to,
            ),
            thread_content=thread_content,
            commit_when="success",
            metadata={
                "origin": "builtin_message_tool",
                "message_action": "send",
                "suppresses_default_reply": True,
                "destination_conversation_id": destination_conversation_id,
            },
        )
    ],
)
```

### Pattern 2: Outbox Materializes High-Level Send Intent Into 1 Low-Level Message

**What:** `send` intent 在 Outbox 里统一编译成一条低层 `SEND_SEGMENTS`。reply 继续复用 `Action.reply_to`，正文段顺序固定为 `at -> text -> images -> render-image`。

**When to use:** 只对高层 `send` intent 用；`react` / `recall` 保持 direct low-level。

**Why this shape works well:**

- OneBot 本来就支持 segment 数组，Phase 4 没必要把一个高层 send 拆成多条平台消息。
- 统一成单条 low-level message 后，持久化、delivery report、working memory 都更简单。
- render 失败时，`render` 原文可以直接回退成 text segment，不需要改变上层控制流。

### Pattern 3: Render Backend 单例对象 + Browser Lazy Init

**What:** bootstrap 在启动时构造 render service / backend 对象，但真正的 Playwright `browser` 只在第一次 render 时创建；停机时统一 `close()`。

**When to use:** 任何 optional runtime capability 都适合这个模式，尤其是重依赖、重进程类能力。

**Integration points:**

- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/app.py`
- `src/acabot/runtime/outbox.py`

**Example:**

```python
# Source: Playwright Python docs, adapted for AcaBot lifecycle
from playwright.async_api import async_playwright

class PlaywrightRenderBackend:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None

    async def ensure_browser(self):
        if self._browser is not None:
            return self._browser
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch()
        return self._browser

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
```

### Pattern 4: Canonical `conversation_id` 必须走共享解析 helper

**What:** 不要继续在各处手写 `channel_scope.split(":", 2)`。Phase 4 会再次引入 destination parsing，如果不收束，这类重复解析会继续扩散。

**When to use:** `target`、approval resume、subagent 派生 target、任何从 canonical id 反解 `EventSource` 的场景。

**Recommended helper contract:**

```python
def parse_conversation_id(
    conversation_id: str,
    *,
    actor_user_id: str,
) -> EventSource:
    ...
```

`actor_user_id` 之所以还需要，是因为现在 `EventSource` 在 group 场景依然强制带 `user_id`，而 canonical `conversation_id` 只有 group id。

### Anti-Patterns to Avoid

- **Tool 里直接调 Gateway:** 这会绕开 Outbox、MessageStore、delivery report、默认回复抑制，后面一定返工。
- **把 render 文件放进 `/workspace/attachments` 或 Work World:** 这会污染模型可见世界，也和已锁定边界冲突。
- **cross-session 仍沿用当前 `ctx.thread.thread_id` 落库:** 这样 `MSG-09` 表面可发，事实记录和长期记忆却错位。
- **靠 tool name 字符串判断默认回复抑制:** 应该看 action metadata / action family，而不是 `"message"` 这种文本匹配。
- **继续让 render 依赖只存在 Dockerfile:** 这样 planner 写出来的测试步骤会在本机和 CI 直接飘掉。

## Don’t Hand-Roll

| Problem | Don’t Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Markdown parsing | 手写正则 parser | `markdown-it-py` | Markdown 边界条件太多，自己写 parser 只会制造不可维护行为 |
| Dollar math parsing | 自己 split `$...$` / `$$...$$` | `mdit-py-plugins.dollarmath_plugin` | inline / block / escaping 很容易写错 |
| LaTeX to browser math | 浏览器端临时拼 JS / 网络拉 KaTeX | `latex2mathml` + Chromium MathML | 离线、纯 Python、依赖简单，和当前 phase 更匹配 |
| Browser lifecycle | 手搓 `subprocess chrome --headless` | Playwright backend singleton | 生命周期、超时、页面上下文、截图 API 都更稳 |
| Canonical id parsing | 到处 `split(":")` | 共享 parser helper | Phase 4 会引入更多 target 派生路径，重复解析会迅速扩散 |
| Emoji reaction fallback | 映射失败时偷偷改发文本 | 严格失败 + 小而明确的映射表 | 这是已锁定决定，静默 fallback 会把 planner 带偏 |

**Key insight:** 这个 phase 的“复杂度陷阱”都长得很像“看起来几行代码就能搞定”。真正该复用的不是大框架，而是已经成熟的 parser、browser lifecycle 和 runtime 自己的 `ToolResult.user_actions -> Outbox -> Gateway` 主线。

## Common Pitfalls

### Pitfall 1: Cross-Session Send 事实落到错误的 thread

**What goes wrong:** bot 成功把消息发到了 `qq:group:123456`，但 `MessageStore` 还记在触发这次工具调用的原始 thread 里。

**Why it happens:** 现在 `Outbox._build_items()` 固定把 `ctx.thread.thread_id` 和 `ctx.thread.channel_scope` 绑到每个 `OutboxItem` 上，`ThreadPipeline._update_thread_after_send()` 也默认把所有 delivered item 回写到当前 thread。

**How to avoid:** 为 `send` intent 单独记录 `destination_conversation_id`，并在 materialization / persistence 处显式分离 origin thread 与 delivery conversation。

**Warning signs:** cross-session send 用例能发出去，但目的会话的事实查询 / LTM / MessageStore 读不到这条消息。

### Pitfall 2: 图片 + 文本发送后，模型默认回复又补发一条

**What goes wrong:** `message.send` 已经把图片和说明文字发出去了，runtime 还是把 LLM 的最终 text 再追加发一条。

**Why it happens:** 当前默认 text reply 是在 `ModelAgentRuntime._to_runtime_result()` 里无条件 append 的。

**How to avoid:** 让 `message.send` 产出的 `PlannedAction.metadata` 带上明确的 suppression 标记，`ModelAgentRuntime` 在拼最终 actions 时根据这个标记决定是否追加默认 text action。

**Warning signs:** 真实 IM 客户端里总是出现“一条工具发的消息 + 一条多余纯文本”。

### Pitfall 3: Render 功能把 Work World 污染了

**What goes wrong:** render 输出图被写进 `/workspace/attachments`，模型后续通过 `read` / `bash` 就能看到这些 runtime 内部产物。

**Why it happens:** 开发者把 render 当成“普通附件 staging”处理了。

**How to avoid:** 单独定义 internal runtime artifacts 根目录，例如 `runtime_data/render_artifacts/{run_id}/`，完全不接入 Work World。

**Warning signs:** 渲染生成的图片出现在 `/workspace/attachments/...`、WebUI workspace、或 computer 附件列表里。

### Pitfall 4: Markdown / HTML 安全边界太松

**What goes wrong:** render 允许原始 HTML 混入，甚至带内联脚本 / 不受控标签，浏览器截图时产生不可预测输出。

**Why it happens:** 直接用 markdown-it 的 permissive 配置，或者把用户 / LLM 传来的 markdown 当成可信输入。

**How to avoid:** 使用 `MarkdownIt("js-default")` 或显式 `html=False` 的安全配置，只开需要的插件；render HTML 模板自己掌控，不把原始 HTML 直接透传。

**Warning signs:** markdown 里写 `<style>` / `<script>` 后，截图输出异常或样式被污染。

### Pitfall 5: Reaction 被误当成 OneBot v11 标准能力

**What goes wrong:** 代码结构默认所有 gateway 都能实现 reaction，结果实际上只有 NapCat 扩展支持。

**Why it happens:** `REACTION` 不在 OneBot v11 标准 API 里，它是 NapCat 扩展能力。

**How to avoid:** 让 `react` 继续保持 direct low-level action，并把 gateway support 明确标成 NapCat-specific。不要把它塞进“平台无关高层 intent”。

**Warning signs:** planner 里出现“其他 OneBot 实现也应该天然支持 reaction”这类假设。

### Pitfall 6: 依赖漂移，容器能跑但本地测试全挂

**What goes wrong:** render 代码在 Docker 里能 import，本地 `pytest` / `uv run` 却直接 `ModuleNotFoundError`。

**Why it happens:** 现在 `playwright`、`markdown-it-py` 等依赖主要装在 Dockerfile，不是项目正式依赖。

**How to avoid:** 把 render stack 收进 `pyproject.toml` 和 `uv.lock`，并让测试命令统一走 `PYTHONPATH=src uv run pytest ...`。

**Warning signs:** `python3 -c "import playwright"` 失败，但 Dockerfile 里明明写了 `pip install playwright`。

## Code Examples

Verified patterns from official sources and current repo patterns:

### 1. Playwright Async Screenshot Backend

```python
# Source: https://playwright.dev/python/docs/library
# Source: https://playwright.dev/python/docs/screenshots
from playwright.async_api import async_playwright

async def screenshot_html(html: str, output_path: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1200, "height": 800},
            device_scale_factor=2,
        )
        page = await context.new_page()
        await page.set_content(html, wait_until="load")
        await page.screenshot(path=output_path, full_page=True)
        await context.close()
        await browser.close()
```

### 2. Markdown + Math -> HTML

```python
# Source: https://markdown-it-py.readthedocs.io/en/latest/
# Source: https://mdit-py-plugins.readthedocs.io/en/latest/
# Source: https://pypi.org/project/latex2mathml/
from latex2mathml.converter import convert as tex_to_mathml
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin


def _render_math(content: str) -> str:
    return tex_to_mathml(content)


md = (
    MarkdownIt("js-default")
    .enable("table")
    .use(dollarmath_plugin, renderer=_render_math)
)

html_body = md.render("行内数学 $E=mc^2$，块数学：\n\n$$a^2+b^2=c^2$$")
```

### 3. Outbox Materialization Produces a Single Segment Message

```python
# Source: repo contracts + OneBot segment model
segments: list[dict[str, object]] = []
if at_user:
    segments.append({"type": "at", "data": {"qq": at_user}})
if text:
    segments.append({"type": "text", "data": {"text": text}})
for image in images:
    segments.append({"type": "image", "data": {"file": image}})
if render_image_file:
    segments.append({"type": "image", "data": {"file": render_image_file}})

return Action(
    action_type=ActionType.SEND_SEGMENTS,
    target=resolved_target,
    payload={"segments": segments},
    reply_to=reply_to,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Dockerfile-only render deps | 项目正式依赖 + lock file 管理 | 当前 phase 必须补齐 | 本地开发、测试、容器行为一致 |
| 直接在 tool / plugin 里拼低层发送动作 | tool surface 返回 intent，Outbox 物化 | AcaBot 当前主线已经成型，适合在这 phase 收束 | render、fallback、cross-session 语义集中到一处 |
| 浏览器端 JS 数学渲染 | Python 侧先转 MathML，再截图 | 近年的 Chromium MathML 支持已足够实用 | 去掉网络资产与浏览器端 JS 依赖 |
| 到处手写 `channel_scope.split(":")` | 共享 canonical parser helper | 现在已出现多处重复解析，Phase 4 应顺手收束 | 避免 target / subagent / approval resume 语义漂移 |

**Deprecated / outdated:**

- Dockerfile 里私装 `playwright` / `markdown-it-py`，但不写进 `pyproject.toml`：对这个 phase 来说已经不够用。
- 把 cross-session send 当成“只是换一个 `Action.target`”处理：会导致 persistence 与 working memory 行为错误。

## Open Questions

1. **cross-session send 后，当前 thread 要不要追加一条本地“已转发到 XXX”工作记忆？**  
   What we know: 当前 `ThreadPipeline._update_thread_after_send()` 会把所有 delivered item 的 `thread_content` 追加到当前 thread。  
   What's unclear: 对 `MSG-09` 来说，这是应该保留的产品行为，还是应该只把事实写到 destination conversation。  
   Recommendation: v1 先把正式 `MessageRecord` 写到 destination conversation；当前 thread 是否追加一条 synthetic note，作为 planner 明确选择项，不要让代码默认偷做。

2. **QQ `emoji_id` 的权威映射表从哪里来？**  
   What we know: NapCat API 需要 `emoji_id`，工具输入却是 name / Unicode。  
   What's unclear: 官方公开资料更容易找到 API 形状，较难找到稳定完整的 name / Unicode -> `emoji_id` 对照表。  
   Recommendation: v1 只做“小而明确”的常用映射表 + 严格失败 + 实机验证；不要为了“覆盖全量 emoji”把 phase 拖死。

3. **render artifact 的保留策略怎么定？**  
   What we know: artifact 必须是 internal runtime artifact，不能进 Work World。  
   What's unclear: 这些文件是长期保留、按 run 清理、还是按 TTL 清理。  
   Recommendation: v1 先用 `runtime_data/render_artifacts/{run_id}/`，不在本 phase 引入 GC；后续如果真有磁盘压力，再单独补一 phase。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime / tests | ✓ | `3.12.3` | — |
| `uv` | 依赖安装、pytest 执行 | ✓ | `0.9.15` | — |
| Node.js | 现有 repo 浏览器类测试、Playwright 安装辅助 | ✓ | `22.22.1` | — |
| Chromium / Chrome | Playwright screenshot backend | ✓ | Chromium `146.0.7680.80`，Chrome `146.0.7680.164` | 只做 fallback，默认仍建议 Playwright bundled Chromium |
| `playwright` Python package | render backend | ✗ | — | render capability disabled，`render` 回退成普通文本 |
| `markdown-it-py` direct dependency | markdown parsing | 部分可用 | 当前宿主机 import 到 `3.0.0`，但不是明确 direct dep | 收进 `pyproject.toml`，避免依赖漂移 |
| `mdit-py-plugins` | dollar math parsing | ✗ | — | 无 clean math render，仅能 raw text fallback |
| `latex2mathml` | 离线 math -> MathML | ✗ | — | raw text fallback |

**Missing dependencies with no fallback:**

- 无。因为已锁定决策要求 render 是 optional capability，runtime 可以在无 backend 时继续启动。

**Missing dependencies with fallback:**

- `playwright` / `mdit-py-plugins` / `latex2mathml` 当前宿主机缺失。fallback 是 `render` 原样回退成普通文本，但这只能保证 runtime 不崩，不能算满足 MSG-08 / PW-01..03 的最终交付。

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.2` + `pytest-asyncio 1.3.0` |
| Config file | `pyproject.toml` |
| Quick run command | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py tests/runtime/test_outbox.py tests/runtime/test_model_agent_runtime.py tests/runtime/test_bootstrap.py tests/runtime/test_app.py tests/runtime/test_pipeline_runtime.py` |
| Full suite command | `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MSG-01 | `message.send(text=...)` 生成并送达基础文本 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_send_text` | ❌ Wave 0 |
| MSG-02 | `reply_to` 进入 reply segment | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_send_with_reply` | ✅ |
| MSG-03 | `at_user` 编译成 `at` segment | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_send_with_at_segment` | ❌ Wave 0 |
| MSG-04 | `react` 直通 NapCat reaction API | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_reaction` | ❌ Wave 0 |
| MSG-05 | `recall` 继续走 `delete_msg` | unit | `PYTHONPATH=src uv run pytest -q tests/test_gateway.py::test_build_recall` | ✅ |
| MSG-06 | `images` 支持 URL / local path | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_materializes_images` | ❌ Wave 0 |
| MSG-07 | tool layer 不直接调 gateway | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_tool_returns_user_actions_only` | ❌ Wave 0 |
| MSG-08 | render success / fallback | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py` | ❌ Wave 0 |
| MSG-09 | cross-session send 正确落 destination conversation | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_persists_cross_session_delivery_to_destination` | ❌ Wave 0 |
| MSG-10 | schema 与 discuss-phase 锁定字段一致 | unit | `PYTHONPATH=src uv run pytest -q tests/runtime/test_message_tool.py::test_message_tool_schema_matches_locked_fields` | ❌ Wave 0 |
| PW-01 | render service 在 Outbox layer 被调用 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_outbox.py::test_outbox_calls_render_service_in_materialization` | ❌ Wave 0 |
| PW-02 | browser 单例可复用且 stop 时关闭 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py::test_playwright_backend_reuses_single_browser` | ❌ Wave 0 |
| PW-03 | markdown-it-py -> HTML -> screenshot 流程可跑通 | integration | `PYTHONPATH=src uv run pytest -q tests/runtime/test_render_service.py::test_render_markdown_to_image_pipeline` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** 运行 quick run command 中与当前改动直接相关的最小子集。
- **Per wave merge:** 运行完整 quick run command。
- **Phase gate:** `PYTHONPATH=src uv run pytest --ignore=tests/runtime/backend/test_pi_adapter.py` 全绿，再进入 `/gsd:verify-work`。

### Wave 0 Gaps

- [ ] `tests/runtime/test_message_tool.py` — 覆盖 schema、tool surface、默认回复抑制触发条件。
- [ ] `tests/runtime/test_render_service.py` — 覆盖 backend lazy init、screenshot pipeline、fallback。
- [ ] `tests/test_gateway.py` 新增 reaction / at segment 用例。
- [ ] `tests/runtime/test_outbox.py` 新增 materialization、cross-session persistence、render fallback 用例。
- [ ] `tests/runtime/test_pipeline_runtime.py` 新增 cross-session working memory 行为用例。
- [ ] render backend test fixtures — 需要 stub render service / fake browser，避免单元测试强依赖真实 Chromium。

## Documentation Sync

只要 Phase 4 按推荐方案落地，至少要同步下面这些文档：

- `docs/01-system-map.md` — 主线要明确出现 `message tool -> PlannedAction -> Outbox materialization -> Gateway`。
- `docs/02-runtime-mainline.md` — RuntimeApp / ThreadPipeline / Outbox 新职责边界。
- `docs/03-data-contracts.md` — `ActionType`、high-level send intent、cross-session persistence 语义。
- `docs/07-gateway-and-channel-layer.md` — NapCat reaction API、reply / at / image segment 出站说明。
- `docs/12-computer.md` — 明确 render artifacts 不属于 Work World / attachments。
- `docs/18-tool-skill-subagent.md` — builtin `message` tool surface、默认回复抑制规则。

## Sources

### Primary (HIGH confidence)

- Current repo code and docs:
  - `src/acabot/types/action.py`
  - `src/acabot/runtime/outbox.py`
  - `src/acabot/runtime/model/model_agent_runtime.py`
  - `src/acabot/runtime/pipeline.py`
  - `src/acabot/gateway/napcat.py`
  - `src/acabot/runtime/builtin_tools/__init__.py`
  - `docs/00-ai-entry.md`
  - `docs/03-data-contracts.md`
  - `docs/07-gateway-and-channel-layer.md`
  - `docs/12-computer.md`
- Playwright Python official docs:
  - https://playwright.dev/python/docs/library
  - https://playwright.dev/python/docs/screenshots
  - https://playwright.dev/python/docs/browsers
  - https://playwright.dev/python/docs/api/class-page
- markdown-it-py official docs:
  - https://markdown-it-py.readthedocs.io/en/latest/
  - https://markdown-it-py.readthedocs.io/en/latest/security.html
- mdit-py-plugins official docs:
  - https://mdit-py-plugins.readthedocs.io/en/latest/
- PyPI release metadata:
  - https://pypi.org/project/playwright/
  - https://pypi.org/project/markdown-it-py/
  - https://pypi.org/project/mdit-py-plugins/
  - https://pypi.org/project/latex2mathml/
- OneBot v11 official spec:
  - https://github.com/botuniverse/onebot-11/blob/master/message/segment.md
  - https://github.com/botuniverse/onebot-11/blob/master/api/public.md

### Secondary (MEDIUM confidence)

- NapCat API docs，确认 reaction 是扩展能力，不是 OneBot v11 标准：
  - https://napneko.github.io/develop/api/doc
- MDN MathML overview，确认现代浏览器具备原生 MathML 渲染能力：
  - https://developer.mozilla.org/en-US/docs/Web/MathML

### Tertiary (LOW confidence)

- QQ `emoji_id` 对照表的完整权威来源未找到。当前 research 只确认了 API 形状，没有确认完整映射全集；这部分需要实机校验。

## Metadata

**Confidence breakdown:**

- Standard stack: **HIGH** — Playwright / markdown-it-py / mdit-py-plugins / latex2mathml 都有官方文档与 PyPI 当前版本可核对。
- Architecture: **MEDIUM** — 主线集成点来自本地源码审计，很明确；但 cross-session working memory 的最终产品语义仍有一个需要 planner 明确的选择点。
- Pitfalls: **HIGH** — 大部分风险直接来自当前 repo 代码路径，尤其是 `Outbox`、`ThreadPipeline`、`ModelAgentRuntime` 的现状。

**Research date:** 2026-04-04  
**Valid until:** 2026-05-04
