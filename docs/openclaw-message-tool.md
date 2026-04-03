# OpenClaw `message` 工具深度分析

本文档基于对 OpenClaw 源码的深入研究，系统整理了 `message` 工具的完整定义、Schema 结构、能力体系和执行路径。

---

## 1. 工具概述

| 属性 | 值 |
|------|-----|
| 工具名称 | `"message"` |
| 显示标签 | `"Message"` |
| 摘要 | `"Send and manage messages across configured channels."` |
| 核心文件 | `src/agents/tools/message-tool.ts`（805 行） |
| 执行引擎 | `src/infra/outbound/message-action-runner.ts`（834 行） |

`message` 工具是 OpenClaw 中唯一的消息操作工具，是一个**统一的超级工具**，支持 58+ 个操作（action），通过 `action` 参数路由到各渠道插件。工具描述和 Schema 在运行时根据当前渠道上下文**动态生成**。

---

## 2. 工具注册与创建

### 2.1 工厂函数

```typescript
// src/agents/tools/message-tool.ts
export function createMessageTool(options?: MessageToolOptions): AnyAgentTool
```

### 2.2 注册入口

```typescript
// src/agents/openclaw-tools.ts
const messageTool = options?.disableMessageTool
  ? null
  : createMessageTool({
      agentAccountId: options?.agentAccountId,
      agentSessionKey: options?.agentSessionKey,
      sessionId: options?.sessionId,
      config: options?.config,
      currentChannelId: options?.currentChannelId,
      currentChannelProvider: options?.currentChannelProvider,
      // ...
    });

// 加入工具列表
...(messageTool ? [messageTool] : []),
```

`disableMessageTool` 选项允许在特定场景下完全禁用该工具。

### 2.3 返回的工具对象结构

```typescript
return {
  label: "Message",
  name: "message",
  displaySummary: "Send and manage messages across configured channels.",
  description,        // 动态生成，基于当前渠道上下文
  parameters: schema, // 动态生成，基于当前渠道上下文
  execute: async (_toolCallId, args, signal) => { ... }
};
```

---

## 3. `MessageToolOptions` 参数类型

工具创建时接受的完整选项：

```typescript
type MessageToolOptions = {
  agentAccountId?: string;          // Agent 账号 ID
  agentSessionKey?: string;         // Agent 会话密钥
  sessionId?: string;               // 会话 ID
  config?: OpenClawConfig;          // OpenClaw 配置对象
  loadConfig?: () => OpenClawConfig; // 配置加载函数（可注入）
  resolveCommandSecretRefsViaGateway?: typeof resolveCommandSecretRefsViaGateway; // 密钥解析（可注入）
  runMessageAction?: typeof runMessageAction; // 消息执行函数（可注入）
  currentChannelId?: string;        // 当前渠道 ID
  currentChannelProvider?: string;  // 当前渠道提供商（如 "telegram", "discord"）
  currentThreadTs?: string;         // 当前线程时间戳（Slack）
  currentMessageId?: string | number; // 当前消息 ID
  replyToMode?: "off" | "first" | "all"; // 回复模式
  hasRepliedRef?: { value: boolean }; // 是否已回复的引用
  sandboxRoot?: string;             // 沙盒根目录
  requireExplicitTarget?: boolean;  // 是否要求显式指定目标
  requesterSenderId?: string;       // 请求者发送者 ID
};
```

---

## 4. 完整 Schema 定义

Schema 在运行时由多个子 Schema 合并构建，以下是各子模块的完整字段定义。

### 4.1 顶级结构

```typescript
Type.Object({
  action: stringEnum(actions),  // 必填，操作类型枚举
  // ... 以下所有子 Schema 的字段展开合并
})
```

`action` 是唯一的必填字段，其余所有字段均为 `Optional`。

---

### 4.2 路由 Schema（`buildRoutingSchema`）

控制消息的目标渠道和账号路由：

```typescript
{
  channel: Type.Optional(Type.String()),
  // 目标渠道标识（如 "telegram", "discord"）

  target: Type.Optional(channelTargetSchema({
    description: "Target channel/user id or name."
  })),
  // 目标频道/用户 ID 或名称

  targets: Type.Optional(channelTargetsSchema()),
  // 多目标数组

  accountId: Type.Optional(Type.String()),
  // 账号 ID（用于多账号场景）

  dryRun: Type.Optional(Type.Boolean()),
  // 是否为演习模式（不实际发送）
}
```

---

### 4.3 发送 Schema（`buildSendSchema`）

控制消息内容和发送行为：

