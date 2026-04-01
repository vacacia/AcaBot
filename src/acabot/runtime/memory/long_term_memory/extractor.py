"""runtime.memory.long_term_memory.extractor 负责窗口提取契约.

这个模块只负责:
- 构造给模型看的窗口 prompt
- 解析模型输出
- 执行窗口级 correctness 校验

它不负责:
- 选模型
- 发 embedding 请求
- 写 LanceDB

user message 模板放在同级 prompts/extraction_user.txt，
变量占位符：{conversation_id} / {context_section} / {facts_text}。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..conversation_facts import ConversationFact
from .contracts import ConversationFactAnchorMap, MemoryEntry, MemoryProvenance
from .fact_ids import (
    build_fact_id_from_conversation_fact,
    build_memory_entry_id,
    resolve_anchor_ids,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt_file(filename: str) -> str:
    """从 prompts/ 目录加载一个 prompt 文件.

    Args:
        filename: 文件名，例如 "extraction_user.txt".

    Returns:
        文件内容字符串.

    Raises:
        RuntimeError: 当文件不存在或无法读取时抛出.
    """

    path = _PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法加载 prompt 文件 {path}: {exc}") from exc


class WindowExtractionError(ValueError):
    """WindowExtractionError 表示整窗提取结果不合格."""


@dataclass(slots=True)
class ExtractionWindowPayload:
    """ExtractionWindowPayload 表示当前提取窗口传给模型的材料.

    Attributes:
        conversation_id (str): 所属对话容器.
        anchor_map (ConversationFactAnchorMap): 当前窗口锚点映射.
        fact_roles (dict[str, str]): fact_id 到 role 的映射，用于校验 evidence 来源。
        system_prompt (str): 给模型的 system prompt.
        prompt (str): 给模型的 user message.
    """

    conversation_id: str
    anchor_map: ConversationFactAnchorMap
    fact_roles: dict[str, str]
    system_prompt: str
    prompt: str


def build_extraction_window_payload(
    *,
    conversation_id: str,
    facts: list[ConversationFact],
    # previous_entry_summaries 暂时不启用。
    # 跨窗口去重由 storage 层负责（相同 entry_id 触发 upsert 合并），
    # 不依赖在 prompt 里告诉模型上一窗口提取了什么。
    # previous_entry_summaries: list[str] | None = None,
) -> ExtractionWindowPayload:
    """把一组事实收成给 extractor 模型看的窗口 payload.

    Args:
        conversation_id: 所属对话容器.
        facts: 当前窗口事实列表.

    Returns:
        提取窗口 payload.
    """

    fact_ids = [build_fact_id_from_conversation_fact(fact) for fact in facts]
    from .fact_ids import build_fact_anchor_map  # 局部导入，避免循环初始化难看

    anchor_map = build_fact_anchor_map(fact_ids)
    # 上一窗口已提取记忆(不使用)
    # context_section = ""
    # if previous_entry_summaries:
        # context_lines = ["[上一窗口已提取的记忆（仅供参考，避免提取重复内容）]"]
        # for summary in previous_entry_summaries[:5]:
            # context_lines.append(f"- {summary}")
        # context_section = "\n".join(context_lines) + "\n\n"
        
    # region 事实行
    fact_lines: list[str] = []
    fact_roles: dict[str, str] = {}
    for fact, fact_id in zip(facts, fact_ids, strict=False):
        anchor_id = anchor_map.anchor_for(fact_id)
        display_part = (
            f" | actor_display_name={fact.actor_display_name}"
            if fact.actor_display_name
            else ""
        )
        try:
            ts_readable = datetime.datetime.fromtimestamp(
                fact.timestamp, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (OSError, OverflowError, ValueError):
            ts_readable = str(fact.timestamp)
        # 每行格式：
        # f1 | role=user | actor_id=qq:user:10001 | actor_display_name=小明 | time=2025-03-15T10:00:00Z | text=我在学钢琴
        # f2 | role=assistant | actor_id=qq:bot:99999 | time=2025-03-15T10:00:05Z | text=学到哪个程度了？
        fact_lines.append(
            f"{anchor_id} | role={fact.role} | actor_id={fact.actor_id}"
            f"{display_part} | time={ts_readable} | text={fact.text}"
        )
        fact_roles[fact_id] = fact.role
    # endregion

    system_prompt = _load_prompt_file("extraction_system.txt")
    user_template = _load_prompt_file("extraction_user.txt")
    prompt = (
        user_template
        .replace("{conversation_id}", conversation_id)
        .replace("{facts_text}", "\n".join(fact_lines))
    )

    return ExtractionWindowPayload(
        conversation_id=conversation_id,
        anchor_map=anchor_map,
        fact_roles=fact_roles,
        system_prompt=system_prompt,
        prompt=prompt,
    )


def parse_extractor_response(
    *,
    response: Any,
    anchor_map: ConversationFactAnchorMap,
    fact_roles: dict[str, str],
    conversation_id: str,
    extractor_version: str,
    now_ts: int,
) -> list[MemoryEntry]:
    """把模型输出解析成 `MemoryEntry` 列表.

    Args:
        response: 模型输出的 Python 对象.
        anchor_map: 当前窗口锚点映射.
        fact_roles: fact_id 到 role 的映射，用于校验 evidence 里至少有一条用户事实。
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
        # 硬校验：至少有一条 evidence 来自用户，防止 bot 自己的回复变成记忆事实
        has_user_evidence = any(
            fact_roles.get(fid, "user") != "assistant" for fid in fact_ids
        )
        if not has_user_evidence:
            raise WindowExtractionError(
                "entry evidence must include at least one user fact, "
                "bot-only evidence is not allowed"
            )
        time_point = _optional_text(raw_entry.get("time_point"))
        time_interval_start = _optional_text(raw_entry.get("time_interval_start"))
        time_interval_end = _optional_text(raw_entry.get("time_interval_end"))
        # time_point 和 time_interval 互斥；模型如果两个都填了，丢弃 interval 保留 time_point
        if time_point and (time_interval_start or time_interval_end):
            time_interval_start = None
            time_interval_end = None
        entry = MemoryEntry(
            entry_id=build_memory_entry_id(conversation_id, fact_ids),
            conversation_id=conversation_id,
            created_at=now_ts,
            updated_at=now_ts,
            extractor_version=extractor_version,
            topic=str(raw_entry.get("topic", "") or ""),
            lossless_restatement=str(raw_entry.get("lossless_restatement", "") or ""),
            keywords=[str(item) for item in list(raw_entry.get("keywords", []) or [])],
            time_point=time_point,
            time_interval_start=time_interval_start,
            time_interval_end=time_interval_end,
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
