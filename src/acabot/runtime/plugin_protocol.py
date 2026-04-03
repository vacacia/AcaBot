"""runtime.plugin_protocol 定义插件作者对接的接口契约.

从 plugin_manager.py 中提取的稳定协议层.
所有插件控制面模块 (package/spec/status/reconciler/host) 都依赖它,
它本身不依赖任何插件控制面模块.

包含:
- RuntimeHookPoint / RuntimeHook / RuntimeHookResult -- hook 体系
- RuntimeToolRegistration -- runtime-native 工具定义
- RuntimePlugin (ABC) -- 插件基类
- RuntimePluginContext -- 插件 setup 时可见的最小运行时上下文
- RuntimePluginModelSlot -- 从 model_targets 重导出
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import logging
from typing import TYPE_CHECKING, Any, Literal

from acabot.agent import ToolDef, ToolSpec
from acabot.runtime.tool_broker import ToolBroker
from acabot.runtime.tool_broker import ToolHandler as RuntimeToolHandler
from acabot.runtime.gateway_protocol import GatewayProtocol
from acabot.runtime.contracts import RunContext
from acabot.runtime.model.model_targets import RuntimePluginModelSlot
from acabot.runtime.skills import SkillCatalog
from acabot.runtime.memory.sticky_notes import StickyNoteService
from acabot.runtime.computer import ComputerRuntime

if TYPE_CHECKING:
    from acabot.runtime.control.control_plane import RuntimeControlPlane

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


# endregion


# region plugin 协议

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
        plugin_id (str): 当前插件的 ID.
        plugin_config (dict[str, Any]): 合并后的最终配置 (default_config | spec.config).
        data_dir (Path): 插件专属可写目录, 如 runtime_data/plugins/<id>/data/.
        gateway (GatewayProtocol): 当前 gateway, 用于发送主动消息.
        tool_broker (ToolBroker): runtime 统一工具入口.
        sticky_notes (StickyNoteService | None): sticky note 的受控服务层.
        computer_runtime (ComputerRuntime | None): computer 基础设施入口.
        skill_catalog (SkillCatalog | None): 统一 skill catalog.
        control_plane (RuntimeControlPlane | None): 本地 control plane 入口.
    """

    plugin_id: str
    plugin_config: dict[str, Any]
    data_dir: Path
    gateway: GatewayProtocol
    tool_broker: ToolBroker
    sticky_notes: StickyNoteService | None = None
    computer_runtime: ComputerRuntime | None = None
    skill_catalog: SkillCatalog | None = None
    control_plane: RuntimeControlPlane | None = None


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
            runtime: runtime plugin 上下文, 提供依赖注入.
        """

    def hooks(self) -> list[tuple[RuntimeHookPoint, RuntimeHook]]:
        """返回要注册的 runtime hooks.

        每个 tuple 是 (hook_point, hook_instance).
        此方法在 setup 成功后调用.

        Returns:
            (RuntimeHookPoint, RuntimeHook) 列表. 默认空列表.
        """
        return []

    def tools(self) -> list[ToolDef]:
        """返回要注册到 ToolBroker 的 legacy ToolDef.

        这些工具会在 agent 的 tool call 中可用.
        工具名应避免与内置工具冲突.

        Returns:
            ToolDef 列表. 默认空列表.
        """
        return []

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        """返回 runtime-native 工具定义.

        这类工具的 handler 会直接拿到 ToolExecutionContext, 适合
        需要读取 actor/channel/thread 作用域的能力.

        Returns:
            RuntimeToolRegistration 列表. 默认空列表.
        """
        return []

    def model_slots(self) -> list[RuntimePluginModelSlot]:
        """返回插件声明的模型槽位.

        Returns:
            RuntimePluginModelSlot 列表. 默认空列表.
        """
        return []

    async def teardown(self) -> None:
        """在 runtime 停止或热卸载时清理资源."""


# endregion


__all__ = [
    "RuntimeHook",
    "RuntimeHookPoint",
    "RuntimeHookResult",
    "RuntimePlugin",
    "RuntimePluginContext",
    "RuntimePluginModelSlot",
    "RuntimeToolHandler",
    "RuntimeToolRegistration",
]