```typescript
{
  message: Type.Optional(Type.String()),
  // 消息正文文本

  effectId: Type.Optional(Type.String({
    description: "Message effect name/id for sendWithEffect (e.g., invisible ink)."
  })),
  // 消息特效 ID（如 iMessage 的隐形墨水效果）

  effect: Type.Optional(Type.String({
    description: "Alias for effectId (e.g., invisible-ink, balloons)."
  })),
  // effectId 的别名

  media: Type.Optional(Type.String({
    description: "Media URL or local path. data: URLs are not supported here, use buffer."
  })),
  // 媒体 URL 或本地路径（不支持 data: URL）

  filename: Type.Optional(Type.String()),
  // 文件名

  buffer: Type.Optional(Type.String({
    description: "Base64 payload for attachments (optionally a data: URL)."
  })),
  // Base64 编码的附件内容（可选 data: URL 格式）

  contentType: Type.Optional(Type.String()),
  // 内容类型

  mimeType: Type.Optional(Type.String()),
  // MIME 类型

  caption: Type.Optional(Type.String()),
  // 媒体说明文字

  path: Type.Optional(Type.String()),
  // 文件路径（别名）

  filePath: Type.Optional(Type.String()),
  // 文件路径

  replyTo: Type.Optional(Type.String()),
  // 被回复的消息 ID

  threadId: Type.Optional(Type.String()),
  // 线程 ID

  asVoice: Type.Optional(Type.Boolean()),
  // 是否以语音消息方式发送

  silent: Type.Optional(Type.Boolean()),
  // 是否静默发送（不通知）

  quoteText: Type.Optional(Type.String({
    description: "Quote text for Telegram reply_parameters"
  })),
  // 引用文字（Telegram 的 reply_parameters）

  bestEffort: Type.Optional(Type.Boolean()),
  // 是否尽力而为（忽略非致命错误）

  gifPlayback: Type.Optional(Type.Boolean()),
  // 是否以 GIF 动画方式播放

  forceDocument: Type.Optional(Type.Boolean({
    description: "Send image/GIF as document to avoid Telegram compression (Telegram only)."
  })),
  // 强制以文件方式发送，避免 Telegram 压缩（仅 Telegram）

  asDocument: Type.Optional(Type.Boolean({
    description: "Send image/GIF as document to avoid Telegram compression. Alias for forceDocument (Telegram only)."
  })),
  // forceDocument 的别名（仅 Telegram）

  interactive: Type.Optional(interactiveMessageSchema),
  // 交互式消息块（仅在渠道支持 interactive 能力时包含）
}
```

#### 交互式消息 Schema（`interactive` 字段）

仅在渠道支持 `interactive` 能力时包含：

```typescript
// 交互式选项（用于 select）
const interactiveOptionSchema = Type.Object({
  label: Type.String(),
  value: Type.String(),
});

// 交互式按钮
const interactiveButtonSchema = Type.Object({
  label: Type.String(),
  value: Type.String(),
  style: Type.Optional(stringEnum(["primary", "secondary", "success", "danger"])),
});

// 交互式块（文本/按钮/选择）
const interactiveBlockSchema = Type.Object({
  type: stringEnum(["text", "buttons", "select"]),
  text: Type.Optional(Type.String()),
  buttons: Type.Optional(Type.Array(interactiveButtonSchema)),
  placeholder: Type.Optional(Type.String()),
  options: Type.Optional(Type.Array(interactiveOptionSchema)),
});

// 完整的交互式消息
const interactiveMessageSchema = Type.Object({
  blocks: Type.Array(interactiveBlockSchema),
}, {
  description: "Shared interactive message payload for buttons and selects. Channels render this into their native components when supported."
});
```

---

### 4.4 反应 Schema（`buildReactionSchema`）

用于消息表情反应操作：

```typescript
{
  messageId: Type.Optional(Type.String({
    description: "Target message id for reaction. If omitted, defaults to the current inbound message id when available."
  })),
  // 目标消息 ID（省略时默认为当前入站消息）

  message_id: Type.Optional(Type.String({
    description: "snake_case alias of messageId. If omitted, defaults to the current inbound message id when available."
  })),
  // messageId 的 snake_case 别名（LLM 易用性）

  emoji: Type.Optional(Type.String()),
  // 表情符号

  remove: Type.Optional(Type.Boolean()),
  // 是否移除反应

  targetAuthor: Type.Optional(Type.String()),
  // 目标作者（Signal 专用）

  targetAuthorUuid: Type.Optional(Type.String()),
  // 目标作者 UUID（Signal 专用）

  groupId: Type.Optional(Type.String()),
  // 群组 ID（Signal 专用）
}
```

---

### 4.5 获取 Schema（`buildFetchSchema`）

