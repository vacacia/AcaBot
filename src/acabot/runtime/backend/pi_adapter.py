"""runtime.backend.pi_adapter 提供最小的 pi backend adapter stub."""

from __future__ import annotations


class PiBackendAdapter:
    """面向后台 session 的最小 pi adapter 占位实现.

    当前阶段只负责锁定接口边界，不真实启动 `pi --mode rpc`.
    """

    def __init__(self, command: list[str]) -> None:
        """保存 adapter 使用的命令行参数."""

        self.command = list(command)
        self.started = False

    async def ensure_started(self) -> None:
        """把 adapter 标记为已启动状态."""

        self.started = True

    async def prompt(self, prompt: str) -> dict[str, object]:
        """执行一次最小 prompt 调用并返回桩结果."""

        await self.ensure_started()
        return {
            "transport": "rpc",
            "command": list(self.command),
            "prompt": prompt,
        }

    async def fork_from_stable_checkpoint(self, prompt: str) -> dict[str, object]:
        """执行一次最小 query fork 调用并返回桩结果."""

        await self.ensure_started()
        return {
            "transport": "rpc",
            "command": list(self.command),
            "prompt": prompt,
            "forked": True,
        }

    async def dispose(self) -> None:
        """释放当前 adapter 状态."""

        self.started = False
