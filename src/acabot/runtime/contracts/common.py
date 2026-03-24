"""runtime.contracts.common 定义 runtime 共享字面量类型."""

from __future__ import annotations

from typing import Literal

RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "interrupted",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
RunMode = Literal["respond", "record_only", "silent_drop"]
CommitWhen = Literal["success", "failure", "waiting_approval", "always"]
ApprovalDecision = Literal["approved", "rejected"]
MemoryEditMode = Literal["readonly", "draft", "private"]
DelegationMode = Literal["inline", "prefer_delegate", "must_delegate", "manual"]

__all__ = [
    "ApprovalDecision",
    "CommitWhen",
    "DelegationMode",
    "MemoryEditMode",
    "RunMode",
    "RunStatus",
]
