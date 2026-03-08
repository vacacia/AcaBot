# ContextCompressorHook: 上下文截断 + 摘要压缩
# 测试: 短上下文不触发, token 截断, 完整轮次保护,
#       preserve_recent, summary 写入 session, token_stats 统计, model=None 跳过

import pytest
from unittest.mock import patch
from acabot.hook.context_compress import ContextCompressorHook
from acabot.types import HookContext, StandardEvent, EventSource, MsgSegment
from acabot.session.base import Session


# region helpers

def make_messages(n_turns: int, content_len: int = 10) -> list[dict]:
    """构造 n 轮对话(user + assistant), 每条消息 content_len 个字符."""
    msgs = []
    for i in range(n_turns):
        msgs.append({"role": "user", "content": f"u{i} " + "x" * content_len})
        msgs.append({"role": "assistant", "content": f"a{i} " + "y" * content_len})
    return msgs


def make_messages_with_tools(n_turns: int) -> list[dict]:
    """构造带 tool_call 的对话, 用于测试完整轮次保护."""
    msgs = []
    for i in range(n_turns):
        msgs.append({"role": "user", "content": f"user {i}"})
        msgs.append({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": f"call_{i}", "function": {"name": "test", "arguments": "{}"}}],
        })
        msgs.append({"role": "tool", "content": f"result {i}", "tool_call_id": f"call_{i}"})
        msgs.append({"role": "assistant", "content": f"answer {i}"})
    return msgs


def make_ctx(messages: list[dict], model: str | None = "gpt-4o") -> HookContext:
    """构造测试用 HookContext, 带 session."""
    source = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
    event = StandardEvent(
        event_id="e", event_type="message", platform="qq", timestamp=0,
        source=source, segments=[MsgSegment(type="text", data={"text": "test"})],
        raw_message_id="m", sender_nickname="T", sender_role=None,
    )
    session = Session(session_key="test:user:1", messages=list(messages))
    return HookContext(
        event=event, session=session, messages=list(messages),
        model=model,
    )


def mock_token_counter(model="", messages=None, **kwargs):
    """mock token_counter: 每条消息算 content 长度作为 token 数."""
    if messages is None:
        return 0
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        if "tool_calls" in m:
            total += 20
    return total


MOCK_MODEL_INFO = {
    "max_input_tokens": 1000,
    "max_output_tokens": 100,
    "max_tokens": 100,
}


@pytest.fixture
def _mock_litellm():
    """统一 mock litellm 的 token_counter 和 get_model_info."""
    with patch("acabot.hook.context_compress.token_counter", side_effect=mock_token_counter), \
         patch("acabot.hook.context_compress.get_model_info", return_value=MOCK_MODEL_INFO):
        yield


# endregion


# region 短上下文 / 跳过
class TestNoCompression:
    """上下文未超预算或无 model 时, 不做任何修改."""

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_short_context_unchanged(self):
        msgs = make_messages(3, content_len=5)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.7)
        original_count = len(ctx.messages)
        result = await hook.handle(ctx)
        assert result.action == "continue"
        assert len(ctx.messages) == original_count

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_no_stats_when_no_compression(self):
        msgs = make_messages(2, content_len=5)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.7)
        await hook.handle(ctx)
        stats = ctx.metadata.get("token_stats", {})
        assert stats.get("messages_dropped", 0) == 0

    async def test_model_none_skips_entirely(self):
        """ctx.model 为 None 时直接跳过, 不崩溃."""
        msgs = make_messages(10, content_len=100)
        ctx = make_ctx(msgs, model=None)
        hook = ContextCompressorHook(max_context_ratio=0.7)
        result = await hook.handle(ctx)
        assert result.action == "continue"
        assert len(ctx.messages) == 20  # 没有任何截断


# endregion


