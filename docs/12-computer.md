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

它不是 plugin，也不是给模型直接看的一个大对象名字。模型看到的是工具名，真正干活的是 `ComputerRuntime`。

## 关键文件

- `src/acabot/runtime/computer/`
- `src/acabot/runtime/builtin_tools/computer.py`
- `src/acabot/runtime/bootstrap/`

## 这层现在负责什么

`computer` 现在主要负责五件事：

- 管 thread 级 workspace
- 把 inbound attachment 拉进 `/workspace/attachments/...`
- 处理 world path 到宿主机路径的读写
- 跑一次性 shell 命令
- 维护内部 shell session 和 backend 状态

前台工具只是它的表面，不是它的全部。

## 前台工具面

现在前台 builtin tool 已经固定成四个：

- `read(path, offset?, limit?)`
- `write(path, content)`
- `edit(path, oldText, newText)`
- `bash(command, timeout?)`

这四个工具都由：

- `src/acabot/runtime/builtin_tools/computer.py`

注册进 `ToolBroker`。

这一层只负责：

- 定义 tool schema
- 接住模型调用
- 把参数转给 `ComputerRuntime`
- 把结果整理成 `ToolResult`

不要把这层当成本体。本体还是 `ComputerRuntime`。

## `ComputerRuntime` 是真正入口

如果你要改这套系统，最先该看的是：

- `src/acabot/runtime/computer/runtime.py`

现在它已经有这组清楚的入口：

- `prepare_run_context()`
- `stage_attachments()`
- `read_world_path()`
- `write_world_path()`
- `edit_world_path()`
- `bash_world()`
- `exec_once()`
- `open_session()` / `write_session()` / `read_session()` / `close_session()`

其中：

- `read / write / edit / bash` 是前台 builtin tool 用的入口
- `exec_once()` 和 shell session 这组方法现在主要是内部能力
- 前台不再直接暴露 `exec / bash_open / bash_write / bash_read / bash_close`

## world path 怎么工作

前台工具传进来的不是宿主机路径，而是 world path。

真正负责把 world path 变成正式路径的是：

- `src/acabot/runtime/computer/world.py`
- `src/acabot/runtime/computer/runtime.py`

现在的规则是：

- `/workspace/...` 指向当前 thread 的工作目录
- `/skills/...` 指向当前 world 真正可见的 skill 目录
- `/self/...` 指向当前 actor 的持久 self 目录

前台工具不用自己知道这些映射细节。它们只管把 world path 交给 `ComputerRuntime`。

## 宿主机目录怎么组织

真正管宿主机目录布局的是：

- `src/acabot/runtime/computer/workspace.py`

现在最重要的几条路径是：

- `threads/<thread>/workspace/`
- `threads/<thread>/workspace/attachments/`
- `threads/<thread>/workspace/scratch/`
- `threads/<thread>/workspace/skills/`
- `threads/<thread>/skill_views/<view>/`
- `self/<scope>/`

可以简单理解成：

- `/workspace` 对应 thread 的工作目录
- `/skills` 的 canonical 目录在 thread workspace 里
- 每个 world 还会有自己的 skills view
- `/self` 是单独的持久目录，不跟 thread 一起删

## `/skills` 现在的规则

这块之前最容易写错，现在要记住当前真相：

- `/skills/...` 的读写已经走 canonical skills 目录
- 不再写进 `skill_views/...` 副本
- 可见的 skill 可以直接被 `read` 访问
- 写完以后会刷新 skills view
- builtin surface 不再自己偷偷做 skill mirror 准备
- 这件事已经收回 `ComputerRuntime` 里处理

## `read` 现在是什么行为

前台 `read` 现在已经对齐到更像 pi 的样子：

- 参数是 `path / offset / limit`
- 文本文件支持分页
- offset 越界会报错
- 图片按文件字节识别，不按后缀猜
- 支持：
  - `png`
  - `jpg`
  - `gif`
  - `webp`
