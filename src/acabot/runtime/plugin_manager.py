"""runtime.plugin_manager 提供 runtime world 的插件管理器.

    RuntimePlugin
         |
         v
    RuntimePluginManager
      |           |
      |           +-- register tools -> ToolBroker
      |
      `-- run hooks -> ThreadPipeline

- 插件不再依赖旧 Pipeline
- 让插件可以注册 runtime hook 和 tool
- 让 lifecycle 进入 RuntimeApp 的 start / stop
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import importlib
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any, Literal

from acabot.agent import ToolDef, ToolSpec
from acabot.config import Config

from .gateway_protocol import GatewayProtocol
from .models import RunContext
from .reference_backend import ReferenceBackend
from .skills import SkillRegistry, SkillSpec
from .sticky_notes import StickyNotesService
from .tool_broker import ToolBroker
from .tool_broker import ToolHandler as RuntimeToolHandler

if TYPE_CHECKING:
    from .control_plane import RuntimeControlPlane

logger = logging.getLogger("acabot.runtime.plugin")


# region HookPoint

class RuntimeHookPoint(Enum):
    """RuntimeHookPoint.

    Attributes:
        ON_EVENT: 事件刚进入 ThreadPipeline, 还未写入 working memory.
        PRE_AGENT: retrieval 和 prompt assembly 完成后, 调 agent 之前.
        POST_AGENT: agent runtime 返回后, 发送前.
        BEFORE_SEND: Outbox dispatch 之前.
        ON_SENT: Outbox dispatch 之后.
        ON_ERROR: pipeline 发生异常时.
    """

    ON_EVENT = "on_event"
    PRE_AGENT = "pre_agent"
    POST_AGENT = "post_agent"
    BEFORE_SEND = "before_send"
    ON_SENT = "on_sent"
    ON_ERROR = "on_error"


@dataclass(slots=True)
class RuntimeHookResult:
    """RuntimeHookResult.

    Attributes:
        action (Literal["continue", "skip_agent"]): hook 对后续主线的控制动作.
    """

    # action="continue": 继续执行后续主线逻辑
    # action="skip_agent": 跳过 agent 调用, 直接返回(用于 PRE_AGENT 钩子)
    action: Literal["continue", "skip_agent"] = "continue"


class RuntimeHook(ABC):
    """runtime hook 基类.

    插件继承此类实现自定义 hook 逻辑.
    每个 hook 实例只在特定 Point 执行一次.

    Attributes:
        name (str): hook 名称, 用于日志标识.
        priority (int): 优先级, 越小越先执行. 相同优先级按注册顺序.
        enabled (bool): 是否启用. 可在运行时动态开关.
    """

    name: str
    priority: int = 100
    enabled: bool = True

    @abstractmethod
    async def handle(self, ctx: RunContext) -> RuntimeHookResult:
        """处理一次 runtime hook."""

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

        注册时会自动按 priority 重新排序.
        同名 hook 可在不同 point 重复注册.

        Args:
            point: hook 切入点.
            hook: 要注册的 hook 实例.
        """

        # 惰性初始化字典 key 
        if point not in self._hooks:
            self._hooks[point] = []
        # 添加到列表并按 priority 排序
        self._hooks[point].append(hook)
        self._hooks[point].sort(key=lambda item: item.priority)
        # 记录注册日志, 便于调试插件加载顺序
        logger.info(
            "Runtime hook registered: %s @ %s (priority=%s)",
            hook.name,
            point.value,
            hook.priority,
        )

    def get(self, point: RuntimeHookPoint) -> list[RuntimeHook]:
        """获取指定 hook 点的已启用 hooks.

        自动过滤 enabled=False 的 hook, 支持运行时动态开关.

        Args:
            point: hook 切入点.

        Returns:
            按优先级排序的 hook 列表. 无 hooks 时返回空列表.
        """
        return [hook for hook in self._hooks.get(point, []) if hook.enabled]


# endregion


# region plugin协议
@dataclass(slots=True)
class RuntimePluginSpec:
    """一条 runtime plugin 加载配置.

    Attributes:
        import_path (str): `module.submodule:Symbol` 形式的导入路径.
        enabled (bool): 是否启用.
    """

    import_path: str
    enabled: bool = True


