"""runtime.memory.conversation_facts 负责统一读取 thread 的增量事实窗口.

组件关系:

    ChannelEventStore + MessageStore
        |
        v
    StoreBackedConversationFactReader
        |
        v
    ConversationDelta / ConversationFact
        |
        v
    LongTermMemoryIngestor

这一层只做两件事:
- 读取指定 thread 的事实增量
- 归一化成统一的对话事实窗口
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..storage.stores import ChannelEventStore, MessageStore


# region 统一事实对象
@dataclass(slots=True)
class ConversationFact:
    """ConversationFact 表示一条统一格式的对话事实.是一条消息

    Attributes:
        thread_id (str): 所属 thread. 
        timestamp (int): 事实时间.
        source_kind (str): 来源类型.
        source_id (str): 来源主键. 
        role (str): 对话角色.
        text (str): 纯文本内容.
        payload (dict[str, Any]): 结构化内容.
        actor_id (str): 稳定身份键.
        actor_display_name (str | None): 给人和模型看的友好名字.
        channel_scope (str): 当前 channel scope.
        run_id (str | None): 关联 run.
    """

    thread_id: str
    timestamp: int
    source_kind: str
    source_id: str
    role: str
    text: str
    payload: dict[str, Any]
    actor_id: str
    actor_display_name: str | None
    channel_scope: str
    run_id: str | None


@dataclass(slots=True)
class ConversationDelta:
    """ConversationDelta 表示一个 thread 的增量事实窗口.

    Attributes:
        facts (list[ConversationFact]): 已按稳定顺序排好的事实(外部的event + bot的msg)列表.
        max_event_id (int | None): 当前窗口里看到的最大事件 sequence.
        max_message_id (int | None): 当前窗口里看到的最大消息 sequence.
    """

    facts: list[ConversationFact]
    max_event_id: int | None
    max_message_id: int | None


class ConversationFactReader(Protocol):
    """ConversationFactReader 定义统一事实窗口读取接口."""

    async def get_thread_delta(
        self,
        thread_id: str,
        after_event_id: int | None,
        after_message_id: int | None,
    ) -> ConversationDelta:
        """读取一个 thread 在双游标之后的事实增量.

        Args:
            thread_id: 目标 thread.
            after_event_id: 上一次已经处理到的事件 sequence.
            after_message_id: 上一次已经处理到的消息 sequence.

        Returns:
            对应 thread 的增量事实窗口.
        """

        ...


# endregion


# region store-backed reader
class StoreBackedConversationFactReader:
    """StoreBackedConversationFactReader 通过两个事实 store 读取增量窗口.

    Attributes:
        channel_event_store (ChannelEventStore): 事件事实存储.
        message_store (MessageStore): assistant 消息事实存储.
    """

    def __init__(
        self,
        *,
        channel_event_store: ChannelEventStore,
        message_store: MessageStore,
    ) -> None:
        """初始化 store-backed fact reader.

        Args:
            channel_event_store: 事件事实存储.
            message_store: assistant 消息事实存储.
        """

        self.channel_event_store = channel_event_store
        self.message_store = message_store

    async def get_thread_delta(
        self,
        thread_id: str,
        after_event_id: int | None,
        after_message_id: int | None,
    ) -> ConversationDelta:
        """读取一个 thread 在双游标之后的事实增量.

        Args:
            thread_id: 目标 thread.
            after_event_id: 上一次已经处理到的事件 sequence.
            after_message_id: 上一次已经处理到的消息 sequence.

        Returns:
            对应 thread 的增量事实窗口.
        """

        event_rows = await self.channel_event_store.get_thread_events_after_sequence(
            thread_id,
            after_sequence=after_event_id,
        )
        message_rows = await self.message_store.get_thread_messages_after_sequence(
            thread_id,
            after_sequence=after_message_id,
        )

        ordered_facts = [
            (item.record.timestamp, 0, item.sequence_id, self._event_to_fact(item.record))
            for item in event_rows
        ]
        ordered_facts.extend(
            (item.record.timestamp, 1, item.sequence_id, self._message_to_fact(item.record))
            for item in message_rows
        )
        ordered_facts.sort(key=lambda item: (item[0], item[1], item[2]))
        facts = [item[3] for item in ordered_facts]

        max_event_id = after_event_id
        if event_rows:
            max_event_id = event_rows[-1].sequence_id

        max_message_id = after_message_id
        if message_rows:
            max_message_id = message_rows[-1].sequence_id

        return ConversationDelta(
            facts=facts,
            max_event_id=max_event_id,
            max_message_id=max_message_id,
        )

    @staticmethod
    def _event_to_fact(record) -> ConversationFact:
        """把事件事实转换成统一格式.

        Args:
            record: 原始事件事实.

        Returns:
            统一格式的对话事实.
        """

        return ConversationFact(
            thread_id=record.thread_id,
            timestamp=record.timestamp,
            source_kind="channel_event",
            source_id=record.event_uid,
            role="user",
            text=record.content_text,
            payload=dict(record.payload_json),
            actor_id=record.actor_id,
            actor_display_name=_read_actor_display_name(record.metadata),
            channel_scope=record.channel_scope,
            run_id=record.run_id,
        )

    @staticmethod
    def _message_to_fact(record) -> ConversationFact:
        """把 assistant 消息事实转换成统一格式.

        Args:
            record: 原始消息事实.

        Returns:
            统一格式的对话事实.
        """

        return ConversationFact(
            thread_id=record.thread_id,
            timestamp=record.timestamp,
            source_kind="message",
            source_id=record.message_uid,
            role=record.role,
            text=record.content_text,
            payload=dict(record.content_json),
            actor_id=record.actor_id,
            actor_display_name=_read_actor_display_name(record.metadata),
            channel_scope=str(record.metadata.get("channel_scope", record.thread_id) or record.thread_id),
            run_id=record.run_id,
        )


# endregion


# region helpers
def _read_actor_display_name(metadata: dict[str, Any]) -> str | None:
    """从 metadata 里读取给人和模型看的名字.

    Args:
        metadata: 原始附加信息.

    Returns:
        一个可选的展示名.
    """

    value = str(metadata.get("actor_display_name", "") or "").strip()
    if not value:
        return None
    return value


# endregion


__all__ = [
    "ConversationDelta",
    "ConversationFact",
    "ConversationFactReader",
    "StoreBackedConversationFactReader",
]