用于读取消息和翻页：

```typescript
{
  limit: Type.Optional(Type.Number()),
  // 最大数量

  pageSize: Type.Optional(Type.Number()),
  // 每页数量

  pageToken: Type.Optional(Type.String()),
  // 翻页令牌

  before: Type.Optional(Type.String()),
  // 消息 ID 游标（之前）

  after: Type.Optional(Type.String()),
  // 消息 ID 游标（之后）

  around: Type.Optional(Type.String()),
  // 消息 ID 游标（周围）

  fromMe: Type.Optional(Type.Boolean()),
  // 是否只获取自己发送的消息

  includeArchived: Type.Optional(Type.Boolean()),
  // 是否包含已归档的内容
}
```

---

### 4.6 投票 Schema（`buildPollSchema`）

用于创建和投票操作：

```typescript
{
  // 投票创建参数（来自 SHARED_POLL_CREATION_PARAM_NAMES）
  pollQuestion: Type.Optional(Type.String()),
  // 投票问题

  pollOption: Type.Optional(Type.Array(Type.String())),
  // 投票选项列表

  pollDurationHours: Type.Optional(Type.Number()),
  // 投票持续时间（小时）

  pollMulti: Type.Optional(Type.Boolean()),
  // 是否允许多选

  // 投票投票参数
  pollId: Type.Optional(Type.String()),
  // 投票 ID

  pollOptionId: Type.Optional(Type.String({
    description: "Poll answer id to vote for. Use when the channel exposes stable answer ids."
  })),
  // 要投票的选项 ID（稳定 ID 时使用）

  pollOptionIds: Type.Optional(Type.Array(Type.String({
    description: "Poll answer ids to vote for in a multiselect poll. Use when the channel exposes stable answer ids."
  }))),
  // 多选投票选项 ID 列表

  pollOptionIndex: Type.Optional(Type.Number({
    description: "1-based poll option number to vote for, matching the rendered numbered poll choices."
  })),
  // 1-based 投票选项编号

  pollOptionIndexes: Type.Optional(Type.Array(Type.Number({
    description: "1-based poll option numbers to vote for in a multiselect poll, matching the rendered numbered poll choices."
  }))),
  // 多选投票选项编号列表
}
```

**注意**：Telegram 特有的投票参数（`pollDurationSeconds`, `pollAnonymous`, `pollPublic`）由 Telegram 插件通过 `describeMessageTool()` 贡献到 Schema 的 `extraProperties` 中，不在基础 Schema 中。

---

### 4.7 频道目标 Schema（`buildChannelTargetSchema`）

用于指定操作的频道、成员、角色等目标：

```typescript
{
  channelId: Type.Optional(Type.String({
    description: "Channel id filter (search/thread list/event create)."
  })),
  // 频道 ID 筛选

  chatId: Type.Optional(Type.String({
    description: "Chat id for chat-scoped metadata actions."
  })),
  // 聊天 ID（聊天范围元数据操作）

  channelIds: Type.Optional(Type.Array(Type.String({
    description: "Channel id filter (repeatable)."
  }))),
  // 多个频道 ID

  memberId: Type.Optional(Type.String()),
  // 成员 ID

  memberIdType: Type.Optional(Type.String()),
  // 成员 ID 类型

  guildId: Type.Optional(Type.String()),
  // 服务器 ID（Discord 专用）

  userId: Type.Optional(Type.String()),
  // 用户 ID

  openId: Type.Optional(Type.String()),
  // 开放平台 ID（Feishu 专用）

  unionId: Type.Optional(Type.String()),
  // 统一 ID（Feishu 专用）

  authorId: Type.Optional(Type.String()),
  // 作者 ID

  authorIds: Type.Optional(Type.Array(Type.String())),
  // 多个作者 ID

  roleId: Type.Optional(Type.String()),
  // 角色 ID

  roleIds: Type.Optional(Type.Array(Type.String())),
  // 多个角色 ID

  participant: Type.Optional(Type.String()),
  // 参与者

  includeMembers: Type.Optional(Type.Boolean()),
  // 是否包含成员信息

  members: Type.Optional(Type.Boolean()),
  // 成员标志

  scope: Type.Optional(Type.String()),
  // 操作范围

  kind: Type.Optional(Type.String()),
  // 种类/类型
}
```

---

### 4.8 贴纸 Schema（`buildStickerSchema`）

```typescript
{
  emojiName: Type.Optional(Type.String()),
  // 表情符号名称

  stickerId: Type.Optional(Type.Array(Type.String())),
  // 贴纸 ID 数组

  stickerName: Type.Optional(Type.String()),
  // 贴纸名称

  stickerDesc: Type.Optional(Type.String()),
  // 贴纸描述

  stickerTags: Type.Optional(Type.String()),
  // 贴纸标签
}
```

