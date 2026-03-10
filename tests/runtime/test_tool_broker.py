"""ToolBroker 测试.

覆盖 3 条关键语义:
- profile.enabled_tools 会过滤可见工具
- ToolBroker 自己可以作为 tool_executor
- legacy ToolDef 迁入 ToolBroker 后, 返回值会被标准化
- policy 可以拒绝工具
- policy 也可以把工具打断到 waiting_approval
- audit 会记录完成和拒绝结果
"""

from dataclasses import dataclass
from typing import Any

import pytest

from acabot.agent import ToolDef, ToolExecutionResult, ToolSpec
from acabot.runtime import (
    AgentProfile,
    ApprovalRequired,
    InMemoryToolAudit,
    ToolBroker,
    ToolPolicyDecision,
    ToolResult,
    ToolRuntimeState,
)

from .test_model_agent_runtime import _context


@dataclass
class Marker:
    """用于验证 raw 返回值保真的简单对象.

    Attributes:
        value (str): 用于区分实例的字符串值.
    """

    value: str


def _profile(*, enabled_tools: list[str]) -> AgentProfile:
    """构造最小 AgentProfile.

    Args:
        enabled_tools: 当前 profile 允许的工具列表.

    Returns:
        一份最小 AgentProfile.
    """

    return AgentProfile(
        agent_id="aca",
        name="Aca",
        prompt_ref="prompt/default",
        default_model="test-model",
        enabled_tools=list(enabled_tools),
    )


async def test_tool_broker_filters_visible_tools_by_profile() -> None:
    broker = ToolBroker()

    async def get_time(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {"time": "12:00"}

    async def get_weather(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {"weather": "sunny"}

    broker.register_tool(
        ToolSpec(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
        ),
        get_time,
    )
    broker.register_tool(
        ToolSpec(
            name="get_weather",
            description="Get weather",
            parameters={"type": "object", "properties": {}},
        ),
        get_weather,
    )

    visible = broker.visible_tools(_profile(enabled_tools=["get_weather"]))

    assert [tool.name for tool in visible] == ["get_weather"]


async def test_tool_broker_build_tool_runtime_returns_executor() -> None:
    broker = ToolBroker()

    async def get_time(arguments: dict[str, Any], ctx) -> ToolResult:
        return ToolResult(
            llm_content=f'time:{arguments.get("timezone", "UTC")}',
            metadata={"run_id": ctx.run_id},
        )

    broker.register_tool(
        ToolSpec(
            name="get_time",
            description="Get current time",
            parameters={"type": "object", "properties": {}},
        ),
        get_time,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["get_time"]

    tool_runtime = broker.build_tool_runtime(ctx)
    execution = await tool_runtime.tool_executor("get_time", {"timezone": "Asia/Shanghai"})

    assert tool_runtime.tools[0].name == "get_time"
    assert isinstance(execution, ToolExecutionResult)
    assert execution.content == "time:Asia/Shanghai"
    assert execution.raw["run_id"] == "run:1"


async def test_tool_broker_normalizes_legacy_tool_def_result() -> None:
    broker = ToolBroker()

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        _ = arguments
        return {
            "nickname": "Acacia",
            "attachments": [
                {"type": "image", "url": "https://example.com/avatar.jpg"},
            ],
        }

    broker.register_legacy_tool(
        ToolDef(
            name="get_user_info",
            description="Get user info",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["get_user_info"]
    result = await broker.execute(
        tool_name="get_user_info",
        arguments={},
        ctx=broker._build_execution_context(ctx),
    )

    assert result.llm_content == '{"nickname": "Acacia"}'
    assert len(result.attachments) == 1
    assert result.attachments[0].type == "image"


async def test_tool_broker_returns_error_when_tool_not_enabled() -> None:
    broker = ToolBroker()

    async def handler(arguments: dict[str, Any], ctx) -> Marker:
        _ = arguments, ctx
        return Marker("should-not-run")

    broker.register_tool(
        ToolSpec(
            name="dangerous_tool",
            description="Dangerous tool",
            parameters={"type": "object", "properties": {}},
        ),
        handler,
    )
    ctx = _context()
    ctx.profile.enabled_tools = []

    result = await broker.execute(
        tool_name="dangerous_tool",
        arguments={"x": 1},
        ctx=broker._build_execution_context(ctx),
    )

    assert '"error": "Tool not enabled for profile: dangerous_tool"' in result.llm_content


async def test_tool_broker_policy_can_reject_tool() -> None:
    class DenyAllPolicy:
        async def allow(self, *, spec, arguments, ctx) -> ToolPolicyDecision:
            _ = spec, arguments, ctx
            return ToolPolicyDecision(
                allowed=False,
                reason="blocked by policy",
                metadata={"policy": "deny-all"},
            )

    audit = InMemoryToolAudit()
    broker = ToolBroker(policy=DenyAllPolicy(), audit=audit)

    async def handler(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        handler,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["restricted"]

    result = await broker.execute(
        tool_name="restricted",
        arguments={"x": 1},
        ctx=broker._build_execution_context(ctx),
    )

    assert '"error": "blocked by policy"' in result.llm_content
    record = next(iter(audit.records.values()))
    assert record.status == "rejected"
    assert record.metadata["policy"] == "deny-all"


async def test_tool_broker_policy_can_request_approval() -> None:
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

    async def handler(arguments: dict[str, Any], ctx) -> dict[str, Any]:
        _ = arguments, ctx
        return {"ok": True}

    broker.register_tool(
        ToolSpec(
            name="restricted",
            description="Restricted tool",
            parameters={"type": "object", "properties": {}},
        ),
        handler,
    )
    ctx = _context()
    ctx.profile.enabled_tools = ["restricted"]
    state = ToolRuntimeState()

    with pytest.raises(ApprovalRequired) as exc_info:
        await broker.execute(
            tool_name="restricted",
            arguments={"x": 1},
            ctx=broker._build_execution_context(ctx, state=state),
        )

    pending = exc_info.value.pending_approval
    assert pending.tool_name == "restricted"
    assert pending.reason == "needs admin approval"
    assert state.pending_approval is not None
    assert state.user_actions[0].commit_when == "waiting_approval"
    record = audit.records[pending.tool_call_id]
    assert record.status == "waiting_approval"
    assert record.metadata["approval_id"] == pending.approval_id
