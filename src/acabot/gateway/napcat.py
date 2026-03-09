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
from acabot.types import StandardEvent, EventSource, MsgSegment, Action, ActionType

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

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, timeout: float = 10.0):
        """初始化 NapCatGateway.

        Args:
            host: WebSocket server 监听地址.
            port: WebSocket server 监听端口.
            timeout: send 和 call_api 等待响应的超时时间, 单位为秒.
        """

        self.host = host
        self.port = port
        self.timeout = timeout
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

        只处理 post_type="message" 的事件, 其他类型返回 None.
        """
        if raw.get("post_type") != "message":
            return None

        sender = raw.get("sender", {})
        source = EventSource(
            platform="qq",
            message_type=raw.get("message_type", ""),
            user_id=str(raw.get("user_id", "")),
            group_id=str(raw["group_id"]) if "group_id" in raw else None,
        )
        segments = [
            MsgSegment(type=s["type"], data=s.get("data", {}))
            for s in raw.get("message", [])
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
