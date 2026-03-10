"""runtime.app 实现新的最小应用组装入口.

RuntimeApp 的职责是把 gateway 事件接到新的 runtime 主线上, 不再让旧 Pipeline 直接暴露
"""

from __future__ import annotations

import logging
from typing import Callable

from acabot.types import StandardEvent

from .gateway_protocol import GatewayProtocol
from .models import AgentProfile, RouteDecision, RunContext
from .pipeline import ThreadPipeline
from .router import RuntimeRouter
from .runs import RunManager
from .threads import ThreadManager

logger = logging.getLogger("acabot.runtime.app")


class RuntimeApp:
    """新的最小 runtime 应用入口.

    负责接线, 不负责具体业务逻辑.
    它只把外部 event 变成 RunContext, 再交给 ThreadPipeline 执行.
    """

    def __init__(
        self,
        *,
        gateway: GatewayProtocol,
        router: RuntimeRouter,
        thread_manager: ThreadManager,
        run_manager: RunManager,
        pipeline: ThreadPipeline,
        profile_loader: Callable[[RouteDecision], AgentProfile],
    ) -> None:
        """初始化 RuntimeApp.

        Args:
            gateway: 平台网关实现.
            router: event 到 runtime world 的路由器.
            thread_manager: thread 状态管理器.
            run_manager: run 生命周期管理器.
            pipeline: 真正执行一次 run 的 ThreadPipeline.
            profile_loader: 根据 RouteDecision 加载 AgentProfile 的回调.
        """

        self.gateway = gateway
        self.router = router
        self.thread_manager = thread_manager
        self.run_manager = run_manager
        self.pipeline = pipeline
        self.profile_loader = profile_loader

    def install(self) -> None:
        """把 RuntimeApp 注册到 gateway 事件流上."""

        self.gateway.on_event(self.handle_event)

    async def start(self) -> None:
        """安装事件处理器并启动 gateway."""

        self.install()
        await self.gateway.start()

    async def stop(self) -> None:
        """停止 gateway."""

        await self.gateway.stop()

    async def handle_event(self, event: StandardEvent) -> None:
        """处理一条来自 gateway 的标准事件.

        Args:
            event: 平台翻译后的标准事件.
        """
        run_id: str | None = None
        try:
            decision = await self.router.route(event)
            thread = await self.thread_manager.get_or_create(
                thread_id=decision.thread_id,
                channel_scope=decision.channel_scope,
                last_event_at=event.timestamp,
            )
            run = await self.run_manager.open(event=event, decision=decision)
            run_id = run.run_id
            profile = self.profile_loader(decision)
            ctx = RunContext(
                run=run,
                event=event,
                decision=decision,
                thread=thread,
                profile=profile,
            )
            await self.pipeline.execute(ctx)
        except Exception as exc:
            logger.exception("Failed to handle event: event_id=%s", event.event_id)
            if run_id is not None:
                await self._mark_failed_safely(run_id, f"runtime app crashed: {exc}")

    async def _mark_failed_safely(self, run_id: str, error: str) -> None:
        """尽力把 run 收尾为 failed.

        Args:
            run_id: 需要收尾的 run_id.
            error: 要写入 run 的错误摘要.
        """

        try:
            await self.run_manager.mark_failed(run_id, error)
        except Exception:
            logger.exception("Failed to mark run as failed: run_id=%s", run_id)
