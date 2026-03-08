from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    """单个会话的状态容器.

    Attributes:
        session_key: 会话标识, 如 "qq:group:456" 或 "qq:user:123"
        messages: 当前上下文消息列表(OpenAI messages 格式)
        metadata: 扩展数据, hook 间传数据等
        lock: 并发写保护 — Pipeline 和后台任务可能同时写 messages.
    """
    session_key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class BaseSessionManager(ABC):
    """会话管理接口. 内存版 v0.2 实现, 持久化版 v0.4 替换."""

    @abstractmethod
    async def get_or_create(self, session_key: str) -> Session:
        """按 session_key 获取会话, 不存在则自动创建空会话.

        主流程用 — 收到消息时调用, 保证永远拿到可用的 Session.
        需要加一个参数选择拉取出多少条消息填充 session 吗?
        
        Args:
            session_key: 会话标识, 如 "qq:group:456".

        Returns:
            已有的或新创建的 Session, 永远不返回 None.
        """
        ...

    @abstractmethod
    async def get(self, session_key: str) -> Session | None:
        """按 key 查询会话, 不存在返回 None.

        辅助查询用 — 如定时任务检查会话是否存在、过期清理等.

        Args:
            session_key: 会话标识.

        Returns:
            存在则返回 Session, 不存在返回 None.
        """
        ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...
