## 目前记忆层级

1. message facts / event facts 就是 gateway 进来的一条消息

2. thread working memory 就是对话的上下文流

不要再把上面两个层级当做记忆 不要再把上面两个层级当做记忆 不要再把上面两个层级当做记忆 不要再把上面两个层级当做记忆
上面两个是消息事实


人格设定: 是配置文件层次的, 固定注入system prompt 

---

实际的记忆:

1. /self 是自我连续性的文件形式的记忆

2. sticky note 是长期稳定知识

3. 需要长期检索记忆, 按需检索记忆
    - 是从 message facts / event facts / 消息数据库 里提炼出来的结构化记忆


---
# 问题
## 检索记忆应该走 MemoryBroker.retrieve

- sticky note
- /self
- 长期检索记忆

## 检索记忆注入的位置

应该位于 user message 之前/之后, 不应该放在system prompt里, 避免破坏 prompt caching


## MemoryBroker 还是 plugin

做成 plugin，确实更可插拔，但 plugin 也不该直接替代 broker。如果完全没有 broker，每种记忆都各自往 pipeline 里塞注入逻辑，最后会变成多头直连，更难维护。

方向是把 broker 做薄，把后端做成可插拔。

broker 只负责几件事：接收 retrieval request、决定本轮要问哪些记忆源、收集结果、转成 `MemoryBlock`、交给 prompt assembly。

真正的 `/self`、sticky note、长期检索记忆、reference memory，都可以是独立 provider，甚至就是 plugin 提供的 backend。这样解耦才是真的解耦。

统一入口是好事，统一归属不是；

可插拔后端是好事，但最好挂在 broker 后面，而不是让每个 plugin 直接侵入 pipeline

# 原则⭐

`MemoryBroker` 应该是 **runtime 和各种记忆来源之间的唯一入口**，但它自己不是任何一种记忆的真源。

每次 run 开始前，它先看当前是谁、在哪个 thread、当前消息是什么、短期上下文压缩后剩下什么、本轮允许读哪些范围，然后决定这次该去问哪些记忆来源。

后面这些来源可以是 sticky note、`/self`、长期记忆... 真正去翻文件、查库、做检索的是这些来源模块，不是 broker。broker 要做的是把它们的结果收齐，整理成统一格式，去掉明显重复的东西，补上“这是哪来的、属于哪一类、为什么会出现在这一轮”这些信息，然后再交给 `RetrievalPlanner` 去拼给模型看的上下文。

一轮结束后，broker 还应该负责另一件事，就是把这轮对话变成一份统一的“可能要更新哪些记忆”的请求，再交给后面的写入模块。比如要不要补一条长期记忆，要不要更新某条 sticky note，要不要写进 `/self`，这些都可以从 broker 这边统一发出去。真正怎么写、写到哪里，还是各自模块自己负责。这样 broker 就能记住这轮到底读了什么、用了什么、写了什么，后面做前端展示或者排查问题时，也有一个统一出口，不会东一块西一块。

`thread working memory` 不归它管，那是 thread 和 compaction 的事情；
`event facts` 和 `message facts` 的存储不归它管，那是事实记录那条线的事情；
`/self` 的目录结构和文件编辑不归它管，那是 `/self` 自己的文件真源；
sticky note 的增删改查也不归它管，那是 sticky note 服务的事情；
怎么把记忆排进 prompt 的前后顺序，也不该归它管，那是 `RetrievalPlanner` 的事情。

把 pipeline 里那些“直接去读 sticky note”“直接去塞 soul 文本”的特殊分支，慢慢收回到 broker 后面的记忆来源模块里。这样主线会更简单：thread 负责短期上下文，`MemoryBroker` 负责去问别的记忆，`RetrievalPlanner` 负责把结果放进 prompt。我觉得这个分工是最顺的。