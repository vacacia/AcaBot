# Work World Computer / Sandbox Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AcaBot 的前台 `computer` 从“thread workspace + file helpers + exec”收成一套真正的 Work World 协议：文件工具统一只吃 `/workspace /skills /self` 这套 World Path，附件正式进入 `/workspace/attachments/...`，host / docker backend 逐步承接同一套执行世界。

**Architecture:** 先做协议，不先做复杂 sandbox。第一阶段先把 world builder 的稳定输入收出来，并把 rule 和 computer 的边界拆开；然后引入 World Path / Host Path / Execution View Path / Origin Handle 这些最小 contract，让 `read / write / edit / ls / grep` 全部改走 world resolver。第二阶段再把附件、`/skills`、`/self` 接进同一套 contract。第三阶段收 host backend 的 execution view，最后再让 docker backend 对齐。backend 只承接世界，不定义世界。

**Tech Stack:** Python runtime、`ComputerRuntime`、`WorkspaceManager`、现有 `host/docker` computer backend、pytest。

---

## 0. 先明确范围和非目标

这份计划只针对 **Work World**：

- 前台 agent
- 前台 subagent
- 其承载层 sandbox / host backend / docker backend

backend maintainer **不进入** 这套协议，继续工作在 repo root 和 `.acabot-runtime/` 上。

这份计划当前 **不要求**：

- 完整的 mount table / fs bridge 复杂度
- shell 命令文本路径重写
- 一步做完所有 sandbox policy 细节
- 删除 `skill(name=...)`
- 定死 `/self` 里有哪些具体文件格式

真正主线只有一句话：

> 先把前台 Work World 的路径协议收稳，再让 shell 和 backend 承接它。

---

## 1. 先把 world 构造依据和 rule 边界拆出来

在真正实现 Work World 之前，先要做一件很容易被忽略、但如果不先做后面一定会继续乱的事：

> 把“哪些输入决定 world”从混乱的 rule 里拆出来。

world builder 以后应该只依赖少数稳定输入：

- actor kind（前台 agent / subagent / backend maintainer）
- profile / capability bundle
- thread / session identity
- effective computer policy / override
- 当前 run 的附件来源（Origin Handle）

而现有 rule 只应通过很窄的上游出口影响 world，例如：

- 决定消息最后给哪个 actor
- 决定当前用哪个 profile
- 决定是否存在 operator 级 backend override

rule 不应该再直接碰这些事情：

- `/self` 对谁可见
- `/skills` 根要不要出现
- file tools 吃什么路径协议
- shell 里是否真的出现 `/workspace /skills /self`

所以第一步不是写路径代码，而是先把 rule 明确拆成：

- routing rules
- context rules
- computer policy

其中前两类不该直接定义 world，第三类才是 world builder 的正式输入。

---

## 2. 预期文件图和职责

### `src/acabot/runtime/computer/contracts.py`

新增或扩展 Work World 相关契约，至少包括：

- World Path / Host Path / Execution View Path / Origin Handle 相关 dataclass
- `WorldRootKind`（`workspace` / `skill` / `self`）
- `ComputerActorKind`（至少 `frontstage_agent` / `subagent`）
- `ResolvedWorldPath`
- `WorldView` / `ExecutionView`

### `src/acabot/runtime/computer/workspace.py`

从“thread workspace 路径工具”提升成 Work World 视图装配器，负责：

- 计算 thread workspace 根
- 计算当前 actor 的可见 roots
- 解析 World Path -> Host Path
- 构造 host backend 的 execution view 根（例如 `exec-root/`）

### `src/acabot/runtime/computer/runtime.py`

变成 Work World runtime 主入口，负责：

- 生成当前 run 的 `WorldView`
- 让 file tools 统一走 world resolver
- 让 attachment staging 输出 World Path
- 让 shell session / exec 使用 `ExecutionView`

### `src/acabot/runtime/computer/backends.py`

backend 不再拥有路径主权，只负责承接 execution view：

- [ ] host backend：在 host 上实现 execution view
- [ ] docker backend：在 docker 里承接同一套 execution view

### `src/acabot/runtime/plugins/computer_tool_adapter.py`

