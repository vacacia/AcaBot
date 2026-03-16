"""runtime.computer 子包."""

from .backends import DockerSandboxBackend, HostComputerBackend, RemoteComputerBackend
from .contracts import (
    AttachmentSnapshot,
    AttachmentStageResult,
    CommandExecutionResult,
    CommandSession,
    ComputerBackend,
    ComputerBackendNotImplemented,
    ComputerPolicy,
    ComputerRuntimeConfig,
    ComputerRuntimeOverride,
    WorkspaceFileEntry,
    WorkspaceSandboxStatus,
    WorkspaceState,
    parse_computer_override,
    parse_computer_policy,
)
from .runtime import ComputerRuntime
from .workspace import WorkspaceManager

__all__ = [
    "AttachmentSnapshot",
    "AttachmentStageResult",
    "CommandExecutionResult",
    "CommandSession",
    "ComputerBackend",
    "ComputerBackendNotImplemented",
    "ComputerPolicy",
    "ComputerRuntime",
    "ComputerRuntimeConfig",
    "ComputerRuntimeOverride",
    "DockerSandboxBackend",
    "HostComputerBackend",
    "RemoteComputerBackend",
    "WorkspaceFileEntry",
    "WorkspaceManager",
    "WorkspaceSandboxStatus",
    "WorkspaceState",
    "parse_computer_override",
    "parse_computer_policy",
]
