"""新插件体系集成冒烟测试.

验证 Wave 1 + Wave 2 的模块可以一起导入, 基本类型和组装逻辑无冲突.
"""

from __future__ import annotations


def test_import_new_plugin_modules():
    """所有新插件模块都能正常导入."""

    from acabot.runtime.plugin_protocol import (
        RuntimeHook,
        RuntimeHookPoint,
        RuntimeHookResult,
        RuntimePlugin,
        RuntimePluginContext,
        RuntimeToolRegistration,
    )
    from acabot.runtime.plugin_package import PackageCatalog, PackageScanError, PluginPackage
    from acabot.runtime.plugin_spec import PluginSpec, SpecParseError, SpecStore
    from acabot.runtime.plugin_status import PluginPhase, PluginStatus, StatusStore
    from acabot.runtime.plugin_runtime_host import PluginLoadSnapshot, PluginRuntimeHost
    from acabot.runtime.plugin_reconciler import PluginReconciler

    assert RuntimeHookPoint.ON_EVENT.value == "on_event"
    assert PluginSpec(plugin_id="test", enabled=True).enabled is True
    assert PluginStatus(plugin_id="test", phase="loaded").phase == "loaded"


def test_import_from_runtime_facade():
    """runtime.__init__ facade 导出新符号."""

    from acabot.runtime import (
        PluginReconciler,
        PluginRuntimeHost,
        PluginLoadSnapshot,
        PluginPackage,
        PackageCatalog,
        PluginSpec,
        SpecStore,
        PluginStatus,
        StatusStore,
        RuntimePlugin,
        RuntimePluginContext,
        RuntimeHookPoint,
        RuntimeHookResult,
        RuntimeToolRegistration,
    )

    assert PluginReconciler is not None
    assert PluginRuntimeHost is not None


def test_import_runtime_app_with_new_deps():
    """RuntimeApp 和新依赖一起导入不报错."""

    from acabot.runtime import RuntimeApp, PluginReconciler, PluginRuntimeHost

    assert RuntimeApp is not None
    assert PluginReconciler is not None
    assert PluginRuntimeHost is not None


def test_backend_bridge_tool_plugin_still_importable():
    """BackendBridgeToolPlugin 过渡期代码仍可导入."""

    from acabot.runtime.plugins import BackendBridgeToolPlugin

    plugin = BackendBridgeToolPlugin()
    assert plugin.name == "backend_bridge_tool"