退回纯接线层：

- 不再自己理解 `/skills` 或 `/self`
- 不再自己拼宿主机路径
- 统一把 World Path 交给 `ComputerRuntime`

### `src/acabot/runtime/tool_broker/broker.py`

向工具上下文传递 actor kind / world view 摘要，让 tool adapter 和 prompt 组装都能知道当前 actor 是前台还是 subagent。

### `src/acabot/runtime/contracts/context.py`

如有必要，增加 run 级 `world_view` / `execution_view` 相关字段，避免语义散落在 metadata 字典里。

### `src/acabot/runtime/skills/tool_adapter.py`

保留兼容入口，但降级为过渡角色。后续主路径应转向 `/skills/...`。

### `tests/runtime/test_computer_world_paths.py`

新增测试文件，专门覆盖：

- World Path resolve
- actor visibility
- `/self` 对 subagent 不可见
- `/skills` 只读
- `/workspace` 可写

### `tests/runtime/test_computer.py`

补现有 runtime 主线测试：

- `prepare_run_context()` 产出 world view
- attachment staging 进入 `/workspace/attachments/...`
- shell/execution view 摘要正确

### `tests/runtime/test_computer_tool_adapter.py`

补 tool adapter 行为测试：

- file tools 走 World Path
- `/self` / `/skills` 权限边界正确

### `docs/12-computer.md`

实现后同步更新，把 `computer` 的定位从“workspace + attachment + shell 基础设施”改写成 Work World runtime。

---

## 3. Task 1：先把 world 构造依据和 rule 边界收出来

**Files:**
- Modify: `src/acabot/runtime/contracts/routing.py`
- Modify: `src/acabot/runtime/router.py`
- Modify: `src/acabot/runtime/app.py`
- Modify: `src/acabot/runtime/control/event_policy.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/computer/contracts.py`
- Test: `tests/runtime/test_computer_world_inputs.py`

- [ ] **Step 1: 写失败测试，把 world builder 的输入边界先定死**

至少覆盖：

- actor kind 由上游路由结果决定，而不是 computer 自己猜
- profile / computer policy 会进入 world builder
- sticky note / memory / prompt 注入规则不会直接改变 world roots
- subagent world 不会因为上下文规则命中而突然看见 `/self`

- [ ] **Step 2: 运行测试确认当前失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_inputs.py -v
```

Expected:

- 失败，说明当前 world 输入和 rule 边界没有被正式建模

- [ ] **Step 3: 在 runtime 层补最小 world input 模型**

至少明确这些输入：

- actor kind
- profile / capability bundle
- thread / session identity
- effective computer policy / override
- attachment origin handles

- [ ] **Step 4: 把 rule 拆成“影响 world 的上游输入”和“不影响 world 的上下文规则”**

这里先做边界收口，不要求一口气把整个 rule 系统重写完。最小目标是：

- routing / profile 选择仍然在上游
- context 注入规则不直接改 computer 世界结构
- computer policy 成为 world builder 正式输入

- [ ] **Step 5: 再跑测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_inputs.py -v
```

Expected:

- world builder 输入边界已明确，rule 不再直接篡改 world 结构

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/contracts/routing.py src/acabot/runtime/router.py src/acabot/runtime/app.py src/acabot/runtime/control/event_policy.py src/acabot/runtime/computer/runtime.py src/acabot/runtime/computer/contracts.py tests/runtime/test_computer_world_inputs.py
git commit -m "refactor: separate world inputs from routing and context rules"
```

---

## 4. Task 2：先立 Work World 的契约和 resolver 骨架

**Files:**

- Modify: `src/acabot/runtime/computer/contracts.py`
- Modify: `src/acabot/runtime/computer/workspace.py`
- Test: `tests/runtime/test_computer_world_paths.py`

- [ ] **Step 1: 写第一批失败测试，先把概念定死**

至少覆盖下面这些 case：

- 前台 agent resolve `/workspace/out/report.md` 成功
- 前台 agent resolve `/skills/excel/SKILL.md` 成功
- 前台 agent resolve `/self/task.md` 成功
- subagent resolve `/self/task.md` 失败（不可见，不是只读失败）
- `/skills/...` resolve 后为只读
- `/workspace/...` resolve 后为可写

- [ ] **Step 2: 运行测试确认当前一定失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py -v
```

