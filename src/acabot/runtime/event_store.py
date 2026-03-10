"""runtime.event_store 提供最小内存版 ChannelEventStore.

组件关系:

    RuntimeApp
        |
        v
    ChannelEventStore
        |
        v
    InMemoryChannelEventStore

用于在不依赖 SQLite 的情况下, 先跑通 inbound event log 主线.
"""

from __future__ import annotations

from .models import ChannelEventRecord
from .stores import ChannelEventStore


# region event存储
class InMemoryChannelEventStore(ChannelEventStore):
    """内存版 ChannelEventStore.

    Attributes:
        _events (list[ChannelEventRecord]): 按写入顺序保存的 event 记录.
    """

    def __init__(self) -> None:
        """初始化 InMemoryChannelEventStore."""

        self._events: list[ChannelEventRecord] = []

    async def save(self, event: ChannelEventRecord) -> None:
        """保存一条 channel event 记录.

        Args:
            event: 待写入的 ChannelEventRecord.
        """

        self._events.append(event)

    async def get_thread_events(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[ChannelEventRecord]:
        """按 thread 查询 channel event 记录.

        Args:
            thread_id: 要查询的 thread 标识.
            limit: 最多返回多少条事件.
            since: 只返回晚于该时间戳的事件.
            event_types: 可选事件类型过滤列表.

        Returns:
            满足条件的 ChannelEventRecord 列表.
        """

        events = [event for event in self._events if event.thread_id == thread_id]
        if since is not None:
            events = [event for event in events if event.timestamp > since]
        if event_types is not None:
            wanted = set(event_types)
            events = [event for event in events if event.event_type in wanted]
        if limit is not None:
            events = events[-limit:]
        return events


# endregion
