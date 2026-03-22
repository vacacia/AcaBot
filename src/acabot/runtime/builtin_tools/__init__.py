"""runtime.builtin_tools 负责注册 runtime 自带的基础工具表面.

这里收的是 runtime 的核心前台工具入口.
它和下面这些组件直接相关:
- `runtime.bootstrap`: 启动时调用这里把 builtin tool 接进 ToolBroker
- `runtime.tool_broker`: 保存稳定的 builtin tool 目录
- `runtime.plugin_manager`: 管理扩展 plugin 的生命周期
"""

from __future__ import annotations

from ..computer import ComputerRuntime
from ..skills import SkillCatalog
from ..subagents import SubagentDelegationBroker
from ..tool_broker import ToolBroker
from .computer import BUILTIN_COMPUTER_TOOL_SOURCE, BuiltinComputerToolSurface
from .skills import BUILTIN_SKILL_TOOL_SOURCE, BuiltinSkillToolSurface
from .subagents import BUILTIN_SUBAGENT_TOOL_SOURCE, BuiltinSubagentToolSurface


# region register

def remove_stale_core_tool_adapter_sources(tool_broker: ToolBroker) -> None:
    """清掉已经退役的旧 core tool adapter source.

    Args:
        tool_broker: 当前 runtime 使用的 ToolBroker.
    """

    tool_broker.unregister_source("plugin:computer_tool_adapter")
    tool_broker.unregister_source("plugin:skill_tool")
    tool_broker.unregister_source("plugin:subagent_delegation")


def register_core_builtin_tools(
    *,
    tool_broker: ToolBroker,
    computer_runtime: ComputerRuntime | None,
    skill_catalog: SkillCatalog | None,
    subagent_delegator: SubagentDelegationBroker | None,
) -> dict[str, list[str]]:
    """把 core builtin tool 注册到 ToolBroker.

    Args:
        tool_broker: 当前 runtime 使用的 ToolBroker.
        computer_runtime: 真实 computer runtime.
        skill_catalog: 统一 skill catalog.
        subagent_delegator: subagent delegation 编排入口.

    Returns:
        dict[str, list[str]]: `source -> tool_names` 的注册结果.
    """

    remove_stale_core_tool_adapter_sources(tool_broker)
    computer_surface = BuiltinComputerToolSurface(
        computer_runtime=computer_runtime,
    )
    skill_surface = BuiltinSkillToolSurface(
        skill_catalog=skill_catalog,
        computer_runtime=computer_runtime,
    )
    subagent_surface = BuiltinSubagentToolSurface(
        delegator=subagent_delegator,
    )
    return {
        BUILTIN_COMPUTER_TOOL_SOURCE: computer_surface.register(tool_broker),
        BUILTIN_SKILL_TOOL_SOURCE: skill_surface.register(tool_broker),
        BUILTIN_SUBAGENT_TOOL_SOURCE: subagent_surface.register(tool_broker),
    }


# endregion


__all__ = [
    "BUILTIN_COMPUTER_TOOL_SOURCE",
    "BUILTIN_SKILL_TOOL_SOURCE",
    "BUILTIN_SUBAGENT_TOOL_SOURCE",
    "BuiltinComputerToolSurface",
    "BuiltinSkillToolSurface",
    "BuiltinSubagentToolSurface",
    "remove_stale_core_tool_adapter_sources",
    "register_core_builtin_tools",
]