@dataclass(slots=True)
class RuntimeToolRegistration:
    """一条 runtime-native 工具注册项.

    Attributes:
        spec (ToolSpec): 模型可见的工具 schema.
        handler (RuntimeToolHandler): 可拿到 ToolExecutionContext 的工具执行逻辑.
        metadata (dict[str, Any]): 附加注册元数据.
    """

    spec: ToolSpec
    handler: RuntimeToolHandler
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimePluginContext:
    """插件 setup 时可见的最小 runtime 上下文.

    封装插件所需的外部依赖, 实现依赖注入.
    插件不直接访问全局状态, 都通过此上下文.

    Attributes:
        config (Config): 项目配置对象.
        gateway (GatewayProtocol): 当前 gateway, 用于发送主动消息.
        tool_broker (ToolBroker): runtime 统一工具入口.
        reference_backend (ReferenceBackend | None): reference provider.
        sticky_notes (StickyNotesService | None): sticky note 的受控服务层.
        skill_registry (SkillRegistry | None): 显式 skill 注册表.
        control_plane (RuntimeControlPlane | None): 本地 control plane 入口.
    """

    config: Config
    gateway: GatewayProtocol
    tool_broker: ToolBroker
    reference_backend: ReferenceBackend | None = None
    sticky_notes: StickyNotesService | None = None
    skill_registry: SkillRegistry | None = None
    control_plane: RuntimeControlPlane | None = None

    def get_plugin_config(self, plugin_name: str) -> dict[str, object]:
        """读取插件配置.

        从配置文件的 plugins.<plugin_name> 读取.

        Args:
            plugin_name: 插件名.

        Returns:
            plugins.<plugin_name> 下的配置字典. 不存在时返回空 dict.
        """

        return dict(self.config.get_plugin_config(plugin_name))


class RuntimePlugin(ABC):
    """runtime world 插件基类.

    插件开发者继承此类实现自定义插件.
    通过重写 hooks() 和 tools() 方法注册能力.

    生命周期:
        setup -> hooks/tools 注册 -> teardown
        |                            |
        +---- RuntimeApp start      +---- RuntimeApp stop / 热卸载
    """

    name: str  # 插件标识名, 唯一且用于配置查找

    @abstractmethod
    async def setup(self, runtime: RuntimePluginContext) -> None:
        """在插件注册前初始化资源.

        此时可连接数据库、加载模型等.
        抛出异常会导致插件被跳过.

        Args:
            runtime: runtime plugin 上下文, 提供 config/gateway/tool_broker.
        """

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        """返回要注册的 runtime hooks.

        每个 tuple 是 (hook_point, hook_instance).
        此方法在 setup 成功后调用.

        Returns:
            (RuntimeHookPoint, RuntimeHook) 列表. 默认空列表.
        """
        # 子类可重写, 返回要注入 pipeline 各切入点的 hooks
        return []

    def tools(self) -> list[ToolDef]:
        """返回要注册到 ToolBroker 的 legacy ToolDef.

        这些工具会在 agent 的 tool call 中可用.
        工具名应避免与内置工具冲突.

        Returns:
            ToolDef 列表. 默认空列表.
        """
        # 子类可重写, 返回要注册的工具定义
        return []

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """返回 runtime-native 工具定义.

        这类工具的 handler 会直接拿到 ToolExecutionContext, 适合
        需要读取 actor/channel/thread 作用域的能力.

        Returns:
            RuntimeToolRegistration 列表. 默认空列表.
        """

        return []

    def skills(self) -> list[SkillSpec]:
        """返回插件声明的显式 skills.

        Returns:
            SkillSpec 列表. 默认空列表.
        """

        return []

    async def teardown(self) -> None:
        """在 runtime 停止或热卸载时清理资源."""
        # 子类可重写, 默认空实现

# endregion


