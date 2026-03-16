"""消息整理入口.

对外只暴露一层, 内部明确拆成两步:
- 先把消息材料拿全
- 再按用途生成各处要用的版本
"""

from __future__ import annotations

from .image_context import parse_image_caption_settings
from .message_projection import MessageProjectionService
from .message_resolution import MessageResolutionService
from .models import RunContext


class MessagePreparationService:
    """统一的消息整理入口."""

    def __init__(
        self,
        *,
        resolution_service: MessageResolutionService,
        projection_service: MessageProjectionService,
    ) -> None:
        self.resolution_service = resolution_service
        self.projection_service = projection_service

    async def prepare(self, ctx: RunContext) -> None:
        """补齐消息材料, 再生成 history / model / memory 候选."""

        settings = parse_image_caption_settings(ctx.profile.config.get("image_caption"))
        if not settings.enabled:
            return

        resolved = await self.resolution_service.resolve(
            ctx,
            include_reply_images=settings.include_reply_images,
        )
        await self.projection_service.project(
            ctx,
            resolved=resolved,
            image_settings=settings,
        )

    def apply_model_message(self, ctx: RunContext) -> None:
        """把整理后的当前轮用户输入应用到最后一条 user message."""

        projection = ctx.message_projection
        if projection is None:
            return
        for index in range(len(ctx.messages) - 1, -1, -1):
            if str(ctx.messages[index].get("role", "")) != "user":
                continue
            ctx.messages[index]["content"] = projection.model_content
            return
