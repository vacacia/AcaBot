"""runtime.plugins.skill_tool 提供统一的 skill(name=...) 入口."""

from __future__ import annotations

from typing import Any

from acabot.agent import ToolSpec

from ..computer import ComputerRuntime
from ..plugin_manager import RuntimePlugin, RuntimePluginContext, RuntimeToolRegistration
from .catalog import SkillCatalog
from ..tool_broker import ToolExecutionContext, ToolResult


class SkillToolPlugin(RuntimePlugin):
    """读取 assigned skill 的 SKILL.md."""

    name = "skill_tool"

    def __init__(self) -> None:
        self._skill_catalog: SkillCatalog | None = None
        self._computer_runtime: ComputerRuntime | None = None

    async def setup(self, runtime: RuntimePluginContext) -> None:
        self._skill_catalog = runtime.skill_catalog
        self._computer_runtime = runtime.computer_runtime

    def runtime_tools(self) -> list[RuntimeToolRegistration]:
        return [
            RuntimeToolRegistration(
                spec=ToolSpec(
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
                handler=self._read_skill,
            )
        ]

    async def _read_skill(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
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
        if self._computer_runtime is not None:
            self._computer_runtime.mark_skill_loaded(ctx.thread_id, skill_name)
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
        if self._skill_catalog is None:
            raise RuntimeError("skill catalog unavailable")
        return self._skill_catalog
