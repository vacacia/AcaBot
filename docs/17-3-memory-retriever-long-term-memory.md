# 长期记忆检索线

这一页只讲 `long_term_memory` 的检索线怎么接进 runtime。

## 先讲结论

当前正式主线已经固定成：

- `MemoryBroker` 统一发出 `SharedMemoryRetrievalRequest`
- `CoreSimpleMemMemorySource` 自己完成 query planning、semantic / lexical / symbolic 三路召回
- `CoreSimpleMemRenderer` 把 top-k 命中记忆渲染成一个统一的 `long_term_memory` XML block
- `ContextAssembler` 把这个 block 当成普通 `MemoryBlock` 继续组装上下文

这意味着：

- 长期记忆检索不再走旧的 `StoreBackedMemoryRetriever`
- sticky notes 和长期记忆都只是普通 `MemorySource`
- `MemoryBroker` 不负责长期记忆写回, 只负责把当前 run 的检索现场交给 source

## 现在的代码落点

- `src/acabot/runtime/memory/memory_broker.py`
- `src/acabot/runtime/memory/long_term_memory/source.py`
- `src/acabot/runtime/memory/long_term_memory/ranking.py`
- `src/acabot/runtime/memory/long_term_memory/renderer.py`

## 检索线的输入和输出

输入是 `SharedMemoryRetrievalRequest`，它带上：

- 当前 `conversation_id`
- 当前 query text
- working summary
- retained history
- retrieval tags 和其他 metadata

输出是一个统一的 `MemoryBlock`：

- `source = "long_term_memory"`
- `assembly.target_slot = "message_prefix"`
- `content` 是 XML

## 为什么这样接

这样接之后，长期记忆和别的记忆层有同一个 runtime 边界：

- `MemoryBroker` 统一调度
- source 自己决定怎么查
- source 自己决定 priority 和渲染格式

所以 runtime 不需要再为长期记忆开特权分支。
