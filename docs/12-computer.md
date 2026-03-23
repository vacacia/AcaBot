# computer 子系统

这一篇讲的是 AcaBot 里的 `computer`。

现在这层已经很明确了：

- `computer` 是前台文件工具和 shell 工具背后的共用运行时
- 前台真正暴露给模型看的 builtin tool 只有：
  - `read`
  - `write`
  - `edit`
  - `bash`
- 这些工具都吃 Work World path：
  - `/workspace/...`
  - `/skills/...`
  - `/self/...`

模型不会直接看到 `computer` 这个名字。模型看到的是工具名，真正干活的是 `ComputerRuntime`。

## 关键文件

先看这些：

- `src/acabot/runtime/builtin_tools/computer.py`
- `src/acabot/runtime/computer/runtime.py`
- `src/acabot/runtime/computer/contracts.py`
- `src/acabot/runtime/computer/backends.py`
- `src/acabot/runtime/computer/workspace.py`
- `src/acabot/runtime/computer/world.py`

如果要看默认装配，再加：

- `src/acabot/runtime/bootstrap/__init__.py`
- `src/acabot/runtime/tool_broker/broker.py`

## 这层现在负责什么

`computer` 现在主要负责这些事情：

1. 管 thread 级工作目录
2. 管 `/workspace /skills /self` 这三块路径怎么映到宿主机
3. 把 inbound attachment 拉进 `/workspace/attachments/...`
4. 处理前台 `read / write / edit / bash`
5. 管内部 shell session、sandbox 状态、workspace 状态
6. 给控制面提供 workspace 相关摘要

也就是说，前台工具只是它的一部分，不是它的全部。

## 前台工具面已经固定成四个

现在前台 builtin tools 就是：

- `read(path, offset?, limit?)`
- `write(path, content)`
- `edit(path, oldText, newText)`
- `bash(command, timeout?)`

它们都在：

- `src/acabot/runtime/builtin_tools/computer.py`

里注册到 `ToolBroker`。

这一层只做四件事：

- 定义工具参数
- 接住模型调用
- 把参数转给 `ComputerRuntime`
- 把结果整理成 `ToolResult`

不要把 builtin surface 当成 `computer` 本体。本体还是 `ComputerRuntime`。

## `ComputerRuntime` 是真正入口

如果你要改这套系统，最先该看的是：

- `src/acabot/runtime/computer/runtime.py`

现在前台工具真正走的是这四个入口：

- `read_world_path()`
- `write_world_path()`
- `edit_world_path()`
- `bash_world()`

除此之外，它还有一些内部能力：

- `prepare_run_context()`
- `stage_attachments()`
- `exec_once()`
- `open_session()` / `write_session()` / `read_session()` / `close_session()`
- `list_workspaces()`
- `list_workspace_attachments()`
- `get_sandbox_status()`
- `prune_workspace()`
- `stop_workspace_sandbox()`

可以简单理解成：

- 前台模型用的是 `read / write / edit / bash`
- 控制面和内部流程还会用到附件、workspace、session、sandbox 这些能力

## Work World 路径怎么工作

前台工具传进来的不是宿主机路径，而是 world path。

当前固定的三块根是：

- `/workspace`
- `/skills`
- `/self`

真正负责把 world path 变成正式路径的是：

- `src/acabot/runtime/computer/world.py`
- `src/acabot/runtime/computer/runtime.py`

现在的意思是：

- `/workspace/...` 指向当前 thread 的工作目录
- `/skills/...` 指向当前 world 真正可见的 skill 目录
- `/self/...` 指向当前 actor 的持久 self 目录

前台工具不用自己知道这些映射细节。它们只把 world path 交给 `ComputerRuntime`。

## 宿主机目录怎么组织

真正管宿主机目录布局的是：

- `src/acabot/runtime/computer/workspace.py`

现在最重要的几条宿主机路径是：

- `threads/<thread>/workspace/`
- `threads/<thread>/workspace/attachments/`
- `threads/<thread>/workspace/scratch/`
- `threads/<thread>/workspace/skills/`
- `threads/<thread>/skill_views/<view>/`
- `self/<scope>/`

可以简单理解成：

- `/workspace` 对应 thread 的工作目录
- 真正的 skills 目录放在当前 thread 的 workspace 下面
- 每个 world 还会有自己的 skills 视图目录
- `/self` 是单独的持久目录，不跟 thread 一起删

