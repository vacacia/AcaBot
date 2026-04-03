"""message builtin tool surface.

这个文件把统一的出站消息意图收束成一个 builtin tool:
- `send`: 产出高层 `SEND_MESSAGE_INTENT`
- `react`: 直接产出底层 `REACTION`
- `recall`: 直接产出底层 `RECALL`

tool surface 只表达意图, 不直接调 Gateway 或 Outbox.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from acabot.agent import ToolSpec
from acabot.types import Action, ActionType, EventSource

from ..contracts import PlannedAction
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


BUILTIN_MESSAGE_TOOL_SOURCE = "builtin:message"

_CANONICAL_CONVERSATION_RE = re.compile(r"^qq:(group|user):[A-Za-z0-9._@!-]+$")
_REACTION_EMOJI_IDS = {
    "thumbs_up": 76,
    "+1": 76,
    "like": 76,
    "👍": 76,
    "heart": 66,
    "red_heart": 66,
    "❤": 66,
    "❤️": 66,
    "fire": 89,
    "🔥": 89,
}


class BuiltinMessageToolSurface:
    """统一 message builtin tool 的注册入口."""

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 message builtin tool 注册到 ToolBroker."""

        tool_broker.unregister_source(BUILTIN_MESSAGE_TOOL_SOURCE)
        tool_broker.register_tool(
            self._tool_spec(),
            self._handle_message,
            source=BUILTIN_MESSAGE_TOOL_SOURCE,
        )
        return ["message"]

    @staticmethod
    def _tool_spec() -> ToolSpec:
        """返回统一 message tool 的 schema."""

        return ToolSpec(
            name="message",
            description=(
                "Unified outbound message tool for send, react, and recall. "
                "Use action=send for any content-type send. When content-type send is used, "
                "content-type send suppresses the default assistant text reply for this turn. "
                "If one outgoing message needs text, images, and render output together, "
                "combine text, images, and render in one send call instead of relying on a "
                "separate assistant text reply. react and recall stay as direct low-level actions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send", "react", "recall"],
                        "default": "send",
                        "description": (
                            "Message operation. send is the default. "
                            "Use react for emoji reactions and recall for message deletion."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "Optional plain text content for action=send.",
                    },
                    "images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional local file paths or remote URLs for action=send."
                        ),
                    },
                    "render": {
                        "type": "string",
                        "description": (
                            "Optional Markdown plus LaTeX math source for action=send."
                        ),
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "Optional quoted message_id for action=send.",
                    },
                    "at_user": {
                        "type": "string",
                        "description": "Optional QQ user_id to mention for action=send.",
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "Optional canonical destination conversation_id for action=send. "
                            "Only qq:group:... and qq:user:... are accepted."
                        ),
                    },
                    "message_id": {
                        "type": "string",
                        "description": (
                            "Target message_id for action=react or action=recall."
                        ),
                    },
                    "emoji": {
                        "type": "string",
                        "description": (
                            "Reaction emoji for action=react. Accepts known aliases or Unicode emoji."
                        ),
                    },
                },
            },
        )

    async def _handle_message(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """执行统一 message tool."""

        action_name = str(arguments.get("action", "send") or "send").strip() or "send"
        if action_name == "send":
            return self._handle_send(arguments, ctx)
        if action_name == "react":
            return self._handle_react(arguments, ctx)
        if action_name == "recall":
            return self._handle_recall(arguments, ctx)
        raise ValueError(f"unsupported message action: {action_name}")

    def _handle_send(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """生成高层 send intent."""

        text = self._optional_text(arguments.get("text"))
        render = self._optional_text(arguments.get("render"))
        reply_to = self._optional_text(arguments.get("reply_to"))
        at_user = self._optional_text(arguments.get("at_user"))
        images = self._normalize_images(arguments.get("images"))
        if text is None and render is None and not images:
            raise ValueError("message send requires at least one of text, images, or render")

        action_target, destination_conversation_id = self._resolve_send_target(
            arguments.get("target"),
            ctx.target,
        )
        plan = PlannedAction(
            action_id=self._build_action_id(ctx, "send"),
            action=Action(
                action_type=ActionType.SEND_MESSAGE_INTENT,
                target=action_target,
                payload={
                    "text": text,
                    "images": images,
                    "render": render,
                    "at_user": at_user,
                    "target": destination_conversation_id,
                },
                reply_to=reply_to,
            ),
            metadata={
                "message_action": "send",
                "suppresses_default_reply": True,
                "destination_conversation_id": destination_conversation_id,
            },
        )
        return ToolResult(user_actions=[plan])

    def _handle_react(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """生成底层 reaction action."""

        message_id = self._require_text(arguments.get("message_id"), field_name="message_id")
        emoji = self._require_text(arguments.get("emoji"), field_name="emoji")
        emoji_id = _REACTION_EMOJI_IDS.get(emoji)
        if emoji_id is None:
            raise ValueError(f"unknown reaction emoji: {emoji}")
        plan = PlannedAction(
            action_id=self._build_action_id(ctx, "react"),
            action=Action(
                action_type=ActionType.REACTION,
                target=ctx.target,
                payload={
                    "message_id": message_id,
                    "emoji_id": emoji_id,
                },
            ),
            metadata={
                "message_action": "react",
                "suppresses_default_reply": False,
                "destination_conversation_id": self._conversation_id_from_target(ctx.target),
            },
        )
        return ToolResult(user_actions=[plan])

    def _handle_recall(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """生成底层 recall action."""

        message_id = self._require_text(arguments.get("message_id"), field_name="message_id")
        plan = PlannedAction(
            action_id=self._build_action_id(ctx, "recall"),
            action=Action(
                action_type=ActionType.RECALL,
                target=ctx.target,
                payload={"message_id": message_id},
            ),
            metadata={
                "message_action": "recall",
                "suppresses_default_reply": False,
                "destination_conversation_id": self._conversation_id_from_target(ctx.target),
            },
        )
        return ToolResult(user_actions=[plan])

    @staticmethod
    def _build_action_id(ctx: ToolExecutionContext, action_name: str) -> str:
        """生成稳定前缀的 action_id."""

        return f"action:{ctx.run_id}:message:{action_name}:{uuid.uuid4().hex}"

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        """把可选文本字段规范成 `str | None`."""

        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _require_text(value: Any, *, field_name: str) -> str:
        """确保一个文本字段非空."""

        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} is required")
        return text

    @classmethod
    def _normalize_images(cls, value: Any) -> list[str]:
        """把 images 输入规范成字符串列表."""

        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise ValueError("images must be a list of strings")
        items = [str(item or "").strip() for item in value]
        return [item for item in items if item]

    @classmethod
    def _resolve_send_target(
        cls,
        raw_target: Any,
        current_target: EventSource,
    ) -> tuple[EventSource, str]:
        """解析 send 使用的目标 EventSource 和 canonical conversation_id."""

        canonical_target = cls._optional_text(raw_target)
        if canonical_target is None:
            return current_target, cls._conversation_id_from_target(current_target)
        if not _CANONICAL_CONVERSATION_RE.match(canonical_target):
            raise ValueError(
                "message target must be a canonical conversation_id like qq:group:123 or qq:user:456"
            )
        _, scope_kind, scope_value = canonical_target.split(":", 2)
        if scope_kind == "group":
            return (
                EventSource(
                    platform="qq",
                    message_type="group",
                    user_id=current_target.user_id,
                    group_id=scope_value,
                ),
                canonical_target,
            )
        return (
            EventSource(
                platform="qq",
                message_type="private",
                user_id=scope_value,
                group_id=None,
            ),
            canonical_target,
        )

    @staticmethod
    def _conversation_id_from_target(target: EventSource) -> str:
        """从 EventSource 推导 canonical conversation_id."""

        if target.message_type == "group":
            return f"{target.platform}:group:{target.group_id}"
        return f"{target.platform}:user:{target.user_id}"


__all__ = [
    "BUILTIN_MESSAGE_TOOL_SOURCE",
    "BuiltinMessageToolSurface",
]