Expected:

- 失败，提示缺少 World Path / actor visibility / resolver 实现

- [ ] **Step 3: 在 `contracts.py` 里补最小契约**

先只补最小需要的结构，不要一上来设计成庞大对象图。至少需要：

- `ComputerActorKind`
- `WorldRootKind`
- `ResolvedWorldPath`
- `WorldView`
- `ExecutionView`

- [ ] **Step 4: 在 `workspace.py` 里写最小 resolver 骨架**

先只支持三类 World Path：

- `/workspace/...`
- `/skills/<name>/...`
- `/self/...`

并先实现最关键的 actor 规则：

- 前台 agent 看得见 `/self`
- subagent 看不见 `/self`

- [ ] **Step 5: 再跑测试，补齐最小实现直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py -v
```

Expected:

- 所有 resolve / visibility 测试通过

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/computer/contracts.py src/acabot/runtime/computer/workspace.py tests/runtime/test_computer_world_paths.py
git commit -m "feat: add work world path contracts and resolver"
```

---

## 5. Task 3：让 file tools 统一只吃 World Path

**Files:**

- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/plugins/computer_tool_adapter.py`
- Modify: `tests/runtime/test_computer.py`
- Modify: `tests/runtime/test_computer_tool_adapter.py`
- Test: `tests/runtime/test_computer_world_paths.py`

- [ ] **Step 1: 为 file tools 行为写失败测试**

补下面这些测试：

- `read("/skills/excel/SKILL.md")` 走 resolver，不直接拼 thread workspace
- `write("/skills/excel/SKILL.md")` 被拒绝
- `write("/self/task.md")` 对前台可行，对 subagent 不可见
- `grep("/workspace")` 仍然工作

- [ ] **Step 2: 运行目标测试确认失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_tool_adapter.py tests/runtime/test_computer.py -v
```

Expected:

- 当前实现仍偏 host workspace 语义，相关 case 失败

- [ ] **Step 3: 在 `ComputerRuntime` 加入统一 world resolve 入口**

不要让 `read_workspace_file`、`write_workspace_file`、`list_workspace_entries`、`grep_workspace` 继续各自理解路径。改成：

- 先 resolve World Path
- 再根据 `ResolvedWorldPath` 决定 Host Path 和权限

- [ ] **Step 4: 让 tool adapter 彻底退回接线层**

`computer_tool_adapter.py` 不应再拥有路径语义。它只负责：

- 收到模型传入的 World Path
- 调 `ComputerRuntime`
- 返回工具结果

- [ ] **Step 5: 再跑 file tools 相关测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py tests/runtime/test_computer_tool_adapter.py tests/runtime/test_computer.py -v
```

Expected:

- file tools 全部按 World Path 协议工作

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/computer/runtime.py src/acabot/runtime/plugins/computer_tool_adapter.py tests/runtime/test_computer.py tests/runtime/test_computer_tool_adapter.py tests/runtime/test_computer_world_paths.py
git commit -m "feat: route computer file tools through world paths"
```

---

## 6. Task 4：把附件正式接进 Work World

**Files:**

- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/computer/attachments.py`
- Modify: `src/acabot/runtime/contracts/context.py`
- Modify: `tests/runtime/test_computer.py`
- Create: `tests/runtime/test_computer_attachments_world_paths.py`

- [ ] **Step 1: 写附件进入 `/workspace/attachments/...` 的失败测试**

至少覆盖：

- inbound 附件 staging 后，World Path 为 `/workspace/attachments/inbound/...`
- reply 附件 staging 后，World Path 为 `/workspace/attachments/reply/...`
- tool / runtime 上下文里不再需要把宿主机真实路径暴露给模型

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_attachments_world_paths.py tests/runtime/test_computer.py -v
```

Expected:

- 当前 staging 只有本地快照，没有正式 World Path 语义

- [ ] **Step 3: 给附件 snapshot 补 Work World 视角字段**

不要只保留“staged_path”，至少让 runtime 能知道：

