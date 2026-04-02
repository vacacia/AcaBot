# Computer 子系统

Computer 是 AcaBot 为 AI 模型提供的受控文件系统和执行环境。模型通过世界路径（World Path）操作文件、执行命令，而永远不会直接接触宿主机的真实路径。模型不直接看到 `computer` 这个名字，看到的是四个 builtin tool——`read`、`write`、`edit`、`bash`，它们都接收 Work World path（`/workspace/...`、`/skills/...`、`/self/...`）。Computer 决定了每一轮 run 中模型能看到什么、能做什么。

`ComputerRuntime` 是真正的入口。前台工具走的四个方法：`read_world_path()`、`write_world_path()`、`edit_world_path()`、`bash_world()`。内部还有：`prepare_run_context()`（准备 world/workspace/附件 staging）、`stage_attachments()`、`exec_once()`、shell session 管理（open/write/read/close）、workspace 列表/清理/sandbox 状态等。前台模型用四个工具，控制面和内部流程用附件、workspace、session、sandbox 这些能力。

---

## 1. Work World

Work World 是模型眼中的"文件系统"，包含三个根路径。这三个根路径分别映射到宿主机上的不同目录，映射关系由 `WorkspaceManager` 管理，路径解析由 `WorldView.resolve()` 完成。模型只使用 `/workspace/...`、`/skills/...`、`/self/...` 这样的世界路径，runtime 负责把它们翻译成宿主机路径或 shell 执行路径。

| World Path | 宿主机映射 | 说明 |
|---|---|---|
| `/workspace/...` | `threads/<thread>/workspace/` | 当前 thread 的工作目录，存放临时文件、附件等 |
| `/skills/...` | 当前 world 可见的 skill 视图目录（按需物化） | runtime 从 `skill_catalog_dirs` 扫描，按 actor 隔离 |
| `/self/...` | `self/<agent_id>/` | 当前 actor 的持久化目录（sticky notes 等），不跟 thread 一起清理 |

宿主机上还有几个重要路径：`threads/<thread>/workspace/attachments/`（附件存储）、`threads/<thread>/workspace/scratch/`（临时文件）、`threads/<thread>/skills/`（thread 共享 skills 目录，物化后的 skill 副本）、`threads/<thread>/skill_views/{view_key}/`（按 actor 隔离的 skill 视图）。

---

## 2. Policy 决策

每一轮 run 的 computer 权限不是固定的，而是通过 Policy 决策机制 per-run 计算。决策有两个来源，按优先级排列：

**Session-driven 决策**。`SessionRuntime.resolve_computer()` 根据会话配置（surface 级 computer domain 配置、cases 条件匹配）生成 `ComputerPolicyDecision`。支持按 `sender_roles`、`actor_lane` 等条件匹配不同的权限预设。

**Profile 兜底**。当没有 session-driven 决策时，从 `profile.computer_policy` 读取配置。如果 profile 也没有配置，使用 `ComputerRuntime` 的默认 policy（host backend，允许 exec 和 sessions）。

### ComputerPolicyDecision 字段

`ComputerPolicyDecision` 是每轮 run 的权限快照，包含以下关键字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `actor_kind` | `str` | 当前 actor 的身份（`frontstage_agent`、`subagent`、`maintainer`），影响 root 可见性 |
| `backend` | `str` | 执行后端（`host`、`docker`、`remote`） |
| `allow_exec` | `bool` | 是否允许一次性 shell 命令 |
| `allow_sessions` | `bool` | 是否允许持久 shell session |
| `roots` | `dict[str, dict]` | 每个 root 的可见性配置，格式为 `{"workspace": {"visible": true}, ...}` |
| `visible_skills` | `list[str] \| None` | 显式限制可见 skill 列表（`None` 表示回退到 profile.skills） |
| `notes` | `list[str]` | 决策附加说明 |
| `reason` | `str` | 决策来源说明 |

### Per-Run 权限矩阵

