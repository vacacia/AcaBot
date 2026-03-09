"""NotepadInjectHook 测试 — 便签注入逻辑."""

from __future__ import annotations

from acabot.kv import InMemoryKVStore
from acabot.types import HookContext, StandardEvent, EventSource, MsgSegment

from notepad.inject import NotepadInjectHook


def _make_ctx(
    user_id: str = "12345",
    group_id: str | None = None,
    messages: list[dict] | None = None,
) -> HookContext:
    """构造测试用 HookContext."""
    source = EventSource(
        platform="qq",
        message_type="group" if group_id else "private",
        user_id=user_id,
        group_id=group_id,
    )
    event = StandardEvent(
        event_id="evt_1",
        event_type="message",
        platform="qq",
        timestamp=1000,
        source=source,
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg_1",
        sender_nickname="tester",
        sender_role=None,
    )
    return HookContext(
        event=event,
        messages=list(messages) if messages else [],
    )


async def test_inject_user_note():
    """有用户便签时, 注入 system 消息到 messages 开头."""
    kv = InMemoryKVStore()
    await kv.set("notepad:user:qq:12345", "记得喝水")
    hook = NotepadInjectHook(kv=kv)

    ctx = _make_ctx(user_id="12345")
    result = await hook.handle(ctx)

    assert result.action == "continue"
    assert len(ctx.messages) == 1
    assert ctx.messages[0]["role"] == "system"
    assert "记得喝水" in ctx.messages[0]["content"]


async def test_no_note_no_injection():
    """无便签时, messages 保持不变."""
    kv = InMemoryKVStore()
    hook = NotepadInjectHook(kv=kv)

    existing = [{"role": "user", "content": "hi"}]
    ctx = _make_ctx(user_id="12345", messages=existing)
    await hook.handle(ctx)

    assert len(ctx.messages) == 1
    assert ctx.messages[0]["role"] == "user"


async def test_inject_both_user_and_group_notes():
    """群聊场景: 同时注入用户级和群级便签."""
    kv = InMemoryKVStore()
    await kv.set("notepad:user:qq:12345", "用户备忘")
    await kv.set("notepad:group:qq:67890", "群公告")
    hook = NotepadInjectHook(kv=kv)

    ctx = _make_ctx(user_id="12345", group_id="67890")
    await hook.handle(ctx)

    assert len(ctx.messages) == 1
    note_msg = ctx.messages[0]
    assert note_msg["role"] == "system"
    # 两条便签都应出现
    assert "用户备忘" in note_msg["content"]
    assert "群公告" in note_msg["content"]


async def test_inject_preserves_existing_messages():
    """注入便签时, 原有 messages 不丢失, 便签在开头."""
    kv = InMemoryKVStore()
    await kv.set("notepad:user:qq:12345", "便签内容")
    hook = NotepadInjectHook(kv=kv)

    existing = [{"role": "user", "content": "hello"}]
    ctx = _make_ctx(user_id="12345", messages=existing)
    await hook.handle(ctx)

    assert len(ctx.messages) == 2
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[1]["role"] == "user"


async def test_inject_group_note_only():
    """群聊场景: 只有群级便签, 无用户级便签."""
    kv = InMemoryKVStore()
    await kv.set("notepad:group:qq:67890", "群规")
    hook = NotepadInjectHook(kv=kv)

    ctx = _make_ctx(user_id="12345", group_id="67890")
    await hook.handle(ctx)

    assert len(ctx.messages) == 1
    assert "群规" in ctx.messages[0]["content"]


async def test_private_chat_ignores_group_note():
    """私聊场景: 即使 KV 中有群便签, 也不会注入(因为没有 group_id)."""
    kv = InMemoryKVStore()
    await kv.set("notepad:group:qq:67890", "不应出现")
    hook = NotepadInjectHook(kv=kv)

    ctx = _make_ctx(user_id="12345", group_id=None)
    await hook.handle(ctx)

    assert len(ctx.messages) == 0
