"""MultimodalPreprocessHook — 多模态消息预处理.

on_receive hook, 在 Pipeline 记录消息前把非文本 segment 替换为文字描述 segment.

处理策略:
- image/mface → VLM 转述(配置了 vision_model 时) 或纯占位, 带 msg_id
- face → 映射表翻译 ID 为名称(无 msg_id, 表情自身含义完整)
- reply → 通过 gateway.call_api("get_msg") 获取被引用消息原文, 带 msg_id
- record/video → 占位, 带 msg_id
- 其他 → [{type} msg_id=xxx] 兜底
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from litellm import acompletion

from acabot.hook.base import Hook
from acabot.hook.face_map import EMCODE_TO_NAME
from acabot.types import HookResult, HookContext, MsgSegment

if TYPE_CHECKING:
    from acabot.gateway.base import BaseGateway

logger = logging.getLogger("acabot.hook.multimodal")


class MultimodalPreprocessHook(Hook):
    """多模态预处理 — on_receive hook.

    把非文本 segment 替换为文字描述, 让 event.text 包含完整信息.
    图片可选用 VLM 生成描述(vision_model), 否则纯占位.

    Attributes:
        vision_model: 图片转述模型名. None 则不做 VLM 描述.
        gateway: 用于 reply 获取被引用消息. None 则 reply 无原文.
    """

    name = "multimodal_preprocess"
    priority = 30
    enabled = True

    def __init__(
        self,
        vision_model: str | None = None,
        gateway: BaseGateway | None = None,
    ):
        self.vision_model = vision_model
        self.gateway = gateway
        logger.info(
            "MultimodalPreprocessHook init: vision_model=%s, gateway=%s",
            vision_model, "yes" if gateway else "no",
        )

    async def handle(self, ctx: HookContext) -> HookResult:
        """遍历 segments, 逐个替换为文字描述."""
        event = ctx.event
        msg_id = event.raw_message_id
        new_segments: list[MsgSegment] = []

        logger.debug(
            "handle() called: msg_id=%s, %d segment(s): %s",
            msg_id, len(event.segments),
            [(s.type, s.data) for s in event.segments],
        )

        for seg in event.segments:
            text_seg = await self._convert_segment(seg, msg_id)
            new_segments.append(text_seg)

        event.segments = new_segments
        logger.debug("handle() done: text=%s", event.text[:300] if event.text else "(empty)")
        return HookResult()

    # region segment 转换

    async def _convert_segment(self, seg: MsgSegment, msg_id: str) -> MsgSegment:
        """把单个 segment 转换为 text segment. 已是 text 则原样返回."""
        seg_type = seg.type

        if seg_type == "text":
            return seg

        if seg_type in ("image", "mface"):
            return await self._convert_image(seg, msg_id)

        if seg_type == "face":
            return self._convert_face(seg)

        if seg_type == "reply":
            return await self._convert_reply(seg)

        if seg_type == "record":
            return self._make_text(f"[语音 msg_id={msg_id}]")

        if seg_type == "video":
            return self._make_text(f"[视频 msg_id={msg_id}]")

        # 兜底: 未知类型(也带 msg_id, 方便后续获取原始内容)
        return self._make_text(f"[{seg_type} msg_id={msg_id}]")

    async def _convert_image(self, seg: MsgSegment, msg_id: str) -> MsgSegment:
        """图片/mface → VLM 描述 或 纯占位."""
        url = seg.data.get("url", "")
        logger.debug(
            "Image: data=%s, vision_model=%s",
            seg.data, self.vision_model,
        )

        # 有 vision_model 且有 URL 时尝试 VLM 转述
        if self.vision_model and url:
            try:
                logger.debug("Calling VLM: model=%s, url=%s", self.vision_model, url[:100])
                description = await self._describe_image(url)
                logger.debug("VLM success: %s", description[:100])
                return self._make_text(f"[图片 msg_id={msg_id}: {description}]")
            except Exception as e:
                logger.warning("VLM describe failed: %s, fallback to placeholder", e)
        elif not url:
            logger.debug("Image has no url, fallback to placeholder")
        elif not self.vision_model:
            logger.debug("No vision_model configured, fallback to placeholder")

        return self._make_text(f"[图片 msg_id={msg_id}]")

    def _convert_face(self, seg: MsgSegment) -> MsgSegment:
        """face → [表情:名称] 或 [表情]."""
        face_id = str(seg.data.get("id", ""))
        name = EMCODE_TO_NAME.get(face_id)
        if name:
            return self._make_text(f"[表情:{name}]")
        return self._make_text("[表情]")

    async def _convert_reply(self, seg: MsgSegment) -> MsgSegment:
        """reply → [回复 msg_id=xxx: 原文] 或 [回复 msg_id=xxx]."""
        reply_msg_id = str(seg.data.get("id", ""))
        if not reply_msg_id:
            return self._make_text("[回复]")

        # 尝试通过 gateway 获取被引用消息内容
        if self.gateway:
            try:
                original_text = await self._fetch_reply_text(reply_msg_id)
                if original_text:
                    return self._make_text(f"[回复 msg_id={reply_msg_id}: {original_text}]")
            except Exception as e:
                logger.warning(f"Fetch reply failed: {e}")

        return self._make_text(f"[回复 msg_id={reply_msg_id}]")

    # endregion

    # region 辅助方法

    @staticmethod
    def _make_text(text: str) -> MsgSegment:
        """构造 text segment."""
        return MsgSegment(type="text", data={"text": text})

    async def _describe_image(self, url: str) -> str:
        """调用 VLM 生成图片描述."""
        response = await acompletion(
            model=self.vision_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "用一句简短的中文描述这张图片的内容."},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("VLM returned empty content")
        return content.strip()

    async def _fetch_reply_text(self, reply_msg_id: str) -> str | None:
        """通过 gateway.call_api 获取被引用消息的文本内容."""
        result = await self.gateway.call_api("get_msg", {"message_id": reply_msg_id})
        if result.get("status") != "ok":
            return None
        data = result.get("data", {})
        message_segs = data.get("message", [])
        # 只提取文本部分
        parts = []
        for s in message_segs:
            if s.get("type") == "text":
                parts.append(s.get("data", {}).get("text", ""))
        return "".join(parts) or None

    # endregion
