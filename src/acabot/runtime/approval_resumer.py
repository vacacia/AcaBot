"""runtime.approval_resumer 定义 approval decision 之后的续执行接口.

RuntimeApp 只管状态和审计，不管业务逻辑

拆解:
- `RuntimeApp` 里的审批决策
- 具体如何继续执行后续逻辑

当前 runtime 没有正式 `ToolBroker`, 先提供一个可插拔接口.后续 tool approval resume 接到这里.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from .models import RunRecord

ApprovalResumeStatus = Literal[
    "completed",
    "completed_with_errors",
    "failed",
    "waiting_approval",
]


# region result
@dataclass(slots=True)
class ApprovalResumeResult:
    """approval 恢复动作的系统级结果.

    这个结果只描述恢复之后 run 应该进入什么状态.
    最终的 run 状态迁移仍由 `RuntimeApp` 统一完成.
    """

    status: ApprovalResumeStatus = "completed"
    message: str = ""
    approval_context: dict[str, Any] = field(default_factory=dict)


# endregion


# region protocol
class ApprovalResumer(ABC):
    """approval 通过后的续执行接口."""

    @abstractmethod
    async def resume(
        self,
        *,
        run: RunRecord,
        approval_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ApprovalResumeResult:
        """在 approval 通过后继续执行后续流程.

        Args:
            run: 当前 waiting approval 的 RunRecord.
            approval_context: 当前 run 上保存的审批上下文.
            metadata: 这次 approval decision 的附加元数据.

        Returns:
            一份描述恢复结果的 ApprovalResumeResult.
        """

        ...


# endregion


# region default
class NoopApprovalResumer(ApprovalResumer):
    """默认的 approval resumer - 没配置 resumer 默认失败.

    在真正的 tool approval resume 落地之前, 默认实现明确返回 failed.
    这样不会让系统悄悄吞掉一次 approval.
    """

    async def resume(
        self,
        *,
        run: RunRecord,
        approval_context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> ApprovalResumeResult:
        """返回一个明确失败的恢复结果.

        Args:
            run: 当前 waiting approval 的 RunRecord.
            approval_context: 当前 run 的审批上下文.
            metadata: 这次 approval decision 的附加元数据.

        Returns:
            一份 `failed` 的 ApprovalResumeResult.
        """

        return ApprovalResumeResult(
            status="failed",
            message="approval resumer is not configured",
        )


# endregion
