参考 simplemem 的实现
- ref/SimpleMem


## 问题

多读单写 架构，拦截了多插拔记忆能力的写回可能性

Write-back 必须是“Fire-and-Forget”（发射即不管）, 否则会直接阻塞这个会话

Sticky Notes 不应该拥有主线的特权判断。它应该作为一个独立的 MemorySource 实例被注册进 MemorySourceRegistry。优先级（Priority = 800）和自己的查询边界，应该在其自身实例的 __call__ 里决定，而不是侵入到 StoreBackedMemoryRetriever 的核心循环中替它判断

在 MemoryBrokerResult 进入 ContextAssembler 之前，必须有一个基于全局 Token 限额（Token Budget）的“截断器（Truncator）”。它基于全体 MemoryBlock 的 assembly.priority 进行倒序裁切，超出 Budget 的低优先级块应该直接丢弃，代码层面目前没有看到任何控制水位的设计。


## 分析

session 不应该管长期记忆要不要提取.这个和session runtime没有关系, 全部信息都会被长期记忆的组件自己提取，长期记忆自己决定留下哪些(会经过各种处理),然后在有新消息到来的时候，memory broker发出检索，长期记忆再根据这个到来的消息把检索到的内容返回给memory broker

Memory broker也不负责写长期记忆，因为每一层记忆都是自己决定要不要做，memory broker 他只管提取，他不能判断要不要写长期记忆呢, 他不能判断要写哪个长期记忆, 他没有判断的能力
- 比如 self 和 sticky notes，这是模型自己判断要不要往里写的记忆
- 比如长期记忆，它要所有的消息，长期记忆组件是自己整合入库

