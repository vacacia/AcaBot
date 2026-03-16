"""runtime.memory_store 最小内存版 MessageStore.

让新的 runtime 组装可以先独立运行, 不立刻依赖新的 SQLite schema.
"""

from __future__ import annotations

from ..contracts import MessageRecord
from .stores import MessageStore


class InMemoryMessageStore(MessageStore):
    """内存版 MessageStore.

    按 thread_id 保存 Message.
    """

    def __init__(self) -> None:
        self._messages: list[MessageRecord] = []

    async def save(self, msg: MessageRecord) -> None:
        self._messages.append(msg)

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

        messages = [msg for msg in self._messages if msg.thread_id == thread_id]
        if since is not None:
            messages = [msg for msg in messages if msg.timestamp > since]
        if limit is not None:
            messages = messages[-limit:]
        return messages
