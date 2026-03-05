from __future__ import annotations

from typing import Any

from .base import BaseMessageStore, StoredMessage


class NullMessageStore(BaseMessageStore):
    """空实现 — 所有方法 no-op, v0.4 替换为 SQLiteMessageStore."""

    async def save(self, msg: StoredMessage) -> None:
        pass

    async def get_messages(
        self, session_key: str, limit: int = 100, since: int | None = None,
    ) -> list[StoredMessage]:
        return []

    async def query_raw(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return []
