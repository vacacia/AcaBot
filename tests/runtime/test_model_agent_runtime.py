"""ModelAgentRuntime 测试.

覆盖两条主线:
- BaseAgent -> AgentRuntimeResult 的转换是否正确
- ToolRuntimeResolver 是否真的把 `tools + tool_executor` 接到底层 agent
"""

from dataclasses import dataclass, field
from typing import Any

from acabot.agent import AgentResponse, Attachment, ToolCallRecord, ToolDef, ToolSpec
from acabot.runtime import (
    AgentProfile,
    ModelAgentRuntime,
    RouteDecision,
    RunContext,
    RunRecord,
    StaticPromptLoader,
    ThreadState,
    ToolBroker,
    ToolRuntime,
)
from acabot.types import EventSource, MsgSegment, StandardEvent


@dataclass
class FakeAgent:
    """用于 ModelAgentRuntime 测试的 fake agent.

    Attributes:
        response (AgentResponse): 预设返回值.
        calls (list[dict[str, Any]]): 调用记录.
    """

    response: AgentResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        tools=None,
        tool_executor=None,
    ) -> AgentResponse:
        """记录调用并返回预设响应.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 上下文消息列表.
            model: 模型名覆盖.
            tools: 当前 run 暴露给模型的 tools.
            tool_executor: 当前 run 的 tool executor.

        Returns:
            预设的 AgentResponse.
        """

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "tools": tools,
                "tool_executor": tool_executor,
            }
        )
        return self.response


def _context() -> RunContext:
    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )
    return RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id=event.event_id,
            status="running",
            started_at=event.timestamp,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        profile=AgentProfile(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            default_model="test-model",
        ),
        messages=[{"role": "user", "content": "[acacia/10001] hello"}],
    )


async def test_model_agent_runtime_builds_completed_result() -> None:
    agent = FakeAgent(
        AgentResponse(
            text="hello back",
            attachments=[
                Attachment(
                    type="image",
                    url="https://example.com/image.jpg",
                    metadata={"width": 800},
                )
            ],
            usage={"total_tokens": 12},
            tool_calls_made=[
                ToolCallRecord(
                    name="get_time",
                    arguments={},
                    result={"time": "2026-03-03 12:00:00"},
                )
            ],
            model_used="test-model",
        )
    )
    runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
    )
    ctx = _context()

    result = await runtime.execute(ctx)

    assert ctx.system_prompt == "You are Aca."
    assert agent.calls[0]["model"] == "test-model"
    assert result.status == "completed"
    assert result.actions[0].action.payload["text"] == "hello back"
    assert result.artifacts[0]["type"] == "image"
    assert result.tool_calls[0]["name"] == "get_time"
    assert result.usage["total_tokens"] == 12


async def test_model_agent_runtime_builds_failed_result() -> None:
    agent = FakeAgent(AgentResponse(error="boom"))
    runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
    )
    ctx = _context()

    result = await runtime.execute(ctx)

    assert result.status == "failed"
    assert result.error == "boom"
    assert result.actions == []


async def test_model_agent_runtime_passes_tools_from_resolver() -> None:
    agent = FakeAgent(AgentResponse(text="ok"))
    tool_spec = ToolSpec(
        name="get_time",
        description="Get current time",
        parameters={"type": "object", "properties": {}},
    )

    async def resolver(ctx: RunContext) -> ToolRuntime:
        return ToolRuntime(
            tools=[tool_spec],
            tool_executor=lambda tool_name, arguments: None,
            metadata={"source": "resolver"},
        )

    runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        tool_runtime_resolver=resolver,
    )
    ctx = _context()

    result = await runtime.execute(ctx)

    assert agent.calls[0]["tools"][0].name == "get_time"
    assert agent.calls[0]["tool_executor"] is not None
    assert result.metadata["source"] == "resolver"
    assert result.metadata["tool_count"] == 1


async def test_model_agent_runtime_can_use_tool_broker() -> None:
    agent = FakeAgent(AgentResponse(text="ok"))
    broker = ToolBroker()

    async def get_time(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"time": arguments.get("timezone", "UTC")}

    broker.register_legacy_tool(
        ToolDef(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
            handler=get_time,
        )
    )

    runtime = ModelAgentRuntime(
        agent=agent,
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        tool_runtime_resolver=broker.build_tool_runtime,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["get_time"]

    result = await runtime.execute(ctx)
    execution = await agent.calls[0]["tool_executor"](
        "get_time",
        {"timezone": "Asia/Shanghai"},
    )

    assert agent.calls[0]["tools"][0].name == "get_time"
    assert execution.content == '{"time": "Asia/Shanghai"}'
    assert result.metadata["source"] == "tool_broker"
    assert result.metadata["tool_count"] == 1
