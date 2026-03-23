# OpenClaw / AstrBot Sandbox 机制笔记

这篇是给 AcaBot 设计 sandbox 用的。

目标很简单:

- 搞清楚 OpenClaw 是怎么做 workspace / sandbox / 路径映射的
- 搞清楚 AstrBot 是怎么做 local / sandbox / 容器执行的
- 直接回答几个实现时绕不开的问题
- 给 AcaBot 一个能落地的方案, 尽量少走弯路

## 一句话结论

如果你要让 bot 在“不受信任会话”里安全执行代码:

- 只靠“把默认工作目录切到某个路径”是不够的
- 只靠“文件工具限制在某个目录”也不够
- 只要还给了真实 shell / bash, 而进程本身还跑在宿主机, 模型就迟早能碰到别的路径

真正有用的边界必须是:

- 独立容器或 VM
- 只挂载 workspace
- 不给宿主机其它目录
- 不给 docker.sock
- 默认关网络
- 非 root
- 工具层再做一层“可见路径”包装

OpenClaw 比较接近这个方向。AstrBot 有 sandbox 能力, 但路径抽象比 OpenClaw 弱, local 模式也不是真隔离。

## OpenClaw 是怎么做的

### 1. 它把 workspace 和 sandbox 明确分成两层

OpenClaw 里有两个核心概念:

- agent workspace: agent 自己的“家”, 默认是 `~/.openclaw/workspace`
- sandbox workspace: 真正给工具执行时用的工作目录

默认 agent workspace 的说明在:

- `ref/openclaw/docs/concepts/agent-workspace.md`
- `ref/openclaw/src/agents/workspace.ts`
- `ref/openclaw/src/agents/agent-scope.ts`

关键点:

- 默认 workspace 是 `~/.openclaw/workspace`
- 如果是多 agent, 非默认 agent 会落到 `~/.openclaw/workspace-<agentId>` 一类路径
- `AGENTS.md` / `SOUL.md` / `USER.md` / `MEMORY.md` 都在这个 workspace 里

### 2. sandbox 开了以后, 真正执行用哪个目录, 取决于 `workspaceAccess`

OpenClaw 的 sandbox 有 3 个常见模式:

- `workspaceAccess: "none"`
- `workspaceAccess: "ro"`
- `workspaceAccess: "rw"`

对应行为:

- `none`: 工具工作在 sandbox 自己的 workspace, host 上通常在 `~/.openclaw/sandboxes/...`, 容器里挂成 `/workspace`
- `ro`: sandbox 主工作区还是它自己的 `/workspace`, 原始 agent workspace 只读挂到 `/agent`
- `rw`: 原始 agent workspace 直接挂到容器 `/workspace`, 工具改的就是真文件

对应源码:

- `ref/openclaw/src/agents/sandbox/context.ts`
- `ref/openclaw/src/agents/sandbox/constants.ts`
- `ref/openclaw/src/agents/sandbox/workspace-mounts.ts`
- `ref/openclaw/docs/gateway/sandboxing.md`

OpenClaw 这里做得比较干净: 它不是让模型自己猜路径, 而是 runtime 先决定“这次真正可见的 workspace 是谁”。

### 3. 它把文件工具和 exec 分开处理

OpenClaw 最关键的一点不是“有 Docker”, 而是“路径语义是分开的”。

它明确区分:

- 文件工具: `read` / `write` / `edit` / `apply_patch`
- 命令工具: `exec` / `bash`

这段如果只写一句“路径语义分开了”其实很难懂。更直白的说法是:

- OpenClaw 想让模型一直以为自己在“同一个 workspace”里工作
- 但后台实现时, 文件工具和 shell 并不是在同一个地方执行
- 所以同一个文件, 会有“给文件工具看的路径语义”和“给 shell 看的路径语义”

先看一个统一例子。

假设当前 agent 的真实 workspace 在宿主机上是:

```text
/home/acacia/.openclaw/workspace
```

