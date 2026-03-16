"""图片理解 helper.

只负责两件事:
- 把本地图片转成说明文字
- 把本地图片转成当前轮模型可读的 image parts
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acabot.agent.base import BaseAgent

from .model_registry import FileSystemModelRegistryManager
from .model_resolution import resolve_image_caption_request_for_profile
from .models import ResolvedImageInput, RunContext

logger = logging.getLogger("acabot.runtime.image_context")

DEFAULT_IMAGE_CAPTION_PROMPT = (
    "请简洁描述这张图片里看得见的内容。"
    "只描述可见信息，不要猜测，不要提链接、文件路径或技术细节。"
)


@dataclass(slots=True)
class ImageCaptionSettings:
    enabled: bool = False
    caption_preset_id: str = ""
    caption_prompt: str = DEFAULT_IMAGE_CAPTION_PROMPT
    include_reply_images: bool = True


def parse_image_caption_settings(raw: object) -> ImageCaptionSettings:
    """把 profile 配置里的 image_caption 块归一化."""

    data = dict(raw or {}) if isinstance(raw, dict) else {}
    prompt = str(data.get("caption_prompt", "") or "").strip() or DEFAULT_IMAGE_CAPTION_PROMPT
    return ImageCaptionSettings(
        enabled=bool(data.get("enabled", False)),
        caption_preset_id=str(data.get("caption_preset_id", "") or "").strip(),
        caption_prompt=prompt,
        include_reply_images=bool(data.get("include_reply_images", True)),
    )


class ImageContextService:
    """图片说明和图片输入装配 helper."""

    def __init__(
        self,
        *,
        agent: BaseAgent,
        model_registry_manager: FileSystemModelRegistryManager | None,
    ) -> None:
        self.agent = agent
        self.model_registry_manager = model_registry_manager

    async def caption_images(
        self,
        ctx: RunContext,
        *,
        resolved_images: list[ResolvedImageInput],
        settings: ImageCaptionSettings,
    ) -> None:
        """按配置给一组图片补上 caption."""

        if not resolved_images:
            return
        caption_request = resolve_image_caption_request_for_profile(
            self.model_registry_manager,
            profile=ctx.profile,
            primary_request=ctx.model_request,
        )
        await self._caption_images(
            ctx,
            resolved_images=resolved_images,
            settings=settings,
            caption_request=caption_request,
        )

    async def build_model_content(
        self,
        *,
        base_text: str,
        resolved_images: list[ResolvedImageInput],
    ) -> str | list[dict[str, Any]]:
        """把当前轮文字和图片本体拼成模型输入."""

        event_images = [item for item in resolved_images if item.origin == "event" and item.staged_path]
        reply_images = [item for item in resolved_images if item.origin == "reply" and item.staged_path]
        if not event_images and not reply_images:
            return base_text

        content_blocks = self.normalize_message_content(base_text)
        for item in event_images:
            image_part = await self.image_part_from_path(item.staged_path, item.mime_type)
            if image_part is not None:
                content_blocks.append(image_part)
        if reply_images:
            content_blocks.append({"type": "text", "text": "以下图片来自被引用消息。"})
            for item in reply_images:
                image_part = await self.image_part_from_path(item.staged_path, item.mime_type)
                if image_part is not None:
                    content_blocks.append(image_part)
        return content_blocks

    async def _caption_images(
        self,
        ctx: RunContext,
        *,
        resolved_images: list[ResolvedImageInput],
        settings: ImageCaptionSettings,
        caption_request,
    ) -> None:
        if not resolved_images:
            return
        if caption_request is None:
            for item in resolved_images:
                if item.caption_status == "pending":
                    item.caption_status = "failed"
            return
        if not caption_request.supports_vision:
            for item in resolved_images:
                if item.caption_status == "pending":
                    item.caption_status = "failed"
            logger.warning(
                "Image caption request does not support vision: model=%s",
                caption_request.model,
            )
            return

        for item in resolved_images:
            if item.caption_status != "pending" or not item.staged_path:
                continue
            try:
                item.caption = await self._caption_single_image(
                    prompt=settings.caption_prompt,
                    model_request=caption_request,
                    staged_path=item.staged_path,
                    mime_type=item.mime_type,
                )
            except Exception:
                logger.exception(
                    "Failed to caption image: run_id=%s origin=%s message_id=%s index=%s",
                    ctx.run.run_id,
                    item.origin,
                    item.message_id,
                    item.attachment_index,
                )
                item.caption_status = "failed"
                continue
            item.caption_status = "completed" if item.caption else "failed"

    async def _caption_single_image(self, *, prompt: str, model_request, staged_path: str, mime_type: str) -> str:
        image_part = await self.image_part_from_path(staged_path, mime_type)
        if image_part is None:
            return ""
        response = await self.agent.complete(
            system_prompt="你负责把用户发送的图片转述成简洁文本。",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_part,
                    ],
                }
            ],
            model=model_request.model,
            request_options=model_request.to_request_options(),
        )
        if getattr(response, "error", None):
            raise RuntimeError(str(response.error))
        return str(getattr(response, "text", "") or "").strip()

    @staticmethod
    def normalize_message_content(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            return [dict(item) for item in content]
        text = str(content or "")
        if not text:
            return [{"type": "text", "text": " "}]
        return [{"type": "text", "text": text}]

    async def image_part_from_path(self, staged_path: str, mime_type: str) -> dict[str, Any] | None:
        path = Path(staged_path)
        if not path.exists():
            return None
        data_uri = await asyncio.to_thread(self._encode_image_data_uri, path, mime_type)
        return {
            "type": "image_url",
            "image_url": {"url": data_uri},
        }

    @staticmethod
    def _encode_image_data_uri(path: Path, mime_type: str) -> str:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        normalized_mime = mime_type or mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return f"data:{normalized_mime};base64,{payload}"
