# run 机制

**runtime 里的 `run` 到底是什么, 一条事件和一个 `run` 是什么关系, `run` 内部会经历什么, 哪些内容会进公共上下文, 哪些不会?**


当前主线里，**正式语义是一条入站 `event` 对应一次 `run`；在最常见的前台路径里，普通 message event 基本就是一条消息一个 `run`**。但一个 `run` 不等于“一次模型请求”。一个 `run` 里面可能有: 
- 多轮 LLM 请求
- 多次 tool call
- approval 中断
- approval 通过后的续执行


真正稳定的边界是: 
- `event`
  - 外部平台送进来的一条真实事件
- `message`
  - `event` 里最常见的前台消息子类
- `thread`
  - 一条对话线共享的上下文容器
- `run`
  - runtime 为处理一次事件而创建的执行实例

不要把 `run` 理解成“最后发给模型的那一次 completion 请求”。

---

## `event` / `message` / `thread` / `run` 分别是什么

## 1. `event`

`event` 是外部世界真实发生的一条事件。

它先经过 gateway 协议翻译，变成 `StandardEvent`，再进入 runtime 主线。

例子: 

- QQ 群里用户发了一句“帮我看一下这个仓库”
- 用户回复了一条旧消息
- 用户发来一张图片

这些都还是事件事实，不是 `run`。

## 2. `message`

`message` 不是比 `event` 更正式的词，它是 `event` 里最常见的那一类。

也就是说: 

- 所有前台聊天消息都是 `event`
- 但不是所有 `event` 都一定是 message

平时口语里经常说“每条消息一个 run”，本质上是在说“每个普通 message event 一个 run”。

## 3. `thread`

`thread` 是一条对话线共享的上下文容器。

它现在主要保存这些运行时状态: 

- `working_messages`
- `working_summary`
- `last_event_at`
- 一把 thread 级 lock

它表达的是: 

> **这条对话线到现在为止，公共上下文是什么。**

