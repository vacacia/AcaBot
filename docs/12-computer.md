# computer 子系统

这一篇讲的是 AcaBot 里的 `computer`。

它不是“给模型直接用的一组工具”那么简单，更准确地说，它是 workspace、附件落地、shell session 和执行后端的基础设施层。上面那层再通过 plugin / tool adapter 暴露给 bot。

关键文件:

- `src/acabot/runtime/computer.py`
- `src/acabot/runtime/plugins/computer_tool_adapter.py`
- `src/acabot/runtime/bootstrap.py`

## 这层到底负责什么

`computer` 现在主要负责四件事:

- 管 thread 级 workspace
- 把 inbound attachment 落到本地
- 提供 exec / bash session 这类执行能力
- 给 skill mirror 留接缝

不要把它理解成“一个工具集合”。工具只是它的上层接口形态。

## 关键对象

### `ComputerPolicy`

这是 agent 级稳定策略。

主要字段:

- `backend`
- `read_only`
- `allow_write`
- `allow_exec`
- `allow_sessions`
- `auto_stage_attachments`
- `network_mode`

它表达的是“这个 agent 默认怎么使用 computer 子系统”，不是某次 run 的临时状态。

### `ComputerRuntimeOverride`

这是 thread metadata 里的临时 override。

它只覆盖 thread 级行为，不改 profile 真源。

### `WorkspaceState`

这是给 runtime、tool 上下文和控制面看的轻量摘要，不是完整文件树。

你如果只是想知道“当前 thread 的 workspace 大致长什么样”，看这个对象就够。

### `AttachmentSnapshot`

表示一条附件从平台引用到本地副本的状态快照。

图片、文件、音频、视频最后只要进入 staging，都会以这种形式进入 run 上下文。

### `CommandSession`

thread 级 shell session。也就是 `bash_open / bash_write / bash_read / bash_close` 那套底层状态。

## workspace 怎么组织

真正管路径布局的是 `WorkspaceManager`。

它大致会给每个 thread 建这样一套结构:

- `workspace/`
- `workspace/attachments/`
- `workspace/scratch/`
- `workspace/skills/`

还有一个 `.thread_id` 文件用来反查 thread。

### 一个重要约束

`resolve_relative_path()` 会检查路径逃逸和 symlink 逃逸。

所以如果你要改 file tool 或 workspace 操作，别随手绕过这层路径约束。

## backend 怎么分层

底层通过 `ComputerBackend` 抽象三类后端:

- `host`
- `docker`
- `remote`

当前最成熟的是 `host`。

### `HostComputerBackend`

现在真正最常用的后端。

负责:

- 列文件
- 读写文本
- grep
- 一次性 exec
- 打开 / 关闭 shell session

### `DockerSandboxBackend`

是 sandbox 方向的抽象接缝，不是“整个 computer 才靠 docker 才能工作”。

### `RemoteComputerBackend`

留给远端执行面，当前不是主用路径。

## `ComputerRuntime` 是真正入口

如果你要改这套系统，最先该看的是 `ComputerRuntime`，不是某个 backend。

它做的事情包括:

- `prepare_run_context()`
- `stage_attachments()`
- workspace 文件读写 / grep
- `exec_once()`
- shell session 生命周期
- skill mirror

### `prepare_run_context()`

这是主线接 computer 的关键点。

它会:

- 计算 effective policy
- 确保 workspace 存在
- 准备 backend
- 如果配置允许，自动把当前 event 的附件做 staging
- 把 `workspace_state` 和 `attachment_snapshots` 填进 `RunContext`

所以图片转述、文件处理、多模态输入这类需求，很多都得从这里接。

现在还要补一句:

- 当前消息附件还是走这里自动 staging
- `reply` 图片虽然不是 `event.attachments`，但也复用同一套 staging 逻辑，只是落到 `attachments/reply/...`

## 附件 staging 怎么走

当前 attachment resolver 主要有两段:

- `UrlAttachmentResolver`
- `GatewayAttachmentResolver`

默认策略是:

