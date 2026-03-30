from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeAgentResponse:
    text: str = ""
    attachments: list[Any] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[Any] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None


class FakeAgent:
    """用于 runtime 测试的最小 fake agent."""

    def __init__(self, response: FakeAgentResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> FakeAgentResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "model": model,
                "request_options": dict(request_options or {}),
                "max_tool_rounds": max_tool_rounds,
                "tools": list(tools or []),
                "tool_executor": tool_executor,
            }
        )
        return self.response