---

### 4.9 线程 Schema（`buildThreadSchema`）

```typescript
{
  threadName: Type.Optional(Type.String()),
  // 线程名称

  autoArchiveMin: Type.Optional(Type.Number()),
  // 自动归档时间（分钟）

  appliedTags: Type.Optional(Type.Array(Type.String())),
  // 应用的标签（Discord Forum 频道）
}
```

---

### 4.10 事件 Schema（`buildEventSchema`）

```typescript
{
  query: Type.Optional(Type.String()),
  // 搜索/查询字符串

  eventName: Type.Optional(Type.String()),
  // 事件名称

  eventType: Type.Optional(Type.String()),
  // 事件类型

  startTime: Type.Optional(Type.String()),
  // 开始时间

  endTime: Type.Optional(Type.String()),
  // 结束时间

  desc: Type.Optional(Type.String()),
  // 描述

  location: Type.Optional(Type.String()),
  // 地点

  durationMin: Type.Optional(Type.Number()),
  // 持续时长（分钟）

  until: Type.Optional(Type.String()),
  // 截止时间
}
```

---

### 4.11 审核 Schema（`buildModerationSchema`）

```typescript
{
  reason: Type.Optional(Type.String()),
  // 操作原因

  deleteDays: Type.Optional(Type.Number()),
  // 删除消息天数（封禁时）
}
```

---

### 4.12 Gateway Schema（`buildGatewaySchema`）

```typescript
{
  gatewayUrl: Type.Optional(Type.String()),
  // Gateway 地址

  gatewayToken: Type.Optional(Type.String()),
  // Gateway 令牌

  timeoutMs: Type.Optional(Type.Number()),
  // 超时时间（毫秒）
}
```

---

### 4.13 频道管理 Schema（`buildChannelManagementSchema`）

```typescript
{
  name: Type.Optional(Type.String()),
  // 频道/分类名称

  type: Type.Optional(Type.Number()),
  // 频道类型（Discord channel type 枚举）

  parentId: Type.Optional(Type.String()),
  // 父分类 ID

  topic: Type.Optional(Type.String()),
  // 频道话题

  position: Type.Optional(Type.Number()),
  // 排序位置

  nsfw: Type.Optional(Type.Boolean()),
  // 是否为 NSFW 频道

  rateLimitPerUser: Type.Optional(Type.Number()),
  // 用户发言冷却时间

  categoryId: Type.Optional(Type.String()),
  // 分类 ID

  clearParent: Type.Optional(Type.Boolean({
    description: "Clear the parent/category when supported by the provider."
  })),
  // 清除父分类关联
}
```

---

### 4.14 存在状态 Schema（`buildPresenceSchema`）

```typescript
{
  activityType: Type.Optional(Type.String({
    description: "Activity type: playing, streaming, listening, watching, competing, custom."
  })),
  // 活动类型

  activityName: Type.Optional(Type.String({
    description: "Activity name shown in sidebar (e.g. 'with fire'). Ignored for custom type."
  })),
  // 活动名称（在侧边栏显示）

  activityUrl: Type.Optional(Type.String({
    description: "Streaming URL (Twitch or YouTube). Only used with streaming type; may not render for bots."
  })),
  // 直播 URL（Twitch 或 YouTube）

  activityState: Type.Optional(Type.String({
    description: "State text. For custom type this is the status text; for others it shows in the flyout."
  })),
  // 状态文本

  status: Type.Optional(Type.String({
    description: "Bot status: online, dnd, idle, invisible."
  })),
  // Bot 在线状态
}
```

---

## 5. 完整的 Action 列表（58+ 个）

所有支持的操作名称定义在 `src/channels/plugins/message-action-names.ts`：

