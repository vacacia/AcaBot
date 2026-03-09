"""处理多模态消息的预处理 hook.

把非文本 segment 转成 text segment.
默认规则如下:
- image/mface: 使用 VLM 描述, 或回退到占位文本.
- face: 根据 face id 转成文字标签.
- reply: 通过 gateway 拉取被引用消息的文本部分.
- record/video: 生成带 msg_id 的占位文本.
- 其他 segment: 生成兜底占位文本.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from acabot.hook.base import Hook
from acabot.hook.face_map import EMCODE_TO_NAME
from acabot.types import HookResult, HookContext, MsgSegment

if TYPE_CHECKING:
    from acabot.gateway.base import BaseGateway

logger = logging.getLogger("acabot.hook.multimodal")

try:
    from litellm import acompletion as _litellm_acompletion
except ImportError:  # pragma: no cover
    _litellm_acompletion = None

acompletion = _litellm_acompletion


class MultimodalPreprocessHook(Hook):
    """在 on_receive 阶段把非文本 segment 转成 text.

    这个 hook 的目标是让后续 Pipeline 和 Agent 只面对纯文本上下文.
    如果配置了 `vision_model`, 图片会先走一次 VLM 描述.

    Attributes:
        vision_model: 用于描述图片的 VLM model name. None 表示只生成占位文本.
        gateway: 用于补全 reply 原文的 Gateway. None 表示只保留 reply msg_id.
    """

    name = "multimodal_preprocess"
    priority = 30
    enabled = True

    def __init__(
        self,
        vision_model: str | None = None,
        gateway: BaseGateway | None = None,
    ):
        """初始化 MultimodalPreprocessHook.

        Args:
            vision_model: 可选的 VLM model name. 配置后会为 image 和 mface 生成描述文本.
            gateway: 可选的 Gateway 实例. 配置后 reply segment 可以补全原文.
        """
        self.vision_model = vision_model
        self.gateway = gateway
        logger.info(
            "MultimodalPreprocessHook init: vision_model=%s, gateway=%s",
            vision_model, "yes" if gateway else "no",
        )

    async def handle(self, ctx: HookContext) -> HookResult:
        """遍历 event.segments 并逐个转换成 text segment.

        Args:
            ctx: 当前 hook 上下文. 这个方法会原地修改 `ctx.event.segments`.

        Returns:
            默认返回 `HookResult()`, 不主动终止后续 hook 链路.
        """
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
        """把单个 segment 转换为 text segment.

        Args:
            seg: 当前待处理的原始 segment.
            msg_id: 当前消息的原始平台消息 id.

        Returns:
            转换后的 text segment. 如果原本就是 text, 则直接返回原对象.
        """
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
        """把 image 或 mface 转成描述文本或占位文本.

        Args:
            seg: 当前 image 或 mface segment.
            msg_id: 当前消息的原始平台消息 id.

        Returns:
            包含图片描述或占位文本的 text segment.
        """
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
        """把 face segment 转成稳定的文字标签.

        Args:
            seg: 当前 face segment.

        Returns:
            映射成功时返回带表情名的 text segment, 否则返回通用占位文本.
        """
        face_id = str(seg.data.get("id", ""))
        name = EMCODE_TO_NAME.get(face_id)
        if name:
            return self._make_text(f"[表情:{name}]")
        return self._make_text("[表情]")

    async def _convert_reply(self, seg: MsgSegment) -> MsgSegment:
        """把 reply segment 转成带原文或带 msg_id 的文本.

        Args:
            seg: 当前 reply segment.

        Returns:
            优先返回包含 reply 原文的 text segment. 获取失败时回退到带 msg_id 的占位文本.
        """
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
        """构造标准的 text segment.

        Args:
            text: 要写入 segment 的文本内容.

        Returns:
            标准化后的 text segment.
        """
        return MsgSegment(type="text", data={"text": text})

    @staticmethod
    def _get_acompletion():
        """返回可用的 litellm `acompletion` callable.

        Returns:
            可直接 await 的 `acompletion` callable.

        Raises:
            RuntimeError: 当前环境未安装 `litellm`, 但代码尝试执行 VLM 调用.
        """
        if acompletion is None:
            raise RuntimeError("litellm dependency is required to describe images")
        return acompletion

    async def _describe_image(self, url: str) -> str:
        """用 VLM 生成图片描述.

        Args:
            url: 图片可访问 URL.

        Returns:
            去除首尾空白后的图片描述文本.

        Raises:
            RuntimeError: 当前环境缺少 `litellm`.
            ValueError: VLM 返回空内容.
        """
        completion = self._get_acompletion()
        response = await completion(
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
        """通过 gateway 获取被引用消息的文本内容.

        Args:
            reply_msg_id: 被引用消息的原始平台消息 id.

        Returns:
            被引用消息中的纯文本内容. 如果调用失败或没有文本, 返回 None.
        """
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
