"""把 session 目录读成完整的 session bundle."""

from __future__ import annotations

from pathlib import Path

from ..contracts import SessionBundle, SessionBundlePaths
from .session_agent_loader import SessionAgentLoader
from .session_loader import SessionConfigLoader


class SessionBundleLoader:
    """按 session 目录加载 `session.yaml + agent.yaml`."""

    def __init__(
        self,
        *,
        config_root: str | Path,
        prompt_refs: set[str] | None = None,
        tool_names: set[str] | None = None,
        skill_names: set[str] | None = None,
        subagent_names: set[str] | None = None,
    ) -> None:
        self.config_root = Path(config_root)
        self.session_loader = SessionConfigLoader(config_root=self.config_root)
        self.session_agent_loader = SessionAgentLoader()
        self.prompt_refs = None if prompt_refs is None else set(prompt_refs)
        self.tool_names = None if tool_names is None else set(tool_names)
        self.skill_names = None if skill_names is None else set(skill_names)
        self.subagent_names = None if subagent_names is None else set(subagent_names)

    def session_dir_for_session_id(self, session_id: str) -> Path:
        return self.session_loader.path_for_session_id(session_id).parent

    def load_by_session_id(self, session_id: str) -> SessionBundle:
        session_config_path = self.session_loader.path_for_session_id(session_id)
        session_dir = session_config_path.parent
        agent_config_path = session_dir / "agent.yaml"
        if not agent_config_path.exists():
            raise FileNotFoundError(f"session agent config not found: {session_id}")

        session_config = self.session_loader.load_by_session_id(session_id)
        frontstage_agent = self.session_agent_loader.load(agent_config_path)
        if session_config.frontstage_agent_id != frontstage_agent.agent_id:
            raise ValueError(
                "frontstage_agent_id must match agent.yaml.agent_id: "
                f"{session_config.frontstage_agent_id} != {frontstage_agent.agent_id}"
            )
        self._validate_catalog_references(frontstage_agent)
        return SessionBundle(
            session_config=session_config,
            frontstage_agent=frontstage_agent,
            paths=SessionBundlePaths(
                session_dir=session_dir,
                session_config_path=session_config_path,
                agent_config_path=agent_config_path,
            ),
        )

    def _validate_catalog_references(self, frontstage_agent) -> None:
        if (
            self.prompt_refs is None
            or self.tool_names is None
            or self.skill_names is None
            or self.subagent_names is None
        ):
            raise ValueError("catalog validation inputs are required")
        problems: list[str] = []
        if frontstage_agent.prompt_ref not in self.prompt_refs:
            problems.append(f"prompt_ref={frontstage_agent.prompt_ref}")
        missing_tools = sorted(item for item in frontstage_agent.visible_tools if item not in self.tool_names)
        if missing_tools:
            problems.append(f"visible_tools={missing_tools}")
        missing_skills = sorted(item for item in frontstage_agent.visible_skills if item not in self.skill_names)
        if missing_skills:
            problems.append(f"visible_skills={missing_skills}")
        missing_subagents = sorted(item for item in frontstage_agent.visible_subagents if item not in self.subagent_names)
        if missing_subagents:
            problems.append(f"visible_subagents={missing_subagents}")
        if problems:
            raise ValueError("Unknown catalog references: " + ", ".join(problems))


__all__ = ["SessionBundleLoader"]
