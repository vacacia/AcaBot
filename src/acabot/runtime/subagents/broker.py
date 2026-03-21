"""runtime.subagents.broker 提供 subagent delegation 承载层.

这一层不决定何时委派.
它只负责:
- 按 `delegate_agent_id` 找到对应的 subagent executor
- 组装标准化的 delegation request/result
- 返回统一的委派结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Protocol

from ..contracts import AgentProfile
from .contracts import SubagentDelegationRequest, SubagentDelegationResult


# region executor
@dataclass(slots=True)
class SubagentExecutorRegistration:
    """一条 runtime plugin 可声明的 subagent executor 注册项.

    Attributes:
        agent_id (str): 这个 executor 负责的 subagent 标识.
        executor (SubagentExecutor): 真实执行逻辑.
        metadata (dict[str, Any]): 附加注册元数据.
    """

    agent_id: str
    executor: "SubagentExecutor"
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentExecutor(Protocol):
    """SubagentExecutor 协议.

    任何接受 `SubagentDelegationRequest` 并返回
    `SubagentDelegationResult` 的对象, 都可以作为 subagent executor.
    """

    async def __call__(self, request: SubagentDelegationRequest) -> SubagentDelegationResult:
        """执行一次 subagent delegation.

        Args:
            request: 标准化后的 delegation request.

        Returns:
            一份标准化的 SubagentDelegationResult.
        """

        ...


@dataclass(slots=True)
class RegisteredSubagentExecutor:
    """一条已注册的 subagent executor.

    Attributes:
        agent_id (str): 这个 executor 负责的 subagent 标识.
        executor (SubagentExecutor): 真实执行逻辑.
        source (str): 注册来源.
        metadata (dict[str, Any]): 附加元数据.
    """

    agent_id: str
    executor: SubagentExecutor
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentExecutorRegistry:
    """subagent executor 注册表.

    Attributes:
        _executors (dict[str, RegisteredSubagentExecutor]): 当前已注册 executor.
    """

    def __init__(self) -> None:
        """初始化空的 executor 注册表."""

        self._executors: dict[str, RegisteredSubagentExecutor] = {}

    def register(
        self,
        agent_id: str,
        executor: SubagentExecutor,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册一条 subagent executor.

        Args:
            agent_id: 目标 subagent 标识.
            executor: 真实执行逻辑.
            source: 注册来源.
            metadata: 附加元数据.
        """

        self._executors[agent_id] = RegisteredSubagentExecutor(
            agent_id=agent_id,
            executor=executor,
            source=source,
            metadata=dict(metadata or {}),
        )

    def get(self, agent_id: str) -> RegisteredSubagentExecutor | None:
        """读取一条已注册 executor.

        Args:
            agent_id: 目标 subagent 标识.

        Returns:
            命中的 RegisteredSubagentExecutor. 不存在时返回 None.
        """

        return self._executors.get(agent_id)

    def list_all(self) -> list[RegisteredSubagentExecutor]:
        """列出全部 executor.

        Returns:
            按 agent_id 排序的 executor 列表.
        """

        return [self._executors[agent_id] for agent_id in sorted(self._executors)]

    def unregister_source(self, source: str) -> list[str]:
        """按来源卸载 executor.

        Args:
            source: 注册来源.

        Returns:
            被删除的 agent_id 列表.
        """

        removed: list[str] = []
        for agent_id, item in list(self._executors.items()):
            if item.source != source:
                continue
            removed.append(agent_id)
            del self._executors[agent_id]
        return removed


# endregion


# region broker
class SubagentDelegationBroker:
    """subagent delegation 的最小编排入口.

    Attributes:
        executor_registry (SubagentExecutorRegistry): subagent executor 注册表.
    """

    def __init__(
        self,
        *,
        executor_registry: SubagentExecutorRegistry,
        default_agent_id: str = "",
    ) -> None:
        """初始化 delegation broker.

        Args:
            executor_registry: subagent executor 注册表.
            default_agent_id: 默认主 agent 标识.
        """

        self.executor_registry = executor_registry
        self.default_agent_id = str(default_agent_id or "")

    async def delegate(
        self,
        *,
        run_id: str,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
        parent_agent_id: str,
        profile: AgentProfile,
        delegate_agent_id: str = "",
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
            profile: 当前父 agent 的 profile.
            delegate_agent_id: 目标 subagent id.
            payload: 委派载荷.
            metadata: 附加元数据.

        Returns:
            一份 SubagentDelegationResult.
        """

        if self.default_agent_id and profile.agent_id != self.default_agent_id:
            return self._failed("", "current agent cannot delegate subagents")
        resolved_delegate_agent_id = str(delegate_agent_id or "").strip()
        if not resolved_delegate_agent_id:
            return self._failed("", "delegate_agent_id is required")
        if resolved_delegate_agent_id == profile.agent_id:
            return self._failed(resolved_delegate_agent_id, "current agent cannot delegate to itself")
        executor_item = self.executor_registry.get(resolved_delegate_agent_id)
        if executor_item is None:
            return self._failed(resolved_delegate_agent_id, f"subagent executor not found: {resolved_delegate_agent_id}")

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
        result = executor_item.executor(request)
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
        result.metadata.setdefault("executor_source", executor_item.source)
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