# region token 截断
class TestTokenTruncation:
    """token 超预算时砍旧消息, 按完整轮次."""

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_token_budget_truncates(self):
        # context_window=1000, ratio=0.7, budget=700
        # 15 轮 = 30 条, 每条 ~50 字符(token), 总 ~1500 token → 超预算
        # preserve_recent=3, 远小于 15 轮, 不会干扰 budget 裁剪
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.7, preserve_recent=3)
        await hook.handle(ctx)
        assert len(ctx.messages) < 30
        # 最近的消息被保留
        assert ctx.messages[-1]["content"].startswith("a14")

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_preserve_recent_guaranteed(self):
        # 即使 token 很紧张, preserve_recent 轮数也必须保留
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.1, preserve_recent=3)
        await hook.handle(ctx)
        # 至少保留 3 轮 = 6 条
        assert len(ctx.messages) >= 6


# endregion


# region 完整轮次保护
class TestTurnIntegrity:
    """截断不拆散 tool_call/tool_result 配对."""

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_tool_call_pair_not_split(self):
        msgs = make_messages_with_tools(5)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.3)
        await hook.handle(ctx)
        for i, m in enumerate(ctx.messages):
            if m["role"] == "tool":
                assert i > 0
                prev = ctx.messages[i - 1]
                assert prev["role"] == "assistant" and "tool_calls" in prev

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_tool_call_answer_kept_together(self):
        msgs = make_messages_with_tools(5)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.3)
        await hook.handle(ctx)
        for i, m in enumerate(ctx.messages):
            if m["role"] == "tool":
                assert i + 1 < len(ctx.messages)
                assert ctx.messages[i + 1]["role"] == "assistant"


# endregion


# region token_stats 统计
class TestTokenStats:
    """ctx.metadata['token_stats'] 记录压缩统计."""

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_stats_recorded_on_compression(self):
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(max_context_ratio=0.7, preserve_recent=3)
        await hook.handle(ctx)
        stats = ctx.metadata.get("token_stats")
        assert stats is not None
        assert stats["context_window"] == 1000
        assert stats["messages_dropped"] > 0
        assert stats["strategy_used"] == "truncate"

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_stats_model_recorded(self):
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs, model="claude-3-5-sonnet")
        hook = ContextCompressorHook(max_context_ratio=0.7, preserve_recent=3)
        await hook.handle(ctx)
        stats = ctx.metadata["token_stats"]
        assert stats["model"] == "claude-3-5-sonnet"


# endregion


# region summary
class TestSummaryPersistence:
    """truncate 模式不写 summary, 已有的 summary 不被清除."""

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_truncate_does_not_write_summary(self):
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(strategy="truncate", max_context_ratio=0.7, preserve_recent=3)
        await hook.handle(ctx)
        assert ctx.session.summary is None

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_session_summary_preserved_for_truncate(self):
        msgs = make_messages(3, content_len=5)
        ctx = make_ctx(msgs)
        ctx.session.summary = "之前的摘要"
        hook = ContextCompressorHook(strategy="truncate", max_context_ratio=0.7)
        await hook.handle(ctx)
        assert ctx.session.summary == "之前的摘要"

    @pytest.mark.usefixtures("_mock_litellm")
    async def test_summarize_falls_back_to_truncate(self):
        """summarize 未实现, 应 fallback 到 truncate 且不崩溃."""
        msgs = make_messages(15, content_len=45)
        ctx = make_ctx(msgs)
        hook = ContextCompressorHook(strategy="summarize", max_context_ratio=0.7, preserve_recent=3)
        result = await hook.handle(ctx)
        assert result.action == "continue"
        assert len(ctx.messages) < 30
        # stats 标记为 truncate(因为 summarize 未实现)
        assert ctx.metadata["token_stats"]["strategy_used"] == "truncate"


# endregion


# region model fallback
class TestModelFallback:
    """模型信息获取失败时的降级处理."""

    async def test_unknown_model_uses_fallback(self):
        with patch("acabot.hook.context_compress.token_counter", side_effect=mock_token_counter), \
             patch("acabot.hook.context_compress.get_model_info", side_effect=Exception("unknown model")):
            msgs = make_messages(3, content_len=5)
            ctx = make_ctx(msgs, model="unknown-model-xyz")
            hook = ContextCompressorHook(max_context_ratio=0.7)
            result = await hook.handle(ctx)
            assert result.action == "continue"


# endregion
