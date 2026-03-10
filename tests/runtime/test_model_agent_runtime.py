"""ModelAgentRuntime 测试.

覆盖两条主线:
- BaseAgent -> AgentRuntimeResult 的转换是否正确
- ToolRuntimeResolver 是否真的把 `tools + tool_executor` 接到底层 agent
"""

from dataclasses import dataclass, field
from typing import Any

from acabot.agent import (
    AgentResponse,
    Attachment,
    ToolCallRecord,
    ToolDef,
    ToolSpec,
)
from acabot.runtime import (
    AgentProfile,
    InMemoryToolAudit,
    ModelAgentRuntime,
    PlannedAction,
    RouteDecision,
    RunContext,
    RunRecord,
    StaticPromptLoader,
    ThreadState,
    ToolBroker,
    ToolPolicyDecision,
    ToolResult,
    ToolRuntime,
)
from acabot.types import Action, ActionType, EventSource, MsgSegment, StandardEvent


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


@dataclass
class ToolCallingAgent:
    """会主动调用 tool_executor 的 fake agent.

    Attributes:
        response_text (str): 最终返回给用户的文本.
        fail_after_tool (bool): tool 调用后是否返回失败.
        calls (list[dict[str, Any]]): 调用记录.
    """

    response_text: str = ""
    fail_after_tool: bool = False
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
        """执行一次带 tool 的 fake run.

        Args:
            system_prompt: 本次调用使用的 system prompt.
            messages: 上下文消息列表.
            model: 模型名覆盖.
            tools: 当前 run 暴露给模型的 tools.
            tool_executor: 当前 run 的 tool executor.

        Returns:
            一份构造好的 AgentResponse.
        """

        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )

        if tool_executor is not None:
            await tool_executor("announce", {"name": "Acacia"})

        if self.fail_after_tool:
            return AgentResponse(
                error="tool flow failed",
                model_used=model or "",
                tool_calls_made=[
                    ToolCallRecord(
                        name="announce",
                        arguments={"name": "Acacia"},
                        result={"status": "failed"},
                    )
                ],
            )

        return AgentResponse(
            text=self.response_text,
            model_used=model or "",
            tool_calls_made=[
                ToolCallRecord(
                    name="announce",
                    arguments={"name": "Acacia"},
                    result={"status": "ok"},
                )
            ],
        )


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


async def test_model_agent_runtime_merges_tool_user_actions_artifacts_and_audit() -> None:
    audit = InMemoryToolAudit()
    broker = ToolBroker(audit=audit)

    async def announce(arguments: dict[str, Any], tool_ctx) -> Any:
        return ToolResult(
            llm_content=f'{{"announced": "{arguments["name"]}"}}',
            user_actions=[
                PlannedAction(
                    action_id="action:tool:announce",
                    action=Action(
                        action_type=ActionType.SEND_TEXT,
                        target=_context().event.source,
                        payload={"text": f'已处理 {arguments["name"]}'},
                    ),
                    thread_content=f'已处理 {arguments["name"]}',
                    commit_when="success",
                    metadata={"origin": "tool_broker"},
                )
            ],
            artifacts=[{"type": "notice", "name": arguments["name"]}],
            metadata={"kind": "announce"},
        )

    broker.register_tool(
        ToolSpec(
            name="announce",
            description="Announce a user",
            parameters={"type": "object", "properties": {}},
        ),
        announce,
    )
    runtime = ModelAgentRuntime(
        agent=ToolCallingAgent(response_text="final reply"),
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        tool_runtime_resolver=broker.build_tool_runtime,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["announce"]

    result = await runtime.execute(ctx)

    assert [item.action.payload["text"] for item in result.actions] == [
        "已处理 Acacia",
        "final reply",
    ]
    assert result.artifacts[0]["type"] == "notice"
    assert any(item.get("status") == "completed" for item in result.tool_calls)
    assert result.metadata["tool_audit_count"] == 1


async def test_model_agent_runtime_filters_tool_actions_for_failed_response() -> None:
    broker = ToolBroker()

    async def announce(arguments: dict[str, Any], tool_ctx) -> Any:
        return ToolResult(
            llm_content=f'{{"announced": "{arguments["name"]}"}}',
            user_actions=[
                PlannedAction(
                    action_id="action:tool:success",
                    action=Action(
                        action_type=ActionType.SEND_TEXT,
                        target=_context().event.source,
                        payload={"text": "success action"},
                    ),
                    thread_content="success action",
                    commit_when="success",
                ),
                PlannedAction(
                    action_id="action:tool:failure",
                    action=Action(
                        action_type=ActionType.SEND_TEXT,
                        target=_context().event.source,
                        payload={"text": "failure action"},
                    ),
                    thread_content="failure action",
                    commit_when="failure",
                ),
            ],
        )

    broker.register_tool(
        ToolSpec(
            name="announce",
            description="Announce a user",
            parameters={"type": "object", "properties": {}},
        ),
        announce,
    )
    runtime = ModelAgentRuntime(
        agent=ToolCallingAgent(fail_after_tool=True),
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        tool_runtime_resolver=broker.build_tool_runtime,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["announce"]

    result = await runtime.execute(ctx)

    assert result.status == "failed"
    assert [item.action.payload["text"] for item in result.actions] == ["failure action"]


async def test_model_agent_runtime_builds_waiting_approval_result() -> None:
    class ApprovalPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="needs admin approval",
                metadata={"risk_level": "dangerous"},
            )

    audit = InMemoryToolAudit()
    broker = ToolBroker(policy=ApprovalPolicy(), audit=audit)

    async def announce(arguments: dict[str, Any], tool_ctx) -> Any:
        _ = arguments, tool_ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="announce",
            description="Announce a user",
            parameters={"type": "object", "properties": {}},
        ),
        announce,
    )
    runtime = ModelAgentRuntime(
        agent=ToolCallingAgent(response_text="should not reach"),
        prompt_loader=StaticPromptLoader({"prompt/default": "You are Aca."}),
        tool_runtime_resolver=broker.build_tool_runtime,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["announce"]

    result = await runtime.execute(ctx)

    assert result.status == "waiting_approval"
    assert result.pending_approval is not None
    assert result.pending_approval.tool_name == "announce"
    assert [item.metadata["origin"] for item in result.actions] == ["approval_prompt"]
    assert any(item.get("status") == "waiting_approval" for item in result.tool_calls)
    assert result.metadata["tool_audit_count"] == 1
