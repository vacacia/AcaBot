"""runtime.runs 定义 run 生命周期管理接口.

RunManager 负责把一次 agent 执行变成正式对象, 并维护状态迁移.

为每次处理创建正式的执行记录, 并管理它的完整生命周期, 以实现: 取消/后台任务/异步执行
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

from acabot.types import StandardEvent

from ..model.model_registry import PersistedModelSnapshot
from ..contracts import RouteDecision, RunRecord, RunStatus, RunStep
from .stores import RunStore

_ACTIVE_STATUSES: set[RunStatus] = {"queued", "running", "waiting_approval"}

# region RunManager
class RunManager(ABC):
    """run 生命周期管理接口.
    
    负责创建 run、维护状态迁移、记录步骤、支持取消
    """

    @abstractmethod
    async def open(
        self,
        *,
        event: StandardEvent,
        decision: RouteDecision,
        model_snapshot: PersistedModelSnapshot | None = None,
    ) -> RunRecord:
        """根据 event 和 route 决策创建一条新的 run 记录."""

        ...

    @abstractmethod
    async def get(self, run_id: str) -> RunRecord | None:
        """按 run_id 获取 run 记录."""

        ...

    @abstractmethod
    async def mark_running(self, run_id: str) -> None:
        """把 run 标记为 running, 并清空旧的审批上下文."""

        ...

    @abstractmethod
    async def mark_waiting_approval(
        self,
        run_id: str,
        *,
        reason: str,
        approval_context: dict[str, object],
    ) -> None:
        """把 run 标记为 waiting_approval, 并写入正式审批上下文."""

        ...

    @abstractmethod
    async def mark_completed(self, run_id: str) -> None:
        """把 run 标记为 completed."""

        ...

    @abstractmethod
    async def mark_completed_with_errors(self, run_id: str, *, error_summary: str) -> None:
        """把 run 标记为 completed_with_errors."""

        ...

    @abstractmethod
    async def mark_failed(self, run_id: str, error: str) -> None:
        """把 run 标记为 failed."""

        ...

    @abstractmethod
    async def mark_cancelled(self, run_id: str, reason: str | None = None) -> None:
        """把 run 标记为 cancelled."""

        ...

    @abstractmethod
    async def mark_interrupted(self, run_id: str, reason: str) -> None:
        """把 run 标记为 interrupted.

        interrupted 表示这次执行因进程重启或宿主中断而被动结束.
        """

        ...

    @abstractmethod
    async def append_step(self, step: RunStep) -> None:
        """追加一条 run 内部步骤记录."""

        ...

    @abstractmethod
    async def list_steps(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        """按 run_id 查询步骤记录."""

        ...

    @abstractmethod
    async def list_thread_steps(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        """按 thread_id 查询步骤记录."""

        ...

    @abstractmethod
    async def list_active(self) -> list[RunRecord]:
        """列出当前仍处于活跃状态的 runs."""

        ...

    @abstractmethod
    async def list_runs(
        self,
        *,
        limit: int | None = None,
        statuses: set[str] | None = None,
        thread_id: str | None = None,
    ) -> list[RunRecord]:
        """按条件列出 runs."""

        ...

    @abstractmethod
    async def cancel(self, run_id: str) -> bool:
        """请求取消一个 run.

        Returns:
            如果 run 存在, 返回 True.
            如果 run 不存在, 返回 False.
        """

        ...

    @abstractmethod
    def is_cancel_requested(self, run_id: str) -> bool:
        """检查某个 run 是否已收到取消请求."""

        ...

# region 内存版 RunManager
class InMemoryRunManager(RunManager):
    """内存版 RunManager."""

    def __init__(self) -> None:
        """初始化 run 表, step 表和取消请求集合."""

        self._runs: dict[str, RunRecord] = {}
        self._steps: dict[str, list[RunStep]] = {}
        self._cancel_requested: set[str] = set()

    async def open(
        self,
        *,
        event: StandardEvent,
        decision: RouteDecision,
        model_snapshot: PersistedModelSnapshot | None = None,
    ) -> RunRecord:
        """创建一条新的 run 记录, 初始状态为 queued."""

        run = RunRecord(
            run_id=self._new_id(),
            thread_id=decision.thread_id,
            actor_id=decision.actor_id,
            agent_id=decision.agent_id,
            trigger_event_id=event.event_id,
            status="queued",
            started_at=event.timestamp,
            metadata={
                **dict(decision.metadata),
                **(
                    {"model_snapshot": model_snapshot.to_dict()}
                    if model_snapshot is not None
                    else {}
                ),
            },
        )
        self._runs[run.run_id] = run
        self._steps[run.run_id] = []
        return run

    async def get(self, run_id: str) -> RunRecord | None:
        """读取一条已有 run 记录."""

        return self._runs.get(run_id)

    async def mark_running(self, run_id: str) -> None:
        """把 run 切到 running.

        清空旧的错误信息和审批上下文, 避免恢复执行时带着陈旧状态.
        """

        run = self._require_run(run_id)
        run.status = "running"
        run.error = None
        run.finished_at = None
        run.approval_context = {}

    async def mark_waiting_approval(
        self,
        run_id: str,
        *,
        reason: str,
        approval_context: dict[str, object],
    ) -> None:
        """把 run 切到 waiting_approval, 并持久化审批上下文."""

        run = self._require_run(run_id)
        run.status = "waiting_approval"
        run.error = reason
        run.finished_at = None
        run.approval_context = {
            "reason": reason,
            **approval_context,
        }

    async def mark_completed(self, run_id: str) -> None:
        """把 run 收尾为 completed."""

        run = self._require_run(run_id)
        run.status = "completed"
        run.error = None
        run.finished_at = self._now()
        run.approval_context = {}

    async def mark_completed_with_errors(self, run_id: str, *, error_summary: str) -> None:
        """把 run 收尾为 completed_with_errors."""

        run = self._require_run(run_id)
        run.status = "completed_with_errors"
        run.error = error_summary
        run.finished_at = self._now()
        run.approval_context = {}

    async def mark_failed(self, run_id: str, error: str) -> None:
        """把 run 收尾为 failed."""

        run = self._require_run(run_id)
        run.status = "failed"
        run.error = error
        run.finished_at = self._now()
        run.approval_context = {}

    async def mark_cancelled(self, run_id: str, reason: str | None = None) -> None:
        """把 run 收尾为 cancelled."""

        run = self._require_run(run_id)
        run.status = "cancelled"
        run.error = reason
        run.finished_at = self._now()
        run.approval_context = {}

    async def mark_interrupted(self, run_id: str, reason: str) -> None:
        """把 run 收尾为 interrupted.

        Args:
            run_id: 目标 run_id.
            reason: 中断原因.
        """

        run = self._require_run(run_id)
        run.status = "interrupted"
        run.error = reason
        run.finished_at = self._now()
        run.approval_context = {}

    async def append_step(self, step: RunStep) -> None:
        """为某个 run 追加一条步骤记录."""

        self._require_run(step.run_id)
        self._steps.setdefault(step.run_id, []).append(step)

    async def list_active(self) -> list[RunRecord]:
        """返回仍然处于活跃状态的 runs."""

        return [run for run in self._runs.values() if run.status in _ACTIVE_STATUSES]

    async def list_runs(
        self,
        *,
        limit: int | None = None,
        statuses: set[str] | None = None,
        thread_id: str | None = None,
    ) -> list[RunRecord]:
        """按条件列出内存中的 runs."""

        runs = list(self._runs.values())
        if statuses:
            runs = [run for run in runs if run.status in statuses]
        if thread_id:
            runs = [run for run in runs if run.thread_id == thread_id]
        runs.sort(key=lambda item: (item.started_at, item.run_id), reverse=True)
        if limit is not None:
            runs = runs[:int(limit)]
        return runs

    async def list_steps(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        steps = list(self._steps.get(run_id, []))
        if step_types:
            allowed = set(step_types)
            steps = [step for step in steps if step.step_type in allowed]
        if limit is not None:
            steps = steps[-int(limit):]
        return steps

    async def list_thread_steps(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        steps = [
            step
            for items in self._steps.values()
            for step in items
            if step.thread_id == thread_id
        ]
        if step_types:
            allowed = set(step_types)
            steps = [step for step in steps if step.step_type in allowed]
        steps.sort(key=lambda item: item.created_at)
        if limit is not None:
            steps = steps[-int(limit):]
        return steps

    async def cancel(self, run_id: str) -> bool:
        """登记一次取消请求.

        这里不会强制中断执行, 只是把取消意图记录下来, 交给执行链路在关键节点检查.
        """

        if run_id not in self._runs:
            return False
        self._cancel_requested.add(run_id)
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        """返回某个 run 是否已被请求取消."""

        return run_id in self._cancel_requested

    def _require_run(self, run_id: str) -> RunRecord:
        """获取 run, 不存在时抛出 KeyError."""

        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    @staticmethod
    def _new_id() -> str:
        """生成新的 run_id."""

        return f"run:{uuid.uuid4().hex}"

    @staticmethod
    def _now() -> int:
        """返回当前 Unix 时间戳, 单位为秒."""

        return int(time.time())

# region RunStore 的 RunManager
class StoreBackedRunManager(RunManager):
    """基于 RunStore 的 RunManager.

    这个实现负责:
    - 通过 RunStore 持久化 run 生命周期.
    - 在内存中缓存热点 run.
    - 保留取消请求的轻量运行时状态.
    """

    def __init__(self, store: RunStore) -> None:
        """初始化 store-backed RunManager.

        Args:
            store: run 持久化实现.
        """

        self.store = store
        self._runs: dict[str, RunRecord] = {}
        self._cancel_requested: set[str] = set()

    async def open(
        self,
        *,
        event: StandardEvent,
        decision: RouteDecision,
        model_snapshot: PersistedModelSnapshot | None = None,
    ) -> RunRecord:
        """创建一条新的 run 记录, 初始状态为 queued.

        Args:
            event: 触发这次 run 的标准事件.
            decision: router 产出的 RouteDecision.

        Returns:
            新建的 RunRecord.
        """

        run = RunRecord(
            run_id=self._new_id(),
            thread_id=decision.thread_id,
            actor_id=decision.actor_id,
            agent_id=decision.agent_id,
            trigger_event_id=event.event_id,
            status="queued",
            started_at=event.timestamp,
            metadata={
                **dict(decision.metadata),
                **(
                    {"model_snapshot": model_snapshot.to_dict()}
                    if model_snapshot is not None
                    else {}
                ),
            },
        )
        self._runs[run.run_id] = run
        await self.store.create_run(run)
        return run

    async def get(self, run_id: str) -> RunRecord | None:
        """按 run_id 获取 run 记录.

        Args:
            run_id: 目标 run_id.

        Returns:
            命中的 RunRecord, 或 None.
        """

        run = self._runs.get(run_id)
        if run is not None:
            return run

        run = await self.store.get_run(run_id)
        if run is not None:
            self._runs[run_id] = run
        return run

    async def mark_running(self, run_id: str) -> None:
        """把 run 切到 running.

        Args:
            run_id: 目标 run_id.
        """

        run = await self._require_run(run_id)
        run.status = "running"
        run.error = None
        run.finished_at = None
        run.approval_context = {}
        await self.store.update_run(run)

    async def mark_waiting_approval(
        self,
        run_id: str,
        *,
        reason: str,
        approval_context: dict[str, object],
    ) -> None:
        """把 run 切到 waiting_approval, 并写入正式审批上下文.

        Args:
            run_id: 目标 run_id.
            reason: 等待审批的原因摘要.
            approval_context: 需要持久化的审批上下文.
        """

        run = await self._require_run(run_id)
        run.status = "waiting_approval"
        run.error = reason
        run.finished_at = None
        run.approval_context = {
            "reason": reason,
            **approval_context,
        }
        await self.store.update_run(run)

    async def mark_completed(self, run_id: str) -> None:
        """把 run 收尾为 completed.

        Args:
            run_id: 目标 run_id.
        """

        run = await self._require_run(run_id)
        run.status = "completed"
        run.error = None
        run.finished_at = self._now()
        run.approval_context = {}
        await self.store.update_run(run)

    async def mark_completed_with_errors(self, run_id: str, *, error_summary: str) -> None:
        """把 run 收尾为 completed_with_errors.

        Args:
            run_id: 目标 run_id.
            error_summary: 这次 run 的错误摘要.
        """

        run = await self._require_run(run_id)
        run.status = "completed_with_errors"
        run.error = error_summary
        run.finished_at = self._now()
        run.approval_context = {}
        await self.store.update_run(run)

    async def mark_failed(self, run_id: str, error: str) -> None:
        """把 run 收尾为 failed.

        Args:
            run_id: 目标 run_id.
            error: 失败摘要.
        """

        run = await self._require_run(run_id)
        run.status = "failed"
        run.error = error
        run.finished_at = self._now()
        run.approval_context = {}
        await self.store.update_run(run)

    async def mark_cancelled(self, run_id: str, reason: str | None = None) -> None:
        """把 run 收尾为 cancelled.

        Args:
            run_id: 目标 run_id.
            reason: 可选的取消原因.
        """

        run = await self._require_run(run_id)
        run.status = "cancelled"
        run.error = reason
        run.finished_at = self._now()
        run.approval_context = {}
        await self.store.update_run(run)

    async def mark_interrupted(self, run_id: str, reason: str) -> None:
        """把 run 收尾为 interrupted.

        Args:
            run_id: 目标 run_id.
            reason: 中断原因.
        """

        run = await self._require_run(run_id)
        run.status = "interrupted"
        run.error = reason
        run.finished_at = self._now()
        run.approval_context = {}
        await self.store.update_run(run)

    async def append_step(self, step: RunStep) -> None:
        """追加一条 run step 审计记录.

        Args:
            step: 待追加的 RunStep.
        """

        await self._require_run(step.run_id)
        await self.store.append_step(step)

    async def list_active(self) -> list[RunRecord]:
        """列出当前仍处于活跃状态的 runs.

        Returns:
            所有活跃 RunRecord.
        """

        runs = await self.store.list_active_runs(_ACTIVE_STATUSES)
        for run in runs:
            self._runs[run.run_id] = run
        return runs

    async def list_runs(
        self,
        *,
        limit: int | None = None,
        statuses: set[str] | None = None,
        thread_id: str | None = None,
    ) -> list[RunRecord]:
        """按条件列出 store 中的 runs."""

        runs = await self.store.list_runs(
            limit=limit,
            statuses=statuses,
            thread_id=thread_id,
        )
        for run in runs:
            self._runs[run.run_id] = run
        return runs

    async def list_steps(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        return await self.store.get_run_steps(
            run_id,
            limit=limit,
            step_types=step_types,
        )

    async def list_thread_steps(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        step_types: list[str] | None = None,
    ) -> list[RunStep]:
        return await self.store.get_thread_steps(
            thread_id,
            limit=limit,
            step_types=step_types,
        )

    async def cancel(self, run_id: str) -> bool:
        """请求取消一个 run.

        Args:
            run_id: 目标 run_id.

        Returns:
            如果 run 存在, 返回 True. 否则返回 False.
        """

        run = await self.get(run_id)
        if run is None:
            return False
        self._cancel_requested.add(run_id)
        return True

    def is_cancel_requested(self, run_id: str) -> bool:
        """检查某个 run 是否已收到取消请求.

        Args:
            run_id: 目标 run_id.

        Returns:
            当前是否已请求取消.
        """

        return run_id in self._cancel_requested

    async def _require_run(self, run_id: str) -> RunRecord:
        """获取 run, 不存在时抛出 KeyError.

        Args:
            run_id: 目标 run_id.

        Returns:
            对应的 RunRecord.

        Raises:
            KeyError: run 不存在.
        """

        run = await self.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return run

    @staticmethod
    def _new_id() -> str:
        """生成新的 run_id.

        Returns:
            新的稳定 run_id.
        """

        return f"run:{uuid.uuid4().hex}"

    @staticmethod
    def _now() -> int:
        """返回当前 Unix 时间戳, 单位为秒.

        Returns:
            当前 Unix 时间戳.
        """

        return int(time.time())
