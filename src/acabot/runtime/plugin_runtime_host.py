"""runtime.plugin_runtime_host 提供插件的运行时执行层.

PluginRuntimeHost 持有已加载的插件实例, 执行 load/unload/teardown,
管理 hook 和 tool 注册, 提供 run_hooks() 给 pipeline 调用.
它只做执行, 不做决策 -- 决策由 PluginReconciler 负责.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from acabot.runtime.tool_broker import ToolBroker

from .plugin_protocol import (
    RuntimeHook,
    RuntimeHookPoint,
    RuntimeHookResult,
    RuntimePlugin,
    RuntimePluginContext,
    RuntimeToolRegistration,
)
from .plugin_package import PluginPackage

if TYPE_CHECKING:
    from .contracts import RunContext
    from .model.model_targets import MutableModelTargetCatalog
    from .scheduler import RuntimeScheduler

logger = logging.getLogger("acabot.runtime.plugin")


@dataclass(frozen=True)
class PluginLoadSnapshot:
    """Host 加载一个插件后返回的摘要.

    Reconciler 用它填充 PluginStatus.

    Attributes:
        tool_names (list[str]): 已注册的工具名列表.
        hook_descriptors (list[str]): 已注册的 hook 描述列表, 如 "pre_agent:OpsCommandHook".
    """

    tool_names: list[str] = field(default_factory=list)
    hook_descriptors: list[str] = field(default_factory=list)


class RuntimeHookRegistry:
    """按 RuntimeHookPoint 分组管理 runtime hooks.

    维护一个字典, key 是 hook point, value 是该点上的 hook 列表.
    按 priority 排序, 保证执行顺序.

    Attributes:
        _hooks (dict[RuntimeHookPoint, list[RuntimeHook]]): 按 hook point 分组的 hook 表.
    """

    def __init__(self) -> None:
        self._hooks: dict[RuntimeHookPoint, list[RuntimeHook]] = {}

    def register(self, point: RuntimeHookPoint, hook: RuntimeHook) -> None:
        """注册 hook 到指定切入点.

        Args:
            point: hook 切入点.
            hook: 要注册的 hook 实例.
        """

        if point not in self._hooks:
            self._hooks[point] = []
        self._hooks[point].append(hook)
        self._hooks[point].sort(key=lambda item: item.priority)
        logger.info(
            "Runtime hook registered: %s @ %s (priority=%s)",
            hook.name,
            point.value,
            hook.priority,
        )

    def get(self, point: RuntimeHookPoint) -> list[RuntimeHook]:
        """获取指定 hook 点的已启用 hooks.

        Args:
            point: hook 切入点.

        Returns:
            按优先级排序的 hook 列表. 无 hooks 时返回空列表.
        """

        return [hook for hook in self._hooks.get(point, []) if hook.enabled]


class PluginRuntimeHost:
    """持有已加载的插件实例, 执行 load/unload/teardown, 管理 hook 和 tool 注册.

    Attributes:
        _tool_broker (ToolBroker): runtime 工具入口.
        _model_target_catalog (MutableModelTargetCatalog | None): 模型 target 目录.
        _loaded (dict[str, RuntimePlugin]): plugin_id -> 已加载插件实例.
        _hook_registry (RuntimeHookRegistry): hook 注册表.
        _plugin_hooks (dict[str, list[tuple[RuntimeHookPoint, RuntimeHook]]]): 每个插件注册的 hooks.
        _plugin_tool_sources (dict[str, str]): 每个插件在 ToolBroker 里的 source 标识.
        _plugin_model_target_ids (dict[str, list[str]]): 每个插件注册的 model target ids.
    """

    def __init__(
        self,
        tool_broker: ToolBroker,
        model_target_catalog: MutableModelTargetCatalog | None = None,
        scheduler: RuntimeScheduler | None = None,
    ) -> None:
        """初始化 PluginRuntimeHost.

        Args:
            tool_broker: runtime 工具入口.
            model_target_catalog: 可选的模型 target 目录.
            scheduler: 可选的定时任务调度器, 用于 unload 时自动清理插件注册的定时任务.
        """

        self._tool_broker = tool_broker
        self._model_target_catalog = model_target_catalog
        self._scheduler = scheduler
        self._loaded: dict[str, RuntimePlugin] = {}
        self._hook_registry = RuntimeHookRegistry()
        self._plugin_hooks: dict[str, list[tuple[RuntimeHookPoint, RuntimeHook]]] = {}
        self._plugin_tool_sources: dict[str, str] = {}
        self._plugin_model_target_ids: dict[str, list[str]] = {}

    async def load_plugin(
        self,
        package: PluginPackage,
        context: RuntimePluginContext,
    ) -> PluginLoadSnapshot:
        """加载一个插件.

        流程:
        1. 按 entrypoint 导入并实例化 RuntimePlugin
        2. 校验 plugin.name == package.plugin_id
        3. 调用 setup(context)
        4. 注册 model targets (如果有), 失败时回滚
        5. 注册 hooks
        6. 注册 runtime_tools 和 legacy tools
        7. 返回 PluginLoadSnapshot

        Args:
            package: 插件包定义.
            context: 插件 setup 上下文.

        Returns:
            PluginLoadSnapshot: 加载摘要.

        Raises:
            ValueError: entrypoint 格式错误或 plugin.name 不匹配.
            Exception: setup 或注册过程中的任意错误.
        """

        # 1. 导入和实例化
        plugin = self._import_plugin(package.entrypoint)

        # 2. name 校验
        if plugin.name != package.plugin_id:
            raise ValueError(
                f"Plugin name mismatch: plugin.name='{plugin.name}' "
                f"but package.plugin_id='{package.plugin_id}'"
            )

        # 3. setup
        await plugin.setup(context)

        # 4. model targets
        if self._model_target_catalog is not None:
            try:
                targets = self._model_target_catalog.register_plugin_slots(
                    plugin_id=package.plugin_id,
                    slots=plugin.model_slots(),
                )
                self._plugin_model_target_ids[package.plugin_id] = [
                    target.target_id for target in targets
                ]
                await self._revalidate_model_registry()
            except Exception:
                logger.exception(
                    "Plugin '%s' model target registration failed, rolling back",
                    package.plugin_id,
                )
                self._model_target_catalog.unregister_plugin_targets(package.plugin_id)
                self._plugin_model_target_ids.pop(package.plugin_id, None)
                try:
                    await self._revalidate_model_registry()
                except Exception:
                    logger.exception(
                        "Plugin '%s' model target rollback revalidation failed",
                        package.plugin_id,
                    )
                try:
                    await plugin.teardown()
                except Exception:
                    logger.exception(
                        "Plugin '%s' teardown failed after model target rollback",
                        package.plugin_id,
                    )
                raise

        # 5. hooks
        plugin_hooks = list(plugin.hooks())
        for point, hook in plugin_hooks:
            self._hook_registry.register(point, hook)
        self._plugin_hooks[package.plugin_id] = plugin_hooks

        # 6. tools
        source = f"plugin:{package.plugin_id}"
        self._plugin_tool_sources[package.plugin_id] = source

        tool_names: list[str] = []

        # runtime tools
        runtime_tools = list(plugin.runtime_tools())
        for registration in runtime_tools:
            self._tool_broker.register_tool(
                registration.spec,
                registration.handler,
                source=source,
                metadata={
                    "plugin_name": package.plugin_id,
                    **dict(registration.metadata),
                },
            )
            tool_names.append(registration.spec.name)

        # legacy tools
        legacy_tools = list(plugin.tools())
        for tool in legacy_tools:
            self._tool_broker.register_legacy_tool(
                tool,
                source=source,
                metadata={"plugin_name": package.plugin_id},
            )
            tool_names.append(tool.name)

        # 7. 记录并返回
        self._loaded[package.plugin_id] = plugin

        hook_descriptors = [
            f"{point.value}:{hook.name}" for point, hook in plugin_hooks
        ]

        logger.info(
            "Plugin loaded: %s (%s hooks, %s tools)",
            package.plugin_id,
            len(plugin_hooks),
            len(tool_names),
        )

        return PluginLoadSnapshot(
            tool_names=tool_names,
            hook_descriptors=hook_descriptors,
        )

    async def unload_plugin(self, plugin_id: str) -> None:
        """卸载一个已加载的插件.

        流程:
        1. 从 ToolBroker 注销工具
        2. 注销 model targets
        3. 调用 teardown()
        4. 移除 hooks, 重建 registry
        5. 从已加载集合移除

        Args:
            plugin_id: 要卸载的插件 ID.
        """

        plugin = self._loaded.get(plugin_id)
        if plugin is None:
            return

        # 1. 注销工具
        source = self._plugin_tool_sources.get(plugin_id, f"plugin:{plugin_id}")
        removed = self._tool_broker.unregister_source(source)
        if removed:
            logger.info(
                "Plugin tools removed: plugin=%s tools=%s",
                plugin_id,
                ",".join(removed),
            )

        # 1.5 注销定时任务
        if self._scheduler is not None:
            cancelled_tasks = await self._scheduler.unregister_by_owner(f"plugin:{plugin_id}")
            if cancelled_tasks:
                logger.info(
                    "Plugin scheduled tasks cancelled: plugin=%s count=%d",
                    plugin_id,
                    len(cancelled_tasks),
                )

        # 2. 注销 model targets
        if self._model_target_catalog is not None:
            self._model_target_catalog.unregister_plugin_targets(plugin_id)
            self._plugin_model_target_ids.pop(plugin_id, None)

        # 3. teardown
        try:
            await plugin.teardown()
        except Exception:
            logger.exception("Plugin '%s' teardown failed", plugin_id)

        # 4. 移除 hooks 并重建 registry
        self._plugin_hooks.pop(plugin_id, None)
        self._rebuild_hook_registry()

        # 5. 移除
        self._loaded.pop(plugin_id, None)
        self._plugin_tool_sources.pop(plugin_id, None)

        if self._model_target_catalog is not None:
            try:
                await self._revalidate_model_registry()
            except Exception:
                logger.exception(
                    "Model registry revalidation failed after unloading plugin '%s'",
                    plugin_id,
                )

        logger.info("Plugin unloaded: %s", plugin_id)

    async def teardown_all(self) -> None:
        """逆序清理所有已加载插件.

        逆序保证依赖关系正确: 后加载的先清理.
        """

        # dict 保持插入顺序, reversed 得到逆序
        for plugin_id in list(reversed(list(self._loaded))):
            await self.unload_plugin(plugin_id)

    def loaded_plugin_ids(self) -> set[str]:
        """返回已加载插件 ID 的拷贝集合.

        Returns:
            已加载插件 ID 集合.
        """

        return set(self._loaded)

    async def run_hooks(self, point: RuntimeHookPoint, ctx: RunContext) -> RuntimeHookResult:
        """执行指定 point 的 hooks.

        按 priority 顺序执行, 单个 hook 异常不影响其他 (记日志继续),
        skip_agent 短路返回.

        Args:
            point: hook 切入点.
            ctx: 当前 run 的执行上下文.

        Returns:
            聚合后的 RuntimeHookResult. 默认返回 continue.
        """

        for hook in self._hook_registry.get(point):
            try:
                result = await hook.handle(ctx)
            except Exception:
                logger.exception(
                    "Runtime hook failed: hook=%s point=%s run_id=%s",
                    hook.name,
                    point.value,
                    ctx.run.run_id,
                )
                continue
            if result.action == "skip_agent":
                return result
        return RuntimeHookResult()

    def _rebuild_hook_registry(self) -> None:
        """根据当前已加载插件重建 hook registry."""

        self._hook_registry = RuntimeHookRegistry()
        for plugin_id in self._loaded:
            for point, hook in self._plugin_hooks.get(plugin_id, []):
                self._hook_registry.register(point, hook)

    async def _revalidate_model_registry(self) -> None:
        """在插件 target 集合变化后触发一次模型 registry 重载.

        NOTE: 这个方法需要 control_plane 的支持才能真正生效.
        当前实现中, 如果 model_target_catalog 存在但没有 control_plane,
        则不执行 revalidation (静默跳过).
        """

        # NOTE: 完整的 revalidation 需要 control_plane.reload_models(),
        # 这个在 Host 独立运行时不可用. 当前版本静默跳过.
        # 未来 bootstrap 集成时, 通过注入 revalidation callback 解决.
        pass

    @staticmethod
    def _import_plugin(entrypoint: str) -> RuntimePlugin:
        """按 entrypoint 字符串导入并实例化 RuntimePlugin.

        Args:
            entrypoint: "module.path:ClassName" 格式的导入路径.

        Returns:
            RuntimePlugin 实例.

        Raises:
            ValueError: entrypoint 格式错误或符号不存在.
            TypeError: 导入对象不是 RuntimePlugin 实例.
        """

        if ":" not in entrypoint:
            raise ValueError(
                f"Plugin entrypoint must be 'module:Symbol', got '{entrypoint}'"
            )

        module_path, symbol_name = entrypoint.split(":", 1)
        module = importlib.import_module(module_path)
        symbol = getattr(module, symbol_name, None)
        if symbol is None:
            raise ValueError(
                f"Plugin symbol '{symbol_name}' not found in module '{module_path}'"
            )

        plugin = symbol() if isinstance(symbol, type) else symbol
        if not isinstance(plugin, RuntimePlugin):
            raise TypeError(
                f"Plugin entrypoint '{entrypoint}' did not resolve to RuntimePlugin instance"
            )
        return plugin


__all__ = [
    "PluginLoadSnapshot",
    "PluginRuntimeHost",
    "RuntimeHookRegistry",
]
