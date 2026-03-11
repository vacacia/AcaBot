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
        subject_user_id="555",
        target_message_id="msg_9",
    )
    assert event.content_preview == "[notice:recall target=msg_9 user=555]"
    assert event.working_memory_text == "[123] [notice:recall target=msg_9 user=555]"


def test_membership_notice_preview_includes_subject_and_subtype():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_member_join_1",
        event_type="member_join",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        notice_type="group_increase",
        notice_subtype="approve",
    )
    assert event.content_preview == "[notice:member_join user=999 sub_type=approve]"


def test_notice_preview_supports_admin_change_and_file_upload():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    admin_event = StandardEvent(
        event_id="evt_admin_change_1",
        event_type="admin_change",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        notice_type="group_admin",
        notice_subtype="set",
    )
    upload_event = StandardEvent(
        event_id="evt_file_upload_1",
        event_type="file_upload",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        notice_type="group_upload",
        metadata={"file_name": "guide.pdf"},
    )
    assert admin_event.content_preview == "[notice:admin_change user=999 sub_type=set]"
    assert upload_event.content_preview == "[notice:file_upload user=999 file=guide.pdf]"


def test_notice_preview_supports_friend_mute_honor_title_and_lucky_king():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    friend_event = StandardEvent(
        event_id="evt_friend_added_1",
        event_type="friend_added",
        platform="qq",
        timestamp=1700000000,
        source=EventSource(platform="qq", message_type="private", user_id="999", group_id=None),
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        targets_self=True,
    )
    mute_event = StandardEvent(
        event_id="evt_mute_1",
        event_type="mute_change",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        notice_subtype="ban",
        metadata={"duration": 60},
    )
    honor_event = StandardEvent(
        event_id="evt_honor_1",
        event_type="honor_change",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        notice_subtype="talkative",
    )
    title_event = StandardEvent(
        event_id="evt_title_1",
        event_type="title_change",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        metadata={"title": "年度答疑官"},
    )
    lucky_event = StandardEvent(
        event_id="evt_lucky_1",
        event_type="lucky_king",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[],
        raw_message_id="",
        sender_nickname="",
        sender_role=None,
        subject_user_id="999",
        metadata={"sender_user_id": "888"},
    )
    assert friend_event.content_preview == "[notice:friend_added user=999]"
    assert mute_event.content_preview == "[notice:mute_change user=999 sub_type=ban duration=60]"
    assert honor_event.content_preview == "[notice:honor_change user=999 sub_type=talkative]"
    assert title_event.content_preview == "[notice:title_change user=999 title=年度答疑官]"
    assert lucky_event.content_preview == "[notice:lucky_king user=999 sender=888]"


def test_to_payload_json_returns_canonical_shape():
    source = EventSource(platform="qq", message_type="group", user_id="123", group_id="456")
    event = StandardEvent(
        event_id="evt_5",
        event_type="message",
        platform="qq",
        timestamp=1700000000,
        source=source,
        segments=[MsgSegment(type="text", data={"text": "你好"})],
        raw_message_id="msg_5",
        sender_nickname="Alice",
        sender_role="member",
        message_subtype="normal",
        reply_reference=ReplyReference(message_id="msg_1", sender_user_id="321"),
        mentioned_user_ids=["111"],
        mentioned_everyone=False,
        targets_self=True,
        attachments=[EventAttachment(type="image", source="https://example.com/a.jpg")],
    )
    payload = event.to_payload_json()
    assert payload["source"]["group_id"] == "456"
    assert payload["reply_reference"]["message_id"] == "msg_1"
    assert payload["mentioned_user_ids"] == ["111"]
    assert payload["targets_self"] is True
    assert payload["attachments"][0]["type"] == "image"
