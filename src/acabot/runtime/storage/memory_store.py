"""runtime.memory_store 最小内存版 MessageStore.

让新的 runtime 组装可以先独立运行, 不立刻依赖新的 SQLite schema.
同时给长期记忆写入线提供基于 sequence 的消息增量读取.
"""

from __future__ import annotations

from ..contracts import MessageRecord, SequencedMessageRecord
from .stores import MessageStore


class InMemoryMessageStore(MessageStore):
    """内存版 MessageStore.

    Attributes:
        _messages (list[SequencedMessageRecord]): 按写入顺序保存的消息记录.
        _message_indexes_by_uid (dict[str, int]): 消息 uid 到列表下标的映射.
        _next_sequence (int): 下一条消息的 sequence 编号.
    """

    def __init__(self) -> None:
        """初始化内存版消息存储."""

        self._messages: list[SequencedMessageRecord] = []
        self._message_indexes_by_uid: dict[str, int] = {}
        self._next_sequence = 1

    async def save(self, msg: MessageRecord) -> None:
        """保存一条消息事实记录.

        Args:
            msg: 待写入的消息记录.
        """

        existing_index = self._message_indexes_by_uid.get(msg.message_uid)
        if existing_index is not None:
            existing = self._messages[existing_index].record
            if existing != msg:
                raise ValueError(f"message '{msg.message_uid}' already exists with different content")
            return

        self._messages.append(
            SequencedMessageRecord(
                sequence_id=self._next_sequence,
                record=msg,
            )
        )
        self._message_indexes_by_uid[msg.message_uid] = len(self._messages) - 1
        self._next_sequence += 1

    async def get_thread_messages(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        since: int | None = None,
    ) -> list[MessageRecord]:
        """按 thread 查询 MessageStore.

        Args:
            thread_id: 要查询的 thread 标识.
            limit: 最多返回多少条消息.
            since: 只返回晚于该时间戳的消息.

        Returns:
            满足条件的MessageStore.
        """

        messages = [item.record for item in self._messages if item.record.thread_id == thread_id]
        if since is not None:
            messages = [msg for msg in messages if msg.timestamp > since]
        if limit is not None:
            messages = messages[-limit:]
        return messages

    async def get_thread_messages_after_sequence(
        self,
        thread_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[SequencedMessageRecord]:
        """按 sequence 查询 thread 的消息增量.

        Args:
            thread_id: 要查询的 thread 标识.
            after_sequence: 只返回大于该 sequence 的消息.
            limit: 最多返回多少条消息.

        Returns:
            满足条件的带 sequence 消息列表.
        """

        messages = [item for item in self._messages if item.record.thread_id == thread_id]
        if after_sequence is not None:
            messages = [item for item in messages if item.sequence_id > after_sequence]
        if limit is not None:
            messages = messages[:limit]
        return messages
