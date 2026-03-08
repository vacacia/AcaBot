"""SessionBridge + Pipeline 持久化 + BotContext 后台发送 测试."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from acabot.bridge import SessionBridge, _extract_content
from acabot.session.base import Session
from acabot.store.null import NullMessageStore
from acabot.store.base import StoredMessage
from acabot.types import (
    Action, ActionType, EventSource, StandardEvent, MsgSegment,
)

# region 构造action
def _text_action(text: str = "hello") -> Action:
    """构造 SEND_TEXT action."""
    return Action(
        action_type=ActionType.SEND_TEXT,
        target=EventSource(platform="qq", message_type="private", user_id="1", group_id=None),
        payload={"text": text},
    )


def _segments_action() -> Action:
    """构造 SEND_SEGMENTS action(含图片)."""
    return Action(
        action_type=ActionType.SEND_SEGMENTS,
        target=EventSource(platform="qq", message_type="group", user_id="1", group_id="100"),
        payload={"segments": [
            {"type": "text", "data": {"text": "看这张图 "}},
            {"type": "image", "data": {"url": "https://example.com/pic.jpg"}},
        ]},
    )


def _typing_action() -> Action:
    """构造 TYPING action(不应被记录)."""
    return Action(
        action_type=ActionType.TYPING,
        target=EventSource(platform="qq", message_type="private", user_id="1", group_id=None),
    )


def _make_event(text: str = "hi", user_id: str = "123") -> StandardEvent:
    """构造测试用 StandardEvent."""
    return StandardEvent(
        event_id="evt_1", event_type="message", platform="qq", timestamp=1700000000,
        source=EventSource(platform="qq", message_type="private", user_id=user_id, group_id=None),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg_1", sender_nickname="Alice", sender_role=None,
    )


# region _extract_content
class TestExtractContent:
    """_extract_content: 从 Action 提取可读文本."""

    def test_text_action(self):
        assert _extract_content(_text_action("hi")) == "hi"

    def test_segments_with_image(self):
        assert _extract_content(_segments_action()) == "看这张图 [图片]"

    def test_unknown_action_type(self):
        assert _extract_content(_typing_action()) == ""


# region SessionBridge
class TestSessionBridge:
    """SessionBridge: 统一写入入口, 管 session + store."""

    def _make_bridge(self) -> tuple:
        """构造 bridge + 依赖 mock."""
        gw = AsyncMock()
        gw.send = AsyncMock(return_value={"message_id": 42})
        session = Session(session_key="qq:group:123")
        store = AsyncMock(spec=NullMessageStore)
        bridge = SessionBridge(
            gateway=gw, session=session, store=store,
            session_key="qq:group:123",
        )
        return bridge, gw, session, store

    # region record_incoming
    async def test_record_incoming_writes_session_and_store(self):
        """record_incoming: 用户消息写入 session + store."""
        bridge, gw, session, store = self._make_bridge()
        await bridge.record_incoming(_make_event("hello"))

        assert len(session.messages) == 1
        assert session.messages[0] == {"role": "user", "content": "hello"}
        store.save.assert_called_once()
        saved: StoredMessage = store.save.call_args[0][0]
        assert saved.role == "user"
        assert saved.content == "hello"
        assert saved.sender_id == "123"
        assert saved.sender_name == "Alice"

    async def test_record_incoming_store_error_does_not_propagate(self):
        """record_incoming: store 异常不抛出, session 仍然追加."""
        sender, gw, session, store = self._make_bridge()
        store.save = AsyncMock(side_effect=RuntimeError("db down"))
        await sender.record_incoming(_make_event("hello"))

        assert len(session.messages) == 1  # session 已追加

    # region send
    async def test_send_success_records_session_and_store(self):
        """发送成功: session + store 都记录."""
        bridge, gw, session, store = self._make_bridge()
        result = await bridge.send(_text_action("hello"))

        assert result == {"message_id": 42}
        assert len(session.messages) == 1
        assert session.messages[0] == {"role": "assistant", "content": "hello"}
        store.save.assert_called_once()
        saved: StoredMessage = store.save.call_args[0][0]
        assert saved.session_key == "qq:group:123"
        assert saved.role == "assistant"
        assert saved.content == "hello"
        assert saved.message_id == "42"

    async def test_send_with_session_content(self):
        """session_content: session 存原始, store 存实际."""
        bridge, gw, session, store = self._make_bridge()
        await bridge.send(_text_action("HELLO!"), session_content="hello!")

        # session 存的是 session_content(LLM 原始回复)
        assert session.messages[0]["content"] == "hello!"
        # store 存的是 action 提取的内容(实际发送)
        saved: StoredMessage = store.save.call_args[0][0]
        assert saved.content == "HELLO!"

    async def test_send_failure_no_record(self):
        """发送失败(gateway 返回 None): 不记录."""
        bridge, gw, session, store = self._make_bridge()
        gw.send = AsyncMock(return_value=None)
        result = await bridge.send(_text_action("hello"))

        assert result is None
        assert len(session.messages) == 0
        store.save.assert_not_called()

    async def test_typing_not_recorded(self):
        """TYPING 动作: gateway.send 被调用, 但不记录."""
        bridge, gw, session, store = self._make_bridge()
        result = await bridge.send(_typing_action())

        assert result is not None
        assert len(session.messages) == 0
        store.save.assert_not_called()

    async def test_store_error_does_not_propagate(self):
        """store.save 异常: 不抛出, session 仍然追加."""
        bridge, gw, session, store = self._make_bridge()
        store.save = AsyncMock(side_effect=RuntimeError("db down"))
        result = await bridge.send(_text_action("hello"))

        assert result == {"message_id": 42}
        assert len(session.messages) == 1

    async def test_segments_content_extraction(self):
        """SEND_SEGMENTS: 提取内容含占位符."""
        bridge, gw, session, store = self._make_bridge()
        await bridge.send(_segments_action())

        assert session.messages[0]["content"] == "看这张图 [图片]"


# region Pipeline 持久化集成
class TestPipelinePersistence:
    """Pipeline + store 集成: 用户消息和 bot 回复都持久化."""

    @pytest.fixture
    def deps(self):
        """构造 Pipeline 依赖."""
        from acabot.pipeline import Pipeline
        from acabot.session.memory import InMemorySessionManager
        from acabot.agent.response import AgentResponse

        gw = AsyncMock()
        gw.send = AsyncMock(return_value={"message_id": 99})
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(text="Reply!"))
        store = AsyncMock(spec=NullMessageStore)
        p = Pipeline(
            gateway=gw, agent=agent,
            session_mgr=InMemorySessionManager(),
            system_prompt="Bot.",
            store=store,
        )
        return p, gw, store

    async def test_user_and_bot_messages_saved(self, deps):
        """完整流程: 用户消息 + bot 回复都调用 store.save."""
        p, gw, store = deps
        source = EventSource(
            platform="qq", message_type="private", user_id="123", group_id=None,
        )
        event = StandardEvent(
            event_id="e1", event_type="message", platform="qq", timestamp=1700000000,
            source=source,
            segments=[MsgSegment(type="text", data={"text": "hi"})],
            raw_message_id="msg_1", sender_nickname="Alice", sender_role=None,
        )

        await p.process(event)

        # store.save 被调用 2 次: user + assistant
        assert store.save.call_count == 2

        # 第一次: 用户消息
        user_saved: StoredMessage = store.save.call_args_list[0][0][0]
        assert user_saved.role == "user"
        assert user_saved.content == "hi"
        assert user_saved.sender_id == "123"
        assert user_saved.sender_name == "Alice"
        assert user_saved.message_id == "msg_1"

        # 第二次: bot 回复
        bot_saved: StoredMessage = store.save.call_args_list[1][0][0]
        assert bot_saved.role == "assistant"
        assert bot_saved.content == "Reply!"
        assert bot_saved.message_id == "99"

    async def test_send_failure_bot_not_saved(self, deps):
        """gateway.send 失败: bot 回复不入 store."""
        p, gw, store = deps
        gw.send = AsyncMock(return_value=None)
        source = EventSource(
            platform="qq", message_type="private", user_id="123", group_id=None,
        )
        event = StandardEvent(
            event_id="e1", event_type="message", platform="qq", timestamp=1700000000,
            source=source,
            segments=[MsgSegment(type="text", data={"text": "hi"})],
            raw_message_id="msg_1", sender_nickname="Alice", sender_role=None,
        )

        await p.process(event)

        # 只有用户消息入 store, bot 回复因发送失败不入
        assert store.save.call_count == 1
        saved: StoredMessage = store.save.call_args_list[0][0][0]
        assert saved.role == "user"

    async def test_session_stores_original_response(self, deps):
        """LLM 路径: session 存原始回复, store 存实际发送(hook 可能修改)."""
        from acabot.pipeline import Pipeline
        from acabot.session.memory import InMemorySessionManager
        from acabot.agent.response import AgentResponse
        from acabot.hook import Hook, HookRegistry
        from acabot.types import HookPoint, HookResult, HookContext

        # post_llm hook 把文本转大写
        class Upper(Hook):
            name = "upper"
            priority = 10
            enabled = True
            async def handle(self, ctx):
                for a in ctx.actions:
                    if "text" in a.payload:
                        a.payload["text"] = a.payload["text"].upper()
                return HookResult()

        gw = AsyncMock()
        gw.send = AsyncMock(return_value={"message_id": 99})
        agent = AsyncMock()
        agent.run = AsyncMock(return_value=AgentResponse(text="Hello World"))
        store = AsyncMock(spec=NullMessageStore)
        hooks = HookRegistry()
        hooks.register(HookPoint.POST_LLM, Upper())

        p = Pipeline(
            gateway=gw, agent=agent,
            session_mgr=InMemorySessionManager(),
            system_prompt="Bot.", store=store, hooks=hooks,
        )

        source = EventSource(
            platform="qq", message_type="private", user_id="1", group_id=None,
        )
        event = StandardEvent(
            event_id="e1", event_type="message", platform="qq", timestamp=0,
            source=source,
            segments=[MsgSegment(type="text", data={"text": "hi"})],
            raw_message_id="msg_1", sender_nickname="T", sender_role=None,
        )

        await p.process(event)

        # session 存原始(Hello World), store 存实际(HELLO WORLD)
        session = await p.session_mgr.get(event.session_key)
        assistant_msgs = [m for m in session.messages if m["role"] == "assistant"]
        assert assistant_msgs[0]["content"] == "Hello World"

        bot_saved: StoredMessage = store.save.call_args_list[1][0][0]
        assert bot_saved.content == "HELLO WORLD"


# region BotContext 后台发送
class TestBotContextBackgroundSend:
    """BotContext: session_key 必传, 发送自动记录."""

    @pytest.fixture
    def bot_ctx(self):
        from acabot.plugin.context import BotContext
        from acabot.session.memory import InMemorySessionManager
        from acabot.config import Config

        gw = AsyncMock()
        gw.send = AsyncMock(return_value={"message_id": 77})
        store = AsyncMock(spec=NullMessageStore)
        ctx = BotContext(
            gateway=gw,
            session_mgr=InMemorySessionManager(),
            agent=AsyncMock(),
            config=Config({}),
            store=store,
        )
        return ctx, gw, store

    async def test_send_text_with_session_key(self, bot_ctx):
        """发送 + 自动记录到 session 和 store."""
        ctx, gw, store = bot_ctx
        target = EventSource(
            platform="qq", message_type="group", user_id="1", group_id="100",
        )
        result = await ctx.send_text(target, "任务完成!", "qq:group:100")

        assert result == {"message_id": 77}
        store.save.assert_called_once()
        saved: StoredMessage = store.save.call_args[0][0]
        assert saved.content == "任务完成!"
        assert saved.session_key == "qq:group:100"

        # session 也被追加了
        session = await ctx.session_mgr.get("qq:group:100")
        assert session is not None
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "任务完成!"

    async def test_send_text_failure_no_record(self, bot_ctx):
        """发送失败: 不记录."""
        ctx, gw, store = bot_ctx
        gw.send = AsyncMock(return_value=None)
        target = EventSource(
            platform="qq", message_type="private", user_id="1", group_id=None,
        )
        result = await ctx.send_text(target, "fail", "qq:user:1")

        assert result is None
        store.save.assert_not_called()
