"""读取 session-owned agent 配置."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..computer import parse_computer_policy
from ..contracts import SessionAgent


def _normalize_string_list(raw_items: object, *, field_name: str, path: Path) -> list[str]:
    if raw_items in (None, ""):
        return []
    if not isinstance(raw_items, list):
        raise ValueError(f"{field_name} must be a list: {path}")
    items: list[str] = []
    seen: set[str] = set()
    for item in list(raw_items):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


class SessionAgentLoader:
    """从 `agent.yaml` 读取 `SessionAgent`."""

    def load(self, path: str | Path) -> SessionAgent:
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Session agent file must be a mapping: {path}")

        agent_id = str(raw.get("agent_id", "") or "").strip()
        if not agent_id:
            raise ValueError(f"agent_id is required: {path}")
        prompt_ref = str(raw.get("prompt_ref", "") or "").strip()
        if not prompt_ref:
            raise ValueError(f"prompt_ref is required: {path}")

        computer_policy_raw = raw.get("computer_policy")
        return SessionAgent(
            agent_id=agent_id,
            prompt_ref=prompt_ref,
            visible_tools=_normalize_string_list(raw.get("visible_tools", []), field_name="visible_tools", path=path),
            visible_skills=_normalize_string_list(raw.get("visible_skills", []), field_name="visible_skills", path=path),
            visible_subagents=_normalize_string_list(
                raw.get("visible_subagents", []),
                field_name="visible_subagents",
                path=path,
            ),
            computer_policy=parse_computer_policy(computer_policy_raw) if computer_policy_raw not in (None, "") else None,
            config=dict(raw),
        )


__all__ = ["SessionAgentLoader"]
