"""runtime.subagents.broker 提供 subagent delegation 承载层.

这一层不决定何时委派.
它只负责:
- 校验 `delegate_agent_id` 和 catalog 可见性
- 组装标准化的 delegation request/result
- 把请求交给 child-run execution service
"""

from __future__ import annotations

from inspect import isawaitable
from typing import Any

from ..contracts import ResolvedAgent
from .catalog import SubagentCatalog
from .contracts import SubagentDelegationRequest, SubagentDelegationResult


class SubagentDelegationBroker:
    """subagent delegation 的最小编排入口."""

    def __init__(
        self,
        *,
        catalog: SubagentCatalog | None = None,
        execution_service=None,
        default_agent_id: str = "",
    ) -> None:
        """初始化 delegation broker.

        Args:
            catalog: 可选的 subagent catalog.
            execution_service: 可选的本地 child run 执行入口.
            default_agent_id: 默认主 agent 标识.
        """

        self.catalog = catalog
        self.execution_service = execution_service
        self.default_agent_id = str(default_agent_id or "")

    async def delegate(
        self,
        *,
        run_id: str,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
        parent_agent_id: str,
        agent: ResolvedAgent,
        delegate_agent_id: str = "",
        visible_subagents: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SubagentDelegationResult:
        """按 `delegate_agent_id` 执行一次 delegation.

        Args:
            run_id: 父 run 标识.
            thread_id: 父 thread 标识.
            actor_id: 当前 actor 标识.
            channel_scope: 当前 channel scope.
            parent_agent_id: 发起 delegation 的 agent 标识.
            agent: 当前父 agent 的快照.
            delegate_agent_id: 目标 subagent id.
            visible_subagents: 当前 run 允许访问的 subagent allowlist.
            payload: 委派载荷.
            metadata: 附加元数据.

        Returns:
            一份 SubagentDelegationResult.
        """

        resolved_delegate_agent_id = str(delegate_agent_id or "").strip()
        if not resolved_delegate_agent_id:
            return self._failed("", "delegate_agent_id is required")
        if resolved_delegate_agent_id == agent.agent_id:
            return self._failed(resolved_delegate_agent_id, "current agent cannot delegate to itself")
        if visible_subagents is not None:
            allowed_subagents = [
                str(item or "").strip()
                for item in list(visible_subagents or [])
                if str(item or "").strip()
            ]
            if resolved_delegate_agent_id not in allowed_subagents:
                return self._failed(
                    resolved_delegate_agent_id,
                    f"subagent not visible in current session: {resolved_delegate_agent_id}",
                )
        if self.catalog is None:
            return self._failed(resolved_delegate_agent_id, "subagent catalog is not configured")
        if self.execution_service is None:
            return self._failed(
                resolved_delegate_agent_id,
                "subagent execution service is not configured",
            )

        manifest = self.catalog.get(resolved_delegate_agent_id)
        if manifest is None:
            return self._failed(
                resolved_delegate_agent_id,
                f"subagent package not found: {resolved_delegate_agent_id}",
            )

        request = SubagentDelegationRequest(
            parent_run_id=run_id,
            parent_thread_id=thread_id,
            parent_agent_id=parent_agent_id,
            actor_id=actor_id,
            channel_scope=channel_scope,
            delegate_agent_id=resolved_delegate_agent_id,
            payload=dict(payload or {}),
            metadata={"delegation_kind": "direct_subagent", **dict(metadata or {})},
        )
        result = self.execution_service.execute(request)
        if isawaitable(result):
            result = await result
        if isinstance(result, dict):
            result = SubagentDelegationResult(
                ok=bool(result.get("ok", False)),
                delegated_run_id=str(result.get("delegated_run_id", "") or ""),
                summary=str(result.get("summary", "") or ""),
                artifacts=list(result.get("artifacts", []) or []),
                error=str(result.get("error", "") or ""),
                metadata=dict(result.get("metadata", {}) or {}),
            )
        result.metadata.setdefault("executor_agent_id", resolved_delegate_agent_id)
        result.metadata.setdefault("executor_source", f"catalog:{manifest.scope}")
        return result

    @staticmethod
    def _failed(delegate_agent_id: str, message: str) -> SubagentDelegationResult:
        """构造一条失败结果.

        Args:
            delegate_agent_id: 目标 subagent id.
            message: 失败原因.

        Returns:
            一份失败的 SubagentDelegationResult.
        """

        return SubagentDelegationResult(
            ok=False,
            error=message,
            metadata={"executor_agent_id": delegate_agent_id} if delegate_agent_id else {},
        )


# endregion
