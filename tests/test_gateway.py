# NapCatGateway: OneBot v11 协议适配
# 测试两个方向:
#   translate: OneBot v11 JSON → StandardEvent (收消息)
#   build_send_payload: Action → OneBot API JSON (发消息)

import pytest
from acabot.gateway.napcat import NapCatGateway
from acabot.gateway import BaseGateway
from acabot.types import StandardEvent, Action, ActionType, EventSource


class TestNapCatTranslation:
    @pytest.fixture
    def gw(self):
        # __new__ 是 Python 的对象分配方法, 只分配内存、创建实例，完全跳过 __init__
        # 只测纯函数(translate/build_send_payload), 不需要 WS
        return NapCatGateway.__new__(NapCatGateway)

    # --- translate: 收消息方向 ---

    def test_is_base_gateway(self, gw):
        # 确认 NapCatGateway 实现了 BaseGateway 接口
        assert isinstance(gw, BaseGateway)

    def test_translate_private_message(self, gw):
        # 私聊消息: user_id 转 str, is_private=True, text 提取正确
        raw = {
            "post_type": "message", "message_type": "private", "sub_type": "friend",
            "time": 1700000000, "self_id": 111, "user_id": 222, "message_id": 333,
            "message": [{"type": "text", "data": {"text": "hello"}}],
            "raw_message": "hello",
            "sender": {"user_id": 222, "nickname": "Alice"},
        }
        event = gw.translate(raw)
        assert isinstance(event, StandardEvent)
        assert event.is_private
        assert event.source.user_id == "222"
        assert event.text == "hello"

    def test_translate_group_message(self, gw):
        # 群消息: group_id 转 str, 多段消息(at+text), sender_role 保留
        raw = {
            "post_type": "message", "message_type": "group", "sub_type": "normal",
            "time": 1700000000, "self_id": 111, "user_id": 222, "group_id": 444,
            "message_id": 333,
            "message": [
                {"type": "at", "data": {"qq": "111"}},
                {"type": "text", "data": {"text": " hey"}},
            ],
            "raw_message": "[CQ:at,qq=111] hey",
            "sender": {"user_id": 222, "nickname": "Bob", "role": "member"},
        }
        event = gw.translate(raw)
        assert event.is_group
        assert event.source.group_id == "444"
        assert len(event.segments) == 2
        assert event.sender_role == "member"

    def test_translate_message_extracts_reply_mentions_and_attachments(self, gw):
        raw = {
            "post_type": "message", "message_type": "group", "sub_type": "normal",
            "time": 1700000000, "self_id": 111, "user_id": 222, "group_id": 444,
            "message_id": 333,
            "message": [
                {"type": "reply", "data": {"id": "999"}},
                {"type": "at", "data": {"qq": "111"}},
                {"type": "text", "data": {"text": "请看图"}},
                {"type": "image", "data": {"file": "https://example.com/cat.jpg"}},
            ],
            "sender": {"user_id": 222, "nickname": "Bob", "role": "member"},
        }
        event = gw.translate(raw)
        assert event.reply_to_message_id == "999"
        assert event.reply_reference is not None
        assert event.reply_reference.message_id == "999"
        assert event.mentioned_user_ids == ["111"]
        assert len(event.attachments) == 1
        assert event.attachments[0].type == "image"
        assert event.attachments[0].source == "https://example.com/cat.jpg"

    def test_translate_ignores_non_message(self, gw):
        # 非消息事件(notice/request等)如果未识别到具体 notice, 返回 None
        assert gw.translate({"post_type": "notice"}) is None

    def test_translate_poke_notice(self, gw):
        raw = {
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "poke",
            "time": 1700000001,
            "user_id": 222,
            "group_id": 444,
            "target_id": 111,
        }
        event = gw.translate(raw)
        assert event is not None
        assert event.event_type == "poke"
        assert event.is_notice
        assert event.source.group_id == "444"
        assert event.operator_id == "222"
        assert event.subject_user_id == "111"
        assert event.notice_type == "notify"
        assert event.notice_subtype == "poke"
        assert event.metadata["target_id"] == "111"

    def test_translate_group_recall_notice(self, gw):
        raw = {
            "post_type": "notice",
            "notice_type": "group_recall",
            "time": 1700000002,
            "user_id": 222,
            "operator_id": 333,
            "group_id": 444,
            "message_id": 555,
        }
        event = gw.translate(raw)
        assert event is not None
        assert event.event_type == "recall"
        assert event.source.user_id == "333"
        assert event.subject_user_id == "222"
        assert event.notice_type == "group_recall"
        assert event.target_message_id == "555"
        assert event.metadata["recalled_user_id"] == "222"

    def test_translate_group_increase_notice(self, gw):
        raw = {
            "post_type": "notice",
            "notice_type": "group_increase",
            "sub_type": "approve",
            "time": 1700000003,
            "group_id": 444,
            "user_id": 222,
            "operator_id": 333,
        }
        event = gw.translate(raw)
        assert event is not None
        assert event.event_type == "member_join"
        assert event.source.group_id == "444"
        assert event.source.user_id == "222"
        assert event.operator_id == "333"
        assert event.subject_user_id == "222"
        assert event.notice_type == "group_increase"
        assert event.notice_subtype == "approve"
        assert event.metadata["sub_type"] == "approve"

    def test_translate_group_decrease_notice(self, gw):
        raw = {
            "post_type": "notice",
            "notice_type": "group_decrease",
            "sub_type": "kick",
            "time": 1700000004,
            "group_id": 444,
            "user_id": 222,
            "operator_id": 333,
        }
        event = gw.translate(raw)
        assert event is not None
        assert event.event_type == "member_leave"
        assert event.source.group_id == "444"
        assert event.source.user_id == "222"
        assert event.operator_id == "333"
        assert event.subject_user_id == "222"
        assert event.notice_type == "group_decrease"
        assert event.notice_subtype == "kick"
        assert event.metadata["notice_type"] == "group_decrease"

    # --- build_send_payload: 发消息方向 ---
    # NOTE: 验证能否把 Action 对象正确转换成 NapCat 格式的 JSON
    
    def test_build_send_private(self, gw):
        # 私聊发文字 → send_private_msg API
        target = EventSource(platform="qq", message_type="private", user_id="222", group_id=None)
        action = Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "hi"})
        payload = gw.build_send_payload(action)
        assert payload["action"] == "send_private_msg"
        assert payload["params"]["user_id"] == "222"
        assert payload["params"]["message"] == [{"type": "text", "data": {"text": "hi"}}]

    def test_build_send_group(self, gw):
        # 群聊发文字 → send_group_msg API
        target = EventSource(platform="qq", message_type="group", user_id="222", group_id="444")
        action = Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "hello"})
        payload = gw.build_send_payload(action)
        assert payload["action"] == "send_group_msg"
        assert payload["params"]["group_id"] == "444"

    def test_build_send_with_reply(self, gw):
        # 引用回复
        # NOTE: reply 段插在消息最前面
        target = EventSource(platform="qq", message_type="group", user_id="1", group_id="2")
        action = Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "ok"}, reply_to="msg_99")
        payload = gw.build_send_payload(action)
        assert payload["params"]["message"][0] == {"type": "reply", "data": {"id": "msg_99"}}

    def test_build_recall(self, gw):
        # 撤回消息 → delete_msg API
        target = EventSource(platform="qq", message_type="group", user_id="1", group_id="2")
        action = Action(action_type=ActionType.RECALL, target=target, payload={"message_id": "12345"})
        payload = gw.build_send_payload(action)
        assert payload["action"] == "delete_msg"
        assert payload["params"]["message_id"] == "12345"

    def test_build_group_ban(self, gw):
        # 群禁言 → set_group_ban API, 包含 duration
        target = EventSource(platform="qq", message_type="group", user_id="1", group_id="444")
        action = Action(action_type=ActionType.GROUP_BAN, target=target, payload={"user_id": "999", "duration": 120})
        payload = gw.build_send_payload(action)
        assert payload["action"] == "set_group_ban"
        assert payload["params"]["group_id"] == "444"
        assert payload["params"]["duration"] == 120

    def test_build_group_kick(self, gw):
        # 群踢人 → set_group_kick API
        target = EventSource(platform="qq", message_type="group", user_id="1", group_id="444")
        action = Action(action_type=ActionType.GROUP_KICK, target=target, payload={"user_id": "999"})
        payload = gw.build_send_payload(action)
        assert payload["action"] == "set_group_kick"
        assert payload["params"]["user_id"] == "999"