```typescript
export const CHANNEL_MESSAGE_ACTION_NAMES = [
  // 基础发送
  "send",           // 发送消息
  "broadcast",      // 广播到多个目标
  "reply",          // 回复消息
  "sendWithEffect", // 带特效发送（iMessage）
  "sendAttachment", // 发送附件

  // 投票
  "poll",           // 创建投票
  "poll-vote",      // 投票

  // 反应
  "react",          // 添加表情反应
  "reactions",      // 获取消息反应列表

  // 消息管理
  "read",           // 标记已读
  "edit",           // 编辑消息
  "unsend",         // 撤回消息
  "delete",         // 删除消息
  "pin",            // 置顶消息
  "unpin",          // 取消置顶
  "list-pins",      // 列出置顶消息

  // 群组管理
  "renameGroup",    // 重命名群组
  "setGroupIcon",   // 设置群组图标
  "addParticipant", // 添加参与者
  "removeParticipant", // 移除参与者
  "leaveGroup",     // 退出群组

  // 权限
  "permissions",    // 管理权限

  // 线程
  "thread-create",  // 创建线程
  "thread-list",    // 列出线程
  "thread-reply",   // 在线程中回复

  // 搜索
  "search",         // 搜索消息

  // 贴纸
  "sticker",        // 发送贴纸
  "sticker-search", // 搜索贴纸
  "sticker-upload", // 上传贴纸

  // 成员与角色信息
  "member-info",    // 获取成员信息
  "role-info",      // 获取角色信息
  "emoji-list",     // 列出 Emoji
  "emoji-upload",   // 上传 Emoji
  "role-add",       // 添加角色
  "role-remove",    // 移除角色

  // 频道管理
  "channel-info",   // 获取频道信息
  "channel-list",   // 列出频道
  "channel-create", // 创建频道
  "channel-edit",   // 编辑频道
  "channel-delete", // 删除频道
  "channel-move",   // 移动频道

  // 分类管理
  "category-create", // 创建分类
  "category-edit",   // 编辑分类
  "category-delete", // 删除分类

  // 话题管理
  "topic-create",   // 创建话题
  "topic-edit",     // 编辑话题

  // 语音
  "voice-status",   // 获取/设置语音状态

  // 日程事件
  "event-list",     // 列出事件
  "event-create",   // 创建事件

  // 审核
  "timeout",        // 禁言
  "kick",           // 踢出成员
  "ban",            // 封禁成员

  // 个人资料与状态
  "set-profile",    // 设置个人资料
  "set-presence",   // 设置存在状态

  // 文件
  "download-file",  // 下载文件
  "upload-file",    // 上传文件
] as const;
```

### 需要显式目标的操作（`EXPLICIT_TARGET_ACTIONS`）

以下操作在 `requireExplicitTarget = true` 时必须提供明确的目标：

```typescript
const EXPLICIT_TARGET_ACTIONS = new Set([
  "send",
  "sendWithEffect",
  "sendAttachment",
  "upload-file",
  "reply",
  "thread-reply",
  "broadcast",
]);
```

---

## 6. 渠道能力体系（ChannelMessageCapability）

定义在 `src/channels/plugins/message-capabilities.ts`，5 种能力标志：

```typescript
export const CHANNEL_MESSAGE_CAPABILITIES = [
  "interactive", // 支持交互式消息（按钮、选择器）
  "buttons",     // 支持 provider 原生按钮行（如 Telegram 内联键盘）
  "cards",       // 支持结构化卡片消息（如 Slack attachments）
  "components",  // 支持高级组件（如 Discord Components v2）
  "blocks",      // 支持块元素（如 Slack Block Kit）
] as const;
```

能力对 Schema 的影响：
- `interactive` → 决定是否在 Schema 中包含 `interactive` 字段
- `buttons` → 插件通过 `describeMessageTool()` 贡献 buttons Schema 片段
- `cards` → 插件通过 `describeMessageTool()` 贡献 card Schema 片段
- `components`/`blocks` → 同上

---

## 7. 动态 Schema 生成机制

### 7.1 Schema 构建流程

```
createMessageTool(options)
  └── buildMessageToolSchema(params)
        ├── resolveMessageToolSchemaActions(params)  → actions[]
        │     ├── 当前渠道支持的操作
        │     └── 其他已配置渠道的操作（合并）
        ├── resolveIncludeInteractive(params)         → boolean
        │     └── channelSupportsMessageCapability(cfg, "interactive")
        └── resolveChannelMessageToolSchemaProperties(params) → extraProperties
              └── 各插件 describeMessageTool() 贡献的 Schema 片段（按 visibility 筛选）
```

### 7.2 `buildMessageToolSchema` 源码

```typescript
function buildMessageToolSchema(params: {
  cfg: OpenClawConfig;
  currentChannelProvider?: string;
  currentChannelId?: string;
  currentThreadTs?: string;
  currentMessageId?: string | number;
  currentAccountId?: string;
  sessionKey?: string;
  sessionId?: string;
  agentId?: string;
  requesterSenderId?: string;
}) {
  const actions = resolveMessageToolSchemaActions(params);
  const includeInteractive = resolveIncludeInteractive(params);
  const extraProperties = resolveChannelMessageToolSchemaProperties({
    cfg: params.cfg,
    channel: normalizeMessageChannel(params.currentChannelProvider),
    // ...
  });
  return buildMessageToolSchemaFromActions(
    actions.length > 0 ? actions : ["send"],
    { includeInteractive, extraProperties }
  );
}
```