| actor_kind | /workspace | /skills | /self | allow_exec | allow_sessions |
|---|---|---|---|---|---|
| frontstage_agent | visible | visible | visible | true | true |
| subagent | visible | visible | **not visible** | true | true |

最关键的区别是 subagent 的 `/self` 不可见——它无法访问主 agent 的 sticky notes 等私有数据。

---

## 3. WorldView 构建

`ComputerRuntime.prepare_run_context()` 在每轮 run 开始时执行，完成以下步骤：

1. 调用 `effective_policy_for_ctx()` 计算当前 run 的有效 policy（合并 profile 配置和 session-driven 决策）。
2. 调用 `WorkWorldBuilder.build()` 构造 `WorldView`。具体过程为：根据可见 skill 列表，从 thread 共享 skills 目录中复制指定的 skill 到当前 actor 的 skill 视图目录（view_key = `actor_kind:profile_id:skill1,skill2,...`）；确保各根目录存在；把 policy 中的 roots 配置转成 `WorldRootPolicy` 映射；根据后端类型生成 `ExecutionView`（shell 侧看到的路径）。
3. 调用 `backend.ensure_workspace()` 准备后端环境。
4. 如果 policy 允许（`auto_stage_attachments`），自动 stage 附件到 `/workspace/attachments/`。
5. 把 `world_view`、`workspace_state` 附加到 `RunContext`。

### ExecutionView

Shell 执行命令时看到的路径和模型使用的世界路径不同。`ExecutionView` 描述这个映射关系：

| Backend | Shell 侧路径行为 | 说明 |
|---|---|---|
| Host | shell 看到真实的宿主机路径（如 `/home/acacia/.acabot/workspaces/threads/xxx/workspace`） | 无隔离，所有 root 均可见 |
| Docker | shell 只看到 `/workspace`，skills 和 self 在容器内不可见（execution_path 为空字符串） | 容器内挂载点 |

### Skill 视图构建

Skill 视图按 actor 隔离。`WorkWorldBuilder.build()` 根据 `visible_skills` 列表，从 thread 共享 skills 目录（`threads/<thread>/skills/`）中复制指定 skill 到视图目录（`threads/<thread>/skill_views/{view_key}/`）。view_key 由 `actor_kind`、`profile_id` 和排序后的 skill 名列表拼接而成，确保相同配置的 actor 共享同一视图，避免重复物化。同一 thread 内不同 actor 可以看到不同的 skill 集合。

---

## 4. 路径解析

`WorldView.resolve()` 是所有文件操作和 shell 执行的路径入口，解析在 `world.py` 和 `runtime.py` 中实现。前台工具不用知道映射细节，整个流程分为七步：

1. **规范化**：去除 `.`，拒绝 `..`（防止路径穿越），确保以 `/` 开头。
2. **拆分 root**：提取 root kind（`workspace`/`skills`/`self`）和 root 内相对路径。不在已知 root 下的路径直接报错。
3. **可见性检查**：查询 `root_policies`，root 不可见则抛出 `FileNotFoundError`。
4. **Skill 可见性检查**（仅 `/skills` 路径）：取出相对路径的第一段作为 skill_name，检查是否在 `visible_skill_names` 中。
5. **宿主机路径解析**：拼接 `root_host_path + relative_path`，并用 `Path.resolve()` + `relative_to()` 确保不逃逸出 root 目录。
6. **物化检查**（仅 `/skills` 路径）：如果相对路径非空但宿主机文件不存在，说明 skill 尚未物化，抛出错误。
7. **计算执行路径**：根据 `ExecutionView` 生成 shell 侧路径。

### 解析示例

| World Path | Root Kind | 相对路径 | 宿主机路径 | Shell 路径 (host) | Shell 路径 (docker) |
|---|---|---|---|---|---|
| `/workspace/test.txt` | workspace | `test.txt` | `~/.acabot/workspaces/threads/{id}/workspace/test.txt` | 同宿主机 | `/workspace/test.txt` |
| `/skills/data:excel/references/spec.md` | skills | `data:excel/references/spec.md` | `~/.acabot/workspaces/threads/{id}/skill_views/{key}/data:excel/references/spec.md` | 同宿主机 | *(不可见)* |
| `/self/notes/memo.md` | self | `notes/memo.md` | `~/.acabot/workspaces/self/{agent_id}/notes/memo.md` | 同宿主机 | *(不可见)* |

