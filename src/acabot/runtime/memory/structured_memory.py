"""runtime.structured_memory 提供最小 structured memory 实现.

组件关系:

    MemoryBroker
      |
      `--> StoreBackedMemoryRetriever
              |
              v
          MemoryStore

这一层先实现最小闭环:
- retrieval 从 MemoryStore 读取长期记忆项

这一版故意不做:
- sticky note 自动提取
- episodic 自动提取 / write-back
- reference 文档切片
- task scratchpad
- 向量检索
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory_broker import (
    MemoryAssemblySpec,
    MemoryBlock,
    SharedMemoryRetrievalRequest,
)
from ..contracts import MemoryItem
from ..storage.stores import MemoryStore

_KNOWN_MEMORY_SCOPES = ("relationship", "user", "channel", "global")


# region retrieval
@dataclass(slots=True)
class StoreBackedMemoryRetriever:
    """基于 MemoryStore 的 retriever.

    Attributes:
        store (MemoryStore): 长期记忆项持久化后端.
        per_scope_limit (int): 每个 scope 最多取回多少条记忆项.
    """

    store: MemoryStore
    per_scope_limit: int = 3

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        """从 MemoryStore 检索长期记忆并转换成 MemoryBlock.

        Args:
            request: 标准化后的 retrieval request.

        Returns:
            一组可注入给 runtime 的 MemoryBlock.
        """

        blocks: list[MemoryBlock] = []

        requested_tags = set(request.requested_tags)
        sticky_note_scopes = (
            set(str(scope) for scope in list(request.metadata.get("sticky_note_scopes", [])))
            if "sticky_note_scopes" in request.metadata
            else None
        )
        for scope in _KNOWN_MEMORY_SCOPES:
            scope_key = _scope_key_for_request(scope=scope, request=request)
            items = await self.store.find(
                scope=scope,
                scope_key=scope_key,
                limit=self.per_scope_limit,
            )
            for item in items:
                if requested_tags and not requested_tags.intersection(item.tags):
                    continue
                if (
                    item.memory_type == "sticky_note"
                    and sticky_note_scopes is not None
                    and item.scope not in sticky_note_scopes
                ):
                    continue
                blocks.append(self._to_block(item))

        return blocks

    @staticmethod
    def _to_block(item: MemoryItem) -> MemoryBlock:
        """把 MemoryItem 转成可注入的 MemoryBlock.

        Args:
            item: 待转换的长期记忆项.

        Returns:
            对应的 MemoryBlock.
        """

        source = "sticky_notes" if item.memory_type == "sticky_note" else "store_memory"
        priority = 800 if item.memory_type == "sticky_note" else 700
        return MemoryBlock(
            content=item.content,
            source=source,
            scope=item.scope,
            source_ids=[item.memory_id],
            assembly=MemoryAssemblySpec(
                target_slot="message_prefix",
                priority=priority,
            ),
            metadata={
                "memory_type": item.memory_type,
                "edit_mode": item.edit_mode,
                "tags": list(item.tags),
                **item.metadata,
            },
        )


# endregion

# region 共享helper
def _scope_key_for_request(
    *,
    scope: str,
    request: SharedMemoryRetrievalRequest,
) -> str:
    """根据 request 计算某个 scope 的 key.

    Args:
        scope: 目标 scope 名称.
        request: retrieval request.

    Returns:
        对应 scope 的 key.
    """

    if scope == "relationship":
        return f"{request.actor_id}|{request.channel_scope}"
    if scope == "user":
        return request.actor_id
    if scope == "channel":
        return request.channel_scope
    if scope == "global":
        return "global"
    return request.channel_scope


# endregion
