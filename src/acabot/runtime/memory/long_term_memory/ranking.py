"""runtime.memory.long_term_memory.ranking 负责三路命中的统一排序."""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import LtmSearchHit, MemoryEntry


@dataclass(slots=True)
class HitChannelScore:
    """HitChannelScore 表示一条命中的来源位权结果.

    Attributes:
        rerank_score (int): 最终位权分数.
        symbolic_hit (bool): 是否命中结构检索.
        semantic_hit (bool): 是否命中语义检索.
        lexical_hit (bool): 是否命中词法检索.
    """

    rerank_score: int
    symbolic_hit: bool
    semantic_hit: bool
    lexical_hit: bool


@dataclass(slots=True)
class _HitAccumulator:
    """_HitAccumulator 暂存一条 entry 在三路召回中的合流状态.

    Attributes:
        entry (MemoryEntry): 原始长期记忆对象.
        symbolic_hit (bool): 是否命中结构检索.
        semantic_hit (bool): 是否命中语义检索.
        lexical_hit (bool): 是否命中词法检索.
        hit_sources (list[str]): 命中来源列表.
    """

    entry: MemoryEntry
    symbolic_hit: bool = False
    semantic_hit: bool = False
    lexical_hit: bool = False
    hit_sources: list[str] = field(default_factory=list)


def score_hit_channels(
    *,
    symbolic_hit: bool,
    semantic_hit: bool,
    lexical_hit: bool,
) -> HitChannelScore:
    """按正式位权规则给一条命中打分.

    Args:
        symbolic_hit: 是否命中结构检索.
        semantic_hit: 是否命中语义检索.
        lexical_hit: 是否命中词法检索.

    Returns:
        对应的位权分数对象.
    """

    rerank_score = 0
    if symbolic_hit:
        rerank_score += 100
    if semantic_hit:
        rerank_score += 40
    if lexical_hit:
        rerank_score += 10
    return HitChannelScore(
        rerank_score=rerank_score,
        symbolic_hit=symbolic_hit,
        semantic_hit=semantic_hit,
        lexical_hit=lexical_hit,
    )


def merge_ranked_entry_hits(
    *,
    semantic_hits: list[MemoryEntry],
    lexical_hits: list[MemoryEntry],
    symbolic_hits: list[MemoryEntry],
) -> list[LtmSearchHit]:
    """把三路召回结果合成统一排序后的命中列表.

    Args:
        semantic_hits: 语义召回结果.
        lexical_hits: 词法召回结果.
        symbolic_hits: 结构召回结果.

    Returns:
        统一排序后的命中列表.
    """

    merged: dict[str, _HitAccumulator] = {}
    for entry in semantic_hits:
        accumulator = merged.setdefault(entry.entry_id, _HitAccumulator(entry=entry))
        accumulator.semantic_hit = True
        if "semantic" not in accumulator.hit_sources:
            accumulator.hit_sources.append("semantic")
    for entry in lexical_hits:
        accumulator = merged.setdefault(entry.entry_id, _HitAccumulator(entry=entry))
        accumulator.lexical_hit = True
        if "lexical" not in accumulator.hit_sources:
            accumulator.hit_sources.append("lexical")
    for entry in symbolic_hits:
        accumulator = merged.setdefault(entry.entry_id, _HitAccumulator(entry=entry))
        accumulator.symbolic_hit = True
        if "symbolic" not in accumulator.hit_sources:
            accumulator.hit_sources.append("symbolic")

    hits: list[LtmSearchHit] = []
    for accumulator in merged.values():
        score = score_hit_channels(
            symbolic_hit=accumulator.symbolic_hit,
            semantic_hit=accumulator.semantic_hit,
            lexical_hit=accumulator.lexical_hit,
        )
        hits.append(
            LtmSearchHit(
                entry=accumulator.entry,
                rerank_score=score.rerank_score,
                hit_sources=list(accumulator.hit_sources),
                metadata={
                    "symbolic_hit": score.symbolic_hit,
                    "semantic_hit": score.semantic_hit,
                    "lexical_hit": score.lexical_hit,
                },
            )
        )
    hits.sort(key=lambda item: (item.rerank_score, item.entry.updated_at), reverse=True)
    return hits


__all__ = ["HitChannelScore", "merge_ranked_entry_hits", "score_hit_channels"]
