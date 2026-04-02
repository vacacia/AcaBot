# Run 机制

## 核心概念

| 概念 | 定义 |
|------|------|
| **event** | 外部平台送进来的一条真实事件，经 gateway 翻译成 `StandardEvent` |
| **message** | event 里最常见的前台消息子类，口语"每条消息一个 run"实际是"每个 message event 一个 run" |
| **thread** | 一条对话线共享的上下文容器，保存 `working_messages`、`working_summary`、`last_event_at` 和 thread 级 lock |
| **run** | runtime 为处理一次事件创建的执行实例，有自己的 run_id、生命周期状态、approval 上下文 |

**run 不等于一次模型请求。** 一个 run 里可能有多轮 LLM 请求、多次 tool call、approval 中断和续执行，它们全属于同一个 run。

## Event → Run 的关系

正式语义：一条入站 event 对应一个新 run。流程：Gateway 收到平台事件 → `StandardEvent` → `RuntimeApp.handle_event()` → RuntimeRouter/SessionRuntime 算出落到哪个 thread → 创建/获取 thread → open 新 run → 构造 RunContext → `ThreadPipeline.execute()`。

### 例外

| 场景 | 行为 |
|------|------|
| `silent_drop` | 直接结束，不创建 run |
| `record_only` | 创建 run，但只写入 thread + 收尾，不调模型 |
| approval resume | 不是新 run，复用原 run 继续执行后半段 |
| subagent delegation | 创建新的 child run（独立执行，产物回流给父 run） |

## Run 内部执行链

`ThreadPipeline.execute()` 的完整顺序：mark_running → computer prepare → message preparation → append 用户消息到 thread → context compaction → retrieval plan → memory injection → agent execute → outbox → 更新 thread → 收尾 run。

## Run 私有 vs 公共 Thread

### Run 私有（不进公共历史）

当前 run 的 system_prompt、组装出的 messages、tool loop 中间消息、tool call 返回结果、tool audit、artifacts、pending approval。这些是"这次执行过程里模型和 runtime 看到了什么"。

### 进入公共 Thread 的

只有两类：
1. **用户消息**：append 进 thread
2. **assistant 可见回复**：真正成功送达的 assistant 内容，以 `thread_content` 回写到 thread

公共 thread 历史的核心语义：**这条对话线上真实发生过、用户和 bot 真正看得到的消息流。**

### Skill 和 Subagent 在上下文中的表现

`Skill` 的 SKILL.md 内容和 `delegate_subagent` 的总结结果会进入当前 run 的 tool loop 消息（即模型能看到），但默认不进公共 thread 历史。只有模型把它们整理成最终回复并成功发出时，才以回复文本形式进入公共 thread。

`mark_skill_loaded` 记录的是 thread 级 workspace/world 状态（"这个 thread 已经 load 过哪些 skill"），不是聊天消息历史。

## 并行 Run

同一个 thread 上多个 run 允许并行——这是当前主线明确接受的语义。run A 先 append 用户消息 A，run B 紧接着 append 用户消息 B，run A 做 snapshot 时可能已经看见消息 B。这表示"当前 run 看到的是对话线上已经真实发生过的新消息"，不是"别的 run 的内部 tool result 被串进来了"。

**允许发生**：新用户消息进入共享 thread 被并发 run 看见。
**不应该发生**：run A 的私有 tool loop 中间态、tool audit 跑到 run B 的私有上下文里。

## Approval Resume

Approval 打断时 run 进入 `waiting_approval`。通过后不是重新当作新消息处理，而是：读取原 run 审批上下文 → 恢复工具执行现场 → replay 等待批准的 tool → 继续收尾。语义是**原 run 的后半段**。

## Subagent Child Run

与 approval resume 相反。`delegate_subagent` 的语义不是"父 run 换个函数接着跑"，而是：父 run 发起委派 → runtime 创建新 child run → child run 在自己的上下文里执行（`deliver_actions=False`，不对外发消息）→ 总结结果回收给父 run。

## 为什么不做 Generic Continuation

当前主线不承载 generic continuation（一次 run 的私有执行过程延续到后续消息）。这里说的不是 approval 这种已正式定义的中断恢复，而是"工具做到一半 → 先发中间状态 → 用户下一条消息来了接着跑"这种。

### 立不住的原因

**run 私有态没有 replay 契约**：tool loop 中间态、工具原始返回、临时变量都是执行现场，不是"下一条消息还能复用的正式对象"。直接当 continuation 接下去，run 不再只是一次执行、thread 不再只是公共消息、工具过程变成半公开半私有的混合状态，恢复/取消/审计/并发全部变脏。

**工具缺字段不等于该挂起等用户**：工具校验只说明缺了什么参数，说明不了模型是不是该从上下文补、该追问用户、还是该换方案。Continuation 不是工具层自动推出来的，而是 agent 显式决策后 runtime 物化成正式状态。

**群聊不适合**：群聊天然多 actor、多消息并发、乱序插话。更稳的边界是 event → short run，新消息就是新 run，共享的只有公共 thread 历史。

**私聊方向不同**：私聊如果要支持连续前台体验（边做工具调用边发状态、用户中途回一句能接上），更合理的方向是 foreground worker，而不是把 continuation 塞回 run。详见 `docs/26-foreground-worker.md`。

## 关键代码

| 文件 | 职责 |
|------|------|
| `runtime/contracts/records.py` | RunRecord、ThreadState 定义 |
| `runtime/storage/threads.py` | thread 存储 |
| `runtime/storage/runs.py` | run 存储 |
| `runtime/app.py` | event → run 创建 |
| `runtime/pipeline.py` | run 执行主线 |
