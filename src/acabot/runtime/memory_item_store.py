"""runtime.memory_item_store 提供最小内存版 MemoryStore.

组件关系:

    StructuredMemoryExtractor
        |
        v
    MemoryStore
        ^
        |
    StoreBackedMemoryRetriever

这一层只负责长期记忆项的持久化.
不负责 message facts, channel event facts, 或 thread working memory.
"""

from __future__ import annotations

from .models import MemoryItem
from .stores import MemoryStore


# region 内存版memory store
class InMemoryMemoryStore(MemoryStore):
    """内存版 MemoryStore.

    Attributes:
        _items (dict[str, MemoryItem]): 按 memory_id 保存的长期记忆项.
    """

    def __init__(self) -> None:
        """初始化 InMemoryMemoryStore."""

        self._items: dict[str, MemoryItem] = {}

    async def upsert(self, item: MemoryItem) -> None:
        """插入或更新一条长期记忆项.

        Args:
            item: 待写入的 MemoryItem.
        """

        self._items[item.memory_id] = item

    async def find(
        self,
        *,
        scope: str,
        scope_key: str,
        memory_types: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryItem]:
        """按 scope 查询长期记忆项.

        Args:
            scope: 当前查询的 scope.
            scope_key: 当前 scope 对应的 key.
            memory_types: 可选的记忆类型过滤列表.
            limit: 最多返回多少条记忆项.

        Returns:
            满足条件的 MemoryItem 列表.
        """

        # region 过滤
        items = [
            item
            for item in self._items.values()
            if item.scope == scope and item.scope_key == scope_key
        ]
        if memory_types:
            allowed = set(memory_types)
            items = [item for item in items if item.memory_type in allowed]

        items.sort(
            key=lambda item: (item.updated_at, item.created_at, item.memory_id),
            reverse=True,
        )
        if limit is not None:
            items = items[:limit]
        return list(items)
        # endregion


# endregion
