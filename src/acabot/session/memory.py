"""InMemorySessionManager — 内存版会话管理, 重启后丢失."""

from __future__ import annotations

import logging

from .base import BaseSessionManager, Session

logger = logging.getLogger("acabot.session")


class InMemorySessionManager(BaseSessionManager):
    """内存版会话管理器.

    所有会话存在 dict 里, 重启后丢失.
    v0.4 替换为 SQLiteSessionManager 实现持久化.

    Args:
        max_messages: 每个会话最大消息条数(预留参数, 截断由 ContextCompressorHook 负责).
    """

    def __init__(self, max_messages: int = 20):
        self.max_messages = max_messages
        self._sessions: dict[str, Session] = {}

    async def get_or_create(self, session_key: str) -> Session:
        if session_key not in self._sessions:
            self._sessions[session_key] = Session(session_key=session_key)
            logger.info(f"New session: {session_key}")
        return self._sessions[session_key]

    async def get(self, session_key: str) -> Session | None:
        return self._sessions.get(session_key)

    async def save(self, session: Session) -> None:
        pass  # 内存版通过引用自动保存, 无需显式写入
