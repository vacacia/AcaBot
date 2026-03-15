"""runtime.subagent_delegation 提供 subagent delegation 承载层.

组件关系:

    SkillCatalog + AgentProfile
             |
             v
    SubagentDelegationBroker
             |
             v
    SubagentExecutorRegistry
             |
             v
      SubagentExecutor

这一层不决定何时委派.
它只负责:
- 根据 profile assignment 解析 delegation policy
- 找到对应的 subagent executor
- 组装标准化的 delegation request/result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, Protocol

from .models import AgentProfile
from .skills import SkillCatalog, SubagentDelegationRequest, SubagentDelegationResult


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
        skill_catalog (SkillCatalog): 统一 skill catalog.
        executor_registry (SubagentExecutorRegistry): subagent executor 注册表.
    """

    def __init__(
        self,
        *,
        skill_catalog: SkillCatalog,
        executor_registry: SubagentExecutorRegistry,
    ) -> None:
        """初始化 delegation broker.

        Args:
            skill_catalog: 统一 skill catalog.
            executor_registry: subagent executor 注册表.
        """

        self.skill_catalog = skill_catalog
        self.executor_registry = executor_registry

    async def delegate(
        self,
        *,
        run_id: str,
        thread_id: str,
        actor_id: str,
        channel_scope: str,
        parent_agent_id: str,
        profile: AgentProfile,
        skill_name: str,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SubagentDelegationResult:
        """按 profile assignment 执行一次 delegation.

        Args:
            run_id: 父 run 标识.
            thread_id: 父 thread 标识.
            actor_id: 当前 actor 标识.
            channel_scope: 当前 channel scope.
            parent_agent_id: 发起 delegation 的 agent 标识.
            profile: 当前父 agent 的 profile.
            skill_name: 目标 skill 名.
            payload: 委派载荷.
            metadata: 附加元数据.

        Returns:
            一份 SubagentDelegationResult.
        """

        assignment = self._resolve_assignment(profile, skill_name)
        if assignment is None:
            return self._failed(skill_name, "skill is not assigned to current agent")
        if assignment.delegation_mode == "inline":
            return self._failed(skill_name, "skill is configured for inline execution")
        if assignment.delegation_mode == "manual":
            return self._failed(skill_name, "skill requires manual delegation choice")
        if not assignment.delegate_agent_id:
            return self._failed(skill_name, "delegate_agent_id is missing")

        executor_item = self.executor_registry.get(assignment.delegate_agent_id)
        if executor_item is None:
            return self._failed(skill_name, f"subagent executor not found: {assignment.delegate_agent_id}")

        request = SubagentDelegationRequest(
            skill_name=skill_name,
            parent_run_id=run_id,
            parent_thread_id=thread_id,
            parent_agent_id=parent_agent_id,
            actor_id=actor_id,
            channel_scope=channel_scope,
            delegate_agent_id=assignment.delegate_agent_id,
            payload=dict(payload or {}),
            metadata={
                "delegation_mode": assignment.delegation_mode,
                "notes": assignment.notes,
                **dict(metadata or {}),
            },
        )
        result = executor_item.executor(request)
        if isawaitable(result):
            result = await result
        if isinstance(result, dict):
            result = SubagentDelegationResult(
                skill_name=str(result.get("skill_name", skill_name) or skill_name),
                ok=bool(result.get("ok", False)),
                delegated_run_id=str(result.get("delegated_run_id", "") or ""),
                summary=str(result.get("summary", "") or ""),
                artifacts=list(result.get("artifacts", []) or []),
                error=str(result.get("error", "") or ""),
                metadata=dict(result.get("metadata", {}) or {}),
            )
        result.metadata.setdefault("executor_agent_id", assignment.delegate_agent_id)
        result.metadata.setdefault("executor_source", executor_item.source)
        return result

    def _resolve_assignment(self, profile: AgentProfile, skill_name: str):
        """解析当前 profile 命中的 skill assignment.

        Args:
            profile: 当前 agent profile.
            skill_name: 目标 skill 名.

        Returns:
            命中的 SkillAssignment. 不存在时返回 None.
        """

        for item in self.skill_catalog.resolve_assignments(profile):
            if item.skill.skill_name == skill_name:
                return item.assignment
        return None

    @staticmethod
    def _failed(skill_name: str, message: str) -> SubagentDelegationResult:
        """构造一条失败结果.

        Args:
            skill_name: 对应的 skill 名.
            message: 失败原因.

        Returns:
            一份失败的 SubagentDelegationResult.
        """

        return SubagentDelegationResult(
            skill_name=skill_name,
            ok=False,
            error=message,
        )


# endregion
