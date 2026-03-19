"""runtime.plugins.subagent_delegation 提供 subagent delegation 工具插件.

组件关系:

    RuntimePluginManager
            |
            v
    SubagentDelegationPlugin
            |
            v
    SubagentDelegationBroker

目标:
- 给主 agent 一个显式的 `delegate_subagent` 工具
- 让 subagent delegation 成为一条独立能力链
- 不再让 skill 承担委派语义
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from ..subagents import SubagentDelegationBroker
from ..tool_broker import ToolExecutionContext, ToolResult


# region plugin
class SubagentDelegationPlugin(RuntimePlugin):
    """subagent delegation 工具插件.

    Attributes:
        name (str): 插件名.
        _delegator (SubagentDelegationBroker | None): subagent delegation 编排入口.
    """

    name = "subagent_delegation"

    def __init__(self) -> None:
        """初始化插件状态."""

        self._delegator: SubagentDelegationBroker | None = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """保存 subagent delegation broker.

        Args:
            runtime: runtime plugin 上下文.
        """

        self._delegator = runtime.subagent_delegator

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """返回 `delegate_subagent` 工具定义.

        Returns:
            一条 runtime-native 工具注册项.
        """

        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
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
                handler=self._delegate_subagent,
            )
        ]

    async def _delegate_subagent(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """执行一次 subagent delegation.

        Args:
            arguments: 工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            一份适合主 agent 消费的 ToolResult.
        """

        delegator = self._delegator
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
            profile=ctx.profile,
            delegate_agent_id=delegate_agent_id,
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
