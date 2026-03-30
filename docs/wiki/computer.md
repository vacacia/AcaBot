# Computer 系统

Computer 是 AcaBot 为 AI 模型提供的受控文件系统和执行环境。模型通过世界路径（World Path）操作文件、执行命令，而永远不会直接接触宿主机的真实路径。Computer 决定了每一轮 run 中模型能看到什么、能做什么。

## Work World

Work World 是模型眼中的"文件系统"，包含三个根路径：

- `/workspace` — 当前线程的工作目录，存放临时文件、附件等
- `/skills` — 当前可见 skill 的目录（按需物化）
- `/self` — 当前 actor 的持久化目录（sticky notes 等）

这三个根路径分别映射到宿主机上的不同目录，映射关系由 `WorkspaceManager` 管理，路径解析由 `WorldView.resolve()` 完成。模型只使用 `/workspace/...`、`/skills/...`、`/self/...` 这样的世界路径，runtime 负责把它们翻译成宿主机路径或 shell 执行路径。

## Policy 决策

每一轮 run 的 computer 权限不是固定的，而是通过 Policy 决策机制 per-run 计算。决策有两个来源，按优先级排列：

**Session-driven 决策**：`SessionRuntime.resolve_computer()` 根据会话配置（surface 级 computer domain 配置、cases 条件匹配）生成 `ComputerPolicyDecision`。支持按 sender_roles、actor_lane 等条件匹配不同的权限预设。

**Profile 兜底**：当没有 session-driven 决策时，从 `profile.computer_policy` 读取配置。如果 profile 也没有配置，使用 `ComputerRuntime` 的默认 policy（host backend，允许 exec 和 sessions）。

`ComputerPolicyDecision` 包含以下关键字段：

- `actor_kind`：当前 actor 的身份（`frontstage_agent`、`subagent`、`maintainer`），影响 root 可见性
- `backend`：执行后端（`host`、`docker`、`remote`）
- `allow_exec`：是否允许一次性 shell 命令
- `allow_sessions`：是否允许持久 shell session
- `roots`：每个 root 的可见性配置，格式为 `{"workspace": {"visible": true}, "skills": {"visible": true}, "self": {"visible": false}}`
- `visible_skills`：显式限制可见 skill 列表（`None` 表示回退到 profile.skills）

### Per-Run 权限示例

| actor_kind | /workspace | /skills | /self | allow_exec | allow_sessions |
|---|---|---|---|---|---|
| frontstage_agent | visible | visible | visible | true | true |
| subagent | visible | visible | **not visible** | true | true |

最关键的区别是 subagent 的 `/self` 不可见——它无法访问主 agent 的 sticky notes 等私有数据。

## WorldView 构建

`ComputerRuntime.prepare_run_context()` 在每轮 run 开始时执行，完成以下步骤：

1. 调用 `effective_policy_for_ctx()` 计算当前 run 的有效 policy（合并 profile 配置和 session-driven 决策）
2. 调用 `WorkWorldBuilder.build()` 构造 `WorldView`：
   - 根据可见 skill 列表，从 thread 共享 skills 目录中复制指定的 skill 到当前 actor 的 skill 视图目录（view_key = `actor_kind:profile_id:skill1,skill2,...`）
   - 确保各根目录存在
   - 把 policy 中的 roots 配置转成 `WorldRootPolicy` 映射
   - 根据后端类型生成 `ExecutionView`（shell 侧看到的路径）
3. 调用 `backend.ensure_workspace()` 准备后端环境
4. 如果 policy 允许，自动 stage 附件到 `/workspace/attachments/`
5. 把 `world_view`、`workspace_state` 附加到 `RunContext`

### ExecutionView

shell 执行命令时看到的路径和模型使用的世界路径不同。`ExecutionView` 描述这个映射关系：

- **Host backend**：shell 看到真实的宿主机路径（如 `/home/acacia/.acabot/workspaces/threads/xxx/workspace`）
- **Docker backend**：shell 只看到 `/workspace`，skills 和 self 在容器内不可见（execution_path 为空字符串）

## 路径解析

`WorldView.resolve()` 是所有文件操作和 shell 执行的路径入口。解析流程如下：

1. **规范化**：去除 `.`，拒绝 `..`（防止路径穿越），确保以 `/` 开头
2. **拆分 root**：提取 root kind（`workspace`/`skills`/`self`）和 root 内相对路径。不在已知 root 下的路径直接报错
3. **可见性检查**：查询 `root_policies`，root 不可见则抛出 `FileNotFoundError`
4. **Skill 可见性检查**（仅 `/skills` 路径）：取出相对路径的第一段作为 skill_name，检查是否在 `visible_skill_names` 中
5. **宿主机路径解析**：拼接 root_host_path + relative_path，并用 `Path.resolve()` + `relative_to()` 确保不逃逸出 root 目录
6. **物化检查**（仅 `/skills` 路径）：如果相对路径非空但宿主机文件不存在，说明 skill 尚未物化，抛出错误
7. **计算执行路径**：根据 `ExecutionView` 生成 shell 侧路径

