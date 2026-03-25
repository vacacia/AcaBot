"""runtime.event_store 提供最小内存版 ChannelEventStore.

组件关系:

    RuntimeApp
        |
        v
    ChannelEventStore
        |
        v
    InMemoryChannelEventStore

用于在不依赖 SQLite 的情况下, 先跑通 inbound event log 主线,
同时给长期记忆写入线提供基于 sequence 的 thread 增量读取.
"""

from __future__ import annotations

from ..contracts import ChannelEventRecord, SequencedChannelEventRecord
from .stores import ChannelEventStore


# region event存储
class InMemoryChannelEventStore(ChannelEventStore):
    """内存版 ChannelEventStore.

    Attributes:
        _events (list[SequencedChannelEventRecord]): 按写入顺序保存的事件记录.
        _event_indexes_by_uid (dict[str, int]): 事件 uid 到列表下标的映射.
        _next_sequence (int): 下一条事件的 sequence 编号.
    """

    def __init__(self) -> None:
        """初始化 InMemoryChannelEventStore."""

        self._events: list[SequencedChannelEventRecord] = []
        self._event_indexes_by_uid: dict[str, int] = {}
        self._next_sequence = 1

    async def save(self, event: ChannelEventRecord) -> None:
        """保存一条 channel event 记录.

        Args:
            event: 待写入的 ChannelEventRecord.
        """

        existing_index = self._event_indexes_by_uid.get(event.event_uid)
        if existing_index is not None:
            existing = self._events[existing_index].record
            if existing != event:
                raise ValueError(f"channel event '{event.event_uid}' already exists with different content")
            return

        self._events.append(
            SequencedChannelEventRecord(
                sequence_id=self._next_sequence,
                record=event,
            )
        )
        self._event_indexes_by_uid[event.event_uid] = len(self._events) - 1
        self._next_sequence += 1

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

        events = [item.record for item in self._events if item.record.thread_id == thread_id]
        if since is not None:
            events = [event for event in events if event.timestamp > since]
        if event_types is not None:
            wanted = set(event_types)
            events = [event for event in events if event.event_type in wanted]
        if limit is not None:
            events = events[-limit:]
        return events

    async def get_thread_events_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
        event_types: list[str] | None = None,
    ) -> list[SequencedChannelEventRecord]:
        """按 sequence 查询 thread 的事件增量.

        Args:
            thread_id: 要查询的 thread 标识.
            after_sequence: 只返回大于该 sequence 的事件.
            limit: 最多返回多少条事件.
            event_types: 可选事件类型过滤列表.

        Returns:
            满足条件的带 sequence 事件列表.
        """

        events = [item for item in self._events if item.record.thread_id == thread_id]
        if after_sequence is not None:
            events = [item for item in events if item.sequence_id > after_sequence]
        if event_types is not None:
            wanted = set(event_types)
            events = [item for item in events if item.record.event_type in wanted]
        if limit is not None:
            events = events[:limit]
        return events


# endregion