- Origin Handle
- Host Path
- World Path

- [ ] **Step 4: 让 staging 的完成条件变成“进入 Work World”**

也就是说，staging 完成后，后续所有消费者都应把附件当成 `/workspace/attachments/...` 下的普通文件对象，而不是临时本地下载物。

- [ ] **Step 5: 再跑测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_attachments_world_paths.py tests/runtime/test_computer.py -v
```

Expected:

- 附件已经正式进入 Work World

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/computer/runtime.py src/acabot/runtime/computer/attachments.py src/acabot/runtime/contracts/context.py tests/runtime/test_computer.py tests/runtime/test_computer_attachments_world_paths.py
git commit -m "feat: stage attachments into work world paths"
```

---

## 7. Task 5：把 `/skills` 和 `/self` 真正收进 actor-aware world view

**Files:**

- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/computer/workspace.py`
- Modify: `src/acabot/runtime/tool_broker/broker.py`
- Modify: `src/acabot/runtime/skills/tool_adapter.py`
- Test: `tests/runtime/test_computer_world_paths.py`
- Modify: `tests/runtime/test_control_plane.py`

- [ ] **Step 1: 写 actor-aware world view 的失败测试**

至少覆盖：

- 前台 agent world view 包含 `/self`
- subagent world view 不包含 `/self`
- `/skills` 是当前 actor 可见 skills 的视图，不是全局 skills 真源直通

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py tests/runtime/test_control_plane.py -v
```

Expected:

- 当前 run context / tool context 还没有稳定 world view 摘要

- [ ] **Step 3: 在 runtime / tool broker 上补 actor kind 和 world view 摘要传递**

不要继续把这些语义塞进松散 metadata，至少让 world view 和 actor kind 成为正式 runtime 概念。

- [ ] **Step 4: 把 `/skills` 从“mirror 接缝”升级成正式 root**

注意这一步不要求删掉 `skill(name=...)`，只要求：

- `/skills/...` 成为正式可见根
- `skill(name=...)` 退回兼容入口

- [ ] **Step 5: 再跑测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py tests/runtime/test_control_plane.py tests/runtime/test_computer_tool_adapter.py -v
```

Expected:

- `/skills` 与 `/self` 已正式进入 actor-aware Work World

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/computer/runtime.py src/acabot/runtime/computer/workspace.py src/acabot/runtime/tool_broker/broker.py src/acabot/runtime/skills/tool_adapter.py tests/runtime/test_computer_world_paths.py tests/runtime/test_control_plane.py
git commit -m "feat: make skills and self part of actor-aware work world"
```

---

## 8. Task 6：先在 host backend 上做出 Execution View

**Files:**

- Modify: `src/acabot/runtime/computer/workspace.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Modify: `src/acabot/runtime/computer/backends.py`
- Create: `tests/runtime/test_computer_execution_view.py`
- Modify: `tests/runtime/test_computer.py`

- [ ] **Step 1: 写 host execution view 的失败测试**

至少覆盖：

- 前台 agent execution view 里有 `workspace/`、`skills/`、`self/`
- subagent execution view 里没有 `self/`
- host shell 默认工作在 execution root 上，而不是裸 thread workspace

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_execution_view.py tests/runtime/test_computer.py -v
```

Expected:

- 当前 host backend 只按 workspace cwd 工作，没有完整 execution view

- [ ] **Step 3: 在 `workspace.py` 里实现 execution root 装配**

最小可行方案即可，不要一上来追求复杂 namespace。第一版只需要让 host backend 有一个真实 execution root，里面包含：

- `workspace`
- `skills`
- `self`（仅前台）

- [ ] **Step 4: 让 host exec / shell session 使用 execution view**

不要再让 host shell 直接对着 thread workspace 跑。它应该对着 execution root 工作。