假设 sandbox 打开后, 这个 workspace 在容器里被挂成:

```text
/workspace
```

假设有一个文件:

```text
notes/todo.md
```

那这个文件其实同时有两种“真实位置”:

- 宿主机视角: `/home/acacia/.openclaw/workspace/notes/todo.md`
- 容器视角: `/workspace/notes/todo.md`

OpenClaw 的核心做法就是:

- 文件工具更接近“宿主机 workspace API”
- `exec/bash` 更接近“容器里的真实 shell”

所以:

- `read path="notes/todo.md"`
  会被当成“workspace 里的 `notes/todo.md`”
- `exec command="cat /workspace/notes/todo.md"`
  会被当成“容器里 `/workspace/notes/todo.md` 这个文件”

这就是“文件工具按 host workspace 语义解析, 但 exec 用容器路径”的意思。

### 3.1 文件工具到底在干什么

文件工具不是把一段 shell 命令塞进容器去跑, 而是 OpenClaw 自己实现的一层文件 API。

它收到的通常是这种参数:

```text
read path="notes/todo.md"
write path="src/app.ts"
edit path="AGENTS.md"
```

这里的 `path` 被理解成:

- “相对当前 workspace 的路径”
- 或者“当前 workspace 下的某个文件”

也就是说, 它问的不是:

- “容器里这个绝对路径存不存在?”

它问的是:

- “在当前 workspace 这棵树里, 这个文件是谁?”

所以我前面说“按 host workspace 语义解析”, 真正的意思是:

- runtime 先拿到 workspace 根目录
- 再把 `notes/todo.md` 这种路径解析到 workspace 根下面
- 如果开了 sandbox, 可能再通过 bridge 把它映射到 sandbox 挂载
- 但对模型来说, 它始终还是“workspace 里的一个文件”

你可以把它理解成:

- 文件工具先做“逻辑路径解析”
- 然后才做“底层如何访问文件”

OpenClaw 这里的关键不是路径长什么样, 而是“路径的基准是谁”。

文件工具的基准是:

- 当前 workspace

不是:

- 容器根目录
- 宿主机根目录

### 3.2 exec / bash 又在干什么

`exec` / `bash` 不一样。

它们是真的跑 shell。

一旦真的跑 shell, shell 就只认它所在环境的真实文件系统。

如果 shell 在 sandbox 容器里, 那它认识的就会是:

- `/workspace`
- `/tmp`
- `/agent`
- 以及其它容器内可见路径

所以 `exec` 的路径语义不是“workspace 逻辑路径”, 而是:

- “容器里 shell 眼中的真实路径”

这也是为什么 OpenClaw 在 prompt 里专门提醒:

- 文件工具路径按 host workspace 解释
- `bash/exec` 要用 sandbox 容器里的路径

因为这两类工具面对的执行环境根本不是一回事。

### 3.3 那为什么它还让模型优先用相对路径

因为相对路径是这两套世界最容易对齐的交集。

还是上面的例子:

- 文件工具里写 `notes/todo.md`
- 如果 `exec` 的默认 cwd 已经是 `/workspace`
- 那 shell 里也可以直接写 `cat notes/todo.md`

这时:

- 文件工具把它理解成“workspace 根下的 `notes/todo.md`”
- shell 把它理解成“当前工作目录 `/workspace` 下的 `notes/todo.md`”

两边就对上了。

所以 OpenClaw prompt 里推荐“优先用相对路径”, 不是因为绝对路径天然危险, 而是因为:

- 相对路径更容易同时兼容文件工具和 shell
- 模型不用记两套完整绝对路径
- backend 切换时不容易把路径写死

### 3.4 为什么这比“全都让模型自己写 `/workspace/...`”更好

如果你让模型把所有文件工具也都当成“容器路径”来理解, 会有几个问题:

- 文件工具并不总是真的直接在容器里执行
- `workspaceAccess=none/ro/rw` 不同模式下, 底层挂载方式可能不同
- host backend 下根本没有 `/workspace` 这个真实宿主机路径

