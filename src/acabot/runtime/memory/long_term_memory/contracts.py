"""runtime.memory.long_term_memory.contracts 定义长期记忆正式对象.

这个模块只负责 Core SimpleMem 的内部正式契约:
- `MemoryEntry` 表示长期记忆原子对象
- `MemoryProvenance` 表示记忆依据
- `ConversationFactAnchorMap` 表示提取窗口里的本地锚点映射
- `LtmSearchHit` 和 `FailedWindowRecord` 表示检索与失败状态

它不负责:
- 生成 `entry_id`
- 给事实分配正式 `fact_id`
- 做 LanceDB 读写
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# region helpers
def _normalize_text(value: str) -> str:
    """清理一个文本字段的首尾空白.

    Args:
        value: 原始字符串.

    Returns:
        去掉首尾空白后的字符串.
    """

    return str(value or "").strip()


def _normalize_string_list(values: list[str]) -> list[str]:
    """把字符串列表收成去空、去重、保序的结果.

    Args:
        values: 原始字符串列表.

    Returns:
        规范化后的字符串列表.
    """

    normalized: list[str] = []
    for item in list(values or []):
        text = _normalize_text(item)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_canonical_fact_ids(fact_ids: list[str]) -> list[str]:
    """把 fact_id 列表收成规范的 canonical 集合.

    Args:
        fact_ids: 原始 fact_id 列表.

    Returns:
        去空、去重、排序后的 fact_id 列表.
    """

    return sorted({text for text in (_normalize_text(item) for item in list(fact_ids or [])) if text})


# endregion


# region contracts
@dataclass(slots=True)
class MemoryProvenance:
    """MemoryProvenance 表示一条长期记忆的依据集合.

    Attributes:
        fact_ids (list[str]): 这条记忆依赖的正式事实主键集合.
    """

    fact_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """规范化 provenance 里的 fact_id 集合."""

        self.fact_ids = _normalize_canonical_fact_ids(self.fact_ids)


@dataclass(slots=True)
class MemoryEntry:
    """MemoryEntry 表示 Core SimpleMem 的正式长期记忆对象.

    Attributes:
        entry_id (str): 这条记忆的稳定主键.
        conversation_id (str): 所属对话容器.
        created_at (int): 首次创建时间.
        updated_at (int): 最近一次实质更新时间.
        extractor_version (str): 提取器版本.
        topic (str): 短主题短语.
        lossless_restatement (str): 可独立理解的单条事实陈述.
        keywords (list[str]): 词法检索关键词.
        time_point (str | None): 单点时间.
        time_interval_start (str | None): 区间开始时间.
        time_interval_end (str | None): 区间结束时间.
        location (str | None): 自然语言地点描述.
        persons (list[str]): 参与人物列表.
        entities (list[str]): 相关实体列表.
        provenance (MemoryProvenance): 依据事实集合.
    """

    entry_id: str
    conversation_id: str
    created_at: int
    updated_at: int
    extractor_version: str
    topic: str
    lossless_restatement: str
    keywords: list[str] = field(default_factory=list)
    time_point: str | None = None
    time_interval_start: str | None = None
    time_interval_end: str | None = None
    location: str | None = None
    persons: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    provenance: MemoryProvenance = field(default_factory=MemoryProvenance)

    def __post_init__(self) -> None:
        """规范化字段并执行最小合法性校验."""

        self.entry_id = _normalize_text(self.entry_id)
        self.conversation_id = _normalize_text(self.conversation_id)
        self.extractor_version = _normalize_text(self.extractor_version)
        self.topic = _normalize_text(self.topic)
        self.lossless_restatement = _normalize_text(self.lossless_restatement)
        self.time_point = _normalize_text(self.time_point) or None
        self.time_interval_start = _normalize_text(self.time_interval_start) or None
        self.time_interval_end = _normalize_text(self.time_interval_end) or None
        self.location = _normalize_text(self.location) or None
        self.keywords = _normalize_string_list(self.keywords)
        self.persons = _normalize_string_list(self.persons)
        self.entities = _normalize_string_list(self.entities)
        if not self.entry_id:
            raise ValueError("entry_id is required")
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.extractor_version:
            raise ValueError("extractor_version is required")
        if not self.topic:
            raise ValueError("topic is required")
        if not self.lossless_restatement:
            raise ValueError("lossless_restatement is required")
        if not self.provenance.fact_ids:
            raise ValueError("provenance.fact_ids is required")


@dataclass(slots=True)
class ConversationFactAnchorMap:
    """ConversationFactAnchorMap 表示窗口级本地事实锚点映射.

    Attributes:
        anchors_by_fact_id (dict[str, str]): `fact_id -> anchor` 映射.
        fact_ids_by_anchor (dict[str, str]): `anchor -> fact_id` 映射.
    """

    anchors_by_fact_id: dict[str, str] = field(default_factory=dict)
    fact_ids_by_anchor: dict[str, str] = field(default_factory=dict)

    def anchor_for(self, fact_id: str) -> str | None:
        """按正式 fact_id 取本地锚点.

        Args:
            fact_id: 正式 fact_id.

        Returns:
            对应的窗口级锚点, 如果不存在则返回 None.
        """

        return self.anchors_by_fact_id.get(_normalize_text(fact_id))

    def fact_id_for(self, anchor_id: str) -> str | None:
        """按本地锚点取正式 fact_id.

        Args:
            anchor_id: 窗口级锚点.

        Returns:
            对应的正式 fact_id, 如果不存在则返回 None.
        """

        return self.fact_ids_by_anchor.get(_normalize_text(anchor_id))


@dataclass(slots=True)
class LtmSearchHit:
    """LtmSearchHit 表示一条长期记忆命中结果.

    Attributes:
        entry (MemoryEntry): 命中的长期记忆对象.
        rerank_score (int): 最终排序分数.
        hit_sources (list[str]): 命中来源, 例如 `semantic`、`lexical`、`symbolic`.
        metadata (dict[str, Any]): 检索阶段附加信息.
    """

    entry: MemoryEntry
    rerank_score: int
    hit_sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """规范化命中来源列表."""

        self.hit_sources = _normalize_string_list(self.hit_sources)


@dataclass(slots=True)
class FailedWindowRecord:
    """FailedWindowRecord 表示一次失败提取窗口.

    Attributes:
        window_id (str): 失败窗口主键.
        conversation_id (str): 所属对话容器.
        thread_id (str): 所属 thread.
        fact_ids (list[str]): 当前窗口涉及的正式事实主键.
        error (str): 最近一次失败原因.
        retry_count (int): 当前已重试次数.
        first_failed_at (int): 首次失败时间.
        last_failed_at (int): 最近一次失败时间.
    """

    window_id: str
    conversation_id: str
    thread_id: str
    fact_ids: list[str] = field(default_factory=list)
    error: str = ""
    retry_count: int = 0
    first_failed_at: int = 0
    last_failed_at: int = 0

    def __post_init__(self) -> None:
        """规范化失败窗口的主字段."""

        self.window_id = _normalize_text(self.window_id)
        self.conversation_id = _normalize_text(self.conversation_id)
        self.thread_id = _normalize_text(self.thread_id)
        self.error = _normalize_text(self.error)
        self.fact_ids = _normalize_canonical_fact_ids(self.fact_ids)
        if not self.window_id:
            raise ValueError("window_id is required")
        if not self.conversation_id:
            raise ValueError("conversation_id is required")
        if not self.thread_id:
            raise ValueError("thread_id is required")


# endregion


__all__ = [
    "ConversationFactAnchorMap",
    "FailedWindowRecord",
    "LtmSearchHit",
    "MemoryEntry",
    "MemoryProvenance",
]
