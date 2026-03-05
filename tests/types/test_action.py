# Action: bot 执行动作的内部表示, 由插件/hook 构造或 LLM tool call 间接触发
# 重点测试: 默认值约定(payload 默认空 dict, reply_to 默认 None)

from acabot.types import Action, ActionType, EventSource


def test_action_creation():
    target = EventSource(platform="qq", message_type="group", user_id="1", group_id="2")
    action = Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "hi"})
    assert action.payload["text"] == "hi"
    assert action.reply_to is None


def test_action_with_reply():
    target = EventSource(platform="qq", message_type="private", user_id="1", group_id=None)
    action = Action(action_type=ActionType.SEND_TEXT, target=target, payload={"text": "ok"}, reply_to="msg_99")
    assert action.reply_to == "msg_99"


def test_action_type_enum():
    assert ActionType.SEND_TEXT.value == "send_text"
    assert ActionType.RECALL.value == "recall"
    assert ActionType.GROUP_BAN.value == "group_ban"


def test_action_default_payload():
    target = EventSource(platform="qq", message_type="group", user_id="1", group_id="2")
    action = Action(action_type=ActionType.TYPING, target=target)
    assert action.payload == {}
    assert action.reply_to is None
