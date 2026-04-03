"""runtime.plugin_reconciler 提供插件系统的决策层.

PluginReconciler 读取 Package + Spec + Host 当前状态, 计算差异,
调用 Host 执行 load/unload, 写入 Status.
它是插件生命周期管理的大脑, Host 是手脚.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from .plugin_package import PackageCatalog, PluginPackage
from .plugin_protocol import RuntimePluginContext
from .plugin_spec import PluginSpec, SpecStore
from .plugin_status import PluginStatus, StatusStore
from .plugin_runtime_host import PluginRuntimeHost

logger = logging.getLogger("acabot.runtime.plugin")


class PluginReconciler:
    """插件系统的决策层.

    读取 Package (已安装代码) + Spec (操作者意图) + Host (运行时状态),
    计算差异并执行收敛.

    Attributes:
        _catalog (PackageCatalog): 插件包目录.
        _spec_store (SpecStore): 操作者意图存储.
        _status_store (StatusStore): 状态观察结果存储.
        _host (PluginRuntimeHost): 运行时执行层.
        _context_factory (Callable[[str, dict[str, Any]], RuntimePluginContext]):
            bootstrap 注入的上下文工厂, 接收 (plugin_id, merged_config) 返回 RuntimePluginContext.
    """

    def __init__(
        self,
        catalog: PackageCatalog,
        spec_store: SpecStore,
        status_store: StatusStore,
        host: PluginRuntimeHost,
        context_factory: Callable[[str, dict[str, Any]], RuntimePluginContext],
    ) -> None:
        """初始化 PluginReconciler.

        Args:
            catalog: 插件包目录.
            spec_store: 操作者意图存储.
            status_store: 状态观察结果存储.
            host: 运行时执行层.
            context_factory: 上下文工厂闭包.
        """

        self._catalog = catalog
        self._spec_store = spec_store
        self._status_store = status_store
        self._host = host
        self._context_factory = context_factory

    async def reconcile_all(self) -> list[PluginStatus]:
        """全量 reconcile.

        流程:
        1. 扫描 packages + 加载 specs
        2. 对解析失败的 plugin_id 生成 failed 状态 (先 unload 已加载的)
        3. 收集所有需要处理的 plugin_id
        4. 按 plugin_id 字母序逐个 reconcile

        Returns:
            所有插件的最终状态列表.
        """

        packages, package_errors = self._catalog.scan()
        specs, spec_errors = self._spec_store.load_all()

        results: list[PluginStatus] = []
        error_ids: set[str] = set()

        # 处理 package 扫描错误
        for err in package_errors:
            error_ids.add(err.plugin_id)
            # 如果之前已加载, 先 unload
            if err.plugin_id in self._host.loaded_plugin_ids():
                try:
                    await self._host.unload_plugin(err.plugin_id)
                except Exception:
                    logger.exception(
                        "Failed to unload errored plugin: %s", err.plugin_id
                    )
            status = PluginStatus(
                plugin_id=err.plugin_id,
                phase="failed",
                load_error=f"bad manifest: {err.error}",
                updated_at=self._now(),
            )
            self._status_store.save(status)
            results.append(status)

        # 处理 spec 解析错误
        for err in spec_errors:
            if err.plugin_id in error_ids:
                continue
            error_ids.add(err.plugin_id)
            if err.plugin_id in self._host.loaded_plugin_ids():
                try:
                    await self._host.unload_plugin(err.plugin_id)
                except Exception:
                    logger.exception(
                        "Failed to unload errored plugin: %s", err.plugin_id
                    )
            status = PluginStatus(
                plugin_id=err.plugin_id,
                phase="failed",
                load_error=f"bad spec: {err.error}",
                updated_at=self._now(),
            )
            self._status_store.save(status)
            results.append(status)

        # 收集所有需要处理的 plugin_id
        all_ids = (
            set(packages) | set(specs) | self._host.loaded_plugin_ids()
        ) - error_ids

        for plugin_id in sorted(all_ids):
            status = await self._reconcile(
                plugin_id,
                package=packages.get(plugin_id),
                spec=specs.get(plugin_id),
            )
            results.append(status)

        return results

    async def reconcile_one(self, plugin_id: str) -> PluginStatus:
        """单插件 reconcile.

        重新读取该插件的 package 和 spec, 执行 reconcile.

        Args:
            plugin_id: 要 reconcile 的插件 ID.

        Returns:
            该插件的最终状态.
        """

        package = self._catalog.get(plugin_id)
        spec = self._spec_store.load(plugin_id)
        return await self._reconcile(plugin_id, package=package, spec=spec)

    async def _reconcile(
        self,
        plugin_id: str,
        package: PluginPackage | None,
        spec: PluginSpec | None,
    ) -> PluginStatus:
        """单插件 reconcile 核心逻辑.

        决策矩阵:
        - Spec 存在但 Package 不见 -> uninstalled
        - 没有 Spec 或 disabled -> disabled
        - Package + Spec enabled -> load (先 unload 旧的)

        Args:
            plugin_id: 插件 ID.
            package: 插件包 (可能不存在).
            spec: 操作者意图 (可能不存在).

        Returns:
            该插件的最终状态.
        """

        is_loaded = plugin_id in self._host.loaded_plugin_ids()

        # Spec 存在但 Package 不见
        if spec and not package:
            if is_loaded:
                try:
                    await self._host.unload_plugin(plugin_id)
                except Exception:
                    logger.exception(
                        "Failed to unload plugin with missing package: %s", plugin_id
                    )
            status = PluginStatus(
                plugin_id=plugin_id,
                phase="uninstalled",
                updated_at=self._now(),
            )
            self._status_store.save(status)
            return status

        # 没有 Spec 或 Spec disabled
        if not spec or not spec.enabled:
            if is_loaded:
                try:
                    await self._host.unload_plugin(plugin_id)
                except Exception:
                    logger.exception(
                        "Failed to unload disabled plugin: %s", plugin_id
                    )
            status = PluginStatus(
                plugin_id=plugin_id,
                phase="disabled",
                updated_at=self._now(),
            )
            self._status_store.save(status)
            return status

        # Package + Spec enabled -> load
        if package and spec.enabled:
            if is_loaded:
                try:
                    await self._host.unload_plugin(plugin_id)
                except Exception as exc:
                    logger.exception(
                        "Failed to unload plugin before reload: %s", plugin_id
                    )
                    status = PluginStatus(
                        plugin_id=plugin_id,
                        phase="failed",
                        load_error=str(exc),
                        updated_at=self._now(),
                    )
                    self._status_store.save(status)
                    return status

            # 合并配置: default_config | spec.config
            merged_config = {**package.default_config, **spec.config}
            context = self._context_factory(plugin_id, merged_config)

            try:
                snapshot = await self._host.load_plugin(package, context)
                status = PluginStatus(
                    plugin_id=plugin_id,
                    phase="loaded",
                    registered_tools=list(snapshot.tool_names),
                    registered_hooks=list(snapshot.hook_descriptors),
                    updated_at=self._now(),
                )
            except Exception as exc:
                logger.exception("Failed to load plugin: %s", plugin_id)
                status = PluginStatus(
                    plugin_id=plugin_id,
                    phase="failed",
                    load_error=str(exc),
                    updated_at=self._now(),
                )

            self._status_store.save(status)
            return status

        # fallback: disabled (Package 存在但没有 Spec)
        status = PluginStatus(
            plugin_id=plugin_id,
            phase="disabled",
            updated_at=self._now(),
        )
        self._status_store.save(status)
        return status

    @staticmethod
    def _now() -> str:
        """返回当前时间的 ISO 8601 字符串."""

        return datetime.now(timezone.utc).isoformat()


__all__ = [
    "PluginReconciler",
]
