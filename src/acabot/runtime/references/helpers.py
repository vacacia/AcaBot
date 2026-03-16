"""runtime.references.helpers 定义 reference provider 共享辅助函数."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .contracts import ReferenceBodyLevel


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_json(raw: str | None) -> Any:
    if not raw:
        return {}
    return json.loads(raw)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def truncate_text(value: str, *, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def build_abstract(content: str) -> str:
    return truncate_text(content, limit=120)


def build_overview(content: str) -> str:
    return truncate_text(content, limit=400)


def normalize_title(title: str, source_path: str) -> str:
    if title.strip():
        return title.strip()
    if source_path.strip():
        return Path(source_path).name or source_path.strip()
    return "untitled-reference"


def sanitize_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return cleaned or "default"


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "reference"


def space_id_from_uri(uri: str) -> str:
    parts = [part for part in uri.rstrip("/").split("/") if part]
    if not parts:
        return ""
    last = parts[-1]
    if last not in {"readonly_reference", "appendable_reference"} and "." not in last:
        return last
    if len(parts) >= 2:
        return parts[-2]
    return ""


def mode_from_uri(uri: str) -> str | None:
    parts = [part for part in uri.rstrip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part in {"readonly_reference", "appendable_reference"}:
            return part
        if part == "acabot" and index + 2 < len(parts):
            candidate = parts[index + 2]
            if candidate in {"readonly_reference", "appendable_reference"}:
                return candidate
    return None


def body_for_level(*, row: sqlite3.Row, level: ReferenceBodyLevel) -> str:
    if level == "overview":
        return str(row["overview"])
    if level == "full":
        return str(row["content"])
    return ""


def compute_local_score(query: str, row: sqlite3.Row) -> float:
    if not query:
        return 1.0
    weighted_fields = [
        (str(row["title"]).lower(), 4.0),
        (str(row["abstract"]).lower(), 3.0),
        (str(row["overview"]).lower(), 2.0),
        (str(row["content"]).lower(), 1.0),
    ]
    score = 0.0
    for text, weight in weighted_fields:
        score += float(text.count(query)) * weight
    if score > 0:
        return score

    tokens = [token for token in re.split(r"\s+", query) if token]
    if not tokens:
        return 0.0
    for text, weight in weighted_fields:
        overlap = sum(1 for token in tokens if token in text)
        if overlap:
            score += (overlap / len(tokens)) * weight
    return score


__all__ = [
    "body_for_level",
    "build_abstract",
    "build_overview",
    "compute_local_score",
    "decode_json",
    "encode_json",
    "hash_text",
    "mode_from_uri",
    "normalize_title",
    "sanitize_filename",
    "sanitize_identifier",
    "space_id_from_uri",
    "truncate_text",
]
