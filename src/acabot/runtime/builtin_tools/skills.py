"""runtime.builtin_tools.skills 注册 skill builtin tool.

这个文件只负责给模型暴露统一的 `Skill(skill=...)` 入口.
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
        """保存 skill builtin tool 需要的依赖.

        Args:
            skill_catalog: 当前统一 skill catalog.
            computer_runtime: 可选的 computer runtime.
        """

        self.skill_catalog = skill_catalog
        self.computer_runtime = computer_runtime

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把 skill builtin tool 注册到 ToolBroker.

        Args:
            tool_broker: 当前 runtime 使用的 ToolBroker.

        Returns:
            list[str]: 本次注册的工具名列表.
        """

        tool_broker.unregister_source(BUILTIN_SKILL_TOOL_SOURCE)
        if self.skill_catalog is None:
            return []
        tool_broker.register_tool(
            ToolSpec(
                name="Skill",
                description=(
                    "Use Skill(skill=...) to load a visible skill by name. "
                    "The runtime reads SKILL.md and returns the skill base directory "
                    "for follow-up reads under /skills/."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "skill": {
                            "type": "string",
                            "description": "Visible skill package name.",
                        }
                    },
                    "required": ["skill"],
                },
            ),
            self._read_skill,
            source=BUILTIN_SKILL_TOOL_SOURCE,
        )
        return ["Skill"]

    async def _read_skill(
        self,
        arguments: dict[str, Any],
        ctx: ToolExecutionContext,
    ) -> ToolResult:
        """读取当前 agent 被分配的一个 skill 文档.

        Args:
            arguments: 模型传入的工具参数.
            ctx: 当前工具执行上下文.

        Returns:
            ToolResult: 给模型的 skill 读取结果.
        """

        catalog = self._require_catalog()
        skill_name = str(arguments.get("skill", "") or "").strip()
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
        base_directory = f"/skills/{manifest.skill_name}"
        if self.computer_runtime is not None:
            self.computer_runtime.mark_skill_loaded(ctx.thread_id, skill_name)
        payload = {
            "ok": True,
            "skill_name": manifest.skill_name,
            "display_name": manifest.display_name,
            "description": manifest.description,
            "base_directory": base_directory,
            "has_references": manifest.has_references,
            "has_scripts": manifest.has_scripts,
            "has_assets": manifest.has_assets,
        }
        llm_content = self._format_skill_result(
            skill_name=manifest.skill_name,
            base_directory=base_directory,
            raw_markdown=document.raw_markdown,
        )
        return ToolResult(
            llm_content=llm_content,
            raw=payload,
            metadata=payload,
        )

    @staticmethod
    def _format_skill_result(*, skill_name: str, base_directory: str, raw_markdown: str) -> str:
        """把 skill 返回值排成固定文本格式.

        Args:
            skill_name: 当前 skill 名.
            base_directory: 返回给模型的 skill 基目录.
            raw_markdown: 原始 `SKILL.md` 文本.

        Returns:
            str: 给模型的完整文本.
        """

        return "\n".join(
            [
                f"Launching skill: {skill_name}",
                "",
                f"Base directory for this skill: {base_directory}",
                "",
                raw_markdown,
            ]
        )

    def _require_catalog(self) -> SkillCatalog:
        """返回当前必需的 skill catalog.

        Returns:
            SkillCatalog: 当前可用的 skill catalog.

        Raises:
            RuntimeError: skill catalog 缺失时抛出.
        """

        if self.skill_catalog is None:
            raise RuntimeError("skill catalog unavailable")
        return self.skill_catalog


# endregion


__all__ = [
    "BUILTIN_SKILL_TOOL_SOURCE",
    "BuiltinSkillToolSurface",
]
