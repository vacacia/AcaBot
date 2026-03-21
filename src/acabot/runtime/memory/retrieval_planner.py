r"""runtime.retrieval_planner 提供 retrieval planning 和 prompt assembly.

组件关系:

    ThreadPipeline
        |
        +--> ContextCompactor.compact()
        |         |
        |         `--> working memory compaction
        |
        `--> RetrievalPlanner.prepare()
                  |
                  `--> retrieval scope / memory_type planning
        |
        `--> RetrievalPlanner.assemble()
                  |
                  +--> PromptSlot
                  `--> model-visible messages

这一层解决 3 个问题:

- 当前 run 到底该检索哪些 memory scopes 和 memory types.
- 把 compaction 后的 thread state 解释成可消费的 retrieval plan.
- system prompt 之外的动态上下文如何进入显式 prompt slots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .memory_broker import MemoryBlock
from ..contracts import PromptSlot, RetrievalPlan, RunContext
_KNOWN_MEMORY_SCOPES = {"relationship", "user", "channel", "global"}
_KNOWN_MEMORY_TYPES = {"sticky_note", "semantic", "relationship", "episodic", "reference", "task"}


# region config
@dataclass(slots=True)
class PromptAssemblyConfig:
    """prompt assembly 的运行配置.

    Attributes:
        soul_slot_position (str): soul 上下文默认注入位置.
        sticky_slot_position (str): sticky note 默认注入位置.
        computer_slot_position (str): computer state 默认注入位置.
        summary_slot_position (str): thread summary 默认注入位置.
        retrieval_slot_position (str): retrieval memory 默认注入位置.
        soul_message_role (str): soul 注入到 messages 时使用的 role.
        sticky_message_role (str): sticky note 注入到 messages 时使用的 role.
        computer_message_role (str): computer state 注入到 messages 时使用的 role.
        summary_message_role (str): thread summary 注入到 messages 时使用的 role.
        retrieval_message_role (str): retrieval memory 注入到 messages 时使用的 role.
        sticky_intro (str): sticky note slot 的提示模板.
        summary_prefix (str): thread summary compaction prefix.
        summary_suffix (str): thread summary compaction suffix.
        retrieval_intro (str): retrieval slot 的提示模板.
        default_scopes (list[str]): 未显式声明时默认读取的 scopes.
        default_memory_types (list[str]): 未显式声明时默认读取的 memory types.
    """

    soul_slot_position: str = "system_message"
    sticky_slot_position: str = "system_message"
    computer_slot_position: str = "system_message"
    summary_slot_position: str = "history_prefix"
    retrieval_slot_position: str = "system_message"
    soul_message_role: str = "system"
    sticky_message_role: str = "system"
    computer_message_role: str = "system"
    summary_message_role: str = "user"
    retrieval_message_role: str = "system"
    sticky_intro: str = "以下是稳定事实和长期规则. 默认可信, 除非当前上下文明确冲突."
    summary_prefix: str = (
        "The conversation history before this point was compacted into the following summary:\n\n"
        "<summary>\n"
    )
    summary_suffix: str = "\n</summary>"
    retrieval_intro: str = "以下是按需检索到的记忆. 可能不完全准确, 需要结合当前上下文判断."
    default_scopes: list[str] = field(
        default_factory=lambda: ["relationship", "user", "channel", "global"]
    )
    default_memory_types: list[str] = field(
        default_factory=lambda: ["sticky_note", "semantic", "relationship", "episodic"]
    )


# endregion


# region planner
class RetrievalPlanner:
    """retrieval planning 和 prompt assembly 的统一入口.

    Attributes:
        config (PromptAssemblyConfig): 当前 planner 的配置.
    """

    def __init__(
        self,
        config: PromptAssemblyConfig | None = None,
    ) -> None:
        """初始化 RetrievalPlanner.

        Args:
            config: 可选的 prompt assembly 配置.
        """

        self.config = config or PromptAssemblyConfig()

    def prepare(self, ctx: RunContext) -> RetrievalPlan:
        """为当前 run 计算 retrieval plan.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            一份 RetrievalPlan.
        """

        requested_scopes = self._requested_scopes(ctx)
        requested_memory_types = self._requested_memory_types(ctx)
        requested_tags = self._requested_tags(ctx)
        sticky_note_scopes = self._sticky_note_scopes(ctx)
        token_stats = dict(ctx.metadata.get("token_stats", {}))
        compressed_messages = [
            dict(message)
            for message in ctx.metadata.get("effective_compacted_messages", ctx.thread.working_messages)
        ]
        dropped_messages = [
            dict(message)
            for message in ctx.metadata.get("effective_dropped_messages", [])
        ]
        dropped_count = len(dropped_messages)
        summary_text = str(ctx.metadata.get("effective_working_summary", ctx.thread.working_summary) or "")
        plan = RetrievalPlan(
            requested_scopes=requested_scopes,
            requested_memory_types=requested_memory_types,
            requested_tags=requested_tags,
            sticky_note_scopes=sticky_note_scopes,
            compressed_messages=compressed_messages,
            dropped_messages=dropped_messages,
            prompt_slots=[],
            metadata={
                "history_before": len(compressed_messages) + dropped_count,
                "history_after": len(compressed_messages),
                "dropped_count": dropped_count,
                "thread_summary_present": bool(summary_text.strip()),
                "working_summary_text": summary_text,
                "token_stats": token_stats,
                "context_labels": list(
                    ctx.context_decision.context_labels if ctx.context_decision is not None else []
                ),
            },
        )
        return plan

    def assemble(
        self,
        ctx: RunContext,
        *,
        memory_blocks: list[MemoryBlock],
    ) -> list[dict[str, Any]]:
        """把 retrieval plan 和 memory blocks 组装成最终 messages.

        Args:
            ctx: 当前 run 的执行上下文.
            memory_blocks: 当前 run 检索到的 memory blocks.

        Returns:
            一份最终发送给 model 的 message 列表.
        """

        plan = ctx.retrieval_plan or self.prepare(ctx)
        sticky_blocks, retrieved_blocks = self._split_memory_blocks(
            memory_blocks,
            allowed_sticky_scopes=plan.sticky_note_scopes,
        )
        slots: list[PromptSlot] = []

        slots.extend(self._context_slots(ctx))

        soul_text = str(ctx.metadata.get("soul_prompt_text", "") or "").strip()
        if soul_text:
            slots.append(
                PromptSlot(
                    slot_id="slot:soul",
                    slot_type="soul_context",
                    title="Soul",
                    content=soul_text,
                    position=self.config.soul_slot_position,
                    message_role=self.config.soul_message_role,
                    stable=True,
                )
            )

        if sticky_blocks:
            slots.append(
                PromptSlot(
                    slot_id="slot:sticky",
                    slot_type="sticky_notes",
                    title="Sticky Notes",
                    content=self._format_sticky_notes(sticky_blocks),
                    position=self.config.sticky_slot_position,
                    message_role=self.config.sticky_message_role,
                    stable=True,
                    metadata={
                        "memory_count": len(sticky_blocks),
                        "source_ids": [source_id for block in sticky_blocks for source_id in block.source_ids],
                    },
                )
            )

        computer_state = self._collect_computer_state(ctx)
        if computer_state:
            slots.append(
                PromptSlot(
                    slot_id="slot:computer",
                    slot_type="computer_state",
                    title="Computer State",
                    content=self._format_computer_state(computer_state),
                    position=self.config.computer_slot_position,
                    message_role=self.config.computer_message_role,
                    stable=False,
                    metadata={
                        "backend_kind": computer_state["backend_kind"],
                        "attachment_count": computer_state["attachment_count"],
                        "session_count": len(computer_state["active_session_ids"]),
                    },
                )
            )

        working_summary = str(plan.metadata.get("working_summary_text", "") or "").strip()
        if not working_summary:
            working_summary = str(ctx.thread.working_summary or "").strip()
        if working_summary:
            slots.append(
                PromptSlot(
                    slot_id="slot:summary",
                    slot_type="thread_summary",
                    title="Thread Summary",
                    content=(
                        f"{self.config.summary_prefix}"
                        f"{working_summary}"
                        f"{self.config.summary_suffix}"
                    ),
                    position=self.config.summary_slot_position,
                    message_role=self.config.summary_message_role,
                    stable=False,
                    metadata={"summary_length": len(working_summary)},
                )
            )

        if retrieved_blocks:
            slots.append(
                PromptSlot(
                    slot_id="slot:retrieval",
                    slot_type="retrieved_memory",
                    title="Retrieved Memory",
                    content=self._format_retrieved_memory(retrieved_blocks),
                    position=self.config.retrieval_slot_position,
                    message_role=self.config.retrieval_message_role,
                    stable=False,
                    metadata={
                        "memory_count": len(retrieved_blocks),
                        "source_ids": [source_id for block in retrieved_blocks for source_id in block.source_ids],
                    },
                )
            )

        plan.prompt_slots = slots
        ctx.prompt_slots = list(slots)
        return self._assemble_messages(plan)

    # region planning
    def _requested_scopes(self, ctx: RunContext) -> list[str]:
        """解析当前 run 需要读取的 memory scopes.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            去重后的 scope 列表.
        """

        raw_values = (
            list(ctx.extraction_decision.memory_scopes)
            if ctx.extraction_decision is not None
            else list(ctx.decision.metadata.get("event_memory_scopes", []))
        )
        context_scopes = self._sticky_note_scopes(ctx)
        scopes = [value for value in raw_values if value in _KNOWN_MEMORY_SCOPES]
        if not scopes:
            scopes = list(self.config.default_scopes)
        scopes.extend(context_scopes)
        return _dedupe(scopes)

    def _requested_memory_types(self, ctx: RunContext) -> list[str]:
        """解析当前 run 需要读取的 memory types.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            去重后的 memory_type 列表.
        """

        raw_values = list(ctx.decision.metadata.get("event_memory_scopes", []))
        memory_types = [value for value in raw_values if value in _KNOWN_MEMORY_TYPES]
        if not memory_types:
            memory_types = list(self.config.default_memory_types)
        return _dedupe(memory_types)

    @staticmethod
    def _requested_tags(ctx: RunContext) -> list[str]:
        """解析当前 run 的 retrieval tag 过滤条件.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[str]: 去重后的 retrieval tag 列表.
        """

        if ctx.context_decision is None:
            return []
        return _dedupe(list(ctx.context_decision.retrieval_tags))

    @staticmethod
    def _sticky_note_scopes(ctx: RunContext) -> list[str]:
        """解析 sticky note 允许注入的 scope 列表.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[str]: 去重后的 sticky note scope 列表.
        """

        if ctx.context_decision is None:
            return []
        return _dedupe([
            value for value in ctx.context_decision.sticky_note_scopes if value in _KNOWN_MEMORY_SCOPES
        ])

    # endregion

    # region slot formatting
    def _split_memory_blocks(
        self,
        blocks: list[MemoryBlock],
        *,
        allowed_sticky_scopes: list[str],
    ) -> tuple[list[MemoryBlock], list[MemoryBlock]]:
        """把 memory blocks 拆成 sticky 和普通 retrieval.

        Args:
            blocks: 当前 run 检索到的 memory blocks.
            allowed_sticky_scopes: sticky note 允许注入的 scope 列表.

        Returns:
            `(sticky_blocks, retrieved_blocks)`.
        """

        sticky_blocks: list[MemoryBlock] = []
        retrieved_blocks: list[MemoryBlock] = []
        allowed = set(allowed_sticky_scopes)
        for block in blocks:
            memory_type = str(block.metadata.get("memory_type", "") or "")
            if memory_type == "sticky_note":
                if allowed and block.scope not in allowed:
                    continue
                sticky_blocks.append(block)
                continue
            retrieved_blocks.append(block)
        return sticky_blocks, retrieved_blocks

    def _context_slots(self, ctx: RunContext) -> list[PromptSlot]:
        """把 context decision 转成 prompt slots.

        Args:
            ctx: 当前 run 的执行上下文.

        Returns:
            list[PromptSlot]: 需要优先注入的 context slots.
        """

        if ctx.context_decision is None:
            return []

        slots: list[PromptSlot] = []
        if ctx.context_decision.context_labels:
            slots.append(
                PromptSlot(
                    slot_id="slot:context-labels",
                    slot_type="context_labels",
                    title="Context Labels",
                    content=self._format_context_labels(ctx.context_decision.context_labels),
                    position="system_message",
                    message_role="system",
                    stable=True,
                    metadata={"labels": list(ctx.context_decision.context_labels)},
                )
            )

        for index, raw in enumerate(ctx.context_decision.prompt_slots, start=1):
            content = str(raw.get("content", "") or "").strip()
            if not content:
                continue
            slots.append(
                PromptSlot(
                    slot_id=str(raw.get("slot_id", f"slot:context:{index}") or f"slot:context:{index}"),
                    slot_type=str(raw.get("slot_type", "session_context") or "session_context"),
                    title=str(raw.get("title", f"Context Slot {index}") or f"Context Slot {index}"),
                    content=content,
                    position=str(raw.get("position", "system_message") or "system_message"),
                    message_role=str(raw.get("message_role", "system") or "system"),
                    stable=bool(raw.get("stable", True)),
                    metadata=dict(raw.get("metadata", {}) or {}),
                )
            )
        return slots

    @staticmethod
    def _format_context_labels(labels: list[str]) -> str:
        """把 context labels 格式化成可注入文本.

        Args:
            labels: 当前命中的 context labels.

        Returns:
            str: 适合注入 prompt 的文本.
        """

        lines = ["当前消息命中了这些上下文标签:"]
        for label in labels:
            lines.append(f"- {label}")
        return "\n".join(lines)

    def _format_sticky_notes(self, blocks: list[MemoryBlock]) -> str:
        """格式化 sticky notes slot.

        Args:
            blocks: sticky note blocks.

        Returns:
            适合注入 prompt 的文本.
        """

        lines = [self.config.sticky_intro]
        for block in blocks:
            lines.append(f"- {block.content}")
        return "\n".join(lines)

    def _format_retrieved_memory(self, blocks: list[MemoryBlock]) -> str:
        """格式化 retrieval memory slot.

        Args:
            blocks: 普通 retrieval blocks.

        Returns:
            适合注入 prompt 的文本.
        """

        sections = [self.config.retrieval_intro]
        for block in blocks:
            sections.append(f"[{block.title}]\n{block.content}")
        return "\n\n".join(sections)

    @staticmethod
    def _collect_computer_state(ctx: RunContext) -> dict[str, Any]:
        state = ctx.workspace_state
        if state is None:
            return {}
        return {
            "backend_kind": state.backend_kind,
            "workspace_visible_root": state.workspace_visible_root,
            "available_tools": list(state.available_tools),
            "attachment_count": state.attachment_count,
            "active_session_ids": list(state.active_session_ids),
            "mirrored_skill_names": list(state.mirrored_skill_names),
        }

    @staticmethod
    def _format_computer_state(state: dict[str, Any]) -> str:
        lines = [
            "You have access to a computer workspace.",
            f"- backend: {state['backend_kind']}",
            f"- cwd: {state['workspace_visible_root']}",
            f"- available_tools: {', '.join(state['available_tools']) or '-'}",
            f"- staged_attachments: {state['attachment_count']}",
            f"- active_sessions: {len(state['active_session_ids'])}",
            f"- mirrored_skills: {', '.join(state['mirrored_skill_names']) or '-'}",
            "Use tools to inspect files, attachments, sessions, or command output in detail.",
        ]
        return "\n".join(lines)

    def _assemble_messages(self, plan: RetrievalPlan) -> list[dict[str, Any]]:
        """把 prompt slots 和对话消息拼成最终 message list.

        Args:
            plan: 当前 run 的 RetrievalPlan.

        Returns:
            最终发送给 model 的消息列表.
        """

        slot_messages = [
            {"role": slot.message_role, "content": slot.content}
            for slot in plan.prompt_slots
            if slot.position in {"system_message", "history_prefix"}
        ]
        return [*slot_messages, *list(plan.compressed_messages)]
    # endregion


# endregion


# region helpers
def _dedupe(values: list[str]) -> list[str]:
    """保持顺序地去重字符串列表.

    Args:
        values: 原始字符串列表.

    Returns:
        去重后的字符串列表.
    """

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

# endregion
