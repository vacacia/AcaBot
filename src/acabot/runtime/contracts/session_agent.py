"""session-owned agent 与 session bundle 的正式契约."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .session_config import SessionConfig

if TYPE_CHECKING:
    from ..computer import ComputerPolicy


@dataclass(slots=True)
class SessionAgent:
    """当前 session 自己的前台 agent 真源对象."""

    agent_id: str
    prompt_ref: str
    visible_tools: list[str] = field(default_factory=list)
    visible_skills: list[str] = field(default_factory=list)
    visible_subagents: list[str] = field(default_factory=list)
    computer_policy: "ComputerPolicy | None" = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionBundlePaths:
    """session bundle 的路径集合."""

    session_dir: Path
    session_config_path: Path
    agent_config_path: Path


@dataclass(slots=True)
class SessionBundle:
    """一个 session 目录解析出来的完整 bundle."""

    session_config: SessionConfig
    frontstage_agent: SessionAgent
    paths: SessionBundlePaths


__all__ = ["SessionAgent", "SessionBundle", "SessionBundlePaths"]