1. 先直接按 URL / file URL 下载
2. 不行再尝试 `gateway.call_api()` 二次解析

当前图片实现就是建立在这条链上的:

- 普通 inbound 图片先走这里
- `reply` 图片先 `get_msg` 拿到消息里的图片引用
- 再交回 staging 逻辑立即落本地

### 这意味着什么

如果平台附件不是直接可下载 URL，而是平台 file_id，这层才是真正要补的地方。

不要在 pipeline 里临时写一段下载逻辑把它绕过去。

## skill mirror 是干什么的

这是为了让当前 thread 的 workspace 里能看到已经加载过的 skill 目录副本。

相关方法:

- `mark_skill_loaded()`
- `ensure_loaded_skills_mirrored()`
- `list_mirrored_skills()`

它的意义不是“执行 skill”，而是:

- 当 bot 已经读取过 skill
- workspace 工具又需要访问 skill 目录里的脚本 / 资源
- 就把 skill root mirror 到当前 thread workspace 里

这和你想要的“外部 skill 真正可用”是有关联的。以后如果要让 AcaBot 真正吃外部 skill，这里大概率还是要继续扩。

## computer tool adapter 是怎么接上的

`computer` 本体不直接暴露给模型。

真正给模型看的，是 `ComputerToolAdapterPlugin` 暴露的工具:

- `read`
- `write`
- `ls`
- `grep`
- `exec`
- `bash_open`
- `bash_write`
- `bash_read`
- `bash_close`

这层做的事是:

- 把 tool call 转给 `ComputerRuntime`
- 把返回值包装成 `ToolResult`
- 在需要时确保已加载的 skill 已经 mirror 进 workspace

## 改这块时最容易搞错的边界

### 1. 把 tool adapter 当本体

本体是 `ComputerRuntime`，不是 `computer_tool_adapter.py`。

### 2. 在主线里自己处理附件下载

附件 staging 应该尽量留在 computer 层。

### 3. 不区分 profile policy 和 thread override

一个是稳定配置，一个是运行中临时覆盖，别混。

### 4. 只改 host backend，不看 runtime 行为

有些行为是 runtime 决定的，不是 backend 决定的，比如 attachment staging、run step 审计、workspace state 组装。

## 哪些需求会碰这里

- 图片转述 / 图片先落本地再喂 VLM
- 文件上传后让 bot 读文件
- 让 bot 执行 shell 命令
- skill 目录里的脚本 / 资源在 workspace 内可见
- WebUI 查看 workspace / sandbox / session

## 当前已知风险 / 缺口

### 1. 文件类操作和 backend 语义还没完全统一

当前 `exec/session` 会按 effective backend 走，但 `list/read/write/grep` 这几条路径的语义还偏向 host workspace。

这意味着如果以后你认真推进 docker / remote backend，一定要重新检查:

- 文件读写到底应该落在哪个 backend
- host path 和 visible workspace 的关系是否还成立

### 2. 附件超限后的清理还不够彻底

当前总附件大小限制是在 staging 之后才判定。

所以如果某个附件已经下到本地，后面才发现超限，磁盘上的临时文件不一定会立刻被清掉。以后如果修这个行为，这里要同步。

### 3. skill mirror 现在只是接缝，不是完整 skill runtime

当前 mirror 更像“让 workspace 能看到已经加载过的 skill 目录”，不是 skill 本体执行系统。

如果以后你让 AcaBot 真正跑外部 skill，这里很可能还要继续扩。

## 如果改这里，通常同步哪些文档

- `12-computer.md`
- 如果影响 skill mirror，再看 `06-tools-plugins-and-subagents.md`
- 如果影响图片 / 文件主线，再看 `02-runtime-mainline.md` 和 `10-change-playbooks.md`

## 读源码顺序建议

1. `src/acabot/runtime/computer.py`
2. `src/acabot/runtime/plugins/computer_tool_adapter.py`
3. `src/acabot/runtime/bootstrap.py`
4. `src/acabot/runtime/control_plane.py`
