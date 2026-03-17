"""runtime.plugins 导出内置 runtime plugins.

这些对象都是装配层.
其中 computer 本体在 `runtime.computer`, 这里只导出把它接成工具的 adapter plugin.
"""

from .backend_bridge_tool import BackendBridgeToolPlugin
from .computer_tool_adapter import ComputerToolAdapterPlugin
from .napcat_tools import NapCatToolsPlugin
from .ops_control import OpsControlPlugin
from .reference_tools import ReferenceToolsPlugin
from ..skills.tool_adapter import SkillToolPlugin
from .sticky_notes import StickyNotesPlugin
from .subagent_delegation import SubagentDelegationPlugin

__all__ = [
    "BackendBridgeToolPlugin",
    "NapCatToolsPlugin",
    "ComputerToolAdapterPlugin",
    "OpsControlPlugin",
    "ReferenceToolsPlugin",
    "SkillToolPlugin",
    "StickyNotesPlugin",
    "SubagentDelegationPlugin",
]
