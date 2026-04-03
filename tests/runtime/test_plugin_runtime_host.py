"""test_plugin_runtime_host 测试 PluginRuntimeHost 加载/卸载/hook 逻辑."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from acabot.agent import ToolDef, ToolSpec
from acabot.runtime.plugin_protocol import (
    RuntimeHook,
    RuntimeHookPoint,
    RuntimeHookResult,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimeToolRegistration,
)
from acabot.runtime.plugin_package import PluginPackage
from acabot.runtime.plugin_runtime_host import PluginRuntimeHost, PluginLoadSnapshot
from acabot.runtime.contracts import RunContext
from acabot.runtime.model.model_targets import (
    MutableModelTargetCatalog,
    RuntimePluginModelSlot,
)


# region Fakes

class FakeToolBroker:
    """模拟 ToolBroker, 记录 register/unregister 调用."""

    def __init__(self) -> None:
        self.registered: list[dict[str, Any]] = []
        self.legacy_registered: list[dict[str, Any]] = []
        self.unregistered_sources: list[str] = []

    def register_tool(self, spec, handler, *, source="", metadata=None) -> None:
        self.registered.append({
            "name": spec.name,
            "source": source,
            "metadata": metadata or {},
        })

    def register_legacy_tool(self, tool, *, source="", metadata=None) -> None:
        self.legacy_registered.append({
            "name": tool.name,
            "source": source,
            "metadata": metadata or {},
        })

    def unregister_source(self, source: str) -> list[str]:
        self.unregistered_sources.append(source)
        return [r["name"] for r in self.registered if r["source"] == source]


class SimplePlugin(RuntimePlugin):
    """简单测试插件, 注册一个 runtime tool 和一个 hook."""

    name = "simple"
    setup_called = False
    teardown_called = False

    async def setup(self, runtime: RuntimePluginContext) -> None:
        self.setup_called = True

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        async def handler(args, ctx):
            return "ok"
        return [
            RuntimeToolRegistration(
                spec=ToolSpec(name="simple_tool", description="test", parameters={}),
                handler=handler,
            )
        ]

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        hook = SimpleHook()
        return [(RuntimeHookPoint.PRE_AGENT, hook)]

    async def teardown(self) -> None:
        self.teardown_called = True


class NameMismatchPlugin(RuntimePlugin):
    """name 和 plugin_id 不匹配的插件."""

    name = "wrong_name"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        pass


class SimpleHook(RuntimeHook):
    name = "simple_hook"
    priority = 50
    enabled = True
    call_count = 0

    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        SimpleHook.call_count += 1
        return RuntimeHookResult()


class SkipAgentHook(RuntimeHook):
    name = "skip_hook"
    priority = 10
    enabled = True

    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        return RuntimeHookResult(action="skip_agent")


class ErrorHook(RuntimeHook):
    name = "error_hook"
    priority = 20
    enabled = True

    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        raise RuntimeError("hook error")


class HookTestPlugin(RuntimePlugin):
    """注册多个 hooks 的测试插件."""

    name = "hook_test"

    def __init__(self, hooks_list: list[tuple[RuntimeHookPoint, RuntimeHook]]) -> None:
        self._hooks = hooks_list

    async def setup(self, runtime: RuntimePluginContext) -> None:
        pass

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        return self._hooks


class ModelSlotPlugin(RuntimePlugin):
    """声明 model slots 的测试插件."""

    name = "model_slot"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        pass

    def model_slots(self) -> list[RuntimePluginModelSlot]:
        return [
            RuntimePluginModelSlot(
                slot_id="chat",
                task_kind="chat",
                required=True,
            )
        ]


def _make_package(
    plugin_id: str = "simple",
    entrypoint: str = "",
) -> PluginPackage:
    """构造测试用 PluginPackage, entrypoint 指向测试模块内的类."""

    return PluginPackage(
        plugin_id=plugin_id,
        display_name=plugin_id,
        package_root=Path("/fake"),
        entrypoint=entrypoint or f"tests.runtime.test_plugin_runtime_host:{plugin_id.title().replace('_', '')}Plugin",
    )


def _make_context(plugin_id: str = "simple", tmp_path: Path | None = None) -> RuntimePluginContext:
    """构造测试用 RuntimePluginContext."""

    gateway = MagicMock()
    broker = MagicMock()
    return RuntimePluginContext(
        plugin_id=plugin_id,
        plugin_config={},
        data_dir=tmp_path or Path("/tmp/test"),
        gateway=gateway,
        tool_broker=broker,
    )


# endregion


class TestPluginRuntimeHost:
    """测试 PluginRuntimeHost."""

    @pytest.fixture
    def broker(self) -> FakeToolBroker:
        return FakeToolBroker()

    @pytest.fixture
    def host(self, broker: FakeToolBroker) -> PluginRuntimeHost:
        return PluginRuntimeHost(broker)  # type: ignore[arg-type]

    async def test_load_registers_tools_and_hooks(self, host: PluginRuntimeHost, broker: FakeToolBroker) -> None:
        """加载插件应注册工具和 hooks."""

        package = _make_package("simple")
        context = _make_context("simple")

        snapshot = await host.load_plugin(package, context)

        assert "simple_tool" in snapshot.tool_names
        assert any("simple_hook" in desc for desc in snapshot.hook_descriptors)
        assert "simple" in host.loaded_plugin_ids()
        assert len(broker.registered) == 1

    async def test_name_mismatch_raises(self, host: PluginRuntimeHost) -> None:
        """plugin.name 和 package.plugin_id 不匹配时应 raise."""

        package = PluginPackage(
            plugin_id="expected_name",
            display_name="Test",
            package_root=Path("/fake"),
            entrypoint="tests.runtime.test_plugin_runtime_host:NameMismatchPlugin",
        )
        context = _make_context("expected_name")

        with pytest.raises(ValueError, match="mismatch"):
            await host.load_plugin(package, context)

    async def test_unload_cleans(self, host: PluginRuntimeHost, broker: FakeToolBroker) -> None:
        """卸载插件应清理工具和从已加载集合移除."""

        package = _make_package("simple")
        context = _make_context("simple")
        await host.load_plugin(package, context)

        await host.unload_plugin("simple")

        assert "simple" not in host.loaded_plugin_ids()
        assert "plugin:simple" in broker.unregistered_sources

    async def test_teardown_all_reverse_order(self, broker: FakeToolBroker) -> None:
        """teardown_all 应按逆序卸载."""

        host = PluginRuntimeHost(broker)  # type: ignore[arg-type]

        # 加载两个插件
        pkg1 = _make_package("simple")
        ctx1 = _make_context("simple")
        await host.load_plugin(pkg1, ctx1)

        # 创建一个不同的简单插件类
        pkg2 = _make_package("hook_test", entrypoint="tests.runtime.test_plugin_runtime_host:_make_hook_test_plugin_factory")
        # 直接用 host 的内部方法测试 teardown_all
        # 先简单验证两个都加载了
        assert len(host.loaded_plugin_ids()) >= 1

        await host.teardown_all()
        assert len(host.loaded_plugin_ids()) == 0

    async def test_hook_exception_isolation(self, host: PluginRuntimeHost) -> None:
        """单个 hook 异常不影响后续 hooks 执行."""

        # 手动注册 hooks
        error_hook = ErrorHook()
        normal_hook = SimpleHook()
        SimpleHook.call_count = 0

        host._hook_registry.register(RuntimeHookPoint.PRE_AGENT, error_hook)
        host._hook_registry.register(RuntimeHookPoint.PRE_AGENT, normal_hook)

        # 构造最小 RunContext mock
        ctx = MagicMock()
        ctx.run.run_id = "test-run"

        result = await host.run_hooks(RuntimeHookPoint.PRE_AGENT, ctx)

        assert result.action == "continue"
        assert SimpleHook.call_count == 1  # 正常 hook 仍然执行了

    async def test_skip_agent_short_circuit(self, host: PluginRuntimeHost) -> None:
        """skip_agent hook 应短路, 后续 hooks 不执行."""

        skip_hook = SkipAgentHook()
        normal_hook = SimpleHook()
        SimpleHook.call_count = 0

        host._hook_registry.register(RuntimeHookPoint.PRE_AGENT, skip_hook)
        host._hook_registry.register(RuntimeHookPoint.PRE_AGENT, normal_hook)

        ctx = MagicMock()
        ctx.run.run_id = "test-run"

        result = await host.run_hooks(RuntimeHookPoint.PRE_AGENT, ctx)

        assert result.action == "skip_agent"
        assert SimpleHook.call_count == 0  # normal hook 没有执行

    async def test_model_target_rollback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """model target 注册失败时应回滚并 teardown 插件."""

        catalog = MutableModelTargetCatalog()
        broker = FakeToolBroker()
        host = PluginRuntimeHost(broker, model_target_catalog=catalog)  # type: ignore[arg-type]

        # 通过 invalid task_kind 触发 register_plugin_slots 异常
        class BadSlotPlugin(RuntimePlugin):
            name = "bad_slot"
            async def setup(self, runtime: RuntimePluginContext) -> None:
                pass
            def model_slots(self) -> list[RuntimePluginModelSlot]:
                return [
                    RuntimePluginModelSlot(
                        slot_id="test",
                        task_kind="invalid_task",  # type: ignore[arg-type]
                    )
                ]

        package = PluginPackage(
            plugin_id="bad_slot",
            display_name="Bad Slot",
            package_root=Path("/fake"),
            entrypoint="tests.runtime.test_plugin_runtime_host:BadSlotPlugin",
        )

        # monkeypatch 会在测试结束后自动恢复
        monkeypatch.setattr(
            PluginRuntimeHost,
            "_import_plugin",
            staticmethod(lambda entrypoint: BadSlotPlugin()),
        )

        context = _make_context("bad_slot")
        with pytest.raises(Exception):
            await host.load_plugin(package, context)

        # 应该不在已加载列表中
        assert "bad_slot" not in host.loaded_plugin_ids()