### 7.3 动态 Action 解析逻辑

```typescript
function resolveMessageToolSchemaActions(params): string[] {
  const currentChannel = normalizeMessageChannel(params.currentChannelProvider);
  if (currentChannel) {
    // 1. 从当前渠道获取支持的操作
    const scopedActions = listChannelSupportedActions({ ... });
    const allActions = new Set<string>(["send", ...scopedActions]);

    // 2. 加入其他已配置渠道的操作（跨渠道操作支持）
    for (const plugin of listChannelPlugins()) {
      if (plugin.id === currentChannel) continue;
      for (const action of listChannelSupportedActions({ cfg, channel: plugin.id, ... })) {
        allActions.add(action);
      }
    }
    return Array.from(allActions);
  }
  // 无当前渠道时，返回所有已配置渠道的操作
  const actions = listChannelMessageActions(params.cfg);
  return actions.length > 0 ? actions : ["send"];
}
```

### 7.4 无 config 时的 fallback

如果创建工具时没有传入 `config`（即 `options?.config` 为空），则使用**静态全量 Schema**：

```typescript
const MessageToolSchema = buildMessageToolSchemaFromActions(AllMessageActions, {
  includeInteractive: true,
});
```

这是包含所有 58+ 个 action 和完整字段的"最大 Schema"。

---

## 8. 插件 Schema 贡献机制

### 8.1 插件接口

渠道插件通过实现 `ChannelMessageActionAdapter.describeMessageTool()` 方法来声明支持的操作和 Schema 贡献：

```typescript
// src/channels/plugins/types.core.ts
type ChannelMessageActionAdapter = {
  describeMessageTool(
    ctx: ChannelMessageActionDiscoveryContext
  ): ChannelMessageToolDiscovery | undefined;
  // ...
};

type ChannelMessageToolDiscovery = {
  actions?: readonly ChannelMessageActionName[];
  capabilities?: readonly ChannelMessageCapability[];
  schema?: ChannelMessageToolSchemaContribution;
};

type ChannelMessageToolSchemaContribution = {
  properties: Record<string, TSchema>;
  visibility?: "current-channel" | "all-configured";
  // "current-channel"  → 仅在当前渠道上下文中显示该字段
  // "all-configured"   → 在所有已配置渠道中都显示（默认）
};
```

### 8.2 Discovery 上下文

插件收到的发现上下文包含完整的会话信息：

```typescript
type ChannelMessageActionDiscoveryContext = {
  cfg?: OpenClawConfig;           // 配置
  currentChannelId?: string;      // 当前频道 ID
  currentChannelProvider?: string; // 当前渠道提供商
  currentThreadTs?: string;       // 当前线程时间戳
  currentMessageId?: string | number; // 当前消息 ID
  accountId?: string;             // 账号 ID
  sessionKey?: string;            // 会话密钥
  sessionId?: string;             // 会话 ID
  agentId?: string;               // Agent ID
  requesterSenderId?: string;     // 请求者发送者 ID
};
```

### 8.3 Telegram 插件示例（测试文件中的示例）

```typescript
// Telegram 插件贡献的 Schema（包含 Telegram 专有参数）
{
  actions: ["send", "react", "poll", "edit", "delete", "pin", "unpin", ...],
  capabilities: ["interactive", "buttons"],
  schema: {
    properties: {
      pollDurationSeconds: Type.Optional(Type.Number()),
      pollAnonymous: Type.Optional(Type.Boolean()),
      pollPublic: Type.Optional(Type.Boolean()),
      // buttons schema（来自 createMessageToolButtonsSchema()）
      buttons: Type.Optional(Type.Array(Type.Array(Type.Object({
        text: Type.String(),
        callback_data: Type.String(),
        style: Type.Optional(createStringEnum(["danger", "success", "primary"])),
      })))),
    },
    visibility: "current-channel", // 仅在 Telegram 上下文中出现
  }
}
```

### 8.4 通用 Schema 辅助函数

插件 SDK 提供了两个标准 Schema 辅助函数（`src/plugin-sdk/channel-actions.ts`）：

```typescript
/** 按钮行 Schema（用于支持按钮的渠道） */
export function createMessageToolButtonsSchema(): TSchema {
  return Type.Optional(
    Type.Array(
      Type.Array(
        Type.Object({
          text: Type.String(),
          callback_data: Type.String(),
          style: Type.Optional(createStringEnum(["danger", "success", "primary"])),
        }),
      ),
      { description: "Button rows for channels that support button-style actions." },
    ),
  );
}

/** 卡片 Schema（用于支持卡片的渠道） */
export function createMessageToolCardSchema(): TSchema {
  return Type.Optional(
    Type.Object(
      {},
      {
        additionalProperties: true,
        description: "Structured card payload for channels that support card-style messages.",
      },
    ),
  );
}
```