- [ ] **Step 5: 再跑测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_execution_view.py tests/runtime/test_computer.py -v
```

Expected:

- host backend 已经能承接 Work World 的 shell 视图

- [ ] **Step 6: Commit**

```bash
git add src/acabot/runtime/computer/workspace.py src/acabot/runtime/computer/runtime.py src/acabot/runtime/computer/backends.py tests/runtime/test_computer_execution_view.py tests/runtime/test_computer.py
git commit -m "feat: add host execution view for work world"
```

---

## 9. Task 7：让 docker backend 承接同一套 Execution View

**Files:**

- Modify: `src/acabot/runtime/computer/backends.py`
- Modify: `src/acabot/runtime/computer/runtime.py`
- Create: `tests/runtime/test_computer_docker_execution_view.py`
- Modify: `docs/18-sandbox-notes-openclaw-vs-astrbot.md`

- [ ] **Step 1: 写 docker execution view 对齐测试**

至少覆盖：

- docker backend 不再只挂 thread workspace 到 `/workspace`
- 它承接的是完整 execution view
- subagent 仍然没有 `/self`

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_docker_execution_view.py -v
```

Expected:

- 当前 docker backend 仍然只有单一 `/workspace` 假设

- [ ] **Step 3: 用最小实现让 docker backend 承接 execution view**

这一步不要追求 OpenClaw 全复杂度。重点是：

- backend 承接 execution view
- backend 不再自己重新定义前台世界

- [ ] **Step 4: 再跑测试直到通过**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_docker_execution_view.py tests/runtime/test_computer.py -v
```

Expected:

- docker backend 已承接同一套 Work World shell 视图

- [ ] **Step 5: Commit**

```bash
git add src/acabot/runtime/computer/backends.py src/acabot/runtime/computer/runtime.py tests/runtime/test_computer_docker_execution_view.py docs/18-sandbox-notes-openclaw-vs-astrbot.md
git commit -m "feat: align docker backend with work world execution view"
```

---

## 10. Task 8：文档和术语收口

**Files:**

- Modify: `docs/12-computer.md`
- Modify: `docs/20-critical-architecture-issues.md`
- Modify: `docs/22-work-world-computer-and-sandbox.md`
- Modify: `docs/00-ai-entry.md`

- [ ] **Step 1: 更新 `12-computer.md`**

把 `computer` 的定位改成 Work World runtime，而不只是 workspace/file/shell helper。

- [ ] **Step 2: 更新 `20-critical-architecture-issues.md`**

把“computer 的文件操作和 backend 语义还没统一”这条问题状态同步为阶段性解决或部分解决。

- [ ] **Step 3: 更新入口文档**

确保 `00-ai-entry.md` 能把读者引到新的总设计文档和更新后的 computer 文档。

- [ ] **Step 4: 运行目标测试和文档相关回归检查**

Run:

```bash
PYTHONPATH=src pytest tests/runtime/test_computer_world_paths.py tests/runtime/test_computer_attachments_world_paths.py tests/runtime/test_computer_execution_view.py tests/runtime/test_computer_docker_execution_view.py tests/runtime/test_computer_tool_adapter.py tests/runtime/test_computer.py -v
```

Expected:

- 相关 computer/world path/execution view 测试全部通过

- [ ] **Step 5: Commit**

```bash
git add docs/12-computer.md docs/20-critical-architecture-issues.md docs/22-work-world-computer-and-sandbox.md docs/00-ai-entry.md
git commit -m "docs: document work world computer and sandbox design"
```

---

## 11. 完成标准

这份计划全部完成后，至少要满足下面这些结果：

- 模型对 file tools 统一只说 `/workspace /skills /self` 这套 World Path
- `/self` 对前台 agent 可见可写，对 subagent 完全不可见
- 附件 staging 后正式进入 `/workspace/attachments/...`
- `/skills` 成为正式 world root，而不只是 mirror 接缝
- host backend 的 shell 已经工作在完整 Execution View 上
- docker backend 承接同一套 Execution View，而不是重新定义前台世界
- `computer` 真正成为 Work World runtime，而不是只是一组 workspace helpers

---

## 12. 实施顺序的最短版本

如果要把整份计划压成最短版本，可以记成三句话：

1. **先统一 file tools 的语言。**
2. **再让附件、skills、self 正式进入这套语言。**
3. **最后让 shell 和 backend 承接同一个世界。**

---

Plan complete and saved to `docs/superpowers/plans/2026-03-20-work-world-computer-and-sandbox.md`. Ready to execute?
