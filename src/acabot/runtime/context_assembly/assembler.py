"""runtime.context_assembly.assembler 负责把上游材料收成最终模型上下文.

组件关系:

    PromptLoader.load()
    MemoryBroker.retrieve()
    ToolRuntimeResolver.resolve()
    RetrievalPlan / MessageProjection
        |
        v
    ContextAssembler
        |
        v
    AssembledContext

这一层不读取文件, 不查记忆, 不做工具权限判断.
它只做两件事:
- 把上游材料统一变成 ContextContribution
- 把这些条目组装成最终的 system prompt 和 messages
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

_PROMPT_DIR = Path(__file__).parent / "prompts"

from ..contracts import MessageProjection, RetrievalPlan, RunContext
from ..memory.memory_broker import FORMAL_TARGET_SLOTS, MemoryBlock
from .contracts import AssembledContext, ContextContribution

if TYPE_CHECKING:
    from ..model.model_agent_runtime import ToolRuntime


# region assembler
class ContextAssembler:
    """正式上下文组装器."""

    SLOT_ORDER = {
        "system_prompt": 0,
        "message_prefix": 1,
        "message_history": 2,
        "message_current_user": 3,
    }

    SYSTEM_PROMPT_PRIORITY = {
        "base_prompt": 1000,
        "workspace_reminder": 950,
        "run_persistence_reminder": 945,
        "admin_host_maintenance_reminder": 940,
        "tool_behavior_reminder": 925,
        "skill_reminder": 900,
        "subagent_reminder": 850,
    }

    WORKING_SUMMARY_PRIORITY = 700

    def assemble(
        self,
        ctx: RunContext,
        *,
        base_prompt: str,
        tool_runtime: ToolRuntime,
    ) -> AssembledContext:
        """把当前 run 的上游材料组装成最终模型上下文.

        Args:
            ctx: 当前 run 的执行上下文.
            base_prompt: 当前 agent 的基础 prompt.
            tool_runtime: 当前 run 的 tool runtime 视图.

        Returns:
            一份最终发给模型的 AssembledContext.
        """

        contributions = self._collect_contributions(
            ctx,
            base_prompt=base_prompt,
            tool_runtime=tool_runtime,
        )
        return self._assemble_contributions(contributions)

    def _collect_contributions(
        self,
        ctx: RunContext,
        *,
        base_prompt: str,
        tool_runtime: ToolRuntime,
    ) -> list[ContextContribution]:
        """把当前 runtime 输入统一转成正式上下文条目.

        Args:
            ctx: 当前 run 的执行上下文.
            base_prompt: 当前 agent 的基础 prompt.
            tool_runtime: 当前 run 的 tool runtime 视图.

        Returns:
            一组 ContextContribution.
        """

        contributions: list[ContextContribution] = [
            ContextContribution(
                source_kind="base_prompt",
                target_slot="system_prompt",
                priority=self.SYSTEM_PROMPT_PRIORITY["base_prompt"],
                role="system",
                content=base_prompt,
            )
        ]
        contributions.extend(self._build_workspace_reminder_contribution())
        contributions.extend(self._build_run_persistence_reminder_contribution())
        contributions.extend(self._build_admin_host_maintenance_contribution(tool_runtime))
        contributions.extend(self._build_tool_behavior_contribution())
        contributions.extend(self._build_tool_summary_contributions(tool_runtime))
        contributions.extend(self._build_memory_contributions(ctx.memory_blocks))
        contributions.extend(self._build_working_summary_contribution(ctx.retrieval_plan))
        contributions.extend(
            self._build_history_contributions(
                ctx.retrieval_plan,
                ctx.message_projection,
            )
        )
        contributions.extend(self._build_current_user_contribution(ctx.message_projection))
        return contributions

    def _build_workspace_reminder_contribution(self) -> list[ContextContribution]:
        """返回稳定注入的 `/workspace` system reminder."""

        return [
            ContextContribution(
                source_kind="workspace_reminder",
                target_slot="system_prompt",
                priority=self.SYSTEM_PROMPT_PRIORITY["workspace_reminder"],
                role="system",
                content=(_PROMPT_DIR / "workspace_reminder.md").read_text(encoding="utf-8").strip(),
            )
        ]

    def _build_run_persistence_reminder_contribution(self) -> list[ContextContribution]:
        """返回稳定注入的 run 持久化提醒。"""

        return [
            ContextContribution(
                source_kind="run_persistence_reminder",
                target_slot="system_prompt",
                priority=self.SYSTEM_PROMPT_PRIORITY["run_persistence_reminder"],
                role="system",
                content=(_PROMPT_DIR / "run_persistence_reminder.md").read_text(encoding="utf-8").strip(),
            )
        ]

    def _build_admin_host_maintenance_contribution(self, tool_runtime: ToolRuntime) -> list[ContextContribution]:
        """为前台 admin+host run 注入真实 skill 维护提醒。"""

        payload = dict(tool_runtime.metadata.get("admin_host_maintenance", {}) or {})
        if not payload:
            return []
        return [
            ContextContribution(
                source_kind="admin_host_maintenance_reminder",
                target_slot="system_prompt",
                priority=self.SYSTEM_PROMPT_PRIORITY["admin_host_maintenance_reminder"],
                role="system",
                content=(
                    (_PROMPT_DIR / "admin_host_maintenance_reminder.md")
                    .read_text(encoding="utf-8")
                    .strip()
                    .format(
                        project_skill_root_path=str(payload.get("project_skill_root_path", "") or ""),
                        session_dir_path=str(payload.get("session_dir_path", "") or ""),
                        session_config_path=str(payload.get("session_config_path", "") or ""),
                        agent_config_path=str(payload.get("agent_config_path", "") or ""),
                    )
                ),
            )
        ]

    def _build_tool_behavior_contribution(self) -> list[ContextContribution]:
        """返回稳定注入的工具使用行为提醒。"""

        return [
            ContextContribution(
                source_kind="tool_behavior_reminder",
                target_slot="system_prompt",
                priority=self.SYSTEM_PROMPT_PRIORITY["tool_behavior_reminder"],
                role="system",
                content=(_PROMPT_DIR / "tool_behavior_reminder.md").read_text(encoding="utf-8").strip(),
            )
        ]

    def _build_tool_summary_contributions(self, tool_runtime: ToolRuntime) -> list[ContextContribution]:
        """把 tool runtime 里的 skill 和 subagent 摘要转成 system prompt 条目.

        Args:
            tool_runtime: 当前 run 的 tool runtime 视图.

        Returns:
            一组 system prompt 条目.
        """

        contributions: list[ContextContribution] = []
        skill_summaries = list(tool_runtime.metadata.get("visible_skill_summaries", []))
        if skill_summaries:
            lines = [
                "<system-reminder>",
                "The following skills are available for use with the Skill tool:",
            ]
            for item in skill_summaries:
                lines.append(
                    f"- {str(item.get('skill_name', '') or '')}: "
                    f"{str(item.get('description', '') or '')}"
                )
            lines.append("</system-reminder>")
            contributions.append(
                ContextContribution(
                    source_kind="skill_reminder",
                    target_slot="system_prompt",
                    priority=self.SYSTEM_PROMPT_PRIORITY["skill_reminder"],
                    role="system",
                    content="\n".join(lines),
                )
            )

        subagent_summaries = list(tool_runtime.metadata.get("visible_subagent_summaries", []))
        if subagent_summaries:
            lines = ["Available Subagents:"]
            for item in subagent_summaries:
                lines.append(
                    f"- {str(item.get('agent_id', '') or '')}: "
                    f"{str(item.get('profile_name', '') or item.get('agent_id', '') or '')}"
                )
            contributions.append(
                ContextContribution(
                    source_kind="subagent_reminder",
                    target_slot="system_prompt",
                    priority=self.SYSTEM_PROMPT_PRIORITY["subagent_reminder"],
                    role="system",
                    content="\n".join(lines),
                )
            )
        return contributions

    def _build_memory_contributions(self, memory_blocks: list[MemoryBlock]) -> list[ContextContribution]:
        """把 MemoryBlock 按 source 自己声明的 assembly 转成正式条目.

        Args:
            memory_blocks: 当前 run 的记忆块列表.

        Returns:
            一组 message_prefix 条目.
        """

        contributions: list[ContextContribution] = []
        for index, block in enumerate(memory_blocks):
            target_slot = str(block.assembly.target_slot or "message_prefix").strip()
            if target_slot not in FORMAL_TARGET_SLOTS:
                continue
            contributions.append(
                ContextContribution(
                    source_kind=str(block.source or "memory_source"),
                    target_slot=target_slot,
                    priority=int(block.assembly.priority),
                    role="system",
                    content=block.content,
                    metadata={
                        "memory_source": block.source,
                        "memory_scope": block.scope,
                        "source_ids": list(block.source_ids),
                        "memory_index": index,
                        **dict(block.metadata),
                    },
                )
            )
        return contributions

    def _build_working_summary_contribution(
        self,
        retrieval_plan: RetrievalPlan | None,
    ) -> list[ContextContribution]:
        """把 working summary 转成 message_prefix 条目.

        Args:
            retrieval_plan: 当前 retrieval 结果.

        Returns:
            一组 working summary 条目, 可能为空.
        """

        if retrieval_plan is None:
            return []
        summary_text = str(retrieval_plan.working_summary or "").strip()
        if not summary_text:
            return []
        return [
            ContextContribution(
                source_kind="working_summary",
                target_slot="message_prefix",
                priority=self.WORKING_SUMMARY_PRIORITY,
                role="system",
                content=summary_text,
            )
        ]

    def _build_history_contributions(
        self,
        retrieval_plan: RetrievalPlan | None,
        message_projection: MessageProjection | None,
    ) -> list[ContextContribution]:
        """把 retained history 转成 message_history 条目.

        Args:
            retrieval_plan: 当前 retrieval 结果.
            message_projection: 当前用户消息投影.

        Returns:
            一组 history 条目.
        """

        if retrieval_plan is None:
            return []

        retained_messages = list(retrieval_plan.retained_history)
        if (
            message_projection is not None
            and retained_messages
            and str(retained_messages[-1].get("role", "user") or "user") == "user"
            and retained_messages[-1].get("content", "") == message_projection.history_text
        ):
            retained_messages = retained_messages[:-1]

        contributions: list[ContextContribution] = []
        for index, item in enumerate(retained_messages):
            contributions.append(
                ContextContribution(
                    source_kind="history_message",
                    target_slot="message_history",
                    priority=0,
                    role=str(item.get("role", "user") or "user"),
                    content=item.get("content", ""),
                    metadata={"history_index": index},
                )
            )
        return contributions

    def _build_current_user_contribution(
        self,
        message_projection: MessageProjection | None,
    ) -> list[ContextContribution]:
        """把当前轮 model_content 转成最后一条用户消息.

        Args:
            message_projection: 当前 run 的消息投影结果.

        Returns:
            一组当前用户消息条目, 可能为空.
        """

        if message_projection is None:
            return []
        return [
            ContextContribution(
                source_kind="current_user_message",
                target_slot="message_current_user",
                priority=0,
                role="user",
                content=message_projection.model_content,
            )
        ]

    def _assemble_contributions(self, contributions: list[ContextContribution]) -> AssembledContext:
        """把正式条目拼成最终 system prompt 和 messages.

        Args:
            contributions: 当前 run 的正式上下文条目列表.

        Returns:
            一份 AssembledContext.
        """

        system_parts = [
            str(item.content)
            for item in sorted(contributions, key=self._sort_key)
            if item.target_slot == "system_prompt"
        ]
        messages = self._build_messages(contributions)
        return AssembledContext(
            system_prompt="\n\n".join(part for part in system_parts if part).strip(),
            messages=messages,
        )

    def _build_messages(self, contributions: list[ContextContribution]) -> list[dict[str, Any]]:
        """按 target_slot 固定顺序生成最终 messages.

        Args:
            contributions: 当前 run 的正式上下文条目列表.

        Returns:
            最终 messages 列表.
        """

        ordered = sorted(contributions, key=self._sort_key)
        messages: list[dict[str, Any]] = []
        for item in ordered:
            if item.target_slot == "system_prompt":
                continue
            messages.append({"role": item.role, "content": item.content})
        return messages

    def _sort_key(self, contribution: ContextContribution) -> tuple[int, int, int]:
        """返回正式上下文条目的稳定排序键.

        Args:
            contribution: 待排序的上下文条目.

        Returns:
            槽位顺序、同槽位优先级和原始历史顺序组成的排序键.
        """

        slot_order = self.SLOT_ORDER.get(contribution.target_slot, 999)
        history_index = int(contribution.metadata.get("history_index", 0) or 0)
        if contribution.target_slot == "message_history":
            return (slot_order, history_index, 0)
        return (slot_order, -contribution.priority, history_index)


# endregion


__all__ = ["ContextAssembler"]