---

## 9. 工具描述动态生成

```typescript
function buildMessageToolDescription(options?: { ... }): string {
  const baseDescription = "Send, delete, and manage messages via channel plugins.";

  if (currentChannel) {
    // 有当前渠道：列出当前渠道的支持操作，并附上其他渠道
    const actionList = Array.from(allActions).toSorted().join(", ");
    let desc = `${baseDescription} Current channel (${currentChannel}) supports: ${actionList}.`;

    // 附上其他已配置渠道
    const otherChannels = [...]; // "discord (ban, channel-info, send, ...)"
    if (otherChannels.length > 0) {
      desc += ` Other configured channels: ${otherChannels.join(", ")}.`;
    }
    return desc;
  }

  // 无当前渠道：列出所有已配置渠道的操作
  if (config) {
    const actions = listChannelMessageActions(config);
    if (actions.length > 0) {
      return `${baseDescription} Supports actions: ${actions.join(", ")}.`;
    }
  }

  // 兜底描述
  return `${baseDescription} Supports actions: send, delete, react, poll, pin, threads, and more.`;
}
```

---

## 10. 工具执行流程（`execute`）

### 10.1 执行函数核心逻辑

```typescript
execute: async (_toolCallId, args, signal) => {
  // 1. 中止检测
  if (signal?.aborted) throw new AbortError();

  // 2. 浅拷贝参数（避免污染原始事件参数，用于日志/去重）
  const params = { ...(args as Record<string, unknown>) };

  // 3. 过滤推理标签（模型可能在参数中包含 <think>...</think>）
  for (const field of ["text", "content", "message", "caption"]) {
    if (typeof params[field] === "string") {
      params[field] = stripReasoningTagsFromText(params[field]);
    }
  }

  // 4. 读取 action 参数（必填）
  const action = readStringParam(params, "action", { required: true });

  // 5. 加载配置（动态或从 options 获取）
  let cfg = options?.config;
  if (!cfg) {
    const loadedRaw = loadConfigForTool();
    // 解析密钥范围（基于 channel/target/accountId）
    const scope = resolveMessageSecretScope({ ... });
    // 解析 Gateway 中的密钥引用
    cfg = (await resolveSecretRefsForTool({
      config: loadedRaw,
      commandName: "tools.message",
      targetIds: scopedTargets.targetIds,
      mode: "enforce_resolved",
    })).resolvedConfig;
  }

  // 6. 显式目标检查（requireExplicitTarget 模式）
  if (requireExplicitTarget && actionNeedsExplicitTarget(action)) {
    const hasTarget = params.target || params.to || params.channelId || params.targets;
    if (!hasTarget) throw new Error("Explicit message target required...");
  }

  // 7. 解析 Gateway 选项
  const gateway = {
    url: gatewayResolved.url,
    token: gatewayResolved.token,
    timeoutMs: gatewayResolved.timeoutMs,
    clientName: GATEWAY_CLIENT_IDS.GATEWAY_CLIENT,
    clientDisplayName: "agent",
    mode: GATEWAY_CLIENT_MODES.BACKEND,
  };

  // 8. 构建工具上下文（跨渠道装饰控制）
  const toolContext = { ... skipCrossContextDecoration: true };

  // 9. 执行消息操作
  const result = await runMessageActionForTool({
    cfg, action, params,
    defaultAccountId, requesterSenderId,
    gateway, toolContext,
    sessionKey, sessionId, agentId,
    sandboxRoot, abortSignal: signal,
  });

  // 10. 返回结果
  const toolResult = getToolResult(result);
  if (toolResult) return toolResult;
  return jsonResult(result.payload);
}
```

### 10.2 `runMessageAction` 执行引擎

`src/infra/outbound/message-action-runner.ts` 中的 `runMessageAction()` 是实际执行入口：

```
runMessageAction(input)
  ├── action === "broadcast"  → handleBroadcastAction()
  ├── action === "send" / "sendWithEffect" / "sendAttachment" / "reply" / "thread-reply"
  │     └── handleSendAction()
  ├── action === "poll"       → handlePollAction()
  └── 其他操作               → handlePluginAction()
        └── 路由到对应渠道插件的 executeMessageAction()
```

