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
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Literal

from acabot.agent import ToolDef
from acabot.config import Config

from .gateway_protocol import GatewayProtocol
from .models import RunContext
from .reference_backend import ReferenceBackend
from .tool_broker import ToolBroker

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
class RuntimePluginContext:
    """插件 setup 时可见的最小 runtime 上下文.

    封装插件所需的外部依赖, 实现依赖注入.
    插件不直接访问全局状态, 都通过此上下文.

    Attributes:
        config (Config): 项目配置对象.
        gateway (GatewayProtocol): 当前 gateway, 用于发送主动消息.
        tool_broker (ToolBroker): runtime 统一工具入口.
        reference_backend (ReferenceBackend | None): reference provider.
    """

    config: Config
    gateway: GatewayProtocol
    tool_broker: ToolBroker
    reference_backend: ReferenceBackend | None = None

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
        hooks (RuntimeHookRegistry): runtime hook 注册表.
        loaded (list[RuntimePlugin]): 已加载插件列表, 按加载顺序.
        _names (set[str]): 已加载插件名集合, 用于去重.
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
        plugins: list[RuntimePlugin] | None = None,
    ) -> None:
        """初始化 RuntimePluginManager.

        注意: 构造函数只保存参数, 实际插件加载在 ensure_started() 中进行.

        Args:
            config: 项目配置对象.
            gateway: 当前 gateway.
            tool_broker: runtime 工具入口.
            reference_backend: 可选的 reference provider.
            plugins: 启动时需要加载的插件实例列表.
        """

        self.config = config
        self.gateway = gateway
        self.tool_broker = tool_broker
        # TODO: 收窄成 ReferenceService, 或者不暴露?
        self.reference_backend = reference_backend
        # 创建空的 hook 注册表
        self.hooks = RuntimeHookRegistry()
        # 维护加载顺序的列表, teardown 时逆序清理
        self.loaded: list[RuntimePlugin] = []
        # 快速去重检查
        self._names: set[str] = set()
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
        runtime = context or RuntimePluginContext(
            config=self.config,
            gateway=self.gateway,
            tool_broker=self.tool_broker,
            reference_backend=self.reference_backend,
        )
        # 步骤 3: 调用 setup, 失败则跳过整个插件
        try:
            await plugin.setup(runtime)
        except Exception:
            logger.exception("Runtime plugin '%s' setup failed, skipping", plugin.name)
            return

        # 步骤 4: 注册 hooks 到各个切入点
        for point, hook in plugin.hooks():
            self.hooks.register(point, hook)
        # 步骤 5: 注册 tools 到 ToolBroker, 带插件来源标记
        for tool in plugin.tools():
            self.tool_broker.register_legacy_tool(
                tool,
                source=f"plugin:{plugin.name}",
                metadata={"plugin_name": plugin.name},
            )

        # 步骤 6: 标记为已加载
        self.loaded.append(plugin)
        self._names.add(plugin.name)
        logger.info(
            "Runtime plugin loaded: %s (%s hooks, %s tools)",
            plugin.name,
            len(plugin.hooks()),
            len(plugin.tools()),
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

    async def teardown_all(self) -> None:
        """逆序清理所有已加载插件.

        逆序保证依赖关系正确: 后加载的先清理.
        单个插件 teardown 异常不影响其他插件.
        """

        # reversed() 实现逆序
        for plugin in reversed(self.loaded):
            try:
                await plugin.teardown()
            except Exception:
                logger.exception("Runtime plugin '%s' teardown failed", plugin.name)
        # 清空状态, 允许重新加载
        self.loaded.clear()
        self._names.clear()
        self._started = False


# endregion
