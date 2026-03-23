## 目前记忆层级

message facts / event facts 就是 gateway 进来的一条消息

thread working memory 就是对话的上下文流

人格设定是配置文件层次的, 固定注入system prompt 

/self 是自我连续性的文件形式的记忆

sticky note 是长期稳定知识

需要长期检索记忆, 按需检索记忆
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