也就是说:

- `/workspace/...` 很适合 shell
- 但不适合作为唯一的底层真相

OpenClaw 更聪明的地方是:

- 对模型, 尽量维持“你在 workspace 里工作”这个抽象
- 对 runtime, 文件工具和 shell 各自走最适合自己的实现

### 3.5 这套设计到底带来了什么

这带来三个直接好处。

第一, bot 不必知道宿主机真实路径。

模型不需要记:

```text
/home/acacia/.openclaw/workspace
```

也不需要知道:

```text
~/.openclaw/sandboxes/<scope-key>
```

它只需要知道:

- 我现在在一个 workspace 里
- 文件工具操作的是 workspace 里的文件
- shell 默认在 `/workspace`

第二, 同一个“可见路径”可以分别映射到 host 文件工具和容器内 exec。

比如逻辑上都是:

```text
notes/todo.md
```

后台可以分别变成:

- host: `/home/acacia/.openclaw/workspace/notes/todo.md`
- container: `/workspace/notes/todo.md`

第三, backend 可以换, 但模型侧协议不用大改。

这点对 AcaBot 很重要。

如果以后你有:

- host backend
- docker backend
- remote backend

那模型最好始终只看到一套稳定的“workspace 语义”。

### 3.6 这个设计最值得 AcaBot 抄的地方

最值得抄的不是 OpenClaw 的 prompt 文案, 而是这个分层:

- 模型层: 只知道自己在 `/workspace` 或 workspace 语义里工作
- 文件工具层: 吃逻辑路径, 由 runtime 负责映射
- shell 层: 吃执行环境里的真实路径
- backend 层: 决定宿主机路径、容器路径、bridge 怎么翻

对应源码看这里:

- `ref/openclaw/src/agents/system-prompt.ts`
- `ref/openclaw/src/agents/pi-tools.ts`
- `ref/openclaw/src/agents/pi-tools.read.ts`
- `ref/openclaw/src/agents/bash-tools.exec.ts`
- `ref/openclaw/src/agents/bash-tools.shared.ts`

如果你只抄一句“优先相对路径”, 那是不够的。

真正该抄的是:

- 不同工具可以有不同底层路径实现
- 但模型侧最好只暴露一套稳定的 workspace 抽象

这是 OpenClaw 比较值得抄的地方。

### 4. 它不是只靠 prompt, 还有工具策略和路径守卫

OpenClaw 不是只有 Docker。它还叠了两层:

- tool policy: allow/deny 哪些工具
- fs policy: `workspaceOnly`

相关位置:

- `ref/openclaw/src/agents/tool-fs-policy.ts`
- `ref/openclaw/src/agents/pi-tools.sandbox-mounted-paths.workspace-only.test.ts`
- `ref/openclaw/docs/gateway/security/index.md`

这意味着:

- 就算容器里还挂了 `/agent`
- 如果 `workspaceOnly=true`
- 文件工具也可以被限制只操作 `/workspace` 这一棵

注意, 这只是“文件工具层”的限制。真正的安全边界仍然主要靠 sandbox 本身。

* [ ] 5. 它的安全边界到底在哪里

OpenClaw 的真正安全点不在 prompt, 而在:

- 工具运行进 Docker sandbox
- 只挂指定目录
- 默认可不给 agent workspace 写权限
- 默认网络可关
- 可以 deny `exec` / `write` / `edit` / `apply_patch`

但也要看清边界:

- 如果你给了广泛 bind mounts, 它还是能看到那些目录
- 如果你给了 `workspaceAccess=rw`, 它就真的能改 agent workspace
- 如果你允许 host-elevated exec, 那就直接回宿主机了

所以 OpenClaw 的结论不是“绝对安全”, 而是:

- 它有一套比较完整的隔离模型
- 但前提是配置别自己把门拆了

## AstrBot 是怎么做的

### 1. 它先把 runtime 分成 `none / local / sandbox`

