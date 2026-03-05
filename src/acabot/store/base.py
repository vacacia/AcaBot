from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoredMessage:
    """一条持久化的聊天消息. 结构化存储, 不依赖裸 dict."""

    session_key: str  # "qq:group:444" 或 "qq:user:222"
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str  # 消息文本
    timestamp: int = 0  # Unix 秒级时间戳
    sender_id: str = ""  # 发送者 ID(群聊区分用户)
    sender_name: str = ""  # 发送者昵称
    message_id: str = ""  # 平台消息 ID(撤回/回复引用)
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展字段

    def to_llm_message(self) -> dict[str, str]:
        """裁剪成 LLM 上下文格式
        - 只需要 {"role": ..., "content": ...}
        - 不需要 session_key, timestamp ...
        """
        return {"role": self.role, "content": self.content}


class BaseMessageStore(ABC):
    """消息存储接口.

    v0.3 NullMessageStore 空实现, v0.4 替换为 SQLiteMessageStore.
    """

    @abstractmethod
    async def save(self, msg: StoredMessage) -> None: ...

    @abstractmethod
    async def get_messages(
        self,
        session_key: str,
        limit: int = 100,
        since: int | None = None,
    ) -> list[StoredMessage]: ...

    async def query(
        self,
        session_key: str,
        *,
        limit: int = 50,
        before: int | None = None,
        after: int | None = None,
        sender: str | None = None,
        keyword: str | None = None,
    ) -> list[StoredMessage]:
        """丰富查询接口. v0.4 SQLiteMessageStore 再补."""
        raise NotImplementedError

    async def count(self, session_key: str, *, after: int | None = None) -> int:
        """统计指定会话的消息数量.

        场景: 
            - 上下文压缩判断
            - 频次限制

        Args:
            session_key: 会话标识, 如 "qq:group:456".
            after: Unix 时间戳(秒). 只统计此时间之后的消息.
                None 则统计全部.

        Returns:
            消息条数(int).
        """
        raise NotImplementedError

    @abstractmethod
    async def query_raw(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """通用只读查询.
        
        封装成 tool 给 agent 用
        实现层只允许 SELECT.
        """
        ...