---

## 5. 宿主机目录布局

```
~/.acabot/workspaces/
├── threads/
│   └── {thread_id}/              # URL 编码的 thread ID
│       ├── workspace/            # /workspace 对应的宿主机目录
│       │   ├── .thread_id        # thread ID 标记文件
│       │   ├── attachments/      # 附件存储
│       │   └── scratch/          # 临时文件
│       ├── skills/               # thread 共享 skills 目录（物化后的 skill 副本）
│       └── skill_views/          # 按 actor 隔离的 skills 视图
│           └── {view_key}/       # view_key = actor:profile:skills
└── self/                         # /self 对应的宿主机目录
    └── {agent_id}/               # 按 agent 隔离
```

`WorkspaceManager` 负责这套目录布局的创建和维护。thread_id 使用 URL 编码（`quote(raw, safe="._-")`）转成安全目录名，保留可区分性。

---

## 6. 前台工具行为

前台工具是模型直接调用的四个 builtin tool，入口在 `runtime/builtin_tools/computer.py`，接住调用后转给 `ComputerRuntime`。以下是每个工具的详细行为规格。

### read

参数 `path / offset / limit`。文本文件支持分页，offset/limit 非法或越界报错。图片按文件头字节识别（png/jpg/gif/webp），返回说明文字 + 图片内容块。非 UTF-8 文件按 `errors="replace"` 读成文本。分页和图片识别的实现在 `reading.py` 和 `media.py`。

### write

自动创建父目录，文件不存在就创建，已存在就覆盖，返回写入的 UTF-8 字节数。

### edit

参数 `path / oldText / newText`（与 pi 一致）。先精确匹配，找不到报错，多次匹配报错——确保每次只改一处。支持 `newText=""` 删除、保留 UTF-8 BOM、保留原换行风格。精确匹配失败后还会尝试 fuzzy 匹配。返回 diff 和第一处改动行号。行为以 pi 当前 `edit.js / edit-diff.js` 为准，实现在 `editing.py`。

### bash

`bash(command, timeout?)`。链路：builtin tool → `ComputerRuntime.bash_world()` → `exec_once()` → host/docker backend。timeout 传到 backend，超时返回失败而不是卡住。当前 world 看不到 `/workspace` 或当前 run 不允许 exec 时，前台不显示 bash。ToolBroker 根据 `WorkspaceState.available_tools` 过滤前台工具可见性——前台能不能看到 bash 不只看 agent 配置，还看当前 workspace 状态。

---

## 7. /skills 规则

Runtime 从 `runtime.filesystem.skill_catalog_dirs` 扫描 skill metadata。computer 内部有 `host_skills_catalog_root_path`（宿主机 skills 根路径），这和 runtime 扫描路径不是一回事。

`/skills/...` 的读写走真正的 skills 目录，只要当前 world 能看见就可以直接读。写完 `/skills/...` 后会刷新当前 world 的 skills 视图。

Skill 镜像与物化的具体逻辑：`WorkWorldBuilder.build()` 时根据可见 skill 列表，从 thread 共享 skills 目录复制 skill 到当前 actor 的 skill 视图目录，实现 per-actor 隔离。同一 thread 内不同 actor 可以看到不同的 skill 集合。同一 thread 内相同 view_key 的 actor 共享同一份 skill 视图，避免重复物化。Skill 镜像准备收回 ComputerRuntime 处理，builtin surface 不再偷偷准备。

---

## 8. /self 规则

| 场景 | 可见性 | 可写性 | 说明 |
|---|---|---|---|
| 前台 agent（frontstage_agent） | 可见 | 可写 | 完整访问 |
| subagent | 不可见 | 不可写 | 如果能看到那是 bug |

`/self` 不跟 thread 一起清理，是 actor 级别的持久化存储。

---

