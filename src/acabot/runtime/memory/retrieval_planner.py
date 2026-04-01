"""retrieval_planner 把 compaction 后的 RunContext 整理成 RetrievalPlan.

调用时机：ThreadPipeline 在 ContextCompactor.compact() 之后调用
RetrievalPlanner.prepare()，产出 RetrievalPlan 交给 MemoryBroker。

职责边界：
- 从 RunContext 里读取 compaction 结果（retained history、dropped messages、
  working summary）和 session 配置侧的 retrieval tags、sticky note targets。
- 把这些材料收成一个统一的 RetrievalPlan，供下游各记忆来源自行解释。
- 不做任何检索动作，也不替记忆来源决定内部查询方式。

数据方向：
  RunContext → RetrievalPlanner.prepare() → RetrievalPlan → MemoryBroker
"""

from __future__ import annotations

from ..contracts import RetrievalPlan, RunContext


class RetrievalPlanner:
    """把 RunContext 转成 RetrievalPlan 的唯一入口。

    调用方是 ThreadPipeline，产出交给 MemoryBroker。
    """

    def prepare(self, ctx: RunContext) -> RetrievalPlan:
        """从 RunContext 里提取 compaction 结果和 session 配置，组装成 RetrievalPlan。

        数据来源：
        - retained history / dropped messages / working summary 来自
          ContextCompactor 写入 ctx.metadata 的 compaction 结果。
        - retrieval tags / sticky note targets 来自 session 配置侧的
          ContextDecision。

        Args:
            ctx: 当前 run 上下文。

        Returns:
            组装好的 RetrievalPlan，包含检索标签、sticky note 目标、
            保留历史、丢弃消息、working summary 和统计元数据。
        """

        requested_tags = self._requested_tags(ctx)
        sticky_note_targets = self._sticky_note_targets(ctx)
        token_stats = dict(ctx.metadata.get("token_stats", {}) or {})

        # compaction 结果：compactor 会把压缩后的消息写进 ctx.metadata，
        # 如果没跑 compaction 就直接用 thread 原始 working_messages。
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
        """从 ContextDecision 里取 retrieval tag 过滤条件（去重、保序）。

        Args:
            ctx: 当前 run 上下文。

        Returns:
            去重后的 tag 列表，ContextDecision 为空时返回空列表。
        """

        if ctx.context_decision is None:
            return []
        return _dedupe(list(ctx.context_decision.retrieval_tags))

    @staticmethod
    def _sticky_note_targets(ctx: RunContext) -> list[str]:
        """从 ContextDecision 里取 sticky note 允许注入的 entity_ref 列表。

        Args:
            ctx: 当前 run 上下文。

        Returns:
            去重后的 entity_ref 列表，ContextDecision 为空时返回空列表。
        """

        if ctx.context_decision is None:
            return []
        return _dedupe([str(value) for value in ctx.context_decision.sticky_note_targets])


def _dedupe(values: list[str]) -> list[str]:
    """去重字符串列表，保持原始顺序。

    Args:
        values: 原始字符串列表。

    Returns:
        去重后的列表，第一次出现的位置保留。
    """

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
