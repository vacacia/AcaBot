"""runtime.plugins.skill_delegation 提供 subagent delegation 工具插件.

组件关系:

    RuntimePluginManager
            |
            v
    SkillDelegationPlugin
            |
            v
    SubagentDelegationBroker

目标:
- 给主 agent 一个显式的 `delegate_skill` 工具
- 让 `prefer_delegate / must_delegate` 不只是 prompt 提示
- 保持 skill 定义和 subagent executor 解耦
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from ..subagent_delegation import SubagentDelegationBroker
from ..tool_broker import ToolExecutionContext, ToolResult


# region plugin
class SkillDelegationPlugin(RuntimePlugin):
    """subagent delegation 工具插件.

    Attributes:
        name (str): 插件名.
        _delegator (SubagentDelegationBroker | None): subagent delegation 编排入口.
    """

    name = "skill_delegation"

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
        """返回 `delegate_skill` 工具定义.

        Returns:
            一条 runtime-native 工具注册项.
        """

        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
                    name="delegate_skill",
                    description=(
                        "Delegate work to a subagent. "
                        "You can either delegate a configured skill_name or directly choose a delegate_agent_id."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "Optional assigned skill name to delegate.",
                            },
                            "delegate_agent_id": {
                                "type": "string",
                                "description": "Optional direct subagent id. Use this when you want to hand the task to a visible subagent directly.",
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
                        "required": ["task"],
                    },
                ),
                handler=self._delegate_skill,
            )
        ]

    async def _delegate_skill(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """执行一次 subagent skill delegation.

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

        skill_name = str(arguments.get("skill_name", "") or "").strip()
        delegate_agent_id = str(arguments.get("delegate_agent_id", "") or "").strip()
        task = str(arguments.get("task", "") or "").strip()
        payload = dict(arguments.get("payload", {}) or {})
        payload.setdefault("task", task)
        if not skill_name and not delegate_agent_id:
            return ToolResult(
                llm_content="Delegation failed: either skill_name or delegate_agent_id is required.",
                raw={"ok": False, "reason": "delegation_target_missing"},
            )

        result = await delegator.delegate(
            run_id=ctx.run_id,
            thread_id=ctx.thread_id,
            actor_id=ctx.actor_id,
            channel_scope=str(ctx.metadata.get("channel_scope", "") or ""),
            parent_agent_id=ctx.agent_id,
            profile=ctx.profile,
            skill_name=skill_name,
            delegate_agent_id=delegate_agent_id,
            payload=payload,
            metadata={
                "requested_by": "delegate_skill",
                "platform": str(ctx.metadata.get("platform", "") or ""),
            },
        )
        if not result.ok:
            return ToolResult(
                llm_content=f"Delegation failed for {skill_name or delegate_agent_id}: {result.error or 'unknown error'}",
                raw={
                    "ok": False,
                    "skill_name": skill_name,
                    "delegate_agent_id": delegate_agent_id,
                    "error": result.error,
                    "metadata": dict(result.metadata),
                },
            )

        return ToolResult(
            llm_content=(
                f"Delegation completed for {skill_name or delegate_agent_id}. "
                f"subagent={result.metadata.get('executor_agent_id', '') or '-'} "
                f"summary={result.summary or 'done'}"
            ),
            artifacts=list(result.artifacts),
            raw={
                "ok": True,
                "skill_name": skill_name,
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