# region manager
class RuntimePluginManager:
    """runtime world 的最小插件管理器.

    职责:
    - 维护插件加载/卸载生命周期
    - 管理 hook 注册和执行
    - 代理工具注册到 ToolBroker

    Attributes:
        config (Config): 项目配置对象.
        gateway (GatewayProtocol): 当前 gateway.
        tool_broker (ToolBroker): runtime 工具入口.
        reference_backend (ReferenceBackend | None): reference provider.
        sticky_notes (StickyNotesService | None): sticky note 服务.
        skill_registry (SkillRegistry | None): 显式 skill 注册表.
        control_plane (RuntimeControlPlane | None): 本地 control plane 入口.
        hooks (RuntimeHookRegistry): runtime hook 注册表.
        loaded (list[RuntimePlugin]): 已加载插件列表, 按加载顺序.
        _names (set[str]): 已加载插件名集合, 用于去重.
        _plugin_hooks (dict[str, list[tuple[RuntimeHookPoint, RuntimeHook]]]): 每个插件注册过的 hooks.
        _pending (list[RuntimePlugin]): 等待 load 的插件列表.
        _started (bool): 是否已经完成插件加载.
    """

    def __init__(
        self,
        *,
        config: Config,
        gateway: GatewayProtocol,
        tool_broker: ToolBroker,
        reference_backend: ReferenceBackend | None = None,
        sticky_notes: StickyNotesService | None = None,
        skill_registry: SkillRegistry | None = None,
        control_plane: RuntimeControlPlane | None = None,
        plugins: list[RuntimePlugin] | None = None,
    ) -> None:
        """初始化 RuntimePluginManager.

        注意: 构造函数只保存参数, 实际插件加载在 ensure_started() 中进行.

        Args:
            config: 项目配置对象.
            gateway: 当前 gateway.
            tool_broker: runtime 工具入口.
            reference_backend: 可选的 reference provider.
            sticky_notes: 可选的 sticky note 服务.
            skill_registry: 可选的显式 skill 注册表.
            control_plane: 可选的本地 control plane 入口.
            plugins: 启动时需要加载的插件实例列表.
        """

        self.config = config
        self.gateway = gateway
        self.tool_broker = tool_broker
        # TODO: 收窄成 ReferenceService, 或者不暴露?
        self.reference_backend = reference_backend
        self.sticky_notes = sticky_notes
        self.skill_registry = skill_registry
        self.control_plane = control_plane
        # 创建空的 hook 注册表
        self.hooks = RuntimeHookRegistry()
        # 维护加载顺序的列表, teardown 时逆序清理
        self.loaded: list[RuntimePlugin] = []
        # 快速去重检查
        self._names: set[str] = set()
        # 记录每个插件实际注册的 hooks, 便于精确卸载和重建 registry
        self._plugin_hooks: dict[str, list[tuple[RuntimeHookPoint, RuntimeHook]]] = {}
        # 延迟加载队列, 支持动态添加插件
        self._pending: list[RuntimePlugin] = list(plugins or [])
        self._started = False
        # 防止并发启动的锁
        self._start_lock = asyncio.Lock()

    def add_plugin(self, plugin: RuntimePlugin) -> None:
        """追加一个待加载插件.

        如果 manager 已启动, 会立即加载;
        否则加入 pending 队列, 在 ensure_started() 时统一加载.

        Args:
            plugin: 要加入待加载队列的插件实例.
        """
        # 简单追加到队列, 不检查重复(去重在 load_plugin 时)
        self._pending.append(plugin)

    def attach_control_plane(self, control_plane: RuntimeControlPlane) -> None:
        """把本地 control plane 接到 plugin manager.

        Args:
            control_plane: 当前 runtime 的本地 control plane.
        """

        self.control_plane = control_plane

    async def ensure_started(self) -> None:
        """确保待加载插件已经完成 setup 和注册.

        幂等操作, 多次调用只有第一次生效.
        使用双检锁模式防止并发问题.
        """

        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            context = RuntimePluginContext(
                config=self.config,
                gateway=self.gateway,
                tool_broker=self.tool_broker,
                reference_backend=self.reference_backend,
                sticky_notes=self.sticky_notes,
                skill_registry=self.skill_registry,
                control_plane=self.control_plane,
            )
            # 复制并清空 pending, 防止 load 过程中 add_plugin 导致重复
            pending = list(self._pending)
            self._pending.clear()

            for plugin in pending:
                await self.load_plugin(plugin, context)
            self._started = True

    async def load_plugin(
        self,
        plugin: RuntimePlugin,
        context: RuntimePluginContext | None = None,
    ) -> None:
        """加载单个插件并注册 hook / tool.

        接收的是已经被实例化好的 RuntimePlugin 对象

        通过协定好的生命周期协议(setup、hooks、tools), 把这个 RuntimePlugin 接入到系统

        加载流程:
        1. 检查重复名
        2. 调用 setup()
        3. 注册 hooks
        4. 注册 tools
        5. 标记为 loaded

        Args:
            plugin: 要加载的插件实例.
            context: 可选的 setup 上下文. 缺省时自动构造.
        """

        # 步骤 1: 去重检查, 同名插件只加载一次
        if plugin.name in self._names:
            logger.warning("Runtime plugin '%s' already loaded, skipping", plugin.name)
            return

        # 步骤 2: 准备上下文
        # 插件不允许直接使用全局单例, 必须通过这个受控的 Context 来调配资源
        runtime = context or RuntimePluginContext(
            config=self.config,
            gateway=self.gateway,
            tool_broker=self.tool_broker,
            reference_backend=self.reference_backend,
            sticky_notes=self.sticky_notes,
            skill_registry=self.skill_registry,
            control_plane=self.control_plane,
        )
        # 步骤 3: 调用 setup, 失败则跳过整个插件
        try:
            await plugin.setup(runtime)
        except Exception:
            logger.exception("Runtime plugin '%s' setup failed, skipping", plugin.name)
            return

        # 步骤 4: 注册 hooks 到各个 Point
        plugin_hooks = list(plugin.hooks())
        for point, hook in plugin_hooks:
            self.hooks.register(point, hook)
        self._plugin_hooks[plugin.name] = plugin_hooks
        plugin_skills = list(plugin.skills())
        if self.skill_registry is not None:
            for skill in plugin_skills:
                self.skill_registry.register_skill(
                    skill,
                    source=f"plugin:{plugin.name}",
                    metadata={"plugin_name": plugin.name},
                )
        runtime_tools = list(plugin.runtime_tools())
        for registration in runtime_tools:
            self.tool_broker.register_tool(
                registration.spec,
                registration.handler,
                source=f"plugin:{plugin.name}",
                metadata={
                    "plugin_name": plugin.name,
                    **dict(registration.metadata),
                },
            )
        # 步骤 5: 注册 tools 到 ToolBroker, 带插件来源标记
        legacy_tools = list(plugin.tools())
        for tool in legacy_tools:
            self.tool_broker.register_legacy_tool(
                tool,
                source=f"plugin:{plugin.name}", # 打上命名空间标签, 方便统一卸载
                metadata={"plugin_name": plugin.name},
            )

        # 步骤 6: 标记为已加载
        self.loaded.append(plugin)
        self._names.add(plugin.name)
        logger.info(
            "Runtime plugin loaded: %s (%s hooks, %s tools, %s skills)",
            plugin.name,
            len(plugin_hooks),
            len(runtime_tools) + len(legacy_tools),
            len(plugin_skills),
        )

    async def run_hooks(self, point: RuntimeHookPoint, ctx: RunContext) -> RuntimeHookResult:
        """执行指定 point 的 hooks.

        执行规则:
        - 按 priority 顺序执行
        - 任一 hook 返回 skip_agent, 立即停止并返回
        - 单个 hook 异常不影响其他 hook, 记录日志后继续

        Args:
            point: hook 切入点.
            ctx: 当前 run 的执行上下文.

        Returns:
            聚合后的 RuntimeHookResult. 默认返回 continue.
        """

        for hook in self.hooks.get(point):
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
            # 短路
            if result.action == "skip_agent":
                return result
        # 默认返回 continue
        return RuntimeHookResult()

    async def unload_plugins(self, plugin_names: list[str]) -> list[str]:
        """按插件名卸载已加载插件.

        Args:
            plugin_names: 要卸载的插件名列表.

        Returns:
            实际被卸载的插件名列表, 按原加载顺序返回.
        """

        if not plugin_names:
            return []

        unload_set = set(plugin_names)
        removed_names: list[str] = []

        for plugin in reversed(self.loaded):
            if plugin.name not in unload_set:
                continue
            if self.skill_registry is not None:
                removed_skills = self.skill_registry.unregister_source(f"plugin:{plugin.name}")
                if removed_skills:
                    logger.info(
                        "Runtime plugin skills removed: plugin=%s skills=%s",
                        plugin.name,
                        ",".join(removed_skills),
                    )
            # 切断响应
            removed = self.tool_broker.unregister_source(f"plugin:{plugin.name}")
            if removed:
                logger.info(
                    "Runtime plugin tools removed: plugin=%s tools=%s",
                    plugin.name,
                    ",".join(removed),
                )
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Runtime plugin '%s' teardown failed", plugin.name)
            removed_names.append(plugin.name)

        if not removed_names:
            return []

        removed_set = set(removed_names)
        self.loaded = [plugin for plugin in self.loaded if plugin.name not in removed_set]
        self._names = {plugin.name for plugin in self.loaded}
        for plugin_name in removed_set:
            self._plugin_hooks.pop(plugin_name, None)
        self._rebuild_hook_registry()
        return [plugin.name for plugin in self.loaded if plugin.name in removed_set] or [
            plugin_name for plugin_name in plugin_names if plugin_name in removed_set
        ]

    def _rebuild_hook_registry(self) -> None:
        """根据当前已加载插件重建 hook registry."""

        # Atomic
        self.hooks = RuntimeHookRegistry()
        for plugin in self.loaded:
            for point, hook in self._plugin_hooks.get(plugin.name, []):
                self.hooks.register(point, hook)

    async def teardown_all(self) -> None:
        """逆序清理所有已加载插件.

        逆序保证依赖关系正确: 后加载的先清理.
        单个插件 teardown 异常不影响其他插件.

        清理流程:
        1. 逆序遍历已加载插件
        2. 从 ToolBroker 注销该插件注册的所有工具
        3. 调用插件的 teardown() 进行资源清理
        4. 清空内部状态, 重置 started 标志
        """

        # reversed() 实现逆序遍历, 保证后加载的插件先清理
        # 这是依赖关系处理的关键: 如果插件A依赖插件B, 应该先加载B再加载A
        # 清理时则相反, 先清理A再清理B, 避免依赖悬空
        for plugin in reversed(self.loaded):
            if self.skill_registry is not None:
                removed_skills = self.skill_registry.unregister_source(f"plugin:{plugin.name}")
                if removed_skills:
                    logger.info(
                        "Runtime plugin skills removed: plugin=%s skills=%s",
                        plugin.name,
                        ",".join(removed_skills),
                    )
            removed = self.tool_broker.unregister_source(f"plugin:{plugin.name}")
            if removed:
                logger.info(
                    "Runtime plugin tools removed: plugin=%s tools=%s",
                    plugin.name,
                    ",".join(removed),
                )
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Runtime plugin '%s' teardown failed", plugin.name)
        # 清空状态, 允许重新加载
        self.loaded.clear()
        self._names.clear()
        self._plugin_hooks.clear()
        self.hooks = RuntimeHookRegistry()
        self._started = False

    async def reload_from_config(self, plugin_names: list[str] | None = None) -> tuple[list[str], list[str]]:
        """按当前 Config 重新加载 runtime plugins.

        热重载流程: 先 teardown 所有现有插件, 再从配置重新加载.
        这是实现插件热更新的入口, 可在运行时动态调整插件配置.

        Args:
            plugin_names: 可选的插件名列表. 缺省时重载全部插件.

        Returns:
            `(loaded_plugins, missing_plugins)` 元组.
        """
        # 预先构建新配置
        plugins = load_runtime_plugins_from_config(self.config)
        if not plugin_names:
            await self.teardown_all()
            self._pending = plugins
            await self.ensure_started()
            return [plugin.name for plugin in self.loaded], []

        requested_names: list[str] = []
        seen: set[str] = set()
        for plugin_name in plugin_names:
            plugin_name = str(plugin_name).strip()
            if not plugin_name or plugin_name in seen:
                continue
            requested_names.append(plugin_name)
            seen.add(plugin_name)

        if not requested_names:
            return [], []

        # 对象按插件名做映射
        plugin_by_name = {plugin.name: plugin for plugin in plugins}
        # 配置文件里不存在的插件
        missing = [plugin_name for plugin_name in requested_names if plugin_name not in plugin_by_name]
        # 被要求重载的、且成功找到新实例的 插件对象
        selected = [plugin_by_name[plugin_name] for plugin_name in requested_names if plugin_name in plugin_by_name]

        if self._started:
            # 在 unload_plugins 中:
            # 1. 根据 plugin_name 反向摘除该插件注册的所有 tool
            # 2. 调用旧实例的 target.teardown() 清理资源或者停止内部 task
            # 3. 将其从 loaded 和 _plugin_hooks 列表中删除
            await self.unload_plugins(requested_names)
        else:
            # 如果系统未 start，仅将待加载队列中的 plugin 排查掉
            self._pending = [
                plugin
                for plugin in self._pending
                if plugin.name not in set(requested_names)
            ]
        # 仅允许使用部分 API
        context = RuntimePluginContext(
            config=self.config,
            gateway=self.gateway,
            tool_broker=self.tool_broker,
            reference_backend=self.reference_backend,
            sticky_notes=self.sticky_notes,
            skill_registry=self.skill_registry,
            control_plane=self.control_plane,
        )
        # 新插件实例，重新执行 load_plugin
        # 1. new_target.setup(context)
        # 2. self.hooks.register(...)
        # 3. self.tool_broker.register(..., source=...)
        for plugin in selected:
            await self.load_plugin(plugin, context)
        return [plugin.name for plugin in selected if plugin.name in self._names], missing