返回结果类型（`MessageActionRunResult` 判别联合）：
- `kind: "send"` — 发送成功
- `kind: "broadcast"` — 广播成功
- `kind: "poll"` — 投票操作成功
- `kind: "action"` — 其他操作成功

---

## 11. Schema 合并逻辑汇总

### 11.1 最终 Schema 的字段来源

```
最终 Schema
  ├── action: stringEnum(actions)          ← 动态枚举（基于渠道）
  │
  ├── buildRoutingSchema()                 ← 固定字段
  │     channel, target, targets, accountId, dryRun
  │
  ├── buildSendSchema({ includeInteractive })
  │     message, effectId, effect, media, filename, buffer,
  │     contentType, mimeType, caption, path, filePath,
  │     replyTo, threadId, asVoice, silent, quoteText,
  │     bestEffort, gifPlayback, forceDocument, asDocument,
  │     interactive (仅当 interactive 能力为 true)
  │
  ├── buildReactionSchema()
  │     messageId, message_id, emoji, remove,
  │     targetAuthor, targetAuthorUuid, groupId
  │
  ├── buildFetchSchema()
  │     limit, pageSize, pageToken, before, after,
  │     around, fromMe, includeArchived
  │
  ├── buildPollSchema()
  │     pollQuestion, pollOption, pollDurationHours, pollMulti,
  │     pollId, pollOptionId, pollOptionIds,
  │     pollOptionIndex, pollOptionIndexes
  │
  ├── buildChannelTargetSchema()
  │     channelId, chatId, channelIds, memberId, memberIdType,
  │     guildId, userId, openId, unionId, authorId, authorIds,
  │     roleId, roleIds, participant, includeMembers, members,
  │     scope, kind
  │
  ├── buildStickerSchema()
  │     emojiName, stickerId, stickerName, stickerDesc, stickerTags
  │
  ├── buildThreadSchema()
  │     threadName, autoArchiveMin, appliedTags
  │
  ├── buildEventSchema()
  │     query, eventName, eventType, startTime, endTime,
  │     desc, location, durationMin, until
  │
  ├── buildModerationSchema()
  │     reason, deleteDays
  │
  ├── buildGatewaySchema()
  │     gatewayUrl, gatewayToken, timeoutMs
  │
  ├── buildChannelManagementSchema()
  │     name, type, parentId, topic, position, nsfw,
  │     rateLimitPerUser, categoryId, clearParent
  │
  ├── buildPresenceSchema()
  │     activityType, activityName, activityUrl, activityState, status
  │
  └── extraProperties (来自插件 describeMessageTool())
        例如 Telegram: buttons, pollDurationSeconds, pollAnonymous, pollPublic
        例如 Discord:  buttons (原生组件)
        例如 Slack:    blocks (Block Kit)
```

---

## 12. 关键文件索引

| 文件 | 作用 |
|------|------|
| `src/agents/tools/message-tool.ts` | 工具定义核心（工厂函数、Schema 构建、execute 逻辑）|
| `src/infra/outbound/message-action-runner.ts` | 消息操作执行引擎 |
| `src/channels/plugins/message-action-names.ts` | 所有 action 名称常量 |
| `src/channels/plugins/message-capabilities.ts` | 5 种能力标志常量 |
| `src/channels/plugins/message-action-discovery.ts` | Schema 发现与合并逻辑 |
| `src/channels/plugins/types.core.ts` | 核心类型：`ChannelMessageActionAdapter`、`ChannelMessageToolDiscovery` 等 |
| `src/plugin-sdk/channel-actions.ts` | 插件 SDK Schema 辅助函数（buttons、card） |
| `src/poll-params.ts` | 投票参数定义 |
| `src/agents/openclaw-tools.ts` | 工具注册入口 |
| `src/agents/tools/message-tool.test.ts` | 完整测试（947 行，含插件 API 使用示例） |

---

## 13. 设计要点总结

1. **统一入口**：所有渠道的所有消息操作都通过单一的 `message` 工具，用 `action` 参数区分
2. **动态 Schema**：Schema 在运行时根据当前渠道上下文动态生成，仅暴露当前场景相关的 action 枚举
3. **插件扩展**：渠道插件通过 `describeMessageTool()` 贡献自己的 action 列表、能力和 Schema 字段
4. **能力门控**：`interactive`/`buttons`/`cards` 等能力标志控制高级字段是否出现在 Schema 中
5. **密钥安全**：执行时通过 Gateway 动态解析密钥引用，支持范围限定的密钥访问
6. **推理标签过滤**：自动剥离 LLM 推理过程中可能注入到文本字段的 `<think>` 标签
7. **跨渠道路由**：当前渠道上下文的工具也包含其他已配置渠道的 action，支持跨渠道操作
