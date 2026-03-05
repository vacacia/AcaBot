# StandardEvent: 框架核心数据结构, 所有消息经 Gateway 翻译后统一为此格式
# 测试: session_key 拼接规则(私聊 vs 群聊), .text 从混合段中提取纯文字

from acabot.types import StandardEvent, EventSource, MsgSegment


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