## `/skills` 现在的规则

这块之前最容易写错，现在要记住当前真相：

- runtime 扫 skill 真源目录, 用的是 `runtime.filesystem.skill_catalog_dirs`
- `computer` 自己内部还有一个宿主机 skills catalog 根路径配置, 叫 `host_skills_catalog_root_path`
- 这两个不是一回事:
  - 前者决定 runtime 去哪里扫描 skill metadata
  - 后者只是 computer 子系统自己在宿主机上保留的一块内部 skills 根路径
- `/skills/...` 的读写已经走真正的 skills 目录
- 不再把写入结果留在 `skill_views/...` 副本里
- 只要当前 world 真能看见这个 skill，`read` 就可以直接读
- 写完 `/skills/...` 之后，会刷新当前 world 的 skills 视图
- builtin surface 不再自己偷偷准备 skill 镜像
- 这件事已经收回 `ComputerRuntime` 处理

## `/self` 的当前边界

这块不是一个“普通目录约定”，而是当前 world 规则的一部分。

当前已经定死：

- 前台 agent：看得见，也能写
- subagent：完全看不见，也不能写
- `/self` 不会跟 thread 一起清理

所以如果你发现 subagent 能摸到 `/self`，那是 bug，不是 feature。

## `read` 现在是什么行为

前台 `read` 现在已经收成和 pi 更接近的样子：

- 参数是 `path / offset / limit`
- 文本文件支持分页
- `offset`、`limit` 非法会报错
- `offset` 越界会报错
- 不是只会读 UTF-8 文本
- 图片按文件字节识别，不按后缀猜
- 支持：
  - `png`
  - `jpg`
  - `gif`
  - `webp`
- 图片返回的是：
  - 一段说明文字
  - 一个图片内容块
- 非 UTF-8 普通文件会按 `errors="replace"` 读成文本，不会直接炸掉

相关 helper：

- `src/acabot/runtime/computer/reading.py`
- `src/acabot/runtime/computer/media.py`

## `write` 现在是什么行为

前台 `write` 现在已经收成：

- 自动创建父目录
- 文件不存在就创建
- 已存在就覆盖
- 返回写入的 UTF-8 字节数
- 前台文案是：
  - `Successfully wrote N bytes to PATH`

## `edit` 现在是什么行为

前台 `edit` 现在已经收成：

- 参数名和 pi 一样：
  - `path`
  - `oldText`
  - `newText`
- 先精确匹配
- 找不到时报错
- 多次匹配时报错
- 支持 `newText=""` 删除文字
- 保留 UTF-8 BOM
- 保留原来的换行风格
- 支持 fuzzy 匹配
- 返回 diff 和第一处改动行号

真正处理这套文字替换规则的是：

- `src/acabot/runtime/computer/editing.py`

这里还有一个很容易误判的点：

- 当前行为要以 **pi 当前 `dist/core/tools/edit.js` / `edit-diff.js`** 为准
- fuzzy 命中后，pi 当前版本就是会拿归一化后的整份文字做替换基底
- `Found N occurrences` 这一步，pi 当前版本也是按归一化后的文字计数

AcaBot 现在和这套行为保持一致。

## `bash` 现在是什么行为

前台 shell 工具面现在已经收成：

- `bash(command, timeout?)`

前台不再直接暴露这些旧名字：

- `exec`
- `bash_open`
- `bash_write`
- `bash_read`
- `bash_close`

现在真正链路是：

- builtin `bash` 工具接住参数
- 调 `ComputerRuntime.bash_world()`
- `bash_world()` 再走 `exec_once()`
- 最后由 host / docker backend 真正执行

当前规则是：

- `timeout` 会一直传到 backend
- 超时后会返回失败结果，而不是一直卡住
- 当前 world 看不到 `/workspace`，或者当前 run 不允许 exec 时，前台不会显示 `bash`

## backend 怎么分层

底层通过 `ComputerBackend` 抽象三类后端：

- `host`
- `docker`
- `remote`

关键文件：

- `src/acabot/runtime/computer/backends.py`
- `src/acabot/runtime/computer/contracts.py`

现在 backend 主要只做这些底层事情：

