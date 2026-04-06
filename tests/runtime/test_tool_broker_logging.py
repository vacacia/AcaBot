import logging

import pytest

from acabot.agent import ToolSpec
from acabot.runtime import ResolvedAgent, ToolBroker, ToolExecutionContext, ToolPolicyDecision
from acabot.runtime.control.log_buffer import InMemoryLogBuffer, InMemoryLogHandler
from acabot.runtime.control.log_setup import configure_structlog
from acabot.types import EventSource


class DenyPolicy:
    def allow(self, *, spec, arguments, ctx):
        _ = spec, arguments, ctx
        return ToolPolicyDecision(allowed=False, reason="not allowed")


def _context(*, enabled_tools: list[str]) -> ToolExecutionContext:
    return ToolExecutionContext(
        run_id="run:1",
        thread_id="qq:user:10001",
        actor_id="qq:user:10001",
        agent_id="agent:frontstage",
        target=EventSource(platform="qq", message_type="private", user_id="10001", group_id=None),
        agent=ResolvedAgent(
            agent_id="agent:frontstage",
            prompt_ref="prompt/default",
            enabled_tools=list(enabled_tools),
        ),
    )


def _capture_tool_broker_logger(buffer: InMemoryLogBuffer):
    configure_structlog()
    handler = InMemoryLogHandler(buffer)
    logger = logging.getLogger("acabot.runtime.tool_broker")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, previous_handlers, previous_level, previous_propagate


@pytest.mark.asyncio
async def test_tool_broker_logs_call_and_result_with_arguments_and_result_snapshot() -> None:
    buffer = InMemoryLogBuffer(max_entries=10)
    logger, previous_handlers, previous_level, previous_propagate = _capture_tool_broker_logger(buffer)
    try:
        broker = ToolBroker()
        broker.register_tool(
            ToolSpec(name="echo", description="echo", parameters={"type": "object"}),
            lambda arguments, ctx: {
                "ok": True,
                "echo": arguments,
                "token": "should-not-leak",
                "ctx": ctx.run_id,
            },
            source="test",
        )

        await broker.execute(
            tool_name="echo",
            arguments={"url": "https://example.com", "token": "secret-value"},
            ctx=_context(enabled_tools=["echo"]),
        )

        snapshot = buffer.list_entries(limit=10)
        call_item = snapshot["items"][-2]
        result_item = snapshot["items"][-1]

        assert call_item["message"].startswith("[TOOL_CALL] echo args=")
        assert call_item["extra"]["tool_name"] == "echo"
        assert call_item["extra"]["run_id"] == "run:1"
        assert call_item["extra"]["thread_id"] == "qq:user:10001"
        assert call_item["extra"]["agent_id"] == "agent:frontstage"
        assert call_item["extra"]["actor_id"] == "qq:user:10001"
        assert call_item["extra"]["tool_arguments"]["url"] == "https://example.com"
        assert call_item["extra"]["tool_arguments"]["token"] == "[REDACTED]"

        assert result_item["message"].startswith("[TOOL_RESULT] echo")
        assert result_item["extra"]["tool_name"] == "echo"
        snapshot_payload = result_item["extra"]["tool_result_snapshot"]
        assert snapshot_payload["attachment_count"] == 0
        assert snapshot_payload["artifact_count"] == 0
        assert snapshot_payload["user_action_count"] == 0
        assert snapshot_payload["raw"]["token"] == "[REDACTED]"
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@pytest.mark.asyncio
async def test_tool_broker_logs_failure_with_error_and_arguments() -> None:
    buffer = InMemoryLogBuffer(max_entries=10)
    logger, previous_handlers, previous_level, previous_propagate = _capture_tool_broker_logger(buffer)
    try:
        broker = ToolBroker()
        broker.register_tool(
            ToolSpec(name="boom", description="boom", parameters={"type": "object"}),
            lambda arguments, ctx: (_ for _ in ()).throw(RuntimeError("kaboom")),
            source="test",
        )

        await broker.execute(
            tool_name="boom",
            arguments={"password": "hidden", "value": "ok"},
            ctx=_context(enabled_tools=["boom"]),
        )

        snapshot = buffer.list_entries(limit=10)
        item = snapshot["items"][-1]

        assert item["level"] == "ERROR"
        assert item["message"].startswith("[TOOL_RESULT] boom failed error=")
        assert item["extra"]["tool_arguments"]["password"] == "[REDACTED]"
        assert item["extra"]["tool_arguments"]["value"] == "ok"
        assert "kaboom" in item["extra"]["error"]
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


@pytest.mark.asyncio
async def test_tool_broker_logs_rejection_with_reason_and_arguments() -> None:
    buffer = InMemoryLogBuffer(max_entries=10)
    logger, previous_handlers, previous_level, previous_propagate = _capture_tool_broker_logger(buffer)
    try:
        broker = ToolBroker(policy=DenyPolicy())
        broker.register_tool(
            ToolSpec(name="nope", description="nope", parameters={"type": "object"}),
            lambda arguments, ctx: {"ok": True},
            source="test",
        )

        await broker.execute(
            tool_name="nope",
            arguments={"authorization": "Bearer secret", "value": "ok"},
            ctx=_context(enabled_tools=["nope"]),
        )

        snapshot = buffer.list_entries(limit=10)
        item = snapshot["items"][-1]

        assert item["level"] == "WARNING"
        assert item["message"] == "[TOOL_REJECTED] nope reason=not allowed"
        assert item["extra"]["tool_arguments"]["authorization"] == "[REDACTED]"
        assert item["extra"]["reason"] == "not allowed"
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