## 9. Backend

`ComputerBackend`（`backends.py`）抽象三类后端，只做底层操作：`ensure_workspace()`、`list_entries()`、`read_text()`、`read_bytes()`、`write_text()`、`exec_once()`、shell session、`get_sandbox_status()`、`stop_workspace_sandbox()`。Backend 不负责 world path 解析、`/skills` `/self` 可见性判断、edit 的替换规则、模型工具文案。

### Host

直接在宿主机上执行命令，无隔离。Shell 看到真实的宿主机路径。通过 `asyncio.create_subprocess_shell/exec` 实现。适用于开发调试和可信环境。

### Docker

每个 thread 一个容器，提供执行隔离。容器名格式为 `acabot-{sha256(thread_id)[:16]}`，宿主机 workspace 目录挂载到容器内的 `/workspace`。容器内只能看到 `/workspace`，skills 和 self 不可见。支持配置网络模式（`bridge`/`none`/`host`）和镜像。

### Remote

占位实现，当前调用会抛出 `ComputerBackendNotImplemented`。

`list_entries()` 虽然前台没有 `ls` 了，但内部仍被控制面、workspace 摘要、附件列表使用。

---

## 10. 附件 Staging

当用户发送图片、文件等附件时，Computer 可以自动把它们拉到 Work World 中。流程如下：

1. `prepare_run_context()` 检查 policy 是否允许自动 stage（`auto_stage_attachments`）。
2. 遍历 `ctx.event.attachments`（来源为 `StandardEvent.attachments`），逐个调用 `AttachmentResolver.stage()`。
3. 附件下载到 `/workspace/attachments/{category}/{event_id}/` 下。
4. 生成 `AttachmentSnapshot`，记录 stage 结果（路径、大小、状态）。
5. `attachment_snapshots` 附加到 `RunContext`，后续文件工具可以直接用世界路径访问。

Reply 图片也走这套链路，后续消息整理、图片说明、reply 图片处理复用本地文件路径。

---

## 11. Shell Session

除了通过 `bash` 工具执行一次性命令外，Computer 还支持持久 shell session。相关方法均挂在 `ComputerRuntime` 上：

| 操作 | 说明 |
|---|---|
| `open_session()` | 创建一个持久的 shell 进程，绑定到当前 thread |
| `write_session()` | 向已有 session 写入命令 |
| `read_session()` | 读取 session 的 stdout/stderr 缓冲 |
| `close_session()` | 关闭 session |

Session 按 thread 隔离，存储在 `ComputerRuntime._sessions` 字典中。是否允许 session 由 `ComputerPolicyDecision.allow_sessions` 控制。前台模型不直接使用 session API，这些能力由控制面和内部流程调用。

---

## 12. WorkspaceState

WorkspaceState 不是文件树本体，而是摘要。给当前 run 上下文、ToolBroker、控制面和 WebUI 看。包含以下信息：当前 thread、backend、`/workspace` 宿主机路径、可见 computer 工具、附件数量、活跃 shell session。

ToolBroker 根据 `WorkspaceState.available_tools` 过滤前台工具可见性——前台能不能看到 bash 不只看 agent 配置，还看当前 workspace 状态。例如当前 world 没有 `/workspace` 或当前 run 不允许 exec 时，bash 工具会被隐藏。

---

## 13. 配置

Computer 的配置分为三个层级，优先级从低到高为：runtime 级别 → profile 级别 → session 级别。

### Runtime 级别

全局默认配置，设定 backend 和文件系统根目录，影响所有 profile 和 session：

```yaml
runtime:
  computer:
    backend: "host"
  filesystem:
    computer_root_dir: "../runtime-data/workspaces"
```

### Profile 级别

每个 profile 可以单独配置 computer 行为，包括 backend、exec 权限、附件自动 stage 等：

```yaml
runtime:
  profiles:
    aca:
      computer:
        backend: "host"
        allow_exec: true
        allow_sessions: true
        auto_stage_attachments: true
        network_mode: "enabled"
```

### Session 级别（computer domain）

