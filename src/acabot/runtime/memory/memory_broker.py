"""runtime.memory_broker 定义长期记忆的统一入口.

这一层不管理 thread working memory.
它只负责:
- 把 RunContext 规范成共享 retrieval request
- 调用已注册的 memory source
- 合并成功结果并记录失败
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from inspect import isawaitable
from typing import Any, Protocol

from ..contracts import RunContext

FORMAL_TARGET_SLOTS = (
    "system_prompt",
    "message_prefix",
    "message_history",
    "message_current_user",
)


def _default_allowed_target_slots() -> list[str]:
    return list(FORMAL_TARGET_SLOTS)


# region memory对象
@dataclass(slots=True)
class MemoryAssemblySpec:
    """一条 memory block 的装配声明."""

    target_slot: str = "message_prefix"
    priority: int = 0


@dataclass(slots=True)
class MemoryBlock:
    """source 产出的统一长期记忆块."""

    content: str
    source: str
    scope: str | None = None
    source_ids: list[str] = field(default_factory=list)
    assembly: MemoryAssemblySpec = field(default_factory=MemoryAssemblySpec)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SharedMemoryRetrievalRequest:
    """所有 memory source 共用的一次 retrieval 输入."""

    run_id: str
    thread_id: str
    actor_id: str
    agent_id: str
    channel_scope: str
    event_id: str
    event_type: str
    event_timestamp: int
    event_tags: list[str] = field(default_factory=list)
    query_text: str = ""
    requested_tags: list[str] = field(default_factory=list)
    working_summary: str = ""
    retained_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemorySourceFailure:
    """单个 source 的 retrieval 失败记录."""

    source: str
    error: str


@dataclass(slots=True)
class MemoryBrokerResult:
    """一次 retrieval 的汇总结果."""

    blocks: list[MemoryBlock] = field(default_factory=list)
    failures: list[MemorySourceFailure] = field(default_factory=list)
    attempted_sources: list[str] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MemorySourcePolicy:
    """单个 source 的最小运行策略."""

    enabled: bool = True
    allowed_target_slots: list[str] = field(default_factory=_default_allowed_target_slots)


class MemorySource(Protocol):
    """Memory source 协议."""

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        ...


@dataclass(slots=True)
class NullMemorySource:
    """默认空 source."""

    async def __call__(self, request: SharedMemoryRetrievalRequest) -> list[MemoryBlock]:
        _ = request
        return []


@dataclass(slots=True)
class MemorySourceRegistry:
    """当前 runtime 已注册的 memory source 集合."""

    _sources: dict[str, MemorySource] = field(default_factory=dict)

    def register(self, source_id: str, source: MemorySource) -> None:
        self._sources[str(source_id)] = source

    def unregister(self, source_id: str) -> None:
        self._sources.pop(str(source_id), None)

    def get(self, source_id: str) -> MemorySource | None:
        return self._sources.get(str(source_id))

    def items(self) -> list[tuple[str, MemorySource]]:
        return list(self._sources.items())


class MemoryBroker:
    """统一记忆入口."""

    def __init__(
        self,
        *,
        registry: MemorySourceRegistry | None = None,
        policies: dict[str, MemorySourcePolicy] | None = None,
    ) -> None:
        self.registry = registry or MemorySourceRegistry()
        self.policies = dict(policies or {})

    async def retrieve(self, ctx: RunContext) -> MemoryBrokerResult:
        """为当前 run 检索长期记忆."""

        request = ctx.shared_memory_request or self._build_retrieval_request(ctx)
        ctx.shared_memory_request = request

        blocks: list[MemoryBlock] = []
        failures: list[MemorySourceFailure] = []
        attempted_sources: list[str] = []
        skipped_sources: list[str] = []

        for source_id, source in self.registry.items():
            policy = self.policies.get(source_id, MemorySourcePolicy())
            if not policy.enabled:
                skipped_sources.append(source_id)
                continue

            attempted_sources.append(source_id)
            try:
                result = source(request)
                if isawaitable(result):
                    result = await result
                normalized, normalization_failures = self._normalize_blocks(
                    source_id=source_id,
                    blocks=list(result),
                    policy=policy,
                )
            except Exception as exc:  # pragma: no cover - error surface covered in tests
                failures.append(MemorySourceFailure(source=source_id, error=str(exc)))
                continue
            blocks.extend(normalized)
            failures.extend(normalization_failures)

        return MemoryBrokerResult(
            blocks=blocks,
            failures=failures,
            attempted_sources=attempted_sources,
            skipped_sources=skipped_sources,
        )

    def _normalize_blocks(
        self,
        *,
        source_id: str,
        blocks: list[MemoryBlock],
        policy: MemorySourcePolicy,
    ) -> tuple[list[MemoryBlock], list[MemorySourceFailure]]:
        normalized: list[MemoryBlock] = []
        failures: list[MemorySourceFailure] = []
        allowed_slots = (
            set(policy.allowed_target_slots)
            if policy.allowed_target_slots is not None
            else set(FORMAL_TARGET_SLOTS)
        )

        for block in blocks:
            try:
                if not isinstance(block, MemoryBlock):
                    raise TypeError(
                        "source returned non-MemoryBlock item: "
                        f"{type(block).__name__}"
                    )
                block_source = str(block.source or source_id).strip()
                target_slot = str(block.assembly.target_slot or "message_prefix").strip()
                if target_slot not in FORMAL_TARGET_SLOTS or target_slot not in allowed_slots:
                    raise ValueError(f"invalid target_slot: {target_slot}")
                normalized.append(
                    replace(
                        block,
                        source=block_source,
                        assembly=MemoryAssemblySpec(
                            target_slot=target_slot,
                            priority=int(block.assembly.priority),
                        ),
                    )
                )
            except Exception as exc:
                failures.append(MemorySourceFailure(source=source_id, error=str(exc)))
        return normalized, failures

    # region request构造
    def _build_retrieval_request(self, ctx: RunContext) -> SharedMemoryRetrievalRequest:
        """把 RunContext 规范成共享 retrieval request."""

        retrieval_plan = ctx.retrieval_plan
        return SharedMemoryRetrievalRequest(
            run_id=ctx.run.run_id,
            thread_id=ctx.thread.thread_id,
            actor_id=ctx.decision.actor_id,
            agent_id=ctx.decision.agent_id,
            channel_scope=ctx.decision.channel_scope,
            event_id=ctx.event.event_id,
            event_type=ctx.event.event_type,
            event_timestamp=ctx.event.timestamp,
            event_tags=(
                list(ctx.extraction_decision.tags)
                if ctx.extraction_decision is not None
                else list(ctx.decision.metadata.get("event_tags", []))
            ),
            query_text=self._user_content(ctx),
            requested_tags=(
                list(retrieval_plan.requested_tags)
                if retrieval_plan is not None
                else (
                    list(ctx.context_decision.retrieval_tags)
                    if ctx.context_decision is not None
                    else []
                )
            ),
            working_summary=self._working_summary(ctx),
            retained_history=list(self._retained_history(ctx)),
            metadata={
                "run_mode": ctx.decision.run_mode,
                "sender_role": ctx.event.sender_role,
                "event_policy_id": ctx.decision.metadata.get("event_policy_id", ""),
                "sticky_note_targets": list(
                    retrieval_plan.sticky_note_targets if retrieval_plan is not None else []
                ),
                "context_labels": list(
                    retrieval_plan.metadata.get("context_labels", [])
                    if retrieval_plan is not None
                    else []
                ),
                "token_stats": dict(
                    retrieval_plan.metadata.get("token_stats", {})
                    if retrieval_plan is not None
                    else {}
                ),
            },
        )

    @staticmethod
    def _user_content(ctx: RunContext) -> str:
        if ctx.message_projection is not None and ctx.message_projection.memory_candidates:
            return MemoryBroker._format_memory_candidates(ctx.message_projection.memory_candidates)
        return str(ctx.memory_user_content or ctx.event.working_memory_text or "")

    @staticmethod
    def _format_memory_candidates(candidates: list[object]) -> str:
        parts: list[str] = []
        for candidate in candidates:
            text = str(getattr(candidate, "text", "") or "").strip()
            if not text:
                continue
            kind = str(getattr(candidate, "kind", "") or "")
            metadata = dict(getattr(candidate, "metadata", {}) or {})
            if kind == "base_text":
                parts.append(text)
                continue
            label = str(metadata.get("label", "") or "").strip()
            if label:
                parts.append(f"[系统补充-{label}: {text}]")
            else:
                parts.append(text)
        return " ".join(parts).strip()

    @staticmethod
    def _working_summary(ctx: RunContext) -> str:
        if ctx.retrieval_plan is not None:
            return str(ctx.retrieval_plan.working_summary or "")
        return str(ctx.metadata.get("effective_working_summary", ctx.thread.working_summary) or "")

    @staticmethod
    def _retained_history(ctx: RunContext) -> list[dict[str, Any]]:
        if ctx.retrieval_plan is not None:
            return [dict(message) for message in ctx.retrieval_plan.retained_history]
        return [
            dict(message)
            for message in ctx.metadata.get("effective_compacted_messages", ctx.thread.working_messages)
        ]

    # endregion


__all__ = [
    "FORMAL_TARGET_SLOTS",
    "MemoryAssemblySpec",
    "MemoryBlock",
    "MemoryBroker",
    "MemoryBrokerResult",
    "MemorySource",
    "MemorySourceFailure",
    "MemorySourcePolicy",
    "MemorySourceRegistry",
    "NullMemorySource",
    "SharedMemoryRetrievalRequest",
]
