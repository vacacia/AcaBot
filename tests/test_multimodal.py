# MultimodalPreprocessHook: 多模态预处理
# 测试: 纯文本不变, 图片占位+VLM描述, face映射, mface/record/video占位,
#       reply获取原文, 未知类型兜底, VLM失败fallback, 混合segment

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from acabot.hook.multimodal import MultimodalPreprocessHook
from acabot.types import HookContext, StandardEvent, EventSource, MsgSegment
from acabot.session.base import Session


# region helpers

def make_event(segments: list[MsgSegment], raw_message_id: str = "msg_100") -> StandardEvent:
    """构造测试用 StandardEvent."""
    source = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
    return StandardEvent(
        event_id="e", event_type="message", platform="qq", timestamp=0,
        source=source, segments=segments,
        raw_message_id=raw_message_id, sender_nickname="T", sender_role=None,
    )


def make_ctx(segments: list[MsgSegment], raw_message_id: str = "msg_100") -> HookContext:
    """构造测试用 HookContext."""
    event = make_event(segments, raw_message_id)
    session = Session(session_key="test:user:1")
    return HookContext(event=event, session=session, messages=[])


def make_gateway_mock(reply_text: str = "被引用的原文") -> AsyncMock:
    """构造 mock gateway, call_api 返回 get_msg 结果."""
    gw = AsyncMock()
    gw.call_api = AsyncMock(return_value={
        "status": "ok",
        "data": {
            "message": [{"type": "text", "data": {"text": reply_text}}],
            "sender": {"nickname": "张三"},
        },
    })
    return gw


async def mock_describe_image(url: str) -> str:
    """mock VLM 图片描述."""
    return "一只橘色的猫坐在桌子上"


# endregion


