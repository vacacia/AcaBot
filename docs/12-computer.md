# Computer 子系统

`computer` 是前台文件工具和 shell 工具背后的共用运行时。模型不直接看到 `computer` 这个名字，看到的是四个 builtin tool：`read`、`write`、`edit`、`bash`，它们都吃 Work World path（`/workspace/...`、`/skills/...`、`/self/...`）。

## 关键文件

| 文件 | 职责 |
|------|------|
| `runtime/builtin_tools/computer.py` | 模型看到的工具 schema，接住调用后转给 ComputerRuntime |
| `runtime/computer/runtime.py` | ComputerRuntime 本体——真正的入口 |
| `runtime/computer/contracts.py` | 契约定义（ComputerPolicy、WorldView、WorkspaceState 等） |
| `runtime/computer/backends.py` | 宿主机 / docker / remote 后端 |
| `runtime/computer/world.py` | Work World 路径解析（world path → 宿主机路径） |
| `runtime/computer/workspace.py` | 宿主机目录布局、thread workspace 管理 |
| `runtime/computer/reading.py` | read 的分页和图片识别 |
| `runtime/computer/editing.py` | edit 的精确/fuzzy 匹配和替换规则 |
| `runtime/computer/media.py` | 图片格式识别 |

## ComputerRuntime

真正的入口。前台工具走的四个方法：`read_world_path()`、`write_world_path()`、`edit_world_path()`、`bash_world()`。

内部还有：`prepare_run_context()`（准备 world/workspace/附件 staging）、`stage_attachments()`、`exec_once()`、shell session 管理（open/write/read/close）、workspace 列表/清理/sandbox 状态等。前台模型用四个工具，控制面和内部流程用附件、workspace、session、sandbox 这些能力。

## Work World 路径

前台工具传入的不是宿主机路径，而是 world path。三块根：

| World Path | 宿主机映射 | 说明 |
|-----------|-----------|------|
| `/workspace/...` | `threads/<thread>/workspace/` | 当前 thread 的工作目录 |
| `/skills/...` | 当前 world 可见的 skill 目录 | runtime 从 `skill_catalog_dirs` 扫描 |
| `/self/...` | `self/<scope>/` | 持久 self 目录，不跟 thread 一起清理 |

路径解析在 `world.py` 和 `runtime.py`，前台工具不用知道映射细节。

宿主机其他重要路径：`threads/<thread>/workspace/attachments/`（附件）、`threads/<thread>/workspace/scratch/`（临时）。

## 前台工具行为

### read

参数 `path / offset / limit`。文本文件支持分页，offset/limit 非法或越界报错。图片按文件字节识别（png/jpg/gif/webp），返回说明文字 + 图片内容块。非 UTF-8 文件按 `errors="replace"` 读成文本。

### write

自动创建父目录，文件不存在就创建，已存在就覆盖，返回写入的 UTF-8 字节数。

### edit

参数 `path / oldText / newText`（与 pi 一致）。先精确匹配，找不到报错，多次匹配报错。支持 `newText=""` 删除、保留 UTF-8 BOM、保留原换行风格、fuzzy 匹配。返回 diff 和第一处改动行号。行为以 pi 当前 `edit.js / edit-diff.js` 为准。

### bash

`bash(command, timeout?)`。链路：builtin tool → `ComputerRuntime.bash_world()` → `exec_once()` → host/docker backend。timeout 传到 backend，超时返回失败而不是卡住。当前 world 看不到 `/workspace` 或当前 run 不允许 exec 时，前台不显示 bash。

## /skills 规则

- runtime 从 `runtime.filesystem.skill_catalog_dirs` 扫描 skill metadata
- computer 内部有 `host_skills_catalog_root_path`（宿主机 skills 根路径），这和 runtime 扫描路径不是一回事
- `/skills/...` 的读写走真正的 skills 目录，只要当前 world 能看见就可以直接读
- 写完 `/skills/...` 后会刷新当前 world 的 skills 视图
- skill 镜像准备收回 ComputerRuntime 处理，builtin surface 不再偷偷准备

## /self 规则

- 前台 agent：看得见，也能写
- subagent：完全看不见，也不能写（如果能看到那是 bug）
- `/self` 不跟 thread 一起清理

## Backend 分层

`ComputerBackend`（`backends.py`）抽象三类后端（host / docker / remote），只做底层操作：`ensure_workspace()`、`list_entries()`、`read_text()`、`read_bytes()`、`write_text()`、`exec_once()`、shell session、`get_sandbox_status()`、`stop_workspace_sandbox()`。

Backend 不负责：world path 解析、`/skills` `/self` 可见性判断、edit 的替换规则、模型工具文案。

`list_entries()` 虽然前台没有 `ls` 了，但内部仍被控制面、workspace 摘要、附件列表使用。

## 附件 Staging

1. 当前消息的附件进入 `StandardEvent.attachments`
2. `ComputerRuntime.prepare_run_context()` 做 staging
3. 文件放进 `/workspace/attachments/...`
4. 后续消息整理、图片说明、reply 图片处理复用本地文件路径

Reply 图片也走这套链路。

## WorkspaceState

不是文件树本体，而是摘要。给当前 run 上下文、ToolBroker、控制面和 WebUI 看：当前 thread、backend、`/workspace` 宿主机路径、可见 computer 工具、附件数量、活跃 shell session。ToolBroker 根据 `WorkspaceState.available_tools` 过滤前台工具可见性——前台能不能看到 bash 不只看 agent 配置，还看当前 workspace 状态。

## 控制面能力

控制面通过 `RuntimeWorkspaceControlOps` / `RuntimeControlPlane` / HTTP API 使用 computer 的内部能力：列 workspace 摘要、附件列表、活跃 shell session、sandbox 状态、workspace 清理、sandbox 停止、已镜像的 skills。这些不给模型直接调。

## 源码阅读顺序

1. `src/acabot/runtime/computer/runtime.py`
2. `src/acabot/runtime/computer/contracts.py`
3. `src/acabot/runtime/computer/backends.py`
4. `src/acabot/runtime/computer/workspace.py`
5. `src/acabot/runtime/builtin_tools/computer.py`
6. `src/acabot/runtime/tool_broker/broker.py`
7. `src/acabot/runtime/control/workspace_ops.py`（控制面）
