"""test_plugin_reconciler 测试 PluginReconciler 决策逻辑."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from acabot.runtime.plugin_package import PackageCatalog, PluginPackage
from acabot.runtime.plugin_protocol import (
    RuntimePlugin,
    RuntimePluginContext,
    RuntimeToolRegistration,
)
from acabot.runtime.plugin_spec import PluginSpec, SpecStore
from acabot.runtime.plugin_status import PluginStatus, StatusStore
from acabot.runtime.plugin_runtime_host import PluginRuntimeHost, PluginLoadSnapshot
from acabot.runtime.plugin_reconciler import PluginReconciler
from acabot.agent import ToolSpec


# region Fakes

class FakeToolBroker:
    """最小 ToolBroker 模拟."""

    def __init__(self) -> None:
        self.registered: list[str] = []
        self.unregistered: list[str] = []

    def register_tool(self, spec, handler, *, source="", metadata=None) -> None:
        self.registered.append(spec.name)

    def register_legacy_tool(self, tool, *, source="", metadata=None) -> None:
        self.registered.append(tool.name)

    def unregister_source(self, source: str) -> list[str]:
        self.unregistered.append(source)
        return []


class GoodPlugin(RuntimePlugin):
    """总是成功加载的测试插件."""

    name = "good"
    setup_called = False

    async def setup(self, runtime: RuntimePluginContext) -> None:
        GoodPlugin.setup_called = True

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        async def handler(args, ctx):
            return "ok"
        return [
            RuntimeToolRegistration(
                spec=ToolSpec(name="good_tool", description="test", parameters={}),
                handler=handler,
            )
        ]


class FailPlugin(RuntimePlugin):
    """总是 setup 失败的测试插件."""

    name = "fail_plugin"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        raise RuntimeError("setup boom")


class ConfigPlugin(RuntimePlugin):
    """记录收到的配置的测试插件."""

    name = "config_test"
    received_config: dict[str, Any] = {}

    async def setup(self, runtime: RuntimePluginContext) -> None:
        ConfigPlugin.received_config = dict(runtime.plugin_config)


# endregion


def _write_manifest(plugin_dir: Path, manifest: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def _make_context_factory(tmp_path: Path):
    """构造测试用 context_factory."""

    def factory(plugin_id: str, plugin_config: dict[str, Any]) -> RuntimePluginContext:
        data_dir = tmp_path / "data" / plugin_id
        data_dir.mkdir(parents=True, exist_ok=True)
        gateway = MagicMock()
        broker = MagicMock()
        return RuntimePluginContext(
            plugin_id=plugin_id,
            plugin_config=plugin_config,
            data_dir=data_dir,
            gateway=gateway,
            tool_broker=broker,
        )

    return factory


class TestPluginReconciler:
    """测试 PluginReconciler."""

    @pytest.fixture
    def dirs(self, tmp_path: Path):
        """创建测试用目录结构."""
        ext_dir = tmp_path / "extensions" / "plugins"
        ext_dir.mkdir(parents=True)
        config_dir = tmp_path / "config" / "plugins"
        config_dir.mkdir(parents=True)
        data_dir = tmp_path / "data" / "plugins"
        data_dir.mkdir(parents=True)
        return ext_dir, config_dir, data_dir

    def _make_reconciler(self, dirs, tmp_path: Path, broker=None):
        ext_dir, config_dir, data_dir = dirs
        if broker is None:
            broker = FakeToolBroker()
        catalog = PackageCatalog(ext_dir)
        spec_store = SpecStore(config_dir)
        status_store = StatusStore(data_dir)
        host = PluginRuntimeHost(broker)  # type: ignore[arg-type]
        context_factory = _make_context_factory(tmp_path)
        reconciler = PluginReconciler(catalog, spec_store, status_store, host, context_factory)
        return reconciler, catalog, spec_store, status_store, host

    async def test_reconcile_loads_enabled(self, dirs, tmp_path: Path) -> None:
        """enabled 的插件应被加载."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, status_store, host = self._make_reconciler(dirs, tmp_path)

        # 安装插件包
        _write_manifest(ext_dir / "good", {
            "plugin": {
                "plugin_id": "good",
                "display_name": "Good",
                "entrypoint": "tests.runtime.test_plugin_reconciler:GoodPlugin",
            }
        })

        # 启用
        spec_store.save(PluginSpec(plugin_id="good", enabled=True))

        GoodPlugin.setup_called = False
        results = await reconciler.reconcile_all()

        loaded = [s for s in results if s.phase == "loaded"]
        assert len(loaded) == 1
        assert loaded[0].plugin_id == "good"
        assert GoodPlugin.setup_called

    async def test_disables_without_spec(self, dirs, tmp_path: Path) -> None:
        """没有 spec 的插件应为 disabled."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, *_ = self._make_reconciler(dirs, tmp_path)

        _write_manifest(ext_dir / "orphan", {
            "plugin": {"plugin_id": "orphan", "display_name": "Orphan"}
        })

        results = await reconciler.reconcile_all()
        orphan = [s for s in results if s.plugin_id == "orphan"]
        assert len(orphan) == 1
        assert orphan[0].phase == "disabled"

    async def test_reports_uninstalled(self, dirs, tmp_path: Path) -> None:
        """有 spec 但没有 package 的插件应为 uninstalled."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, *_ = self._make_reconciler(dirs, tmp_path)

        spec_store.save(PluginSpec(plugin_id="missing_pkg", enabled=True))

        results = await reconciler.reconcile_all()
        missing = [s for s in results if s.plugin_id == "missing_pkg"]
        assert len(missing) == 1
        assert missing[0].phase == "uninstalled"

    async def test_catches_load_failure(self, dirs, tmp_path: Path) -> None:
        """加载失败的插件应为 failed."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, *_ = self._make_reconciler(dirs, tmp_path)

        _write_manifest(ext_dir / "fail_plugin", {
            "plugin": {
                "plugin_id": "fail_plugin",
                "display_name": "Fail",
                "entrypoint": "tests.runtime.test_plugin_reconciler:FailPlugin",
            }
        })
        spec_store.save(PluginSpec(plugin_id="fail_plugin", enabled=True))

        results = await reconciler.reconcile_all()
        failed = [s for s in results if s.plugin_id == "fail_plugin"]
        assert len(failed) == 1
        assert failed[0].phase == "failed"
        assert "boom" in failed[0].load_error

    async def test_unloads_errored_manifests(self, dirs, tmp_path: Path) -> None:
        """manifest 解析失败时, 已加载的插件应被 unload."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, status_store, host = self._make_reconciler(dirs, tmp_path)

        # 先正常加载
        _write_manifest(ext_dir / "good", {
            "plugin": {
                "plugin_id": "good",
                "display_name": "Good",
                "entrypoint": "tests.runtime.test_plugin_reconciler:GoodPlugin",
            }
        })
        spec_store.save(PluginSpec(plugin_id="good", enabled=True))
        await reconciler.reconcile_all()
        assert "good" in host.loaded_plugin_ids()

        # 破坏 manifest
        (ext_dir / "good" / "plugin.yaml").write_text("bad: [yaml: {{", encoding="utf-8")

        results = await reconciler.reconcile_all()
        good_results = [s for s in results if s.plugin_id == "good"]
        assert len(good_results) == 1
        assert good_results[0].phase == "failed"
        assert "good" not in host.loaded_plugin_ids()

    async def test_reconcile_one(self, dirs, tmp_path: Path) -> None:
        """reconcile_one 应只处理单个插件."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, *_, host = self._make_reconciler(dirs, tmp_path)

        _write_manifest(ext_dir / "good", {
            "plugin": {
                "plugin_id": "good",
                "display_name": "Good",
                "entrypoint": "tests.runtime.test_plugin_reconciler:GoodPlugin",
            }
        })
        spec_store.save(PluginSpec(plugin_id="good", enabled=True))

        # 先 scan 一次让 catalog 有缓存
        catalog.scan()

        GoodPlugin.setup_called = False
        status = await reconciler.reconcile_one("good")

        assert status.phase == "loaded"
        assert GoodPlugin.setup_called

    async def test_config_merge(self, dirs, tmp_path: Path) -> None:
        """reconcile 时应合并 default_config 和 spec.config."""

        ext_dir, config_dir, data_dir = dirs
        reconciler, catalog, spec_store, *_ = self._make_reconciler(dirs, tmp_path)

        _write_manifest(ext_dir / "config_test", {
            "plugin": {
                "plugin_id": "config_test",
                "display_name": "Config Test",
                "entrypoint": "tests.runtime.test_plugin_reconciler:ConfigPlugin",
                "default_config": {"a": 1, "b": 2},
            }
        })
        spec_store.save(PluginSpec(
            plugin_id="config_test",
            enabled=True,
            config={"b": 99, "c": 3},
        ))

        ConfigPlugin.received_config = {}
        await reconciler.reconcile_all()

        # default_config | spec.config -> b 被 override, c 被新增
        assert ConfigPlugin.received_config == {"a": 1, "b": 99, "c": 3}