AstrBot 的 computer use runtime 很直接:

- `none`: 不开
- `local`: 直接在本机跑
- `sandbox`: 走 sandbox booter

相关位置:

- `ref/AstrBot/astrbot/core/config/default.py`
- `ref/AstrBot/astrbot/core/astr_main_agent.py`

主 agent 会根据 `computer_use_runtime` 决定往模型暴露什么工具:

- `local` 时暴露本地 shell / python
- `sandbox` 时暴露 sandbox shell / python / 文件上传下载

### 2. AstrBot 的 sandbox 是“booter 抽象”

AstrBot 的 computer backend 不是一个统一容器层, 而是一组 booter:

- `LocalBooter`
- `ShipyardBooter`
- `ShipyardNeoBooter`
- `BoxliteBooter`

相关位置:

- `ref/AstrBot/astrbot/core/computer/booters/base.py`
- `ref/AstrBot/astrbot/core/computer/booters/local.py`
- `ref/AstrBot/astrbot/core/computer/booters/shipyard.py`
- `ref/AstrBot/astrbot/core/computer/booters/shipyard_neo.py`
- `ref/AstrBot/astrbot/core/computer/booters/boxlite.py`

`computer_client.get_booter()` 会按 session id 缓存一个 booter。

也就是说 AstrBot 的 sandbox 粒度偏“会话级 booter 实例”。

### 3. Local 模式不是“真 sandbox”

AstrBot 的 `LocalBooter` 只有一些轻量限制:

- shell 有黑名单, 比如拦 `rm -rf`、`mkfs`、`shutdown`
- 文件系统 helper 只允许访问 AstrBot root / data / temp 这些允许目录
- `cwd` 也会经过 `_ensure_safe_path()`

源码:

- `ref/AstrBot/astrbot/core/computer/booters/local.py`
- `ref/AstrBot/tests/unit/test_computer.py`

但这不等于真隔离。

最关键的问题是:

- `LocalShellComponent.exec()` 只检查命令字符串里有没有一些危险模式
- 它没有把 shell 真的关进独立容器
- 也没有把命令里出现的绝对路径全部拦住

所以这种情况是可能的:

- `cwd` 在允许目录里
- 但命令本身访问别的绝对路径

这说明 AstrBot 的 local 模式更像“加了点护栏的宿主机模式”, 不是拿来跑不受信任会话的。

### 4. AstrBot 的 sandbox 真正依赖外部 sandbox 服务

AstrBot 自己不直接实现完整 sandbox orchestration, 它更像一个 client:

- `ShipyardBooter` 连接 Shipyard API
- `ShipyardNeoBooter` 连接 Bay API
- `BoxliteBooter` 起一个临时容器盒子

其中 `ShipyardNeoBooter` 最重要, 因为它支持:

- shell
- python
- filesystem
- browser
- skills lifecycle

相关位置:

- `ref/AstrBot/astrbot/core/computer/booters/shipyard_neo.py`
- `ref/AstrBot/astrbot/core/computer/tools/browser.py`
- `ref/AstrBot/astrbot/core/computer/tools/fs.py`

### 5. 它会自动起 Bay, 但本质上还是靠 Docker socket 起“兄弟容器”

AstrBot 的 `BayContainerManager` 很值得你参考, 因为它正好回答了“容器里怎么再起容器”。

它做的不是 DinD, 而是 DooD:

- 当前进程连宿主机 Docker daemon
- 通过 `/var/run/docker.sock` 调 Docker API
- 让宿主机帮它再起 sandbox 容器

相关源码:

- `ref/AstrBot/astrbot/core/computer/booters/bay_manager.py`
- `ref/AstrBot/compose-with-shipyard.yml`

`compose-with-shipyard.yml` 里很直白:

- Bay 容器挂了 `/var/run/docker.sock`
- Bay 再用这个 socket 去创建 sandbox ship

这不是“容器嵌套容器”, 而是“容器调用宿主机 Docker 去起兄弟容器”。