- 图片返回的是说明文字 + 图片内容块

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
- 返回 diff

相关 helper：

- `src/acabot/runtime/computer/editing.py`

这里还有一个很容易误判的点：

- 当前行为要以 **pi 当前 `dist/core/tools/edit.js` / `edit-diff.js`** 为准
- fuzzy 命中后，pi 当前版本就是会拿归一化后的整份文字做替换基底
- `Found N occurrences` 这一步，pi 当前版本也是按 fuzzy 归一化后的文字计数

AcaBot 现在和这套行为保持一致。

## `bash` 现在是什么行为

前台 shell 工具面现在已经收成：

- `bash(command, timeout?)`

这层现在由：

- `src/acabot/runtime/builtin_tools/computer.py`
- `src/acabot/runtime/computer/runtime.py`

配合完成。

当前规则是：

- 前台不再暴露 `exec / bash_open / bash_write / bash_read / bash_close`
- `bash` 会把 `command / timeout` 转给 `ComputerRuntime.bash_world()`
- `bash_world()` 再走 `exec_once()`
- host / docker backend 的一次性命令执行都已经支持可选超时秒数
- 当前 world 看不到 `/workspace` 时，前台不会显示 `bash`

## backend 怎么分层

底层通过 `ComputerBackend` 抽象三类后端：

- `host`
- `docker`
- `remote`

关键文件：

- `src/acabot/runtime/computer/backends.py`
- `src/acabot/runtime/computer/contracts.py`

现在 backend 主要只做这些底层事情：

- `read_text()`
- `read_bytes()`
- `write_text()`
- `exec_once()`
- shell session 打开 / 写入 / 读取 / 关闭

backend 不负责这些事情：

- world path 解析
- `/skills` `/self` 可见性判断
- `oldText / newText` 的编辑规则
- 给模型拼最终工具文案

## 附件 staging 怎么走

附件 staging 还是 `computer` 这层的重要职责。

关键入口：

- `stage_attachments()`
- `prepare_run_context()`

默认流程还是：

1. 先按 URL / file URL 拉取
2. 不行再尝试 gateway API 做二次解析
3. 最后把文件放进 `/workspace/attachments/...`

当前 event 附件和 reply 图片都复用这套路径。

## `WorkspaceState` 给谁看

`WorkspaceState` 是给这些地方看的摘要：

- runtime 上下文
- tool 上下文
- control plane
- WebUI

它不是完整文件树，但会告诉你这些关键信息：

- 当前 thread
- 当前 backend
- `/workspace` 的宿主机路径
- 当前 run 真正可见的 computer 工具
- 当前 attachment 数量
- 当前活跃 shell session

## 现在最容易搞错的边界

### 1. 把 builtin tool 当本体

前台 builtin tool 只是接线层。本体还是 `ComputerRuntime`。

### 2. 把 plugin 当成基础工具入口

现在 `read / write / edit / bash` 已经不是 plugin 了。
它们属于 runtime 自带的 builtin tool。

### 3. 在 pipeline 里自己写附件下载

附件 staging 现在还是应该尽量留在 `computer` 里处理。

### 4. 只改 backend，不看 runtime

很多行为是 `ComputerRuntime` 决定的，不是 backend 决定的。
比如：

- `/skills` 准备
- world path 解析
- attachment staging
- `WorkspaceState` 组装

## 改这里时通常一起看哪些文档

- `12-computer.md`
- `06-tools-plugins-and-subagents.md`
- 如果影响主线，再看 `02-runtime-mainline.md`

## 读源码顺序建议

1. `src/acabot/runtime/computer/runtime.py`
2. `src/acabot/runtime/computer/contracts.py`
3. `src/acabot/runtime/computer/backends.py`
4. `src/acabot/runtime/computer/workspace.py`
5. `src/acabot/runtime/builtin_tools/computer.py`
