"""Shared high-level send-intent normalization helpers.

这层只负责统一 `message.send` / notifications 这类高层发送入口的输入合同，
不直接发送消息，也不做 gateway 协议翻译。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

_CANONICAL_CONVERSATION_RE = re.compile(r"^qq:(group|user):[A-Za-z0-9._@!-]+$")
_REMOTE_PREFIXES = ("http://", "https://", "data:", "base64://")


def optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def require_send_content(*, text: str | None, images: list[str], render: str | None) -> None:
    if text is None and render is None and not images:
        raise ValueError("send requires at least one of text, images, or render")


def normalize_images(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("images must be a list of strings")
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        normalized.append(normalize_send_image_ref(text))
    return normalized


def normalize_send_image_ref(file_ref: str) -> str:
    raw = str(file_ref or "").strip()
    if raw.startswith(_REMOTE_PREFIXES):
        return raw
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ValueError("QQ local file sends require a relative path under /workspace")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("QQ local file sends require a safe relative path under /workspace")
    normalized = PurePosixPath(*parts).as_posix()
    return f"/workspace/{normalized}"


def normalize_target(raw_target: Any) -> str | None:
    canonical_target = optional_text(raw_target)
    if canonical_target is None:
        return None
    if not _CANONICAL_CONVERSATION_RE.match(canonical_target):
        raise ValueError(
            "message target must be a canonical conversation_id like qq:group:123 or qq:user:456"
        )
    return canonical_target


def normalize_send_intent_payload(
    *,
    text: Any = None,
    images: Any = None,
    render: Any = None,
    at_user: Any = None,
    target: Any = None,
) -> dict[str, Any]:
    normalized_text = optional_text(text)
    normalized_render = optional_text(render)
    normalized_images = normalize_images(images)
    require_send_content(text=normalized_text, images=normalized_images, render=normalized_render)
    return {
        "text": normalized_text,
        "images": normalized_images,
        "render": normalized_render,
        "at_user": optional_text(at_user),
        "target": normalize_target(target),
    }


__all__ = [
    "normalize_images",
    "normalize_send_image_ref",
    "normalize_send_intent_payload",
    "normalize_target",
    "optional_text",
    "require_send_content",
]
