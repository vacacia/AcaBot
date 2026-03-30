"""runtime.builtin_tools.subagents 注册 subagent builtin tool.

这个文件负责把 subagent delegation 能力暴露成一个基础工具.
它和下面这些组件直接相关:
- `runtime.subagents`: 真正做委派编排
- `runtime.tool_broker`: 保存对模型可见的工具目录
- `runtime.bootstrap`: 启动时注册 builtin subagent tool
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..subagents import SubagentDelegationBroker
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


# region source
BUILTIN_SUBAGENT_TOOL_SOURCE = "builtin:subagents"


# endregion


# region surface
class BuiltinSubagentToolSurface:
    """subagent builtin tool 的注册和执行入口.

    Attributes:
        delegator (SubagentDelegationBroker | None): subagent delegation 编排入口.
    """

    def __init__(self, *, delegator: SubagentDelegationBroker | None) -> None:
        """保存 builtin subagent tool 依赖."""

        self.delegator = delegator

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 subagent builtin tool 注册到 ToolBroker."""

        tool_broker.unregister_source(BUILTIN_SUBAGENT_TOOL_SOURCE)
        if self.delegator is None:
            return []
        tool_broker.register_tool(
            ToolSpec(
                name="delegate_subagent",
                description="Delegate work to a visible subagent by delegate_agent_id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "delegate_agent_id": {
                            "type": "string",
                            "description": "Visible subagent id.",
                        },
                        "task": {
                            "type": "string",
                            "description": "A concise task description for the subagent.",
                        },
                        "payload": {
                            "type": "object",
                            "description": "Optional structured payload passed to the subagent.",
                        },
                    },
                    "required": ["delegate_agent_id", "task"],
                },
            ),
            self._delegate_subagent,
            source=BUILTIN_SUBAGENT_TOOL_SOURCE,
        )
        return ["delegate_subagent"]

    async def _delegate_subagent(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """执行一次 subagent delegation."""

        delegator = self.delegator
        if delegator is None:
            return ToolResult(
                llm_content="Delegation broker unavailable.",
                raw={"ok": False, "reason": "delegation_unavailable"},
            )

        delegate_agent_id = str(arguments.get("delegate_agent_id", "") or "").strip()
        task = str(arguments.get("task", "") or "").strip()
        payload = dict(arguments.get("payload", {}) or {})
        payload.setdefault("task", task)
        if not delegate_agent_id:
            return ToolResult(
                llm_content="Delegation failed: delegate_agent_id is required.",
                raw={"ok": False, "reason": "delegation_target_missing"},
            )

        result = await delegator.delegate(
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            actor_id=ctx.actor_id,
            channel_scope=str(ctx.metadata.get("channel_scope", "") or ""),
            parent_agent_id=ctx.agent_id,
            agent=ctx.agent,
            delegate_agent_id=delegate_agent_id,
            visible_subagents=list(ctx.visible_subagents),
            payload=payload,
            metadata={
                "requested_by": "delegate_subagent",
                "platform": str(ctx.metadata.get("platform", "") or ""),
            },
        )
        if not result.ok:
            return ToolResult(
                llm_content=f"Delegation failed for {delegate_agent_id}: {result.error or 'unknown error'}",
                raw={
                    "ok": False,
                    "delegate_agent_id": delegate_agent_id,
                    "error": result.error,
                    "metadata": dict(result.metadata),
                },
            )

        return ToolResult(
            llm_content=(
                f"Delegation completed for {delegate_agent_id}. "
                f"subagent={result.metadata.get('executor_agent_id', '') or '-'} "
                f"summary={result.summary or 'done'}"
            ),
            artifacts=list(result.artifacts),
            raw={
                "ok": True,
                "delegate_agent_id": delegate_agent_id,
                "delegated_run_id": result.delegated_run_id,
                "summary": result.summary,
                "artifacts": list(result.artifacts),
                "metadata": dict(result.metadata),
            },
            metadata={
                "delegated_run_id": result.delegated_run_id,
                "delegate_agent_id": str(result.metadata.get("executor_agent_id", "") or ""),
            },
        )


# endregion


__all__ = [
    "BUILTIN_SUBAGENT_TOOL_SOURCE",
    "BuiltinSubagentToolSurface",
]
