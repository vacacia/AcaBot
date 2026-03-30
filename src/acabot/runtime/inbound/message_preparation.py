"""消息整理入口.

对外只暴露一层, 内部明确拆成两步:
- 先把消息材料拿全
- 再按用途生成各处要用的版本
"""

from __future__ import annotations

from .image_context import parse_image_caption_settings
from .message_projection import MessageProjectionService
from .message_resolution import MessageResolutionService
from ..contracts import RunContext


class MessagePreparationService:
    """统一的消息整理入口."""

    def __init__(
        self,
        *,
        resolution_service: MessageResolutionService,
        projection_service: MessageProjectionService,
    ) -> None:
        """初始化消息整理服务.

        Args:
            resolution_service: 负责补齐消息材料的服务.
            projection_service: 负责生成 history / model / memory 版本的服务.
        """

        self.resolution_service = resolution_service
        self.projection_service = projection_service

    async def prepare(self, ctx: RunContext) -> None:
        """补齐消息材料, 再生成 history / model / memory 候选.

        Args:
            ctx: 当前 run 的执行上下文.
        """

        settings = parse_image_caption_settings(ctx.agent.config.get("image_caption"))
        resolved = await self.resolution_service.resolve(
            ctx,
            include_reply_images=settings.enabled and settings.include_reply_images,
        )
        await self.projection_service.project(
            ctx,
            resolved=resolved,
            image_settings=settings,
        )
