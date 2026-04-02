# Foreground Worker

私聊里，当一个任务需要跨越多条消息、维护连续执行上下文时，bot 可以显式升级成一个 foreground worker。

群聊继续走 `event -> short run`，不受影响。

---

## 核心概念

### Worker 是什么

Worker 是绑定在私聊 thread 上的、有 inbox 的、可以被用户消息打断的长期执行实体。

它和 run 的区别：

| | run | foreground worker |
|---|---|---|
| 生命周期 | 一条消息，结束即销毁 | 跨越多条消息，显式结束 |
| 用户消息怎么进来 | 触发新 run | 进入 worker inbox |
| 工具上下文 | 每次重新组装 | worker 自己维护，天然连续 |
| 并发 | 同 thread 可并发 | 同 thread 同时只有一个 active worker |

### Worker 的状态

```
idle -> running -> waiting_input -> running -> ... -> done / failed
```

- `running`：worker 正在执行 tool loop
- `waiting_input`：worker 主动挂起，等用户回复
- `done`：任务完成，worker 销毁
- `failed`：执行失败，worker 销毁

### Worker 的执行上下文

Worker 有自己的私有执行上下文，不是某个 run 的私有态泄漏出来的：

```python
@dataclass
class WorkerExecutionContext:
    worker_id: str
    thread_id: str
    tool_messages: list[ModelMessage]   # worker 自己的 tool loop 历史
    inbox_messages: list[InboxMessage]  # 用户通过 inbox 发来的消息
    task_description: str               # 当前任务描述
    progress_summary: str | None        # 中间进度摘要（可选）
```

用户发新消息进 inbox 时，worker 把这条消息 append 进 `inbox_messages`，然后继续 tool loop。模型能看到完整的执行历史 + 用户的新输入。

---

## 触发方式：模型显式升级

Worker 不是 runtime 自动猜出来的，而是模型做出显式决策后创建的。

前台 bot 调用 builtin tool：

```
create_foreground_worker(task="重构 utils.py 里的三个函数")
```

runtime 收到后：
1. 创建 worker，绑定到当前 thread
2. 把任务描述交给 worker
3. worker 开始执行，控制权转移给 worker

这样"这件事需不需要 worker"完全由模型判断，runtime 不猜。

---

## 消息路由

引入 worker 后，私聊的消息路由多一个判断：

```
私聊消息进来
    │
    ▼
SessionRuntime：当前 thread 有 active worker？
    │
    ├── 有 → run_mode = worker_inbox，消息进 worker inbox，不开新 run
    │
    └── 没有 → 正常 run 逻辑
                │
                └── 这次 run 里模型调用了 create_foreground_worker？
                        └── 是 → 创建 worker，把任务交给它
```

新增 `run_mode`：

```python
run_mode: "respond" | "record_only" | "silent_drop" | "worker_inbox"
```

`worker_inbox` 的语义：这条消息不开新 run，直接进当前 thread 的 active worker inbox。

---

## Worker 和 thread working memory 的边界

Worker 执行过程中：

- 中间状态消息（"正在分析第 2 个函数..."）发给用户，但**不进** `thread.working_messages`
- 用户通过 inbox 发来的消息**不进** `thread.working_messages`
- Worker 完成后，把最终结果写进 thread，和普通 run 一样

这样 thread 历史保持干净，只有真正的对话事实。

---

## Worker 和其他机制的关系

| 机制 | 关系 |
|---|---|
| 群聊 short run | 完全不变，worker 只在私聊 |
| approval | worker 内部不走 approval replay，命中需要审批的工具时直接通过 inbox 问用户 |
| subagent child run | worker 可以内部创建 subagent child run，child run 结果回流给 worker |
| thread working memory | worker 完成后把最终结果写进 thread |

---

## 文件结构

```
src/acabot/runtime/worker/
  __init__.py
  contracts.py        # WorkerState, WorkerExecutionContext, InboxMessage
  manager.py          # ForegroundWorkerManager
  execution.py        # worker 内部 tool loop
  builtin_tool.py     # create_foreground_worker builtin tool
```

---

## 第一版边界

- worker 只在私聊里存在
- 同一个 thread 同时只有一个 active worker
- worker 不持久化，重启后消失
- worker 内部不递归创建 worker
- 不做 worker 进度的 WebUI 展示
- session config 不支持"自动升级为 worker"，只支持模型显式触发
