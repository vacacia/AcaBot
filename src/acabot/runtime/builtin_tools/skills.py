"""runtime.builtin_tools.skills 注册 skill builtin tool.

这个文件只负责给模型暴露统一的 `skill(name=...)` 入口.
它和下面这些组件直接相关:
- `runtime.skills`: 读取 skill 包和 SKILL.md
- `runtime.computer`: 记录当前线程已经加载过哪些 skill
- `runtime.tool_broker`: 注册最终对模型可见的工具
"""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..computer import ComputerRuntime
from ..skills import SkillCatalog
from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


# region source
BUILTIN_SKILL_TOOL_SOURCE = "builtin:skills"


# endregion


# region surface
class BuiltinSkillToolSurface:
    """skill builtin tool 的注册和执行入口.

    Attributes:
        skill_catalog (SkillCatalog | None): 当前统一 skill catalog.
        computer_runtime (ComputerRuntime | None): 可选的 computer runtime, 用来记录已加载 skill.
    """

    def __init__(
        self,
        *,
        skill_catalog: SkillCatalog | None,
        computer_runtime: ComputerRuntime | None,
    ) -> None:
        """保存 skill builtin tool 需要的依赖."""

        self.skill_catalog = skill_catalog
        self.computer_runtime = computer_runtime

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 skill builtin tool 注册到 ToolBroker."""

        tool_broker.unregister_source(BUILTIN_SKILL_TOOL_SOURCE)
        if self.skill_catalog is None:
            return []
        tool_broker.register_tool(
            ToolSpec(
                name="skill",
                description="Use skill(name=...) to read an assigned skill's SKILL.md.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Assigned skill package name.",
                        }
                    },
                    "required": ["name"],
                },
            ),
            self._read_skill,
            source=BUILTIN_SKILL_TOOL_SOURCE,
        )
        return ["skill"]

    async def _read_skill(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """读取当前 agent 被分配的一个 skill 文档."""

        catalog = self._require_catalog()
        skill_name = str(arguments.get("name", "") or "").strip()
        if ctx.world_view is not None:
            skills_policy = ctx.world_view.root_policies.get("skills")
            if skills_policy is None or not skills_policy.visible:
                allowed = set()
            else:
                allowed = set(ctx.world_view.visible_skill_names)
        else:
            allowed = {item.skill_name for item in catalog.visible_skills(ctx.profile)}
        if not skill_name or skill_name not in allowed:
            return ToolResult(
                llm_content=f"Skill not assigned to current agent: {skill_name or '-'}",
                raw={"ok": False, "skill_name": skill_name, "reason": "skill_not_assigned"},
            )

        document = catalog.read(skill_name)
        manifest = document.manifest
        if self.computer_runtime is not None:
            self.computer_runtime.mark_skill_loaded(ctx.thread_id, skill_name)
        payload = {
            "ok": True,
            "skill_name": manifest.skill_name,
            "display_name": manifest.display_name,
            "description": manifest.description,
            "has_references": manifest.has_references,
            "has_scripts": manifest.has_scripts,
            "has_assets": manifest.has_assets,
        }
        return ToolResult(
            llm_content=document.raw_markdown,
            raw=payload,
            metadata=payload,
        )

    def _require_catalog(self) -> SkillCatalog:
        """返回当前必需的 skill catalog."""

        if self.skill_catalog is None:
            raise RuntimeError("skill catalog unavailable")
        return self.skill_catalog


# endregion


__all__ = [
    "BUILTIN_SKILL_TOOL_SOURCE",
    "BuiltinSkillToolSurface",
]
