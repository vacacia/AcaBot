from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from acabot.config import Config
from acabot.runtime import build_runtime_components
from acabot.runtime.control.extension_refresh import ExtensionRefreshService

from .test_outbox import FakeGateway


@dataclass
class FakeAgentResponse:
    text: str = ""
    attachments: list[Any] = field(default_factory=list)
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls_made: list[Any] = field(default_factory=list)
    model_used: str = ""
    raw: Any = None


class FakeAgent:
    def __init__(self, response: FakeAgentResponse) -> None:
        self.response = response

    async def run(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        request_options=None,
        max_tool_rounds=None,
        tools=None,
        tool_executor=None,
    ) -> FakeAgentResponse:
        _ = (
            system_prompt,
            messages,
            model,
            request_options,
            max_tool_rounds,
            tools,
            tool_executor,
        )
        return self.response


def _write_config(
    path: Path,
    *,
    base_dir: Path,
    skill_catalog_dirs: list[str] | None = None,
) -> None:
    runtime_filesystem: dict[str, Any] = {
        "base_dir": str(base_dir),
        "sessions_dir": "sessions",
    }
    if skill_catalog_dirs is not None:
        runtime_filesystem["skill_catalog_dirs"] = list(skill_catalog_dirs)
    path.write_text(
        yaml.safe_dump(
            {
                "gateway": {"host": "127.0.0.1", "port": 8080},
                "agent": {},
                "runtime": {
                    "filesystem": runtime_filesystem,
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_prompt(base_dir: Path) -> None:
    prompts_dir = base_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "default.md").write_text("hello", encoding="utf-8")


def _write_session_bundle(
    base_dir: Path,
    *,
    session_id: str = "qq:group:123",
    visible_skills: list[str] | None = None,
) -> Path:
    platform, scope_kind, identifier = session_id.split(":", 2)
    bundle_dir = base_dir / "sessions" / platform / scope_kind / identifier
    bundle_dir.mkdir(parents=True, exist_ok=True)
    agent_id = f"session:{session_id}:frontstage"
    (bundle_dir / "session.yaml").write_text(
        "\n".join(
            [
                "session:",
                f"  id: {session_id}",
                "  template: qq_group",
                "frontstage:",
                f"  agent_id: {agent_id}",
                "surfaces:",
                "  message.mention:",
                "    admission:",
                "      default:",
                "        mode: respond",
            ]
        ),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": agent_id,
                "prompt_ref": "prompt/default",
                "visible_tools": [],
                "visible_skills": list(visible_skills or []),
                "visible_subagents": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return bundle_dir


def _write_skill_package(root_dir: Path, relative_dir: str, *, name: str, description: str) -> None:
    skill_dir = root_dir / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
            ]
        ),
        encoding="utf-8",
    )


async def test_extension_refresh_rejects_when_project_skill_root_is_not_unique(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        base_dir=tmp_path,
        skill_catalog_dirs=["./extensions/skills", "./more-skills"],
    )
    _write_prompt(tmp_path)
    _write_session_bundle(tmp_path)
    _write_skill_package(tmp_path / "extensions" / "skills", "demo-skill", name="demo-skill", description="demo")

    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    service = ExtensionRefreshService(
        config_control_plane=components.config_control_plane,
        skill_catalog=components.skill_catalog,
    )

    with pytest.raises(ValueError, match="unique project-scope skill root"):
        await service.refresh_skills(session_id="qq:group:123")


async def test_extension_refresh_rewrites_visible_skills_and_recovers_stale_bundle(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    user_skills_dir = tmp_path / "user-skills"
    _write_config(
        config_path,
        base_dir=tmp_path,
        skill_catalog_dirs=["./extensions/skills", str(user_skills_dir)],
    )
    _write_prompt(tmp_path)
    bundle_dir = _write_session_bundle(tmp_path, visible_skills=["demo-skill"])
    project_skills_dir = tmp_path / "extensions" / "skills"
    _write_skill_package(project_skills_dir, "demo-skill", name="demo-skill", description="demo")
    _write_skill_package(project_skills_dir, "shared", name="shared", description="project winner")
    _write_skill_package(user_skills_dir, "shared", name="shared", description="user loser")
    _write_skill_package(user_skills_dir, "user-only", name="user-only", description="user only")

    config = Config.from_file(str(config_path))
    components = build_runtime_components(
        config,
        gateway=FakeGateway(),
        agent=FakeAgent(FakeAgentResponse(text="ok")),
    )
    service = ExtensionRefreshService(
        config_control_plane=components.config_control_plane,
        skill_catalog=components.skill_catalog,
    )

    _write_skill_package(project_skills_dir, "newly-added", name="newly-added", description="newly added")
    agent_yaml = bundle_dir / "agent.yaml"
    agent_payload = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
    agent_payload["visible_skills"] = ["stale-old", "shared", "shared"]
    agent_yaml.write_text(yaml.safe_dump(agent_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="visible_skills"):
        components.config_control_plane.session_bundle_loader.load_by_session_id("qq:group:123")

    result = await service.refresh_skills(session_id="qq:group:123")

    assert result["kind"] == "skills"
    assert result["changed"] is True
    assert result["visible_skills"] == ["demo-skill", "newly-added", "shared", "user-only"]
    assert yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))["visible_skills"] == [
        "demo-skill",
        "newly-added",
        "shared",
        "user-only",
    ]
    bundle = components.config_control_plane.session_bundle_loader.load_by_session_id("qq:group:123")
    assert bundle.frontstage_agent.visible_skills == ["demo-skill", "newly-added", "shared", "user-only"]