这也是你在 Docker 里跑 AcaBot 时最实用的方案。

### 6. AstrBot 的路径抽象比较弱, 更靠 prompt 约定

AstrBot 也会给模型一些路径提示, 但比 OpenClaw 弱很多。

最典型的是 `shipyard_neo` 模式下, 主 agent 直接往 prompt 里塞一条规则:

- 文件路径相对 sandbox workspace root
- 不要写 `/workspace/xxx`
- 直接写 `xxx`

源码:

- `ref/AstrBot/astrbot/core/astr_main_agent.py`

这说明 AstrBot 的路径抽象更偏“提示模型怎么写路径”, 而不是像 OpenClaw 那样在 runtime 层明确分离“host 路径语义”和“容器路径语义”。

### 7. AstrBot 会把技能同步进 sandbox

AstrBot 还有一个你可以借鉴的小点:

- 本地 skills 会打 zip
- 上传到 sandbox
- 再在 sandbox 里解压和扫描

相关位置:

- `ref/AstrBot/astrbot/core/computer/computer_client.py`

这个思路对 AcaBot 也有用:

- 不要让 sandbox 直接看到宿主机整个 skill 目录
- 只把这次需要的内容镜像进去

## 两个项目的差异

### OpenClaw 更像“本体内建 sandbox runtime”

特点:

- workspace / sandbox / host path / container path 分得清
- 文件工具和 exec 分得清
- 有 tool policy 和 fs policy
- 可以让模型几乎不关心真实宿主机路径

缺点:

- 配置复杂
- 一旦给了太宽的 mount 或 elevated 权限, 也会失守

### AstrBot 更像“接外部 sandbox 服务”

特点:

- 接 Shipyard / Bay 比较顺
- 会话级 sandbox 直观
- browser / python / shell / file upload-download 集成比较快

缺点:

- local 模式不是真隔离
- 路径抽象比较依赖 prompt
- 对模型屏蔽真实路径这件事, 没 OpenClaw 做得系统

## 直接回答你的 3 个问题

## 1. “虽然模型被隔离在这个路径下, 但不是还能随便访问其它路径吗?”

对。

如果你只是做下面这些:

- 把默认 cwd 设成 workspace
- 文件工具只允许 `/workspace`
- prompt 告诉模型“不要出这个目录”

那都不够。

只要你还给了真实 shell, 而这个 shell 还在宿主机上跑, 模型就能:

- 用绝对路径
- 用重定向
- 用解释器
- 用各种系统命令绕过你的“默认目录”

AstrBot 的 local 模式就是一个反例:

- `cwd` 被限制了
- fs helper 被限制了
- 但 shell 命令本身并没有形成真正的 OS 级隔离

所以真要挡住这件事, 必须靠:

- 独立容器或 VM
- sandbox 里只挂 `/workspace`
- 不挂宿主机其它目录
- 不给 `/var/run/docker.sock`
- 默认 `--network none`
- 非 root
- 最好再加 seccomp / AppArmor / capability drop / 只读 rootfs

一句话:

- “默认目录”只是用户体验
- “容器边界”才是安全边界

## 2. “工具默认路径和实际路径不一样, 怎么做到让 bot 不关心路径?”

做一层“可见路径空间”。

这是 OpenClaw 最值得抄的设计。

建议 AcaBot 对模型只暴露这种路径:

- `/workspace/...`
- `/workspace/attachments/...`
- `/workspace/skills/...`
- `/workspace/out/...`

模型永远只看到这套路径。

然后 backend 自己负责映射:

- host backend:
  - `/workspace/foo.txt` -> `/real/host/path/thread-123/foo.txt`
- docker backend:
  - `/workspace/foo.txt` -> 容器里的 `/workspace/foo.txt`
  - 同时它实际对应 host 上的 `/real/host/path/thread-123/foo.txt`

这样做有几个好处:

- bot 不需要知道宿主机绝对路径
- host 和 sandbox 可以共用同一套工具协议
- 切 backend 时 prompt 不用大改

