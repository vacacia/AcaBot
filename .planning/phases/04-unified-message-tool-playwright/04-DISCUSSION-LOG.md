# Phase 4: Unified Message Tool + Playwright - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 04-unified-message-tool-playwright
**Areas discussed:** 工具 Schema 结构, 文转图触发方式, Playwright 生命周期管理, 跨会话 target 设计

---

## 工具 Schema 结构

| Option | Description | Selected |
|--------|-------------|----------|
| 多个独立工具 | send_message/react/recall/send_image 各为独立工具，schema 小且聚焦 | |
| 单一工具 + action 参数 | 一个 message 工具，action 参数枚举所有操作，与 OpenClaw 设计一致 | ✓ |

**User's choice:** 单一工具 + action 参数

---

| Option | Description | Selected |
|--------|-------------|----------|
| 4 个核心 action | send/react/recall/send_image，发送相关能力全在 send action 里通过字段控制 | ✓ |
| 6 个 action | 拆出 send_text/quote_reply/mention 为独立 action，更细粒度 | |

**User's choice:** 4 个核心 action（后续调整为 3 个，send_image 合并入 send）

---

| Option | Description | Selected |
|--------|-------------|----------|
| at_user 宗立字段 | send action 增加 at_user: user_id 字段，工具内部拼接 at segment | ✓ |
| text 嵌入 @{user_id} | agent 在 message 文本里写 @{user_id} 占位符，工具解析后拼接 | |

**User's choice:** at_user 宗立字段

---

| Option | Description | Selected |
|--------|-------------|----------|
| 本地文件路径 + URL | images 字段支持两种来源 | ✓ |
| 仅本地文件路径 | 只支持 image_path | |

**User's choice:** 本地文件路径 + URL

---

| Option | Description | Selected |
|--------|-------------|----------|
| emoji_id + emoji_name 两种 | 工具内部解析地址 | |
| 仅 emoji_id 数字 | 直接与 OneBot v11 API 对应 | |
| emoji_name / emoji，工具自建映射 | 工具维护 name/unicode → QQ emoji_id 映射表 | ✓ |

**User's choice:** emoji_name or emoji，工具自建 QQ emoji 映射
**Notes:** 用户明确："emoji_name or emoji, 我们自己建立name和emoji-to-QQemoji的映射"

---

**Schema 整合讨论：**
用户指出需要考虑 QQ bot 消息所有可能的组合（文本/文本+图片/文本+@/文本+reply 等），建议 send action 覆盖所有组合。
结论：`send` action 包含 text + images + render_to_image + reply_to + at_user + target，多字段可共存。

---

## 文转图触发方式

| Option | Description | Selected |
|--------|-------------|----------|
| message 工具里的 render action | 独立 action="render_to_image" | |
| send action 的 render 参数 | send action 内嵌 render_markdown 字段 | |
| 独立 computer 工具 | agent 先 bash 运行 playwright，再 send | |

**User's choice:** message 工具里的 render action（初始选择）

后续修正：用户说 "render_to_image不应该是action，应该是send"，"render_to_image应该是渲染这个字段里的内容成图片"
**最终决策：** `render_to_image` 是 `send` action 的可选字段，不是独立 action。字段有内容即渲染并作为图片发出，可与 text/images 共存。

---

| Option | Description | Selected |
|--------|-------------|----------|
| 渲染 + 直接发送 | action 内部渲染后通过 Outbox 发送 | ✓ |
| 渲染后返回路径 | 返回图片路径给 agent，再由 agent 决定发送 | |

**User's choice:** 渲染 + 直接发送

---

## Playwright 生命周期管理

| Option | Description | Selected |
|--------|-------------|----------|
| Bootstrap 级别，注入 Outbox | PlaywrightRenderer 作为 RuntimeComponents 字段 | 太耦合，否决 |
| Outbox 内部管理 | Outbox 自己拥有 browser | 太耦合，否决 |
| RuntimeApp 直接管理 | RuntimeApp start/stop 时管理 PlaywrightRenderer | |
| 和 RuntimeScheduler 一样的模式 | bootstrap 构建实例，RuntimeApp start/stop 调用 | |

**User's choice:** 用户说"太耦合了"后要求记录已定内容，具体集成点留作 Claude 自决
**Notes:** 用户认为前两个选项耦合性太强，倾向于 PlaywrightRenderer 作为独立服务，但未明确指定集成点

---

## 跨会话 target 设计

讨论被用户中断，未完成选择。

**留作 Claude 自决：** 推荐沿用 session_key 格式（与现有 session_config 基础设施对齐），如 `"group:123456"`

---

## Claude's Discretion

- `target` 字段的具体格式和解析逻辑
- PlaywrightRenderer 生命周期集成具体实现（参考 RuntimeScheduler 模式）
- emoji 映射表初始收录范围
- 渲染临时文件存储位置和清理策略
- message 工具注册到 BuiltinMessagingToolSurface 的实现细节

## Deferred Ideas

- 合并转发消息 (MSG-V2-01) — OneBot v11 复杂，v1 不做
- Interactive components（按钮/卡片）— v2 需求
- 通过 list_sessions 查询跨会话目标 — 暂不实现