# region 纯文本
class TestTextOnly:
    """纯文本消息不做任何修改."""

    async def test_single_text_unchanged(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([MsgSegment(type="text", data={"text": "hello"})])
        await hook.handle(ctx)
        assert len(ctx.event.segments) == 1
        assert ctx.event.segments[0].type == "text"
        assert ctx.event.text == "hello"

    async def test_multiple_text_unchanged(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([
            MsgSegment(type="text", data={"text": "hello "}),
            MsgSegment(type="text", data={"text": "world"}),
        ])
        await hook.handle(ctx)
        assert len(ctx.event.segments) == 2
        assert ctx.event.text == "hello world"


# endregion


# region 图片
class TestImage:
    """图片 segment 替换为 [图片 msg_id=xxx: VLM描述]."""

    async def test_image_with_vlm(self):
        hook = MultimodalPreprocessHook(vision_model="gpt-4o-mini")
        hook._describe_image = mock_describe_image
        ctx = make_ctx(
            [MsgSegment(type="image", data={"url": "https://example.com/cat.jpg"})],
            raw_message_id="msg_42",
        )
        await hook.handle(ctx)
        assert len(ctx.event.segments) == 1
        assert ctx.event.segments[0].type == "text"
        text = ctx.event.text
        assert "图片" in text
        assert "msg_42" in text
        assert "橘色的猫" in text

    async def test_image_vlm_disabled(self):
        """未配置 vision_model 时只做占位."""
        hook = MultimodalPreprocessHook(vision_model=None)
        ctx = make_ctx(
            [MsgSegment(type="image", data={"url": "https://example.com/cat.jpg"})],
            raw_message_id="msg_42",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "图片" in text
        assert "msg_42" in text
        # 无描述
        assert "橘色" not in text

    async def test_image_vlm_failure_fallback(self):
        """VLM 调用失败时 fallback 到纯占位."""
        async def fail_describe(url: str) -> str:
            raise RuntimeError("VLM down")

        hook = MultimodalPreprocessHook(vision_model="gpt-4o-mini")
        hook._describe_image = fail_describe
        ctx = make_ctx(
            [MsgSegment(type="image", data={"url": "https://example.com/img.jpg"})],
            raw_message_id="msg_55",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "图片" in text
        assert "msg_55" in text

    async def test_image_no_url(self):
        """图片没有 url 也不崩溃."""
        hook = MultimodalPreprocessHook()
        ctx = make_ctx(
            [MsgSegment(type="image", data={"file": "abc.jpg"})],
            raw_message_id="msg_60",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "图片" in text

    async def test_image_vlm_returns_none(self):
        """VLM 返回 None content 时 fallback 到占位."""
        async def none_describe(url: str) -> str:
            raise ValueError("VLM returned empty content")

        hook = MultimodalPreprocessHook(vision_model="gpt-4o-mini")
        hook._describe_image = none_describe
        ctx = make_ctx(
            [MsgSegment(type="image", data={"url": "https://example.com/img.jpg"})],
            raw_message_id="msg_65",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "图片" in text
        assert "msg_65" in text


# endregion


# region face 表情
class TestFace:
    """face segment 替换为 [表情:名称]."""

    async def test_face_known_id(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([MsgSegment(type="face", data={"id": "100"})])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "表情" in text
        assert "微笑" in text

    async def test_face_unknown_id(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([MsgSegment(type="face", data={"id": "99999"})])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "表情" in text
        # 查不到名称, 不崩溃
        assert ctx.event.segments[0].type == "text"


# endregion


# region mface (市场表情)
class TestMface:
    """mface 本质是图片, 同 image 处理."""

    async def test_mface_as_image(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx(
            [MsgSegment(type="mface", data={"url": "https://example.com/sticker.gif"})],
            raw_message_id="msg_70",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "图片" in text
        assert "msg_70" in text


# endregion


# region reply
class TestReply:
    """reply segment 替换为 [回复 msg_id=xxx: 原文]."""

    async def test_reply_fetches_original(self):
        gw = make_gateway_mock("被引用的原文")
        hook = MultimodalPreprocessHook(gateway=gw)
        ctx = make_ctx([
            MsgSegment(type="reply", data={"id": "msg_99"}),
            MsgSegment(type="text", data={"text": "回复这个"}),
        ])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "回复" in text
        assert "msg_99" in text
        assert "被引用的原文" in text
        assert "回复这个" in text
        gw.call_api.assert_called_once_with("get_msg", {"message_id": "msg_99"})

    async def test_reply_gateway_none(self):
        """未注入 gateway 时, reply 只有 msg_id 没有原文."""
        hook = MultimodalPreprocessHook(gateway=None)
        ctx = make_ctx([
            MsgSegment(type="reply", data={"id": "msg_99"}),
            MsgSegment(type="text", data={"text": "回复这个"}),
        ])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "回复" in text
        assert "msg_99" in text

    async def test_reply_api_failure(self):
        """get_msg 失败时 fallback 到无原文."""
        gw = AsyncMock()
        gw.call_api = AsyncMock(return_value={"status": "failed"})
        hook = MultimodalPreprocessHook(gateway=gw)
        ctx = make_ctx([
            MsgSegment(type="reply", data={"id": "msg_99"}),
        ])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "回复" in text
        assert "msg_99" in text

    async def test_reply_empty_id(self):
        """reply segment 缺少 id 时不调 API, 直接 [回复]."""
        gw = make_gateway_mock()
        hook = MultimodalPreprocessHook(gateway=gw)
        ctx = make_ctx([MsgSegment(type="reply", data={})])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "回复" in text
        gw.call_api.assert_not_called()

    async def test_reply_with_image_in_original(self):
        """被引用消息含图片时, 提取文本部分."""
        gw = AsyncMock()
        gw.call_api = AsyncMock(return_value={
            "status": "ok",
            "data": {
                "message": [
                    {"type": "text", "data": {"text": "看这张"}},
                    {"type": "image", "data": {"url": "http://img.jpg"}},
                ],
            },
        })
        hook = MultimodalPreprocessHook(gateway=gw)
        ctx = make_ctx([MsgSegment(type="reply", data={"id": "msg_88"})])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "看这张" in text


# endregion


# region record / video
class TestRecordVideo:
    """语音和视频占位."""

    async def test_record_placeholder(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx(
            [MsgSegment(type="record", data={"url": "http://voice.amr"})],
            raw_message_id="msg_80",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "语音" in text
        assert "msg_80" in text

    async def test_video_placeholder(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx(
            [MsgSegment(type="video", data={"file": "video.mp4"})],
            raw_message_id="msg_81",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "视频" in text
        assert "msg_81" in text


# endregion


# region 未知类型兜底
class TestUnknownType:
    """未知 segment 类型替换为 [{type} msg_id=xxx]."""

    async def test_unknown_type_fallback(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx(
            [MsgSegment(type="forward", data={"id": "xxx"})],
            raw_message_id="msg_95",
        )
        await hook.handle(ctx)
        text = ctx.event.text
        assert "forward" in text
        assert "msg_95" in text


# endregion


# region 混合 segment
class TestMixedSegments:
    """多种类型混合时保持顺序."""

    async def test_text_image_text(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([
            MsgSegment(type="text", data={"text": "看这个"}),
            MsgSegment(type="image", data={"url": "http://img.jpg"}),
            MsgSegment(type="text", data={"text": "怎么样"}),
        ], raw_message_id="msg_90")
        await hook.handle(ctx)
        text = ctx.event.text
        assert "看这个" in text
        assert "怎么样" in text
        assert "图片" in text
        # 所有 segment 都是 text 类型
        assert all(s.type == "text" for s in ctx.event.segments)

    async def test_reply_face_text(self):
        hook = MultimodalPreprocessHook()
        ctx = make_ctx([
            MsgSegment(type="reply", data={"id": "msg_50"}),
            MsgSegment(type="face", data={"id": "100"}),
            MsgSegment(type="text", data={"text": "你好"}),
        ])
        await hook.handle(ctx)
        text = ctx.event.text
        assert "回复" in text
        assert "微笑" in text
        assert "你好" in text


# endregion
