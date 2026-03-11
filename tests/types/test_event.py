# StandardEvent: 框架核心数据结构, 所有消息经 Gateway 翻译后统一为此格式
# 测试: session_key 拼接规则(私聊 vs 群聊), .text 从混合段中提取纯文字

from acabot.types import StandardEvent, EventSource, MsgSegment, EventAttachment, ReplyReference


def test_private_event():
    source = EventSource(platform="qq", message_type="private", user_id="123", group_id=None)
    seg = MsgSegment(type="text", data={"text": "hello"})
    event = StandardEvent(
        event_id="evt_1", event_type="message", platform="qq", timestamp=1700000000,
        source=source, segments=[seg], raw_message_id="msg_1",
        sender_nickname="Alice", sender_role=None,
    )
    assert event.is_private
    assert not event.is_group
    assert event.session_key == "qq:user:123"
    assert event.text == "hello"


def test_group_event():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_2", event_type="message", platform="qq", timestamp=0,
        source=source, segments=[], raw_message_id="msg_2",
        sender_nickname="Bob", sender_role="member",
    )
    assert event.is_group
    assert event.session_key == "qq:group:456"


def test_text_extraction_multi_segment():
    source = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
    event = StandardEvent(
        event_id="e", event_type="message", platform="qq", timestamp=0,
        source=source, raw_message_id="m", sender_nickname="X", sender_role=None,
        segments=[
            MsgSegment(type="at", data={"qq": "111"}),
            MsgSegment(type="text", data={"text": "hello "}),
            MsgSegment(type="text", data={"text": "world"}),
        ],
    )
    assert event.text == "hello world"


def test_notice_event_keeps_metadata_and_empty_text():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_poke_1",
        event_type="poke",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        operator_id="123",
        metadata={"target_id": "999"},
        raw_event={"notice_type": "notify", "sub_type": "poke"},
    )
    assert event.is_notice
    assert not event.is_message
    assert event.text == ""
    assert event.metadata["target_id"] == "999"


def test_message_preview_includes_reply_mentions_and_attachments():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_msg_3",
        event_type="message",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[MsgSegment(type="text", data={"text": "请看图"})],
        raw_message_id="msg_3",
        sender_nickname="Alice",
        sender_role="member",
        reply_to_message_id="msg_1",
        mentioned_user_ids=["111", "all"],
        attachments=[EventAttachment(type="image", source="https://example.com/cat.jpg")],
    )
    assert event.message_preview == "[reply:msg_1] [mentions:111,all] 请看图 [attachments:image]"


def test_working_memory_text_uses_unified_canonical_projection():
    source = EventSource(platform="qq", message_type="private", user_id="123", group_id=None)
    event = StandardEvent(
        event_id="evt_4",
        event_type="message",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[MsgSegment(type="text", data={"text": "你好"})],
        raw_message_id="msg_4",
        sender_nickname="Alice",
        sender_role=None,
        reply_reference=ReplyReference(message_id="msg_1", sender_user_id="321"),
    )
    assert event.reply_to_message_id == "msg_1"
    assert event.content_preview == "[reply:msg_1] 你好"
    assert event.working_memory_text == "[Alice/123] [reply:msg_1] 你好"


def test_notice_preview_is_canonical():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_recall_1",
        event_type="recall",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        target_message_id="msg_9",
    )
    assert event.content_preview == "[notice:recall target=msg_9]"
    assert event.working_memory_text == "[123] [notice:recall target=msg_9]"