### 解析示例

| World Path | Root Kind | 相对路径 | 宿主机路径 | Shell 路径 (host) | Shell 路径 (docker) |
|---|---|---|---|---|---|
| `/workspace/test.txt` | workspace | `test.txt` | `~/.acabot/workspaces/threads/{id}/workspace/test.txt` | 同宿主机 | `/workspace/test.txt` |
| `/skills/data:excel/references/spec.md` | skills | `data:excel/references/spec.md` | `~/.acabot/workspaces/threads/{id}/skill_views/{key}/data:excel/references/spec.md` | 同宿主机 | *(不可见)* |
| `/self/notes/memo.md` | self | `notes/memo.md` | `~/.acabot/workspaces/self/{agent_id}/notes/memo.md` | 同宿主机 | *(不可见)* |

## 宿主机目录布局

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

## Backend

Backend 决定了命令的实际执行方式。当前有三个 backend：

### Host

直接在宿主机上执行命令，无隔离。shell 看到真实的宿主机路径。通过 `asyncio.create_subprocess_shell/exec` 实现。适用于开发调试和可信环境。

### Docker

每个 thread 一个容器，提供执行隔离。容器名格式为 `acabot-{sha256(thread_id)[:16]}`，宿主机 workspace 目录挂载到容器内的 `/workspace`。容器内只能看到 `/workspace`，skills 和 self 不可见。支持配置网络模式（`bridge`/`none`/`host`）和镜像。

### Remote

占位实现，当前调用会抛出 `ComputerBackendNotImplemented`。

## 附件 Staging

当用户发送图片、文件等附件时，Computer 可以自动把它们拉到 Work World 中。流程如下：

1. `prepare_run_context()` 检查 policy 是否允许自动 stage（`auto_stage_attachments`）
2. 遍历 `ctx.event.attachments`，逐个调用 `AttachmentResolver.stage()`
3. 附件下载到 `/workspace/attachments/{category}/{event_id}/` 下
4. 生成 `AttachmentSnapshot`，记录 stage 结果（路径、大小、状态）
5. `attachment_snapshots` 附加到 `RunContext`，后续文件工具可以直接用世界路径访问

## Shell Session

除了通过 `bash` 工具执行一次性命令外，Computer 还支持持久 shell session：

- `open_session()`：创建一个持久的 shell 进程，绑定到当前 thread
- `write_session()`：向已有 session 写入命令
- `close_session()`：关闭 session
- `read_session()`：读取 session 的 stdout/stderr 缓冲

Session 按 thread 隔离，存储在 `ComputerRuntime._sessions` 字典中。

## 配置

### Profile 级别

```yaml
runtime:
  profiles:
    aca:
      computer:
        backend: "host"           # host | docker | remote
        allow_exec: true
        allow_sessions: true
        auto_stage_attachments: true
        network_mode: "enabled"   # enabled | disabled | bridge | none | host
```

### Session 级别（computer domain）

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

Session 级配置可以按条件覆盖 profile 级别的默认值。

### Runtime 级别

```yaml
runtime:
  computer:
    backend: "host"
  filesystem:
    computer_root_dir: "../runtime-data/workspaces"
```

---

## 附录

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

### 源码索引

| 文件 | 职责 |
|------|------|
| `src/acabot/runtime/computer/contracts.py` | 数据结构定义、协议声明 |
| `src/acabot/runtime/computer/world.py` | WorldView 实现、WorkWorldBuilder |
| `src/acabot/runtime/computer/workspace.py` | 宿主机目录布局管理 |
| `src/acabot/runtime/computer/runtime.py` | 统一入口（prepare_run_context、文件操作、命令执行） |
| `src/acabot/runtime/computer/backends.py` | Backend 实现（Host、Docker、Remote） |
| `src/acabot/runtime/computer/attachments.py` | 附件 staging |
| `src/acabot/runtime/computer/editing.py` | 文本编辑（diff 生成） |
| `src/acabot/runtime/computer/reading.py` | 文件读取（文本格式化） |
| `src/acabot/runtime/computer/media.py` | 图片等媒体文件处理 |
| `src/acabot/runtime/control/session_runtime.py` | Session-driven computer 决策 |
