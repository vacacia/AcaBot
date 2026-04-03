"""test_scheduler_integration 测试 RuntimeScheduler 与 plugin/app 生命周期的集成.

覆盖: 插件 unload 自动清理定时任务, RuntimeApp start/stop 正确启停 scheduler.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from acabot.runtime.scheduler import IntervalSchedule, RuntimeScheduler
from acabot.runtime.plugin_protocol import (
    RuntimePlugin,
    RuntimePluginContext,
)
from acabot.runtime.plugin_runtime_host import PluginRuntimeHost
from acabot.runtime.plugin_package import PluginPackage
from acabot.runtime.tool_broker import ToolBroker
from acabot.runtime.app import RuntimeApp
from acabot.runtime.storage.runs import InMemoryRunManager
from acabot.runtime.storage.event_store import InMemoryChannelEventStore
from acabot.runtime.storage.threads import InMemoryThreadManager


# region fakes


class FakeGateway:
    """最小 Gateway 伪实现."""

    def __init__(self) -> None:
        self.handler = None
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, action: Any) -> dict[str, object] | None:
        _ = action
        return {"message_id": "msg-1"}

    def on_event(self, handler) -> None:
        self.handler = handler

    async def call_api(self, api: str, **kwargs: Any) -> dict[str, object]:
        _ = api, kwargs
        return {}


class _FakeSchedulerPlugin(RuntimePlugin):
    """测试用插件, setup 时通过 ctx.scheduler 注册一个定时任务."""

    name = "fake_scheduler_test"

    def __init__(self) -> None:
        self._scheduler: RuntimeScheduler | None = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        self._scheduler = runtime.scheduler
        if self._scheduler is not None:
            async def _noop() -> None:
                pass

            await self._scheduler.register(
                task_id="fake_scheduler_test:heartbeat",
                owner=f"plugin:{self.name}",
                schedule=IntervalSchedule(seconds=3600),
                callback=_noop,
            )

    async def teardown(self) -> None:
        pass


def _make_fake_package() -> PluginPackage:
    """构造 _FakeSchedulerPlugin 对应的 PluginPackage."""
    return PluginPackage(
        plugin_id="fake_scheduler_test",
        display_name="Fake Scheduler Test",
        package_root=Path("."),
        entrypoint=f"{_FakeSchedulerPlugin.__module__}:{_FakeSchedulerPlugin.__qualname__}",
    )


# endregion


# region plugin lifecycle tests


async def test_unload_plugin_cancels_scheduled_tasks() -> None:
    """插件 unload 时, 其注册的定时任务被自动取消."""
    scheduler = RuntimeScheduler()
    await scheduler.start()

    broker = ToolBroker()
    host = PluginRuntimeHost(
        tool_broker=broker,
        scheduler=scheduler,
    )

    package = _make_fake_package()
    ctx = RuntimePluginContext(
        plugin_id="fake_scheduler_test",
        plugin_config={},
        data_dir=Path("."),
        gateway=FakeGateway(),  # type: ignore[arg-type]
        tool_broker=broker,
        scheduler=scheduler,
    )
    await host.load_plugin(package, ctx)

    # 验证任务已注册
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].task_id == "fake_scheduler_test:heartbeat"

    # 卸载插件
    await host.unload_plugin("fake_scheduler_test")

    # 验证任务已清理
    assert scheduler.list_tasks() == []
    await scheduler.stop()


async def test_unload_plugin_without_scheduler_is_noop() -> None:
    """PluginRuntimeHost 没有 scheduler 时, unload 不 raise."""
    broker = ToolBroker()
    host = PluginRuntimeHost(
        tool_broker=broker,
        scheduler=None,
    )

    package = _make_fake_package()
    ctx = RuntimePluginContext(
        plugin_id="fake_scheduler_test",
        plugin_config={},
        data_dir=Path("."),
        gateway=FakeGateway(),  # type: ignore[arg-type]
        tool_broker=broker,
    )
    await host.load_plugin(package, ctx)
    await host.unload_plugin("fake_scheduler_test")
    # 只要不 raise 就算通过


# endregion


# region RuntimeApp lifecycle tests


async def test_app_start_starts_scheduler() -> None:
    """RuntimeApp start/stop 正确启停 scheduler."""
    scheduler = RuntimeScheduler()
    gw = FakeGateway()

    run_manager = InMemoryRunManager()
    thread_manager = InMemoryThreadManager()
    channel_event_store = InMemoryChannelEventStore()

    app = RuntimeApp(
        gateway=gw,  # type: ignore[arg-type]
        router=None,  # type: ignore[arg-type]
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=None,  # type: ignore[arg-type]
        scheduler=scheduler,
    )

    await app.start()
    assert scheduler._started is True

    await app.stop()
    assert scheduler._started is False


async def test_app_stop_order() -> None:
    """验证 stop 顺序: gateway -> scheduler -> plugin_host."""
    order: list[str] = []

    scheduler = RuntimeScheduler()

    # 包装 scheduler.stop 记录调用顺序
    _original_scheduler_stop = scheduler.stop

    async def _tracked_scheduler_stop() -> None:
        order.append("scheduler")
        await _original_scheduler_stop()

    scheduler.stop = _tracked_scheduler_stop  # type: ignore[assignment]

    gw = FakeGateway()
    _original_gw_stop = gw.stop

    async def _tracked_gw_stop() -> None:
        order.append("gateway")
        await _original_gw_stop()

    gw.stop = _tracked_gw_stop  # type: ignore[assignment]

    broker = ToolBroker()
    host = PluginRuntimeHost(tool_broker=broker)
    _original_host_teardown = host.teardown_all

    async def _tracked_host_teardown() -> None:
        order.append("plugin_host")
        await _original_host_teardown()

    host.teardown_all = _tracked_host_teardown  # type: ignore[assignment]

    run_manager = InMemoryRunManager()
    thread_manager = InMemoryThreadManager()
    channel_event_store = InMemoryChannelEventStore()

    app = RuntimeApp(
        gateway=gw,  # type: ignore[arg-type]
        router=None,  # type: ignore[arg-type]
        thread_manager=thread_manager,
        run_manager=run_manager,
        channel_event_store=channel_event_store,
        pipeline=None,  # type: ignore[arg-type]
        scheduler=scheduler,
        plugin_runtime_host=host,
    )

    await app.start()
    await app.stop()

    assert order == ["gateway", "scheduler", "plugin_host"]


# endregion