建议具体规则:

- 所有文件类工具只收“可见路径”
- 工具返回结果时也只返回“可见路径”
- 不要把宿主机真实路径回给模型
- `exec` 默认工作目录固定为 `/workspace`
- 如果确实需要 workdir, 也只允许传“可见路径”

AstrBot 目前更像“告诉模型你写相对路径”, 不够稳。AcaBot 不要走这条路, 直接做 runtime 映射层。

## 3. “现在运行在 docker 内, 如果还想给 bot 再开容器, 怎么做?”

最实用的方案不是 DinD, 而是 DooD。

也就是:

- AcaBot 自己跑在容器 A 里
- 把宿主机的 Docker socket 挂给容器 A
- AcaBot 通过这个 socket 去让宿主机起容器 B
- 容器 B 作为 bot 的 sandbox

这正是 AstrBot 的 Bay 在做的事。

### 不推荐优先用 DinD

DinD 就是“容器里再跑一个 Docker daemon”。

能做, 但问题多:

- 一般要 privileged
- 网络更复杂
- 镜像缓存更麻烦
- 路径映射更绕
- 调试也更难

除非你真的要完全独立的 inner daemon, 不然没必要。

### DooD 需要注意一个关键坑: Docker daemon 看到的是宿主机路径

这点非常重要。

如果 AcaBot 在容器里执行:

```text
docker run -v /app/workspaces/thread-1:/workspace ...
```

这个 `/app/workspaces/thread-1` 必须是“宿主机上真的存在, 而且 Docker daemon 能看到的路径”。

不是说 AcaBot 容器里有这个路径就行。

所以你有两种靠谱方案:

### 方案 A: 容器内外路径做成同一路径

比如宿主机和 AcaBot 容器都把 workspace 根放在:

```text
/srv/acabot/workspaces
```

这样 AcaBot 容器里看到的路径, 刚好也是宿主机路径。

优点:

- 最简单
- backend 不用额外做 host/container path 转换

### 方案 B: 显式维护两套根路径

比如配置里写:

- `workspace_root_in_app=/app/workspaces`
- `workspace_root_on_host=/srv/acabot/workspaces`

然后 AcaBot runtime 负责把:

- app 内路径 -> host 给 docker daemon 的路径

这个更灵活, 也更通用。

如果你准备长期把 AcaBot 跑在 Docker 里, 我建议你明确支持这两套根路径配置。

### 怎么对 bot 屏蔽路径细节

答案还是一样:

- bot 只看到 `/workspace`
- backend 自己做 3 段映射

映射分层:

- visible path: 给 bot 看, 例如 `/workspace/a.txt`
- app host path: AcaBot 进程自己读写时用
- docker daemon host path: 起 sandbox 容器挂载时用

bot 不应该知道后两者。

## 对 AcaBot 的建议

你现在这个仓库里其实已经有一半基础设施了:

- `src/acabot/runtime/computer/runtime.py`
- `src/acabot/runtime/computer/backends.py`
- `src/acabot/runtime/control/workspace_ops.py`

里面已经有:

- `host` / `docker` backend
- per-thread override
- workspace 状态查询
- stop sandbox

但是现阶段还比较“薄”, 最大的问题是:

- `DockerSandboxBackend` 现在是直接 `docker run -v {host_path}:/workspace`
- 这要求当前进程拿到的 `host_path` 对 Docker daemon 必须是有效宿主机路径
- 如果 AcaBot 本身跑在容器里, 这个假设不一定成立

也就是说, 你下一步最应该补的是“路径映射层”, 不是继续往 prompt 里写规则。

### 我建议你这样落

### 1. policy

默认策略:

- 管理员: 可选 host / sandbox
- 非管理员: 默认 sandbox

而且 host override 只能走 control plane 或显式白名单, 不要让模型自己切。

### 2. backend 语义

保留:

- `host`
- `docker`

未来可扩:

- `remote`

