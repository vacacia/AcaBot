"""把当前消息需要的输入材料拿全."""

from __future__ import annotations

import logging
import mimetypes
from typing import Any

from acabot.gateway.onebot_message import (
    extract_onebot_message_features,
    extract_onebot_text,
)

from .computer import AttachmentSnapshot, ComputerRuntime
from .gateway_protocol import GatewayProtocol
from .models import ResolvedImageInput, ResolvedMessage, RunContext

logger = logging.getLogger("acabot.runtime.message_resolution")


class MessageResolutionService:
    """负责把当前消息和 reply 里的可用输入补齐."""

    def __init__(
        self,
        *,
        gateway: GatewayProtocol | None,
        computer_runtime: ComputerRuntime | None,
    ) -> None:
        self.gateway = gateway
        self.computer_runtime = computer_runtime

    async def resolve(
        self,
        ctx: RunContext,
        *,
        include_reply_images: bool,
    ) -> ResolvedMessage:
        """把这条消息能用到的材料补齐成一份稳定结果."""

        resolved_images = self._collect_event_images(ctx)
        reply_text = ""
        if include_reply_images and ctx.event.reply_reference is not None:
            reply_text, reply_images = await self._collect_reply_images(ctx)
            resolved_images.extend(reply_images)

        resolved = ResolvedMessage(
            base_text=ctx.event.working_memory_text,
            reply_text=reply_text,
            resolved_images=resolved_images,
            metadata={
                "bot_relation": ctx.event.bot_relation,
                "target_reasons": list(ctx.event.target_reasons),
            },
        )
        ctx.resolved_message = resolved
        ctx.resolved_images = list(resolved_images)
        if reply_text:
            ctx.metadata["reply_reference_text"] = reply_text
        return resolved

    def _collect_event_images(self, ctx: RunContext) -> list[ResolvedImageInput]:
        message_id = str(ctx.event.raw_message_id or ctx.event.event_id)
        resolved: list[ResolvedImageInput] = []
        for snapshot in ctx.attachment_snapshots:
            if snapshot.type != "image":
                continue
            resolved.append(
                ResolvedImageInput(
                    origin="event",
                    message_id=message_id,
                    attachment_index=snapshot.attachment_index,
                    staged_path=snapshot.staged_path,
                    mime_type=self._mime_type_for_snapshot(snapshot),
                    caption_status="pending" if snapshot.staged_path else "failed",
                )
            )
        return resolved

    async def _collect_reply_images(self, ctx: RunContext) -> tuple[str, list[ResolvedImageInput]]:
        if (
            self.gateway is None
            or self.computer_runtime is None
            or ctx.event.reply_reference is None
        ):
            preview = ctx.event.reply_reference.text_preview if ctx.event.reply_reference is not None else ""
            return str(preview or ""), []

        reply_message_id = str(ctx.event.reply_reference.message_id or "").strip()
        if not reply_message_id:
            return "", []

        try:
            params: dict[str, Any] = {"message_id": int(reply_message_id)}
        except ValueError:
            params = {"message_id": reply_message_id}

        try:
            response = await self.gateway.call_api("get_msg", params)
        except Exception:
            logger.exception("Failed to fetch quoted message: message_id=%s", reply_message_id)
            return str(ctx.event.reply_reference.text_preview or ""), []

        if str(response.get("status", "")) != "ok":
            return str(ctx.event.reply_reference.text_preview or ""), []

        data = dict(response.get("data", {}) or {})
        raw_segments = list(data.get("message", []) or [])
        reply_text = extract_onebot_text(raw_segments) or str(ctx.event.reply_reference.text_preview or "")
        _, _, _, attachments = extract_onebot_message_features(raw_segments)
        image_attachments = [item for item in attachments if item.type == "image"]
        if not image_attachments:
            return reply_text, []

        reply_event_id = f"{ctx.event.event_id}_reply_{reply_message_id}"
        staged = await self.computer_runtime.stage_attachments(
            thread_id=ctx.thread.thread_id,
            run_id=ctx.run.run_id,
            event_id=reply_event_id,
            attachments=image_attachments,
            category="reply",
        )
        resolved: list[ResolvedImageInput] = []
        for snapshot in staged.snapshots:
            if snapshot.type != "image":
                continue
            resolved.append(
                ResolvedImageInput(
                    origin="reply",
                    message_id=reply_message_id,
                    attachment_index=snapshot.attachment_index,
                    staged_path=snapshot.staged_path,
                    mime_type=self._mime_type_for_snapshot(snapshot),
                    caption_status="pending" if snapshot.staged_path else "failed",
                )
            )
        return reply_text, resolved

    @staticmethod
    def _mime_type_for_snapshot(snapshot: AttachmentSnapshot) -> str:
        mime_type = str(snapshot.metadata.get("mime", "") or snapshot.metadata.get("mime_type", "") or "")
        if mime_type:
            return mime_type
        guessed, _ = mimetypes.guess_type(snapshot.staged_path)
        return guessed or "image/jpeg"
