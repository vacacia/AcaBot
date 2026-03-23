# subagent

## subagent 是什么
> 把 subagent 当作一个智能的 tool, 调用 + 收集结果; 只需要输入自然语言做desc, subagent 就能完成各种任务并返回结果
> 使用 subagent 是为了节省上下文: 上下文重的任务外包给 subagent;主 agent 只需要等着 subagent 返回任务结果
> 支持并行调用 subagent 

subagent 是一个能被主 agent 委派出去独立工作的 agent

主 agent 上下文重的任务交给另一个内部 agent 跑完，再把结果拿回来。

- `delegate_subagent` 是 **调用入口**
- subagent 本身是 **执行者**

例子:
    - 文件的处理, 整理和分析, 检索..
    - 难的逻辑推理/数学题, 让使用更聪明模型的 subagent 解答, 只需要等待结果


## 当前实现

前台现在暴露给模型的 subagent 入口是`delegate_subagent`

它来自 `src/acabot/runtime/builtin_tools/subagents.py`
- subagent 的前台入口是 **builtin tool**
- `delegate_subagent` 只是入口，真正的委派编排和 child run 执行在 subagent 子域里


当前主线代码在：
- `src/acabot/runtime/subagents/contracts.py`
- `src/acabot/runtime/subagents/broker.py`
- `src/acabot/runtime/subagents/execution.py`
- `src/acabot/runtime/builtin_tools/subagents.py`




## 当前 subagent 是怎么跑起来的

当前委派链路是：

1. 模型调用 `delegate_subagent`
2. builtin tool 把请求交给 `SubagentDelegationBroker`
3. broker 按 `delegate_agent_id` 找 executor
4. 当前默认本地实现是 `LocalSubagentExecutionService`
5. 它会伪造一条内部事件，创建 child run
6. 再复用 runtime 自己的 `ThreadPipeline.execute(...)`
7. 但 `deliver_actions=False`，不会把 child run 的动作直接发到外部平台
8. 最后只把结果总结返回给父 run


## subagent 边界

### subagent child run 有自己的 computer 决策

当前 child run 会显式拿到 subagent 用的 computer 决策。
    - `workspace` 可见
    - `skills` 可见
    - `self` 不可见

### subagent 不走完整的 session-config 主线

当前子任务会共享 Work World 契约，但不会重新走完整的前台：
    - session-config
    - surface
    - context

它不是第二个完整前台用户会话


### 不要把 `delegate_subagent` 当成一个普通函数型 tool

`delegate_subagent` 只是前台入口。

真正发生的事情不是“跑一个小函数”，而是：
    - 做一次委派编排
    - 创建 child run
    - 复用 runtime 执行链路
    - 回收结果给父 run