当前代码在: 

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/threads.py`

## 4. `run`

`run` 是 runtime 为处理某次事件创建的一次正式执行。

它有自己的: 

- `run_id`
- `thread_id`
- `actor_id`
- `agent_id`
- 生命周期状态
- 错误信息
- approval 上下文

它表达的是: 

> **系统这一次为了处理某条事件，实际跑了什么执行流程。**

当前代码在: 

- `src/acabot/runtime/contracts/records.py`
- `src/acabot/runtime/storage/runs.py`

---

## 一条 `event` 和一个 `run` 的关系

当前主线大致是: 

1. Gateway 收到平台事件
2. 翻译成 `StandardEvent`
3. `RuntimeApp.handle_event()` 接住这条事件
4. `RuntimeRouter` / `SessionRuntime` 算出这次事件落到哪个 `thread`
5. `RuntimeApp` 创建或获取这个 `thread`
6. `RuntimeApp` 为这次事件 `open()` 一个新的 `run`
7. 构造 `RunContext`
8. 交给 `ThreadPipeline.execute()`

也就是说，**正式语义是一条事件对应一个新的 `run`**。

但在最常见的前台对话路径里，这条事件通常刚好就是一条 message event，所以平时才会顺手说成“每条消息一个 run”。

当前接线点在: 

- `src/acabot/runtime/app.py`
- `src/acabot/runtime/pipeline.py`

### 当前的例外

不是所有事件都会变成正常前台 `run`。

#### 1. `silent_drop`

这类事件会直接结束，不创建正常执行主线。

#### 2. `record_only`

这类事件会创建 `run`，但不会进入模型调用。

它只负责: 

- 把用户消息写进 thread
- 保存 thread
- 收尾 run

#### 3. approval resume

approval 通过后的恢复，不是“新消息再开一个 run”。

它是拿原来的 `run` 继续做后半段执行。

#### 4. subagent child run

`delegate_subagent` 不会把父 `run` 继续硬塞进子任务里。

它会创建一个新的 child run。

所以: 

- 普通消息 -> 新 run
- approval resume -> 复用原 run
- subagent delegation -> 新 child run

---

## 一个 `run` 里面到底会发生什么

当前 `ThreadPipeline.execute()` 这条线大致是: 

1. `mark_running`
2. `computer_runtime.prepare_run_context(ctx)`
3. `message_preparation_service.prepare(ctx)`
4. 把当前用户消息 append 到 thread
5. 做 context compaction
6. 准备 retrieval plan
7. 注入 memory blocks
8. 调 `agent_runtime.execute(ctx)`
9. 把动作交给 `Outbox`
10. 根据送达结果更新 thread
11. 收尾 run

所以一个 `run` 不是“调一下模型就完”。

它是一整条 runtime 执行链。

---

## 一个 `run` 不等于一次模型请求

这点最容易看错。

当前 `ModelAgentRuntime.execute(ctx)` 最终会调用 `BaseAgent.run(...)`。

而 `BaseAgent.run(...)` 内部本身就可能进入 tool loop, 所以: 
- 一个 `run` 里可能有多轮 LLM 请求
- 一个 `run` 里可能有多次 tool call
- 它们全部仍然属于同一个 `run`


## 当前 `run` 私有的东西有哪些

当前 `run` 里有一批东西是**只属于这次执行**的，不会直接变成公共聊天历史。

比如: 

- 这次模型调用用的 `system_prompt`
- 这次组装出来的 `messages`
- 这次 tool loop 的中间消息
- 这次 tool call 的返回结果
- 这次 tool audit
- 这次 run 的 artifacts
- 这次 run 的 pending approval
- ...

它们的语义是: 

> **这次执行过程里模型和 runtime 自己看到了什么。**

不是: 

> **这条对话线上每个人以后都应该一直看到什么。**

---

## 哪些东西会进公共 `thread` 上下文

当前真正会回写到共享 `thread.working_messages` 的，主要是两类可见消息: 

### 1. 用户消息

用户输入会先 append 进当前 thread。

### 2. assistant 可见回复

只有真正成功送达出去的 assistant 可见内容，才会把 `thread_content` 回写到 thread。

所以公共 `thread` 历史的核心语义是: **这条对话线上真实发生过、用户和 bot 真正看得到的消息流。**


## `Skill` 和 `subagent` 会不会出现在上下文里

## 1. 会出现在当前 run 的模型上下文里

### `Skill`

当前 run ，`ContextAssembler` 就把可见 skills 摘要放进 system prompt。

如果模型真的调用了 `Skill(skill=...)`: 

- tool 会把 `SKILL.md` 原文和 `/skills/...` 基目录作为 tool result 返回给当前 run
- 这份结果会进入当前 run 私有的 tool loop 消息里

#### `mark_skill_loaded` 

它记录的是: **当前这个 thread 已经显式 load 过哪些 skill。**

所以它属于: thread 级 workspace/world 状态

不属于: 公共聊天消息历史

它表达的是“这个 thread 的工作环境记住了这件事”，不是“聊天记录里多了一条消息”。



### `delegate_subagent`

当前 run 一开始，`ContextAssembler` 也把可见 subagent 摘要放进 system prompt。

如果模型真的调用了 `delegate_subagent`: 

- tool 会创建 child run
- 子任务跑完后，把总结结果返回给父 run
- 这份总结会进入父 run 私有的 tool loop 消息里

所以它们当然会进入**当前 run 的模型上下文**。

## 2. 默认不会直接进入公共 thread 历史

`Skill` 和 `delegate_subagent` 的 tool result 默认不会自动变成共享消息历史。

它们只有在最后被模型整理成用户可见回复并成功发出去时，才会以**最终回复文本**的形式进入公共 thread。


## 同一个 `thread` 上多个 `run` 可以并行

当前实现里，同一个 thread 上多个 run 是允许并行的。

这不是 bug，而是当前主线明确接受的语义: 

- run A 先 append 了用户消息 A
- run B 紧接着 append 了用户消息 B
- run A 做 snapshot 时可能已经看见消息 B

这表示的是: **当前 run 看到的是这条对话线上已经真实发生过的新消息。**

不是: **别的 run 的内部 tool result 被串进来了。**

### 1. 允许发生的

同一 thread 上，新的用户消息进入共享 thread，被别的并发 run 看见。

这是当前设计接受的行为。

### 2. 不应该发生的

run A 的私有 tool loop 中间态、tool audit、内部 tool result 直接跑到 run B 的私有上下文里。

当前实现不是这么做的。


## approval resume 为什么还是同一个 `run`

approval 打断时，当前 run 会进入 `waiting_approval`。

approval 通过后，系统不是重新把这件事当作一条新消息处理，而是: 

- 读取原 run 的审批上下文
- 恢复工具执行现场
- replay 之前等待批准的那次 tool
- 继续把这次 run 收尾

所以 approval resume 的语义是:  **原 run 的后半段。**

不是: **另起一个全新的普通消息 run。**

---

## subagent child run 为什么是新的 `run`

subagent 跟 approval resume 正好相反。

`delegate_subagent` 的语义不是“父 run 的后半段换个函数接着跑”，而是: 

- 父 run 发起一次委派
- runtime 创建一个新的 child run
- child run 在自己的上下文里执行
- child run 不直接对外发送前台消息
- 最后把总结结果回收给父 run

所以 child run 是一个独立的 `run`，只是它的产物会回流到父 run。

