"""runtime.memory.long_term_memory.extractor 负责窗口提取契约.

这个模块只负责:
- 构造给模型看的窗口 prompt
- 解析模型输出
- 执行窗口级 correctness 校验

它不负责:
- 选模型
- 发 embedding 请求
- 写 LanceDB
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..conversation_facts import ConversationFact
from .contracts import ConversationFactAnchorMap, MemoryEntry, MemoryProvenance
from .fact_ids import (
    build_fact_id_from_conversation_fact,
    build_memory_entry_id,
    resolve_anchor_ids,
)


class WindowExtractionError(ValueError):
    """WindowExtractionError 表示整窗提取结果不合格."""


@dataclass(slots=True)
class ExtractionWindowPayload:
    """ExtractionWindowPayload 表示当前提取窗口传给模型的材料.

    Attributes:
        conversation_id (str): 所属对话容器.
        anchor_map (ConversationFactAnchorMap): 当前窗口锚点映射.
        prompt (str): 最终 prompt 文本.
    """

    conversation_id: str
    anchor_map: ConversationFactAnchorMap
    prompt: str


def build_extraction_window_payload(
    *,
    conversation_id: str,
    facts: list[ConversationFact],
) -> ExtractionWindowPayload:
    """把一组事实收成给 extractor 模型看的窗口 payload.

    Args:
        conversation_id: 所属对话容器.
        facts: 当前窗口事实列表.

    Returns:
        提取窗口 payload.
    """

    fact_ids = [build_fact_id_from_conversation_fact(fact) for fact in facts]
    anchor_map = ConversationFactAnchorMap(
        anchors_by_fact_id={},
        fact_ids_by_anchor={},
    )
    from .fact_ids import build_fact_anchor_map  # 局部导入，避免循环初始化难看

    anchor_map = build_fact_anchor_map(fact_ids)
    lines = [
        "你负责从当前对话窗口里抽取长期记忆。",
        f"conversation_id: {conversation_id}",
        "",
        "[当前窗口事实]",
    ]
    for fact, fact_id in zip(facts, fact_ids, strict=False):
        anchor_id = anchor_map.anchor_for(fact_id)
        lines.append(
            f"{anchor_id} | role={fact.role} | actor_id={fact.actor_id} | timestamp={fact.timestamp} | text={fact.text}"
        )
    lines.extend(
        [
            "",
            "输出 JSON。每条 entry 都必须带 evidence，evidence 只能引用上面的 f1/f2/... 锚点。",
        ]
    )
    return ExtractionWindowPayload(
        conversation_id=conversation_id,
        anchor_map=anchor_map,
        prompt="\n".join(lines).strip(),
    )


def parse_extractor_response(
    *,
    response: Any,
    anchor_map: ConversationFactAnchorMap,
    conversation_id: str,
    extractor_version: str,
    now_ts: int,
) -> list[MemoryEntry]:
    """把模型输出解析成 `MemoryEntry` 列表.

    Args:
        response: 模型输出的 Python 对象.
        anchor_map: 当前窗口锚点映射.
        conversation_id: 所属对话容器.
        extractor_version: 当前提取器版本.
        now_ts: 当前时间戳.

        Returns:
            当前窗口产出的长期记忆列表.

        Raises:
            WindowExtractionError: 当任何一条 entry 不合法时抛出.
    """

    raw_entries = _extract_entries_payload(response)
    parsed_entries: list[MemoryEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise WindowExtractionError("extractor entry must be an object")
        evidence = list(raw_entry.get("evidence", []) or [])
        try:
            fact_ids = resolve_anchor_ids(anchor_map, evidence)
        except ValueError as exc:
            raise WindowExtractionError(str(exc)) from exc
        if not fact_ids:
            raise WindowExtractionError("entry evidence is required")
        entry = MemoryEntry(
            entry_id=build_memory_entry_id(conversation_id, fact_ids),
            conversation_id=conversation_id,
            created_at=now_ts,
            updated_at=now_ts,
            extractor_version=extractor_version,
            topic=str(raw_entry.get("topic", "") or ""),
            lossless_restatement=str(raw_entry.get("lossless_restatement", "") or ""),
            keywords=[str(item) for item in list(raw_entry.get("keywords", []) or [])],
            time_point=_optional_text(raw_entry.get("time_point")),
            time_interval_start=_optional_text(raw_entry.get("time_interval_start")),
            time_interval_end=_optional_text(raw_entry.get("time_interval_end")),
            location=_optional_text(raw_entry.get("location")),
            persons=[str(item) for item in list(raw_entry.get("persons", []) or [])],
            entities=[str(item) for item in list(raw_entry.get("entities", []) or [])],
            provenance=MemoryProvenance(fact_ids=fact_ids),
        )
        parsed_entries.append(entry)
    return parsed_entries


def _extract_entries_payload(response: Any) -> list[dict[str, Any]]:
    """把模型输出规范成 entry 对象列表.

    Args:
        response: 模型输出.

    Returns:
        entry 对象列表.

    Raises:
        WindowExtractionError: 当输出结构不合法时抛出.
    """

    if isinstance(response, dict):
        entries = response.get("entries", [])
    else:
        entries = response
    if not isinstance(entries, list):
        raise WindowExtractionError("extractor response must be a list or an object with entries")
    return list(entries)


def _optional_text(value: Any) -> str | None:
    """把一个可选字段规范成字符串或 `None`.

    Args:
        value: 原始值.

    Returns:
        去空白后的字符串, 或者 `None`.
    """

    text = str(value or "").strip()
    return text or None


__all__ = [
    "ExtractionWindowPayload",
    "WindowExtractionError",
    "build_extraction_window_payload",
    "parse_extractor_response",
]
