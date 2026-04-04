"""runtime.outbound_projection 负责统一出站消息摘要投影.

这里把一条出站消息拆成三层语义:
- `source_intent`: 模型原本想发什么, 只对高层 `SEND_MESSAGE_INTENT` 有意义
- `delivery action`: 平台最终真的发出去的低层动作
- `OutboundMessageProjection`: 基于上面两层生成的摘要结果

其中:
- `fact_text` 给 `MessageRecord.content_text` 用, 追求稳定、可搜索
- `thread_text` 给 thread working memory 用, 追求语义连续性
"""

from __future__ import annotations

from typing import Any

from acabot.types import Action, ActionType

from .contracts import OutboundMessageProjection


def snapshot_source_intent(action: Action) -> dict[str, Any]:
    """抓取高层 send intent 的原始语义快照.

    Args:
        action: 当前待发送动作.

    Returns:
        只有 `SEND_MESSAGE_INTENT` 会返回非空字典. 结果保留 `text`、
        `images`、`render`、`at_user`、`reply_to`、`target` 这些高层字段，
        方便 materialize 之后继续生成 continuity 摘要.
    """

    if action.action_type != ActionType.SEND_MESSAGE_INTENT:
        return {}

    payload = dict(action.payload)
    return {
        "text": _optional_text(payload.get("text")),
        "images": _normalize_images(payload.get("images")),
        "render": _optional_text(payload.get("render")),
        "at_user": _optional_text(payload.get("at_user")),
        "reply_to": _optional_text(action.reply_to),
        "target": _optional_text(payload.get("target")),
    }


def project_outbound_message(
    *,
    action: Action,
    source_intent: dict[str, Any] | None = None,
) -> OutboundMessageProjection:
    """为一条已送达消息生成 facts / working memory 两种摘要.

    Args:
        action: 平台最终真的发送出去的低层动作.
        source_intent: materialize 之前保留下来的高层发送语义.

    Returns:
        一个 `OutboundMessageProjection`.
    """

    fact_text = _project_fact_text(action)
    thread_text = _project_thread_text(action=action, source_intent=source_intent)
    return OutboundMessageProjection(
        fact_text=fact_text,
        thread_text=thread_text,
    )


def _project_fact_text(action: Action) -> str:
    """从 delivery action 生成稳定事实摘要."""

    payload = action.payload
    if action.action_type == ActionType.SEND_TEXT:
        return str(payload.get("text", ""))
    if action.action_type != ActionType.SEND_SEGMENTS:
        return ""

    parts: list[tuple[str, str]] = []
    for seg in payload.get("segments", []):
        seg_type = str(seg.get("type", "") or "")
        seg_data = dict(seg.get("data", {}) or {})
        if seg_type == "text":
            text = str(seg_data.get("text", "") or "")
            if text:
                parts.append(("text", text))
        elif seg_type == "at":
            qq = str(seg_data.get("qq", "") or "").strip()
            if qq:
                parts.append(("mention", f"@{qq}"))
        elif seg_type == "image":
            parts.append(("placeholder", "[图片]"))
        else:
            placeholder = seg_type.strip()
            if placeholder:
                parts.append(("placeholder", f"[{placeholder}]"))
    return _join_inline_parts(parts)


def _project_thread_text(
    *,
    action: Action,
    source_intent: dict[str, Any] | None,
) -> str:
    """从 source intent 优先生成 continuity 摘要, 不足时回退到事实摘要.

    对 render 来说, `thread_text` 要忠实保留原始 markdown / LaTeX 文本,
    而不是只留下最终图片占位符. 这样下一轮 run 读取 working memory 快照时，
    还能知道 bot 当时到底发了什么语义内容。
    """

    if not source_intent:
        return _project_fact_text(action)

    inline_parts: list[tuple[str, str]] = []
    at_user = _optional_text(source_intent.get("at_user"))
    if at_user:
        inline_parts.append(("mention", f"@{at_user}"))

    text = _optional_text(source_intent.get("text"))
    if text:
        inline_parts.append(("text", text))

    for _ in _normalize_images(source_intent.get("images")):
        inline_parts.append(("placeholder", "[图片]"))

    blocks: list[str] = []
    inline_text = _join_inline_parts(inline_parts)
    if inline_text:
        blocks.append(inline_text)

    render = _optional_text(source_intent.get("render"))
    if render:
        blocks.append(render)

    if blocks:
        return "\n".join(blocks)
    return _project_fact_text(action)


def _join_inline_parts(parts: list[tuple[str, str]]) -> str:
    """把行内片段拼成稳定文本, 兼顾 mention 和 placeholder 可读性."""

    preview = ""
    previous_kind = ""
    for kind, piece in parts:
        if not piece:
            continue
        if not preview:
            preview = piece
            previous_kind = kind
            continue

        joiner = ""
        if previous_kind == "mention":
            joiner = " "
        elif previous_kind == "text" and kind == "text":
            if not preview.endswith((" ", "\n", "\t")) and not piece.startswith((" ", "\n", "\t")):
                joiner = " "
        elif previous_kind == "text" and kind == "placeholder":
            if not preview.endswith((" ", "\n", "\t")) and not piece.startswith((" ", "\n", "\t")):
                joiner = " "
        elif previous_kind == "placeholder" and kind in {"text", "mention", "placeholder"}:
            joiner = " "
        elif previous_kind == "text" and kind == "mention":
            joiner = " "

        preview = f"{preview}{joiner}{piece}"
        previous_kind = kind
    return preview


def _normalize_images(value: Any) -> list[str]:
    """把图片列表规范成稳定的非空字符串数组."""

    images: list[str] = []
    for item in value or []:
        file_ref = str(item or "").strip()
        if file_ref:
            images.append(file_ref)
    return images


def _optional_text(value: Any) -> str | None:
    """把可选文本字段规范成 `str | None`."""

    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return None
    return text


__all__ = [
    "project_outbound_message",
    "snapshot_source_intent",
]
