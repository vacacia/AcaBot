"""message builtin tool 测试."""

from __future__ import annotations

import pytest

from acabot.runtime import ToolBroker
from acabot.runtime.builtin_tools.message import (
    BUILTIN_MESSAGE_TOOL_SOURCE,
    BuiltinMessageToolSurface,
)
from acabot.types import ActionType

from .test_model_agent_runtime import _context


def _register_message_tool() -> tuple[ToolBroker, dict[str, object]]:
    """注册 message tool 并返回 broker 与目录项."""

    broker = ToolBroker()
    surface = BuiltinMessageToolSurface()
    names = surface.register(broker)
    assert names == ["message"]
    registration = next(
        item for item in broker.list_registered_tools() if item["name"] == "message"
    )
    return broker, registration


def _message_tool_ctx():
    """构造 message tool 执行上下文."""

    ctx = _context()
    ctx.agent.enabled_tools = ["message"]
    return ctx


async def test_message_tool_schema_matches_locked_fields() -> None:
    """schema 只暴露锁定的 action 和字段."""

    _, registration = _register_message_tool()

    assert registration["source"] == BUILTIN_MESSAGE_TOOL_SOURCE
    assert registration["parameters"]["type"] == "object"
    assert registration["parameters"]["properties"]["action"]["enum"] == [
        "send",
        "react",
        "recall",
    ]
    assert registration["parameters"]["properties"]["action"]["default"] == "send"
    assert set(registration["parameters"]["properties"]) == {
        "action",
        "text",
        "images",
        "render",
        "reply_to",
        "at_user",
        "target",
        "message_id",
        "emoji",
    }


async def test_message_tool_returns_user_actions_only() -> None:
    """send 只通过 ToolResult.user_actions 返回高层消息意图."""

    broker, _ = _register_message_tool()
    ctx = _message_tool_ctx()

    result = await broker.execute(
        tool_name="message",
        arguments={
            "text": "hello",
            "images": ["https://example.com/cat.png"],
            "render": "# hi",
            "reply_to": "msg-99",
            "at_user": "20002",
        },
        ctx=broker._build_execution_context(ctx),
    )

    assert result.llm_content == ""
    assert result.attachments == []
    assert result.artifacts == []
    assert len(result.user_actions) == 1
    plan = result.user_actions[0]
    assert plan.action.action_type == ActionType.SEND_MESSAGE_INTENT
    assert plan.action.reply_to == "msg-99"
    assert plan.action.payload == {
        "text": "hello",
        "images": ["https://example.com/cat.png"],
        "render": "# hi",
        "at_user": "20002",
        "target": "qq:user:10001",
    }
    assert plan.metadata["message_action"] == "send"
    assert plan.metadata["suppresses_default_reply"] is True
    assert plan.metadata["destination_conversation_id"] == "qq:user:10001"

    with pytest.raises(ValueError, match="canonical conversation_id"):
        await broker._tools["message"].handler(
            {"action": "send", "text": "hello", "target": "group:123"},
            broker._build_execution_context(ctx),
        )


async def test_message_react_requires_known_emoji() -> None:
    """react 只接受已知 emoji, 未知值直接失败."""

    broker, _ = _register_message_tool()
    ctx = _message_tool_ctx()
    tool_ctx = broker._build_execution_context(ctx)

    alias_result = await broker._tools["message"].handler(
        {
            "action": "react",
            "message_id": "msg-1",
            "emoji": "thumbs_up",
        },
        tool_ctx,
    )
    unicode_result = await broker._tools["message"].handler(
        {
            "action": "react",
            "message_id": "msg-2",
            "emoji": "👍",
        },
        tool_ctx,
    )

    assert alias_result.user_actions[0].action.action_type == ActionType.REACTION
    assert alias_result.user_actions[0].action.payload["message_id"] == "msg-1"
    assert alias_result.user_actions[0].action.payload["emoji_id"] == 76
    assert unicode_result.user_actions[0].action.payload["emoji_id"] == 76

    with pytest.raises(ValueError, match="unknown reaction emoji"):
        await broker._tools["message"].handler(
            {
                "action": "react",
                "message_id": "msg-3",
                "emoji": "not-real",
            },
            tool_ctx,
        )


async def test_message_recall_returns_low_level_action() -> None:
    """recall 直接映射到底层 RECALL action."""

    broker, _ = _register_message_tool()
    ctx = _message_tool_ctx()

    result = await broker.execute(
        tool_name="message",
        arguments={
            "action": "recall",
            "message_id": "msg-55",
        },
        ctx=broker._build_execution_context(ctx),
    )

    assert result.llm_content == ""
    assert len(result.user_actions) == 1
    assert result.user_actions[0].action.action_type == ActionType.RECALL
    assert result.user_actions[0].action.payload == {"message_id": "msg-55"}


async def test_message_tool_schema_includes_send_guidance() -> None:
    """schema 文案必须明确写出默认回复抑制、组合发送和本地图片相对路径规则."""

    _, registration = _register_message_tool()

    description = str(registration["description"])
    images_description = str(registration["parameters"]["properties"]["images"]["description"])
    assert "content-type send suppresses the default assistant text reply" in description
    assert "combine text, images, and render in one send call" in description
    assert "relative workspace paths" in images_description
    assert "never `/workspace/foo.png`" in images_description
