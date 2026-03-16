"""把补齐后的消息变成各处要用的版本."""

from __future__ import annotations

from .image_context import ImageCaptionSettings, ImageContextService
from ..contracts import MemoryCandidate, MessageProjection, ResolvedImageInput, ResolvedMessage, RunContext


class MessageProjectionService:
    """根据当前 run 规则生成 history / model / memory 候选."""

    def __init__(self, *, image_context: ImageContextService) -> None:
        self.image_context = image_context

    async def project(
        self,
        ctx: RunContext,
        *,
        resolved: ResolvedMessage,
        image_settings: ImageCaptionSettings,
    ) -> MessageProjection:
        """把补齐后的消息投影成系统后面要消费的几个版本."""

        resolved_images = list(resolved.resolved_images)
        if image_settings.enabled and resolved_images:
            await self.image_context.caption_images(
                ctx,
                resolved_images=resolved_images,
                settings=image_settings,
            )

        history_text = self._build_history_text(
            base_text=resolved.base_text,
            resolved_images=resolved_images,
            reply_text=resolved.reply_text,
        )
        memory_candidates = self._build_memory_candidates(
            base_text=resolved.base_text,
            resolved_images=resolved_images,
            reply_text=resolved.reply_text,
        )

        model_content: str | list[dict[str, object]] = history_text
        if (
            ctx.decision.run_mode == "respond"
            and ctx.model_request is not None
            and ctx.model_request.supports_vision
            and resolved_images
        ):
            model_content = await self.image_context.build_model_content(
                base_text=history_text,
                resolved_images=resolved_images,
            )

        projection = MessageProjection(
            history_text=history_text,
            model_content=model_content,
            memory_candidates=memory_candidates,
            metadata={
                "has_images": bool(resolved_images),
                "has_reply_text": bool(resolved.reply_text),
            },
        )
        ctx.message_projection = projection
        ctx.memory_user_content = history_text
        ctx.resolved_images = resolved_images
        if resolved.reply_text:
            ctx.metadata["reply_reference_text"] = resolved.reply_text
        return projection

    def _build_history_text(
        self,
        *,
        base_text: str,
        resolved_images: list[ResolvedImageInput],
        reply_text: str,
    ) -> str:
        parts: list[str] = [part for part in [base_text] if part]
        event_captions = [item.caption for item in resolved_images if item.origin == "event" and item.caption]
        reply_captions = [item.caption for item in resolved_images if item.origin == "reply" and item.caption]
        if reply_text:
            parts.append(f"[系统补充-引用文本: {reply_text}]")
        if event_captions:
            parts.append(self._format_tagged_block("系统补充-图片说明", event_captions))
        if reply_captions:
            parts.append(self._format_tagged_block("系统补充-引用图片说明", reply_captions))
        return " ".join(part for part in parts if part).strip()

    def _build_memory_candidates(
        self,
        *,
        base_text: str,
        resolved_images: list[ResolvedImageInput],
        reply_text: str,
    ) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        if base_text:
            candidates.append(
                MemoryCandidate(
                    kind="base_text",
                    text=base_text,
                    origin="event",
                    generated=False,
                )
            )
        if reply_text:
            candidates.append(
                MemoryCandidate(
                    kind="reply_text",
                    text=reply_text,
                    origin="reply",
                    generated=False,
                    metadata={"label": "引用文本"},
                )
            )
        for item in resolved_images:
            if not item.caption:
                continue
            candidates.append(
                MemoryCandidate(
                    kind="image_caption",
                    text=item.caption,
                    origin=item.origin,
                    generated=True,
                    metadata={
                        "label": "图片说明" if item.origin == "event" else "引用图片说明",
                    },
                )
            )
        return candidates

    @staticmethod
    def _format_tagged_block(label: str, values: list[str]) -> str:
        if len(values) == 1:
            return f"[{label}: {values[0]}]"
        joined = " ".join(f"{index}. {value}" for index, value in enumerate(values, start=1))
        return f"[{label}: {joined}]"