但模型一侧不要感知 backend 名称, 最多只知道“当前是受限环境”还是“管理员放开的环境”。

### 3. visible path

统一给模型只暴露:

- `/workspace`
- `/workspace/attachments`
- `/workspace/skills`
- `/workspace/out`

不要再把真实线程目录、宿主机目录暴露进工具返回。

### 4. file tools

文件工具只接 visible path:

- `read`
- `write`
- `ls`
- `grep`

全部在 runtime 层翻译。

### 5. exec / shell

`exec` 的默认 cwd 永远设成 `/workspace`。

如果是 host backend:

- runtime 把 `/workspace/...` 翻译到真实 host path

如果是 docker backend:

- 容器里直接就是 `/workspace`

### 6. 安全默认值

对不受信任 session:

- backend = `docker`
- `network = none`
- non-root
- 不挂 docker.sock
- 只挂 workspace
- 不挂宿主机代码仓库
- 不挂家目录

管理员 host 模式才允许更宽权限。

### 7. 容器编排方式

如果 AcaBot 跑在 Docker 里:

- 优先 DooD, 不优先 DinD
- 明确配置 `workspace_root_on_host`
- sandbox 容器一律做成“兄弟容器”

### 8. 你真正要抄谁

如果按“安全模型”抄:

- 抄 OpenClaw

如果按“如何在 bot 系统里接入外部 sandbox 服务”抄:

- 抄 AstrBot

如果按“你这个项目现在最容易落地的路径”:

- OpenClaw 的路径抽象
- AstrBot/Bay 的容器编排思路
- AcaBot 现有 `ComputerRuntime` / `DockerSandboxBackend` 当落点

## 最后给一个最直白的判断

你这个需求如果要做对, 不要把它理解成“给 bot 一个默认目录”。

应该把它理解成三件事:

1. 给 bot 一个假的、稳定的、统一的可见文件系统
2. 给不受信任 session 一个真的隔离执行环境
3. 给管理员一个可控的 override 入口, 但默认不要放开到宿主机

只做第 1 件, 不安全。

只做第 2 件, 体验会乱, 模型会一直搞不清路径。

第 1 和第 2 一起做, 才是能长期维护的方案。

## 参考源码

- OpenClaw

  - `ref/openclaw/docs/concepts/agent-workspace.md`
  - `ref/openclaw/docs/gateway/sandboxing.md`
  - `ref/openclaw/src/agents/system-prompt.ts`
  - `ref/openclaw/src/agents/pi-tools.ts`
  - `ref/openclaw/src/agents/pi-tools.read.ts`
  - `ref/openclaw/src/agents/bash-tools.exec.ts`
  - `ref/openclaw/src/agents/sandbox/context.ts`
  - `ref/openclaw/src/agents/sandbox/workspace-mounts.ts`
  - `ref/openclaw/src/agents/tool-fs-policy.ts`
- AstrBot

  - `ref/AstrBot/astrbot/core/astr_main_agent.py`
  - `ref/AstrBot/astrbot/core/astr_main_agent_resources.py`
  - `ref/AstrBot/astrbot/core/computer/computer_client.py`
  - `ref/AstrBot/astrbot/core/computer/booters/local.py`
  - `ref/AstrBot/astrbot/core/computer/booters/shipyard.py`
  - `ref/AstrBot/astrbot/core/computer/booters/shipyard_neo.py`
  - `ref/AstrBot/astrbot/core/computer/booters/bay_manager.py`
  - `ref/AstrBot/astrbot/core/computer/tools/fs.py`
  - `ref/AstrBot/astrbot/core/computer/tools/shell.py`
  - `ref/AstrBot/astrbot/core/config/default.py`
  - `ref/AstrBot/compose-with-shipyard.yml`
- AcaBot 现有落点

  - `src/acabot/runtime/computer/runtime.py`
  - `src/acabot/runtime/computer/backends.py`
  - `src/acabot/runtime/control/workspace_ops.py`