- `ensure_workspace()`
- `list_entries()`
- `read_text()`
- `read_bytes()`
- `write_text()`
- `exec_once()`
- shell session 打开 / 写入 / 读取 / 关闭
- `get_sandbox_status()`
- `stop_workspace_sandbox()`

backend 不负责这些事情：

- world path 解析
- `/skills` `/self` 可见性判断
- `oldText / newText` 的编辑规则
- 给模型拼最终工具文案

## `list_entries()` 现在是给谁用的

虽然前台已经没有 `ls` 了，但 `list_entries()` 这个 backend 方法还在。

它现在主要给这些地方用：

- 控制面
- workspace 摘要
- 附件列表
- 内部状态展示

不要再把它理解成“前台还藏着一个没删干净的 `ls` 工具”。
前台 `ls` 已经移除了。

## 附件 staging 怎么走

附件 staging 还是 `computer` 这层的重要职责。

关键入口：

- `prepare_run_context()`
- `stage_attachments()`

当前大致流程是：

1. 当前消息的附件先进入 `StandardEvent.attachments`
2. `ComputerRuntime.prepare_run_context()` 需要时先做 staging
3. 文件被放进 `/workspace/attachments/...`
4. 后面消息整理、图片说明、reply 图片处理都复用这套本地文件路径

reply 图片现在也是这套链的一部分，不是另一条完全独立的下载逻辑。

## `WorkspaceState` 给谁看

`WorkspaceState` 不是文件树本体，而是一份摘要。

它主要给这些地方看：

- 当前 run 上下文
- `ToolBroker`
- 控制面
- WebUI

它会告诉你：

- 当前 thread 是谁
- 当前 backend 是什么
- `/workspace` 宿主机路径是什么
- 当前 run 真正可见的 computer 工具有哪些
- 当前附件数量
- 当前活跃 shell session 有哪些

`ToolBroker` 会根据 `WorkspaceState.available_tools` 再去过滤前台工具可见性。
所以前台能不能看到 `bash`，不只是看 profile，还要看当前 workspace 状态。

## 控制面还会用这层做什么

虽然前台只有四个 builtin tools，但控制面还会通过 `computer` 做这些事：

- 列 workspace 摘要
- 看附件列表
- 看活跃 shell session
- 看 sandbox 状态
- 清理 workspace
- 停止 sandbox
- 看已经镜像到宿主机的 skills

这些能力主要是：

- `RuntimeWorkspaceControlOps`
- `RuntimeControlPlane`
- HTTP API
- WebUI

在用，不是给模型直接调的。

## 现在最容易搞错的边界

### 1. 把 builtin tool 当成本体

前台 builtin tool 只是接线层。本体还是 `ComputerRuntime`。

### 2. 把 plugin 当成基础工具入口

现在 `read / write / edit / bash` 已经不是 plugin 了。  
它们属于 runtime 自带的 builtin tool。

### 3. 在 pipeline 里自己写附件下载

附件 staging 现在应该尽量留在 `computer` 里处理。

### 4. 只改 backend，不看 `ComputerRuntime`

很多行为是 `ComputerRuntime` 决定的，不是 backend 决定的。  
比如：

- `/skills` 准备
- world path 解析
- attachment staging
- `WorkspaceState` 组装
- 前台工具可见性

### 5. 看到内部 shell session，就以为前台也该暴露 session 工具

不是。  
内部还保留 session 能力，不代表前台还要暴露 `bash_open / bash_write / bash_read / bash_close`。

## 改这里时建议一起看哪些文档

- `docs/19-tool.md`
- `docs/12-computer.md`
- 如果影响主线，再看 `docs/02-runtime-mainline.md`
- 如果影响消息准备，再看 `docs/05-memory-and-context.md`

## 读源码顺序建议

建议顺序：

1. `src/acabot/runtime/computer/runtime.py`
2. `src/acabot/runtime/computer/contracts.py`
3. `src/acabot/runtime/computer/backends.py`
4. `src/acabot/runtime/computer/workspace.py`
5. `src/acabot/runtime/builtin_tools/computer.py`
6. `src/acabot/runtime/tool_broker/broker.py`

如果要查控制面，再加：

7. `src/acabot/runtime/control/workspace_ops.py`
8. `src/acabot/runtime/control/control_plane.py`
9. `src/acabot/runtime/control/http_api.py`