最高优先级，通过 surface 的 computer domain 实现最细粒度的控制，支持 cases 条件匹配：

```yaml
surfaces:
  message.mention:
    computer:
      default:
        preset: sandbox_member
      cases:
        - case_id: admin_host
          when:
            sender_roles: [admin]
          use:
            preset: host_operator
```

Session 级别配置通过 `SessionRuntime.resolve_computer()` 解析为 `ComputerPolicyDecision`，传入 `prepare_run_context()`。没有 session-driven 决策时回退到 profile 配置，再没有则使用 runtime 默认值。

---

## 14. 控制面能力

控制面通过 `RuntimeWorkspaceControlOps` / `RuntimeControlPlane` / HTTP API 使用 computer 的内部能力。这些能力不给模型直接调用：

| 能力 | 说明 |
|---|---|
| 列 workspace 摘要 | 查看各 thread 的 workspace 概况 |
| 附件列表 | 枚举已 stage 的附件 |
| 活跃 shell session | 查看当前存活的 session |
| sandbox 状态 | 查询 Docker 容器运行状态 |
| workspace 清理 | 删除指定 thread 的工作目录 |
| sandbox 停止 | 停止 Docker 容器 |
| 已镜像的 skills | 查看当前已物化到 skill_views 的 skill 列表 |

内部还有 `prepare_run_context()`（准备 world/workspace/附件 staging）、`stage_attachments()`、`exec_once()` 等方法供内部流程使用。

---

## 15. 附录：数据结构

### ComputerPolicyDecision

```python
@dataclass
class ComputerPolicyDecision:
    actor_kind: str              # frontstage_agent | subagent | maintainer
    backend: str                 # host | docker | remote
    allow_exec: bool
    allow_sessions: bool
    roots: dict[str, dict]       # {"workspace": {"visible": true}, ...}
    visible_skills: list[str] | None
    notes: list[str]
    reason: str
```

### ResolvedWorldPath

```python
@dataclass
class ResolvedWorldPath:
    world_path: str              # 模型侧使用的路径
    root_kind: str               # workspace | skills | self
    relative_path: str           # root 内相对路径
    host_path: str               # 宿主机路径
    execution_path: str          # shell 侧路径（不可见时为空）
    visible: bool
```

---

## 16. 源码索引

建议按以下顺序阅读源码，从入口到边缘逐步展开：

| 顺序 | 文件 | 职责 |
|---|---|---|
| 1 | `src/acabot/runtime/computer/runtime.py` | ComputerRuntime 本体——统一入口（prepare_run_context、文件操作、命令执行） |
| 2 | `src/acabot/runtime/computer/contracts.py` | 数据结构定义（ComputerPolicy、WorldView、WorkspaceState 等）、协议声明 |
| 3 | `src/acabot/runtime/computer/world.py` | WorldView 实现、WorkWorldBuilder、路径解析 |
| 4 | `src/acabot/runtime/computer/workspace.py` | 宿主机目录布局管理（WorkspaceManager）、thread workspace 管理 |
| 5 | `src/acabot/runtime/computer/backends.py` | Backend 实现（Host、Docker、Remote） |
| 6 | `src/acabot/runtime/computer/attachments.py` | 附件 staging（AttachmentResolver） |
| 7 | `src/acabot/runtime/computer/reading.py` | read 的分页和图片识别 |
| 8 | `src/acabot/runtime/computer/editing.py` | edit 的精确/fuzzy 匹配和替换规则 |
| 9 | `src/acabot/runtime/computer/media.py` | 图片格式识别 |
| 10 | `src/acabot/runtime/builtin_tools/computer.py` | 模型看到的工具 schema，接住调用后转给 ComputerRuntime |
| 11 | `src/acabot/runtime/tool_broker/broker.py` | ToolBroker 根据 WorkspaceState 过滤工具可见性 |
| 12 | `src/acabot/runtime/control/workspace_ops.py` | 控制面 workspace 操作 |
| 13 | `src/acabot/runtime/control/session_runtime.py` | Session-driven computer 决策 |
