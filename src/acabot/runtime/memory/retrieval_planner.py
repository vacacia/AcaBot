r"""runtime.retrieval_planner 提供 prepare-only retrieval planning.

组件关系:

    ThreadPipeline
        |
        +--> ContextCompactor.compact()
        |         |
        |         `--> working memory compaction
        |
        `--> RetrievalPlanner.prepare()
                  |
                  `--> retrieval scope / retained-history planning

这一层解决 3 个问题:

- 当前 run 到底该检索哪些 memory scopes 和 memory types.
- 把 compaction 后的 thread state 解释成可消费的 retrieval plan.
- 把 context labels / sticky note scopes 这些控制面信息收进 plan metadata.
"""

from __future__ import annotations

from typing import Any

from ..contracts import RetrievalPlan, RunContext

_KNOWN_MEMORY_SCOPES = {"relationship", "user", "channel", "global"}


class RetrievalPlanner:
    """retrieval planning 的统一入口."""

    DEFAULT_SCOPES = ["relationship", "user", "channel", "global"]

    def prepare(self, ctx: RunContext) -> RetrievalPlan:
        """为当前 run 计算 retrieval plan."""

        requested_scopes = self._requested_scopes(ctx)
        requested_tags = self._requested_tags(ctx)
        sticky_note_scopes = self._sticky_note_scopes(ctx)
        token_stats = dict(ctx.metadata.get("token_stats", {}) or {})
        retained_history = [
            dict(message)
            for message in ctx.metadata.get("effective_compacted_messages", ctx.thread.working_messages)
        ]
        dropped_messages = [
            dict(message)
            for message in ctx.metadata.get("effective_dropped_messages", [])
        ]
        dropped_count = len(dropped_messages)
        summary_text = str(
            ctx.metadata.get("effective_working_summary", ctx.thread.working_summary) or ""
        ).strip()
        return RetrievalPlan(
            requested_scopes=requested_scopes,
            requested_tags=requested_tags,
            sticky_note_scopes=sticky_note_scopes,
            retained_history=retained_history,
            dropped_messages=dropped_messages,
            working_summary=summary_text,
            metadata={
                "history_before": len(retained_history) + dropped_count,
                "history_after": len(retained_history),
                "dropped_count": dropped_count,
                "summary_present": bool(summary_text),
                "token_stats": token_stats,
                "context_labels": list(
                    ctx.context_decision.context_labels if ctx.context_decision is not None else []
                ),
            },
        )

    def _requested_scopes(self, ctx: RunContext) -> list[str]:
        """解析当前 run 需要读取的 memory scopes."""

        raw_values = (
            list(ctx.extraction_decision.memory_scopes)
            if ctx.extraction_decision is not None
            else list(ctx.decision.metadata.get("event_memory_scopes", []))
        )
        context_scopes = self._sticky_note_scopes(ctx)
        scopes = [value for value in raw_values if value in _KNOWN_MEMORY_SCOPES]
        if raw_values and not scopes:
            return _dedupe(context_scopes)
        if not raw_values and not scopes:
            scopes = list(self.DEFAULT_SCOPES)
        scopes.extend(context_scopes)
        return _dedupe(scopes)

    @staticmethod
    def _requested_tags(ctx: RunContext) -> list[str]:
        """解析当前 run 的 retrieval tag 过滤条件."""

        if ctx.context_decision is None:
            return []
        return _dedupe(list(ctx.context_decision.retrieval_tags))

    @staticmethod
    def _sticky_note_scopes(ctx: RunContext) -> list[str]:
        """解析 sticky note 允许注入的 scope 列表."""

        if ctx.context_decision is None:
            return []
        return _dedupe(
            [
                value
                for value in ctx.context_decision.sticky_note_scopes
                if value in _KNOWN_MEMORY_SCOPES
            ]
        )


def _dedupe(values: list[str]) -> list[str]:
    """保持顺序地去重字符串列表."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
