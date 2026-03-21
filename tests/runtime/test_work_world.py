from pathlib import Path

import pytest

from acabot.runtime import ComputerPolicyDecision, ComputerRuntimeConfig, WorkspaceManager
from acabot.runtime.computer.world import WorkWorldBuilder, WorldInputBundle


# region helpers

def _manager(tmp_path: Path) -> WorkspaceManager:
    """构造一个测试用的 WorkspaceManager.

    Args:
        tmp_path (Path): pytest 提供的临时目录.

    Returns:
        WorkspaceManager: 绑定到临时根目录的管理器.
    """

    return WorkspaceManager(
        ComputerRuntimeConfig(
            root_dir=str(tmp_path / "computer"),
            skill_catalog_dir=str(tmp_path / "skills-catalog"),
        )
    )



def _builder(tmp_path: Path) -> WorkWorldBuilder:
    """构造一个测试用的 WorkWorldBuilder.

    Args:
        tmp_path (Path): pytest 提供的临时目录.

    Returns:
        WorkWorldBuilder: 绑定到临时根目录的 builder.
    """

    manager = _manager(tmp_path)
    shared_skills = manager.ensure_skills_layout("qq:group:123")
    sample_skill = shared_skills / "sample_skill"
    sample_skill.mkdir(parents=True, exist_ok=True)
    (sample_skill / "SKILL.md").write_text("sample", encoding="utf-8")
    return WorkWorldBuilder(manager)



def _bundle(*, actor_kind: str) -> WorldInputBundle:
    """构造一份最小可用的 world input bundle.

    Args:
        actor_kind (str): 当前 actor 的 world 身份.

    Returns:
        WorldInputBundle: 测试使用的 world 输入对象.
    """

    roots = {
        "workspace": {"visible": True, "writable": True},
        "skills": {"visible": True, "writable": False},
        "self": {"visible": actor_kind != "subagent", "writable": actor_kind != "subagent"},
    }
    return WorldInputBundle(
        thread_id="qq:group:123",
        profile_id="aca.qq.group.default",
        actor_kind=actor_kind,
        self_scope_id="aca.qq.group.default",
        visible_skill_names=["sample_skill"],
        computer_policy=ComputerPolicyDecision(
            actor_kind=actor_kind,
            backend="host",
            allow_exec=True,
            allow_sessions=True,
            roots=roots,
            visible_skills=["sample_skill"],
        ),
    )


# endregion


def test_frontstage_world_exposes_workspace_skills_and_self(tmp_path: Path) -> None:
    world = _builder(tmp_path).build(_bundle(actor_kind="frontstage_agent"))

    workspace = world.resolve("/workspace/out.txt")
    skills = world.resolve("/skills/sample_skill/SKILL.md")
    self_path = world.resolve("/self/note.md")

    assert workspace.root_kind == "workspace"
    assert skills.root_kind == "skills"
    assert self_path.root_kind == "self"
    assert workspace.writable is True
    assert skills.writable is False
    assert Path(workspace.host_path).parent.name == "workspace"



def test_subagent_world_hides_self(tmp_path: Path) -> None:
    world = _builder(tmp_path).build(_bundle(actor_kind="subagent"))

    with pytest.raises(FileNotFoundError):
        world.resolve("/self/note.md")



def test_world_marks_skills_read_only_and_workspace_writable(tmp_path: Path) -> None:
    world = _builder(tmp_path).build(_bundle(actor_kind="frontstage_agent"))

    workspace = world.resolve("/workspace/out/report.md")
    skills = world.resolve("/skills/sample_skill/SKILL.md")

    assert workspace.writable is True
    assert skills.writable is False
    assert skills.execution_path == skills.host_path



def test_world_rejects_hidden_skill_even_if_files_exist_on_host(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    shared_skills = manager.ensure_skills_layout("qq:group:123")
    (shared_skills / "sample_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "sample_skill" / "SKILL.md").write_text("sample", encoding="utf-8")
    (shared_skills / "secret_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "secret_skill" / "SKILL.md").write_text("secret", encoding="utf-8")
    world = WorkWorldBuilder(manager).build(_bundle(actor_kind="frontstage_agent"))

    visible = world.resolve("/skills/sample_skill/SKILL.md")

    assert visible.root_kind == "skills"
    with pytest.raises(FileNotFoundError):
        world.resolve("/skills/secret_skill/SKILL.md")



def test_workspace_manager_keeps_distinct_ids_isolated(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    left = manager.workspace_dir_for_thread("qq:group:123")
    right = manager.workspace_dir_for_thread("qq/group/123")
    self_left = manager.self_dir_for_scope("aca:group:123")
    self_right = manager.self_dir_for_scope("aca/group/123")

    assert left != right
    assert self_left != self_right



def test_workspace_manager_round_trips_thread_ids_with_encoded_chars(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    workspace = manager.ensure_workspace_layout("qq:group:123/with space")

    assert manager.thread_id_from_workspace_path(workspace) == "qq:group:123/with space"



def test_world_resolves_root_paths_without_dot_suffix(tmp_path: Path) -> None:
    world = _builder(tmp_path).build(_bundle(actor_kind="frontstage_agent"))

    workspace_root = world.resolve("/workspace")
    skills_root = world.resolve("/skills")

    assert workspace_root.relative_path == ""
    assert skills_root.execution_path == skills_root.host_path



def test_world_rejects_visible_skill_that_was_not_materialized(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    world = WorkWorldBuilder(manager).build(_bundle(actor_kind="frontstage_agent"))

    with pytest.raises(FileNotFoundError):
        world.resolve("/skills/sample_skill/SKILL.md")



def test_world_respects_explicit_empty_visible_skill_list(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    shared_skills = manager.ensure_skills_layout("qq:group:123")
    (shared_skills / "sample_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "sample_skill" / "SKILL.md").write_text("sample", encoding="utf-8")
    bundle = _bundle(actor_kind="frontstage_agent")
    bundle = WorldInputBundle(
        thread_id=bundle.thread_id,
        profile_id=bundle.profile_id,
        actor_kind=bundle.actor_kind,
        self_scope_id=bundle.self_scope_id,
        visible_skill_names=[],
        computer_policy=ComputerPolicyDecision(
            actor_kind=bundle.computer_policy.actor_kind,
            backend=bundle.computer_policy.backend,
            allow_exec=bundle.computer_policy.allow_exec,
            allow_sessions=bundle.computer_policy.allow_sessions,
            roots=dict(bundle.computer_policy.roots),
            visible_skills=["sample_skill"],
        ),
    )
    world = WorkWorldBuilder(manager).build(bundle)

    with pytest.raises(FileNotFoundError):
        world.resolve("/skills/sample_skill/SKILL.md")
