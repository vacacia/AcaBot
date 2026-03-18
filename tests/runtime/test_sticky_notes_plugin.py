from pathlib import Path

from acabot.config import Config
from acabot.runtime import (
    AgentProfile,
    InMemoryMemoryStore,
    RuntimePluginManager,
    StickyNotesPlugin,
    StickyNotesService,
    ToolBroker,
    build_runtime_components,
)
from acabot.runtime.tool_broker import ToolExecutionContext
from acabot.types import EventSource, MsgSegment, StandardEvent

from .test_bootstrap import FakeAgent, FakeAgentResponse
from .test_outbox import FakeGateway


def _profile(enabled_tools: list[str]) -> AgentProfile:
    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_tools=enabled_tools,
    )


def _execution_ctx(enabled_tools: list[str]) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:sticky",
        thread_id="qq:group:20002",
        actor_id="qq:user:10001",
        agent_id="aca",
        target=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        profile=_profile(enabled_tools),
        metadata={
            "channel_scope": "qq:group:20002",
            "event_id": "evt:sticky",
            "event_timestamp": 123,
            "platform": "qq",
            "message_type": "group",
        },
    )


def _group_event(text: str) -> StandardEvent:
    return StandardEvent(
        event_id="evt-group",
        event_type="message",
        platform="qq",
        timestamp=456,
        source=EventSource(
            platform="qq",
            message_type="group",
            user_id="10001",
            group_id="20002",
        ),
        segments=[MsgSegment(type="text", data={"text": text})],
        raw_message_id="msg-group-1",
        sender_nickname="acacia",
        sender_role="member",
    )


async def test_sticky_notes_plugin_can_put_get_list_and_delete() -> None:
    store = InMemoryMemoryStore()
    gateway = FakeGateway()
    broker = ToolBroker()
    manager = RuntimePluginManager(
        config=Config({"plugins": {"sticky_notes": {"default_scope": "relationship"}}}),
        gateway=gateway,
        tool_broker=broker,
        sticky_notes=StickyNotesService(store=store),
        plugins=[StickyNotesPlugin()],
    )
    await manager.ensure_started()

    ctx = _execution_ctx(
        [
            "sticky_note_put",
            "sticky_note_get",
            "sticky_note_list",
            "sticky_note_delete",
        ]
    )
    created = await broker.execute(
        tool_name="sticky_note_put",
        arguments={
            "key": "internship_rule",
            "content": "十个月的只需要实习成果鉴定, 不用实习证明.",
            "scope": "channel",
            "tags": ["faq", "internship"],
        },
        ctx=ctx,
    )
    got = await broker.execute(
        tool_name="sticky_note_get",
        arguments={"key": "internship_rule", "scope": "channel"},
        ctx=ctx,
    )
    listed = await broker.execute(
        tool_name="sticky_note_list",
        arguments={"scope": "channel"},
        ctx=ctx,
    )
    deleted = await broker.execute(
        tool_name="sticky_note_delete",
        arguments={"key": "internship_rule", "scope": "channel"},
        ctx=ctx,
    )
    missing = await broker.execute(
        tool_name="sticky_note_get",
        arguments={"key": "internship_rule", "scope": "channel"},
        ctx=ctx,
    )

    assert "Sticky note saved" in str(created.llm_content)
    assert created.raw["metadata"]["note_key"] == "internship_rule"
    assert "不用实习证明" in str(got.llm_content)
    assert listed.raw["items"][0]["metadata"]["note_key"] == "internship_rule"
    assert deleted.raw["ok"] is True
    assert missing.raw["ok"] is False


async def test_sticky_notes_plugin_injects_readonly_notes_into_next_run(tmp_path: Path) -> None:
    config = Config(
        {
            "agent": {
                "default_model": "test-model",
                "system_prompt": "You are Aca.",
            },
            "runtime": {
                "default_agent_id": "aca",
                "default_prompt_ref": "prompt/default",
                "runtime_root": str(tmp_path / ".acabot-runtime"),
                "plugins": [
                    "acabot.runtime.plugins.sticky_notes:StickyNotesPlugin",
                ],
            },
        }
    )
    gateway = FakeGateway()
    agent = FakeAgent(FakeAgentResponse(text="收到"))
    components = build_runtime_components(
        config,
        gateway=gateway,
        agent=agent,
    )
    await components.plugin_manager.ensure_started()

    put_ctx = _execution_ctx(["sticky_note_put"])
    forbidden = await components.tool_broker.execute(
        tool_name="sticky_note_put",
        arguments={
            "key": "internship_rule",
            "content": "十个月的只需要实习成果鉴定, 不用实习证明.",
            "scope": "channel",
            "edit_mode": "readonly",
        },
        ctx=put_ctx,
    )
    assert forbidden.raw["ok"] is False
    assert forbidden.raw["reason"] == "readonly_forbidden"
    components.sticky_notes_source.create_note(
        scope="channel",
        scope_key="qq:group:20002",
        key="internship_rule",
        readonly_content="十个月的只需要实习成果鉴定, 不用实习证明.",
    )

    components.app.install()
    await gateway.handler(_group_event("十个月需要交什么材料"))

    messages = agent.calls[0]["messages"]
    assert any("十个月的只需要实习成果鉴定" in str(message["content"]) for message in messages)
    assert any(message["role"] == "system" for message in messages)
