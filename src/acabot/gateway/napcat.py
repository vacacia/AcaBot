"""NapCat Gateway — OneBot v11 反向 WebSocket 实现."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Awaitable

try:
    import websockets
    from websockets.asyncio.server import ServerConnection, serve
except ImportError:
    websockets = None
    ServerConnection = Any
    serve = None

from .base import BaseGateway
from acabot.types import (
    StandardEvent,
    EventSource,
    MsgSegment,
    EventAttachment,
    ReplyReference,
    Action,
    ActionType,
)

logger = logging.getLogger("acabot.gateway")


class NapCatGateway(BaseGateway):
    """NapCat (OneBot v11 反向 WS) 网关实现.

    作为 WebSocket 服务端, 等待 NapCat 主动连接.
    负责两个方向的翻译:
        收消息: OneBot v11 JSON → StandardEvent (translate)
        发消息: Action → OneBot API JSON (build_send_payload)

    Args:
        host: WebSocket 服务监听地址.
        port: WebSocket 服务监听端口.
        timeout: send / call_api 等待响应的超时秒数.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, timeout: float = 10.0, token: str = ""):
        """初始化 NapCatGateway.

        Args:
            host: WebSocket server 监听地址.
            port: WebSocket server 监听端口.
            timeout: send 和 call_api 等待响应的超时时间, 单位为秒.
        """

        self.host = host
        self.port = port
        self.timeout = timeout
        self.token = str(token or "")
        self._ws: ServerConnection | None = None
        self._on_event: Callable[[StandardEvent], Awaitable[None]] | None = None
        self._pending: dict[str, asyncio.Future] = {}  # echo → Future, 请求-响应匹配
        self._self_id: str | None = None                # bot 自己的 QQ 号
        self._server = None

    # region 生命周期

    def on_event(self, handler: Callable[[StandardEvent], Awaitable[None]]) -> None:
        """注册 StandardEvent handler.

        Args:
            handler: 收到标准事件后要调用的 async handler.
        """

        self._on_event = handler

    async def start(self) -> None:
        """启动 WebSocket server.

        Raises:
            RuntimeError: 当 websockets dependency 不可用时抛出.
        """

        if serve is None:
            raise RuntimeError("websockets dependency is required to start NapCatGateway")
        logger.info(f"Gateway listening on ws://{self.host}:{self.port}")
        self._server = await serve(self._handle_connection, self.host, self.port)

    async def stop(self) -> None:
        """停止 WebSocket server."""

        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # endregion

    # region WS连接

    async def _handle_connection(self, ws: ServerConnection) -> None:
        """处理单个 NapCat WebSocket 连接.

        Args:
            ws: 当前建立好的 server connection.
        """

        if websockets is None:
            raise RuntimeError("websockets dependency is required to handle NapCat connections")
        if self.token:
            auth_header = str(ws.request.headers.get("Authorization", "") or "")
            expected = f"Bearer {self.token}"
            if auth_header != expected:
                logger.warning("NapCat connection rejected: invalid Authorization header")
                await ws.close(code=4401, reason="unauthorized")
                return
        self._ws = ws
        self._self_id = ws.request.headers.get("X-Self-ID")
        logger.info(f"NapCat connected, self_id={self._self_id}")
        try:
            async for raw_msg in ws:
                data = json.loads(raw_msg)
                # API 响应: 通过 echo 匹配到 pending Future
                if "echo" in data and data["echo"] in self._pending:
                    self._pending[data["echo"]].set_result(data)
                    continue
                # 事件: 翻译后分发给 Pipeline
                event = self.translate(data)
                if event and self._on_event:
                    asyncio.create_task(self._on_event(event))
        except websockets.ConnectionClosed:
            logger.warning("NapCat disconnected")
        finally:
            self._ws = None

    # endregion

    # region 协议翻译: OneBot v11 JSON → StandardEvent

    def translate(self, raw: dict[str, Any]) -> StandardEvent | None:
        """将 OneBot v11 原始 JSON 翻译为 StandardEvent.

        当前支持:
        - post_type="message"
        - 部分 notice event, 例如 `poke`, `recall`, `member_join`, `member_leave`
        """
        post_type = raw.get("post_type")
        if post_type == "message":
            return self._translate_message(raw)
        if post_type == "notice":
            return self._translate_notice(raw)
        return None

    def _translate_message(self, raw: dict[str, Any]) -> StandardEvent:
        """翻译普通消息事件.

        Args:
            raw: OneBot v11 原始消息事件.

        Returns:
            统一的 StandardEvent.
        """

        sender = raw.get("sender", {})
        raw_segments = list(raw.get("message", []))
        (
            reply_reference,
            mentioned_user_ids,
            mentioned_everyone,
            attachments,
        ) = self._extract_message_features(raw_segments)
        self_user_id = str(self._self_id or "")
        source = EventSource(
            platform="qq",
            message_type=raw.get("message_type", ""),
            user_id=str(raw.get("user_id", "")),
            group_id=str(raw["group_id"]) if "group_id" in raw else None,
        )
        segments = [
            MsgSegment(type=s["type"], data=s.get("data", {}))
            for s in raw_segments
        ]
        logger.debug(
            "translate: msg_id=%s, segments=%s",
            raw.get("message_id"),
            [(s.type, s.data) for s in segments],
        )
        return StandardEvent(
            event_id=f"evt_{raw.get('message_id', '')}",
            event_type="message",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=segments,
            raw_message_id=str(raw.get("message_id", "")),
            sender_nickname=sender.get("nickname", ""),
            sender_role=sender.get("role"),
            message_subtype=str(raw.get("sub_type", "") or "") or None,
            reply_to_message_id=reply_reference.message_id if reply_reference is not None else None,
            reply_reference=reply_reference,
            mentioned_user_ids=mentioned_user_ids,
            mentioned_everyone=mentioned_everyone,
            targets_self=(
                raw.get("message_type") == "private"
                or mentioned_everyone
                or (bool(self_user_id) and self_user_id in mentioned_user_ids)
            ),
            attachments=attachments,
            raw_event=dict(raw),
        )

    def _translate_notice(self, raw: dict[str, Any]) -> StandardEvent | None:
        """翻译 notice 事件.

        Args:
            raw: OneBot v11 notice 事件.

        Returns:
            可识别时返回 StandardEvent, 否则返回 None.
        """

        notice_type = str(raw.get("notice_type", "") or "")
        if notice_type == "notify":
            return self._translate_notify_notice(raw)
        if notice_type in {"group_recall", "friend_recall"}:
            return self._translate_recall_notice(raw, notice_type=notice_type)
        if notice_type == "group_increase":
            return self._translate_group_membership_notice(
                raw,
                event_type="member_join",
                notice_type=notice_type,
            )
        if notice_type == "group_decrease":
            return self._translate_group_membership_notice(
                raw,
                event_type="member_leave",
                notice_type=notice_type,
            )
        if notice_type == "group_admin":
            return self._translate_group_admin_notice(raw, notice_type=notice_type)
        if notice_type == "group_upload":
            return self._translate_group_upload_notice(raw, notice_type=notice_type)
        if notice_type == "friend_add":
            return self._translate_friend_add_notice(raw, notice_type=notice_type)
        if notice_type == "group_ban":
            return self._translate_group_ban_notice(raw, notice_type=notice_type)
        return None

    def _translate_notify_notice(self, raw: dict[str, Any]) -> StandardEvent | None:
        """翻译 notify notice.

        Args:
            raw: OneBot v11 notify 原始事件.

        Returns:
            可识别时返回 StandardEvent, 否则返回 None.
        """

        sub_type = str(raw.get("sub_type", "") or "")
        if sub_type == "poke":
            return self._translate_poke_notice(raw)
        if sub_type == "lucky_king":
            return self._translate_lucky_king_notice(raw)
        if sub_type == "honor":
            return self._translate_honor_notice(raw)
        if sub_type == "title":
            return self._translate_title_notice(raw)
        return None

    def _translate_poke_notice(self, raw: dict[str, Any]) -> StandardEvent:
        """翻译 poke notice.

        Args:
            raw: poke 原始事件.

        Returns:
            统一的 poke StandardEvent.
        """

        group_id = str(raw["group_id"]) if "group_id" in raw else None
        operator_id = str(raw.get("user_id", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group" if group_id is not None else "private",
            user_id=operator_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=f"evt_poke_{raw.get('time', 0)}_{operator_id}",
            event_type="poke",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            operator_id=operator_id or None,
            subject_user_id=str(raw.get("target_id", "") or "") or None,
            notice_type="notify",
            notice_subtype="poke",
            targets_self=(
                bool(self._self_id)
                and str(raw.get("target_id", "") or "") == str(self._self_id)
            ),
            metadata={
                "notice_type": "poke",
                "target_id": str(raw.get("target_id", "") or ""),
            },
            raw_event=dict(raw),
        )

    def _translate_recall_notice(
        self,
        raw: dict[str, Any],
        *,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 recall notice.

        Args:
            raw: recall 原始事件.
            notice_type: OneBot v11 recall 类型.

        Returns:
            统一的 recall StandardEvent.
        """

        group_id = str(raw["group_id"]) if "group_id" in raw else None
        operator_id = str(raw.get("operator_id") or raw.get("user_id") or "")
        recalled_user_id = str(raw.get("user_id", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group" if group_id is not None else "private",
            user_id=operator_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=f"evt_recall_{raw.get('time', 0)}_{raw.get('message_id', '')}",
            event_type="recall",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            operator_id=operator_id or None,
            subject_user_id=recalled_user_id or None,
            target_message_id=str(raw.get("message_id", "") or "") or None,
            notice_type=notice_type,
            metadata={
                "notice_type": notice_type,
                "recalled_user_id": recalled_user_id,
            },
            raw_event=dict(raw),
        )

    def _translate_group_membership_notice(
        self,
        raw: dict[str, Any],
        *,
        event_type: str,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 group membership notice.

        Args:
            raw: group membership 原始事件.
            event_type: canonical 事件类型.
            notice_type: OneBot v11 notice 类型.

        Returns:
            统一的 membership StandardEvent.
        """

        affected_user_id = str(raw.get("user_id", "") or "")
        operator_id = str(raw.get("operator_id", "") or "") or None
        group_id = str(raw.get("group_id", "") or "") or None
        sub_type = str(raw.get("sub_type", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=affected_user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=(
                f"evt_{event_type}_{raw.get('time', 0)}_"
                f"{group_id or ''}_{affected_user_id}_{sub_type}"
            ),
            event_type=event_type,
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            operator_id=operator_id,
            subject_user_id=affected_user_id or None,
            notice_type=notice_type,
            notice_subtype=sub_type or None,
            metadata={
                "notice_type": notice_type,
                "sub_type": sub_type,
                "affected_user_id": affected_user_id,
            },
            raw_event=dict(raw),
        )

    def _translate_group_admin_notice(
        self,
        raw: dict[str, Any],
        *,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 group admin notice.

        Args:
            raw: group admin 原始事件.
            notice_type: OneBot v11 notice 类型.

        Returns:
            统一的 admin_change StandardEvent.
        """

        affected_user_id = str(raw.get("user_id", "") or "")
        group_id = str(raw.get("group_id", "") or "") or None
        sub_type = str(raw.get("sub_type", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=affected_user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=(
                f"evt_admin_change_{raw.get('time', 0)}_"
                f"{group_id or ''}_{affected_user_id}_{sub_type}"
            ),
            event_type="admin_change",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            subject_user_id=affected_user_id or None,
            notice_type=notice_type,
            notice_subtype=sub_type or None,
            metadata={
                "notice_type": notice_type,
                "sub_type": sub_type,
                "affected_user_id": affected_user_id,
            },
            raw_event=dict(raw),
        )

    def _translate_group_upload_notice(
        self,
        raw: dict[str, Any],
        *,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 group upload notice.

        Args:
            raw: group upload 原始事件.
            notice_type: OneBot v11 notice 类型.

        Returns:
            统一的 file_upload StandardEvent.
        """

        uploader_user_id = str(raw.get("user_id", "") or "")
        group_id = str(raw.get("group_id", "") or "") or None
        file_info = dict(raw.get("file", {}) or {})
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=uploader_user_id,
            group_id=group_id,
        )
        attachments: list[EventAttachment] = []
        if file_info:
            attachments.append(
                EventAttachment(
                    type="file",
                    source=str(file_info.get("id") or file_info.get("name") or ""),
                    name=str(file_info.get("name", "") or ""),
                    metadata=dict(file_info),
                )
            )
        return StandardEvent(
            event_id=(
                f"evt_file_upload_{raw.get('time', 0)}_"
                f"{group_id or ''}_{uploader_user_id}_{file_info.get('id', '')}"
            ),
            event_type="file_upload",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            subject_user_id=uploader_user_id or None,
            notice_type=notice_type,
            attachments=attachments,
            metadata={
                "notice_type": notice_type,
                "file": dict(file_info),
                "file_name": str(file_info.get("name", "") or ""),
            },
            raw_event=dict(raw),
        )

    def _translate_friend_add_notice(
        self,
        raw: dict[str, Any],
        *,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 friend add notice.

        Args:
            raw: friend add 原始事件.
            notice_type: OneBot v11 notice 类型.

        Returns:
            统一的 friend_added StandardEvent.
        """

        user_id = str(raw.get("user_id", "") or "")
        source = EventSource(
            platform="qq",
            message_type="private",
            user_id=user_id,
            group_id=None,
        )
        return StandardEvent(
            event_id=f"evt_friend_add_{raw.get('time', 0)}_{user_id}",
            event_type="friend_added",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            subject_user_id=user_id or None,
            notice_type=notice_type,
            targets_self=True,
            metadata={"notice_type": notice_type},
            raw_event=dict(raw),
        )

    def _translate_group_ban_notice(
        self,
        raw: dict[str, Any],
        *,
        notice_type: str,
    ) -> StandardEvent:
        """翻译 group ban notice.

        Args:
            raw: group ban 原始事件.
            notice_type: OneBot v11 notice 类型.

        Returns:
            统一的 mute_change StandardEvent.
        """

        affected_user_id = str(raw.get("user_id", "") or "")
        operator_id = str(raw.get("operator_id", "") or "") or None
        group_id = str(raw.get("group_id", "") or "") or None
        sub_type = str(raw.get("sub_type", "") or "")
        duration = int(raw.get("duration", 0) or 0)
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=affected_user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=(
                f"evt_mute_change_{raw.get('time', 0)}_"
                f"{group_id or ''}_{affected_user_id}_{sub_type}"
            ),
            event_type="mute_change",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            operator_id=operator_id,
            subject_user_id=affected_user_id or None,
            notice_type=notice_type,
            notice_subtype=sub_type or None,
            targets_self=(
                bool(getattr(self, "_self_id", None))
                and affected_user_id == str(getattr(self, "_self_id", ""))
            ),
            metadata={
                "notice_type": notice_type,
                "sub_type": sub_type,
                "duration": duration,
                "affected_user_id": affected_user_id,
            },
            raw_event=dict(raw),
        )

    def _translate_lucky_king_notice(self, raw: dict[str, Any]) -> StandardEvent:
        """翻译 lucky king notify.

        Args:
            raw: lucky king 原始事件.

        Returns:
            统一的 lucky_king StandardEvent.
        """

        group_id = str(raw.get("group_id", "") or "") or None
        sender_user_id = str(raw.get("user_id", "") or "")
        lucky_user_id = str(raw.get("target_id", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=sender_user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=f"evt_lucky_king_{raw.get('time', 0)}_{group_id or ''}_{lucky_user_id}",
            event_type="lucky_king",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            operator_id=sender_user_id or None,
            subject_user_id=lucky_user_id or None,
            notice_type="notify",
            notice_subtype="lucky_king",
            targets_self=(
                bool(getattr(self, "_self_id", None))
                and lucky_user_id == str(getattr(self, "_self_id", ""))
            ),
            metadata={
                "notice_type": "notify",
                "sender_user_id": sender_user_id,
            },
            raw_event=dict(raw),
        )

    def _translate_honor_notice(self, raw: dict[str, Any]) -> StandardEvent:
        """翻译 honor notify.

        Args:
            raw: honor 原始事件.

        Returns:
            统一的 honor_change StandardEvent.
        """

        group_id = str(raw.get("group_id", "") or "") or None
        user_id = str(raw.get("user_id", "") or "")
        honor_type = str(raw.get("honor_type", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=f"evt_honor_{raw.get('time', 0)}_{group_id or ''}_{user_id}_{honor_type}",
            event_type="honor_change",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            subject_user_id=user_id or None,
            notice_type="notify",
            notice_subtype=honor_type or None,
            targets_self=(
                bool(getattr(self, "_self_id", None))
                and user_id == str(getattr(self, "_self_id", ""))
            ),
            metadata={
                "notice_type": "notify",
                "honor_type": honor_type,
            },
            raw_event=dict(raw),
        )

    def _translate_title_notice(self, raw: dict[str, Any]) -> StandardEvent:
        """翻译 title notify.

        Args:
            raw: title 原始事件.

        Returns:
            统一的 title_change StandardEvent.
        """

        group_id = str(raw.get("group_id", "") or "") or None
        user_id = str(raw.get("user_id", "") or "")
        title = str(raw.get("title", "") or "")
        source = EventSource(
            platform="qq",
            message_type="group",
            user_id=user_id,
            group_id=group_id,
        )
        return StandardEvent(
            event_id=f"evt_title_{raw.get('time', 0)}_{group_id or ''}_{user_id}",
            event_type="title_change",
            platform="qq",
            timestamp=raw.get("time", 0),
            source=source,
            segments=[],
            raw_message_id="",
            sender_nickname="",
            sender_role=None,
            subject_user_id=user_id or None,
            notice_type="notify",
            notice_subtype="title",
            targets_self=(
                bool(getattr(self, "_self_id", None))
                and user_id == str(getattr(self, "_self_id", ""))
            ),
            metadata={
                "notice_type": "notify",
                "title": title,
            },
            raw_event=dict(raw),
        )

    def _extract_message_features(
        self,
        raw_segments: list[dict[str, Any]],
    ) -> tuple[ReplyReference | None, list[str], bool, list[EventAttachment]]:
        """从 OneBot message segments 提取 canonical message feature.

        OneBot v11 的 message 是 segment 数组, 每个 segment 有 type 和 data.
        例如: [{"type": "text", "data": {"text": "hello"}}, {"type": "at", "data": {"qq": "12345"}}]

        Args:
            raw_segments: OneBot v11 message 字段里的原始 segments.

        Returns:
            (reply_reference, mentioned_user_ids, mentioned_everyone, attachments).
            - reply_reference: 回复的目标消息引用信息, 从 reply segment 提取
            - mentioned_user_ids: 被 @ 的用户 ID 列表, 从 at segment 提取
            - mentioned_everyone: 当前消息是否显式 @全体
            - attachments: 附件列表(图片/文件/语音/视频), 从对应 segment 转换
        """

        reply_reference: ReplyReference | None = None
        mentioned_user_ids: list[str] = []
        mentioned_everyone = False
        attachments: list[EventAttachment] = []

        for segment in raw_segments:
            seg_type = str(segment.get("type", "") or "")
            data = dict(segment.get("data", {}) or {})

            # reply segment: 是一条回复消息, data.id 是被回复的消息 ID
            if seg_type == "reply":
                reply_message_id = str(data.get("id", "") or "") or ""
                if reply_message_id:
                    reply_reference = ReplyReference(
                        message_id=reply_message_id,
                        sender_user_id=str(
                            data.get("user_id")
                            or data.get("qq")
                            or ""
                        ),
                        text_preview=str(data.get("text", "") or ""),
                        metadata=dict(data),
                    )
                continue  # reply 不生成 attachment

            # at segment: data.qq 是被 @ 的用户 ID
            if seg_type == "at":
                mentioned_user_id = str(data.get("qq", "") or "") or None
                if mentioned_user_id:
                    if mentioned_user_id in {"all", "everyone"}:
                        mentioned_everyone = True
                    mentioned_user_ids.append(mentioned_user_id)
                continue  # at 不生成 attachment

            # 其他 segment 类型(image/file/record/video)转换为 attachment
            # text segment 不在这里处理, 因为文本内容在 message_preview 中提取
            attachment = self._segment_to_attachment(seg_type, data)
            if attachment is not None:
                attachments.append(attachment)

        return reply_reference, mentioned_user_ids, mentioned_everyone, attachments

    def _segment_to_attachment(
        self,
        seg_type: str,
        data: dict[str, Any],
    ) -> EventAttachment | None:
        """把单个 OneBot segment 投影成 canonical EventAttachment.

        类型映射:
        - image -> image: 图片消息
        - file -> file: 文件消息
        - record -> audio: 语音消息(OneBot 叫 record, AcaBot 内部叫 audio)
        - video -> video: 视频消息

        Args:
            seg_type: segment 类型, 如 "image", "file", "record", "video".
            data: segment 负载, 包含 url/file/path/id 等字段.

        Returns:
            可识别时返回 EventAttachment, 否则返回 None.
        """

        # OneBot 类型 -> AcaBot 内部类型的映射表
        attachment_type_map = {
            "image": "image",
            "file": "file",
            "record": "audio",
            "video": "video",
        }
        attachment_type = attachment_type_map.get(seg_type)
        if attachment_type is None:
            # 未识别的类型不生成 attachment
            return None

        # source 的优先级
        # - url: 最直接可访问的 HTTP URL
        # - file: 本地文件路径或缓存标识
        # - path: 备用路径字段
        # - id: 最简标识, 需要二次解析
        source = str(
            data.get("url")
            or data.get("file")
            or data.get("path")
            or data.get("id")
            or ""
        )
        name = str(data.get("name", "") or "")  # 文件名, 用于展示
        mime_type = str(data.get("mime", "") or "")  # MIME 类型, 用于内容识别

        # 保留原始 data 的完整内容, 供后续处理使用
        return EventAttachment(
            type=attachment_type,
            source=source,
            name=name,
            mime_type=mime_type,
            metadata=dict(data),
        )

    # endregion

    # region 协议翻译: Action → OneBot v11 API JSON

    def build_send_payload(self, action: Action) -> dict[str, Any]:
        """将 Action 转换为 OneBot v11 API 请求.

        不同 ActionType 对应不同的 OneBot API endpoint.
        """
        target = action.target
        echo = str(uuid.uuid4())

        if action.action_type in (ActionType.SEND_TEXT, ActionType.SEND_SEGMENTS):
            return self._build_msg_payload(action, target, echo)
        if action.action_type == ActionType.RECALL:
            return {"action": "delete_msg", "params": {"message_id": action.payload["message_id"]}, "echo": echo}
        if action.action_type == ActionType.GROUP_BAN:
            return {"action": "set_group_ban", "params": {
                "group_id": target.group_id,
                "user_id": action.payload["user_id"],
                "duration": action.payload.get("duration", 60),
            }, "echo": echo}
        if action.action_type == ActionType.GROUP_KICK:
            return {"action": "set_group_kick", "params": {
                "group_id": target.group_id,
                "user_id": action.payload["user_id"],
            }, "echo": echo}
        raise ValueError(f"Unsupported action type: {action.action_type}")

    def _build_msg_payload(self, action: Action, target: EventSource, echo: str) -> dict[str, Any]:
        """构建发送消息的 API 请求(SEND_TEXT / SEND_SEGMENTS 共用)."""
        segments: list[dict] = []
        if action.reply_to:
            segments.append({"type": "reply", "data": {"id": action.reply_to}})
        if action.action_type == ActionType.SEND_TEXT:
            segments.append({"type": "text", "data": {"text": action.payload["text"]}})
        else:
            segments.extend(action.payload.get("segments", []))

        if target.message_type == "group":
            return {"action": "send_group_msg", "params": {"group_id": target.group_id, "message": segments}, "echo": echo}
        return {"action": "send_private_msg", "params": {"user_id": target.user_id, "message": segments}, "echo": echo}

    # endregion

    # region 发送 + 通用 API

    async def send(self, action: Action) -> dict[str, Any] | None:
        """发送 Action, 等待 NapCat 返回结果."""
        if not self._ws:
            logger.error("No WS connection")
            return None
        payload = self.build_send_payload(action)
        echo = payload["echo"]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.error(f"Send timeout echo={echo}")
            return None
        finally:
            self._pending.pop(echo, None)

    async def call_api(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """通用 API 调用. 查询型 API(get_msg, get_group_member_info 等)走此方法."""
        if not self._ws:
            return {"status": "failed", "retcode": -1, "msg": "No WS connection"}
        echo = str(uuid.uuid4())
        payload = {"action": action, "params": params, "echo": echo}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(future, timeout=self.timeout)
        except asyncio.TimeoutError:
            return {"status": "failed", "retcode": -1, "msg": f"Timeout: {action}"}
        finally:
            self._pending.pop(echo, None)

    # endregion
