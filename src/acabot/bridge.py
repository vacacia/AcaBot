"""SessionBridge — 会话桥接器, session + store 的统一写入入口.

- 发送成功才记录
- session_content 参数: LLM 上下文里是原始的回复; 存储的是实际发送的消息(分段/hook..)
- HookPoint.ON_RECEIVE 之后, 如果非 abort, 输入消息都会被记录
- 所有消息(用户/assistant/plugin)的持久化都应该通过 sender, 给 LLM 提供完整上下文

"""

from __future__ import annotations

import logging
import time
from typing import Any

from .gateway.base import BaseGateway
from .session.base import Session
from .store.base import BaseMessageStore, StoredMessage
from .types import Action, ActionType, StandardEvent

logger = logging.getLogger("acabot.bridge")


class SessionBridge:
    """桥接 gateway(网络层) 和 session/store(数据层).

    绑定一次会话, 统一管理消息的流入(record_incoming)和流出(send)及持久化.

    Args:
        session: 当前会话(引用, 直接追加 messages).
        store: 消息持久化存储.
        session_key: 会话标识, store.save 时需要.
    """

    def __init__(
        self,
        gateway: BaseGateway,
        session: Session,
        store: BaseMessageStore,
        session_key: str,
    ) -> None:
        self.gateway = gateway
        self.session = session
        self.store = store
        self.session_key = session_key

    # region 输入侧
    async def record_incoming(self, event: StandardEvent) -> None:
        """记录用户消息到 session + store.
        
        Args:
            event: Gateway 翻译后的标准事件.
        """
        user_msg = {"role": "user", "content": event.text}
        async with self.session.lock:
            self.session.messages.append(user_msg)

        try:
            await self.store.save(
                StoredMessage(
                    session_key=self.session_key,
                    role="user",
                    content=event.text,
                    timestamp=event.timestamp,
                    sender_id=event.source.user_id,
                    sender_name=event.sender_nickname,
                    message_id=event.raw_message_id,
                )
            )
        except Exception:
            logger.exception(
                "Failed to persist user message, session=%s",
                self.session_key,
            )

    # endregion

    # region 输出侧
    async def send(
        self,
        action: Action,
        *,
        session_content: str | None = None,
    ) -> dict[str, Any] | None:
        """发送一个 Action, 成功后自动记录到 session + store.

        Args:
            action: 要发送的动作(SEND_TEXT, SEND_SEGMENTS 等).
            session_content: 写入 session 的内容, 与 store 不同时使用.
                Pipeline LLM 路径传 response.text(session 存原始回复),
                其余场景不传(session 和 store 存相同内容).

        Returns:
            gateway 返回的结果(含 message_id 等), 失败返回 None.
        """
        result = await self.gateway.send(action)
        if result is None:
            logger.warning(
                "Send failed (no ack), session=%s action=%s — not recording",
                self.session_key,
                action.action_type,
            )
            return None

        # 只记录"产生消息"的动作, 不记录 typing/reaction 等
        if action.action_type in (ActionType.SEND_TEXT, ActionType.SEND_SEGMENTS):
            await self._record(action, result, session_content=session_content)

        return result

    async def _record(
        self,
        action: Action,
        result: dict[str, Any],
        *,
        session_content: str | None = None,
    ) -> None:
        """发送成功后记录到 session + store.

        Args:
            action: 已成功发送的动作.
            result: gateway 返回的结果(含 message_id).
            session_content: 写入 session 的内容. None 则与 store 相同.
        """
        store_content = _extract_content(action)
        message_id = str(result.get("message_id", ""))

        # session 存 session_content(LLM 原始回复) 或 store_content(实际发送)
        async with self.session.lock:
            self.session.messages.append(
                {"role": "assistant", "content": session_content or store_content},
            )

        # store 始终存实际发送内容, 写入失败不影响主流程
        try:
            await self.store.save(
                StoredMessage(
                    session_key=self.session_key,
                    role="assistant",
                    content=store_content,
                    timestamp=int(time.time()),
                    message_id=message_id,
                )
            )
        except Exception:
            logger.exception(
                "Failed to persist sent message, session=%s",
                self.session_key,
            )

    # endregion


def _extract_content(action: Action) -> str:
    """从 Action 提取文本内容, 用于 store 记录.

    Args:
        action: 已发送的动作.

    Returns:
        消息文本. 非文本段用占位符表示.
    """
    if action.action_type == ActionType.SEND_TEXT:
        return action.payload.get("text", "")

    if action.action_type == ActionType.SEND_SEGMENTS:
        parts: list[str] = []
        for seg in action.payload.get("segments", []):
            seg_type = seg.get("type", "")
            seg_data = seg.get("data", {})
            if seg_type == "text":
                parts.append(seg_data.get("text", ""))
            elif seg_type == "image":
                parts.append("[图片]")
            else:
                parts.append(f"[{seg_type}]")
        return "".join(parts)

    return ""
