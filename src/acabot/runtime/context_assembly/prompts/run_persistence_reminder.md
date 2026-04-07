<system-reminder name="run_persistence">

## Run Persistence Reminder

你现在处在一次独立的 **run** 里。

- 每次 run 都是一次新的执行, 会从 "公共上下文" 里取到一份 snapshot, 包含: system prompt + tool definitions + messages
- run 结束后, 只会把用户的消息 + 你这次run的每个消息(直接发送出去的或者message工具发送出去的)加入到"公共上下文"; 你这次 run 内部临时的思路、草稿和工具调用结果都不会保留下来
- 只有被明确写入外部状态的信息, 你的最终回应后续 run 才更可能继续利用
- 如果探索、排查、实现进行了多步推进，请把关键进展写进可持续读取的位置，例如 `/workspace` 下的文件、可复用的产物，或其他持久化机制
- 如果任务会跨多个 run 延续，优先保持「文件中的事实」比「脑中的记忆」更完整

</system-reminder>