# endregion


# region config loading
def parse_runtime_plugin_spec(raw: str | dict[str, Any]) -> RuntimePluginSpec | None:
    """把配置项解析成 RuntimePluginSpec.

    Args:
        raw: `runtime.plugins` 下的一条配置.

    Returns:
        解析后的 RuntimePluginSpec. 无效或禁用时返回 None.

    Examples:
        >>> parse_runtime_plugin_spec("my_plugin:MyPlugin")
        RuntimePluginSpec(import_path="my_plugin:MyPlugin", enabled=True)
        >>> parse_runtime_plugin_spec({"path": "my_plugin:MyPlugin", "enabled": False})
        None  # 禁用的插件返回 None
    """

    # 字符串格式
    if isinstance(raw, str):
        return RuntimePluginSpec(import_path=raw)

    if not isinstance(raw, dict):
        return None
    if not bool(raw.get("enabled", True)):
        return None
    import_path = str(raw.get("path", "") or raw.get("import_path", "") or "")
    if not import_path:
        return None
    return RuntimePluginSpec(import_path=import_path, enabled=True)


def load_runtime_plugin(spec: RuntimePluginSpec) -> RuntimePlugin:
    """按 import_path 动态导入并实例化一个 runtime plugin 对象.

    使用 importlib 动态导入模块, 获取指定符号并实例化.
    支持类(自动实例化)和实例(直接使用)两种形式.

    Args:
        spec: 目标插件配置, 包含 import_path.

    Returns:
        实例化后的 RuntimePlugin.

    Raises:
        ValueError: import_path 格式错误或符号不存在.
        TypeError: 导入对象不是 RuntimePlugin 实例.
    """

    # import_path 必须为 "module:Symbol" 形式
    if ":" not in spec.import_path:
        raise ValueError(
            f"Runtime plugin import path must be 'module:Symbol', got '{spec.import_path}'",
        )
    module_path, symbol_name = spec.import_path.split(":", 1)
    # 动态导入模块文件(返回的是模块对象, 而非插件本身), 模块缓存机制保证同一模块不会重复加载
    module = importlib.import_module(module_path)
    # 从模块的 __dict__ 命名空间中获取指定符号
    symbol = getattr(module, symbol_name, None)
    if symbol is None:
        raise ValueError(
            f"Runtime plugin symbol '{symbol_name}' not found in module '{module_path}'",
        )
    # 实例化或直接使用获取的符号
    # 如果是类: 调用 symbol() 实例化得到对象
    # 如果不是类 (已是实例): 直接使用该对象
    plugin = symbol() if isinstance(symbol, type) else symbol
    # 确保最终对象符合 RuntimePlugin 协议
    if not isinstance(plugin, RuntimePlugin):
        raise TypeError(
            f"Runtime plugin '{spec.import_path}' did not resolve to RuntimePlugin instance",
        )
    return plugin


def load_runtime_plugins_from_config(config: Config) -> list[RuntimePlugin]:
    """从 Config 批量加载 runtime plugin 列表.

    读取配置中的 runtime.plugins 列表, 逐个解析并加载.
    跳过无效配置和禁用的插件, 保持配置顺序.

    Args:
        config: 项目配置对象, 需包含 runtime.plugins 配置项.

    Returns:
        按配置顺序实例化后的 RuntimePlugin 列表.
        无效配置会被静默跳过, 不会抛出异常.
    """

    # 从配置中读取 runtime.plugins, 默认为空列表
    runtime_conf = config.get("runtime", {})
    raw_plugins = list(runtime_conf.get("plugins", []) or [])
    loaded: list[RuntimePlugin] = []
    for raw in raw_plugins:
        spec = parse_runtime_plugin_spec(raw)
        if spec is None:
            continue
        loaded.append(load_runtime_plugin(spec))
    return loaded


# endregion
