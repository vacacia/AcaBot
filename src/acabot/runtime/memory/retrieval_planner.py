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
                  `--> retained-history / summary / retrieval-tag planning

这一层只整理共享 retrieval 现场:

- 把 compaction 后的 thread state 解释成可消费的 retrieval plan.
- 把 retrieval tags / sticky note scopes / context labels 收进 plan.
- 不替任何 memory source 预先决定内部 scope.
"""

from __future__ import annotations

from typing import Any

from ..contracts import RetrievalPlan, RunContext


class RetrievalPlanner:
    """retrieval planning 的统一入口."""

    def prepare(self, ctx: RunContext) -> RetrievalPlan:
        """为当前 run 计算 retrieval plan."""

        requested_tags = self._requested_tags(ctx)
        sticky_note_targets = self._sticky_note_targets(ctx)
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
            requested_tags=requested_tags,
            sticky_note_targets=sticky_note_targets,
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

    @staticmethod
    def _requested_tags(ctx: RunContext) -> list[str]:
        """解析当前 run 的 retrieval tag 过滤条件."""

        if ctx.context_decision is None:
            return []
        return _dedupe(list(ctx.context_decision.retrieval_tags))

    @staticmethod
    def _sticky_note_targets(ctx: RunContext) -> list[str]:
        """解析 sticky note 允许注入的实体引用列表."""

        if ctx.context_decision is None:
            return []
        return _dedupe([str(value) for value in ctx.context_decision.sticky_note_targets])


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
