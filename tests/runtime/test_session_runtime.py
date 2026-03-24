from dataclasses import replace
from pathlib import Path

from acabot.runtime.control.session_loader import SessionConfigLoader
from acabot.runtime.control.session_runtime import SessionRuntime
from acabot.types import EventSource, MsgSegment, StandardEvent


def _write_session(tmp_path: Path, *, plain_mode: str = "record_only") -> Path:
    """写入一份最小可用的 session config 测试夹具.

    Args:
        tmp_path (Path): pytest 提供的临时目录.
        plain_mode (str): `message.plain` surface 的 admission mode.

    Returns:
        Path: 写入后的配置文件路径.
    """

    config_path = tmp_path / "sessions/qq/group/123.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f"""
session:
  id: qq:group:123
  template: qq_group
  title: Example Group
frontstage:
  profile: aca.qq.group.default
selectors:
  sender_is_admin:
    sender_roles: [admin]
surfaces:
  message.mention:
    routing:
      default:
        profile: aca.qq.group.default
    admission:
      default:
        mode: respond
    computer:
      default:
        backend: docker
        allow_exec: true
        allow_sessions: true
      cases:
        - case_id: admin_host
          when_ref: sender_is_admin
          use:
            backend: host
  message.plain:
    admission:
      default:
        mode: {plain_mode}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _group_mention_event(*, sender_role: str = "admin") -> StandardEvent:
    """构造一条群聊里 @bot 的消息事件.

    Args:
        sender_role (str): 当前发言者角色.

    Returns:
        StandardEvent: 测试使用的标准事件对象.
    """

    return StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(platform="qq", message_type="group", user_id="10001", group_id="123"),
        segments=[MsgSegment(type="text", data={"text": "hello @bot"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=sender_role,
        mentions_self=True,
        targets_self=True,
    )


def test_session_loader_reads_surface_matrix_and_selectors(tmp_path: Path) -> None:
    _write_session(tmp_path)
    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    session = loader.load_by_session_id("qq:group:123")

    assert session.template_id == "qq_group"
    assert session.selectors["sender_is_admin"].sender_roles == ["admin"]
    assert session.surfaces["message.mention"].computer is not None
    assert session.surfaces["message.mention"].computer.cases[0].use["backend"] == "host"


def test_session_runtime_builds_facts_and_resolves_surface(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))

    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    assert facts.scene == "group"
    assert facts.channel_scope == "qq:group:123"
    assert facts.sender_roles == ["admin"]
    assert surface.surface_id == "message.mention"


def test_session_runtime_resolves_domain_decisions_from_surface_cases(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    routing = runtime.resolve_routing(facts, session, surface)
    admission = runtime.resolve_admission(facts, session, surface)
    computer = runtime.resolve_computer(facts, session, surface)

    assert routing.profile_id == "aca.qq.group.default"
    assert admission.mode == "respond"
    assert computer.backend == "host"
    assert computer.source_case_id == "admin_host"


def test_session_runtime_context_decision_no_longer_exposes_prompt_slots(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert not hasattr(decision, "prompt_slots")


def test_session_runtime_defaults_sticky_note_scopes_from_group_scene(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert decision.sticky_note_scopes == ["user", "channel"]


def test_session_runtime_preserves_explicit_empty_sticky_note_scopes(tmp_path: Path) -> None:
    config_path = tmp_path / "sessions/qq/group/123.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  profile: aca.qq.group.default
surfaces:
  message.mention:
    context:
      default:
        sticky_note_scopes: []
    admission:
      default:
        mode: respond
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert decision.sticky_note_scopes == []


def test_session_runtime_rejects_invalid_admission_mode(tmp_path: Path) -> None:
    _write_session(tmp_path, plain_mode="recordonly")
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="member"))
    facts = replace(facts, mentions_self=False, targets_self=False, metadata={**facts.metadata, "text": "plain"})
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    try:
        runtime.resolve_admission(facts, session, surface)
    except ValueError as exc:
        assert "unsupported admission mode" in str(exc)
    else:
        raise AssertionError("invalid admission mode should fail")



def test_session_runtime_does_not_fall_from_mention_into_command_surface(tmp_path: Path) -> None:
    config_path = tmp_path / "sessions/qq/group/123.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  profile: aca.qq.group.default
surfaces:
  message.command:
    admission:
      default:
        mode: respond
  message.plain:
    admission:
      default:
        mode: record_only
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="member"))
    session = runtime.load_session(facts)

    surface = runtime.resolve_surface(facts, session)

    assert surface.surface_id == "message.plain"



def test_session_runtime_rejects_unknown_when_ref(tmp_path: Path) -> None:
    config_path = tmp_path / "sessions/qq/group/123.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  profile: aca.qq.group.default
surfaces:
  message.mention:
    computer:
      default:
        backend: docker
      cases:
        - case_id: broken_ref
          when_ref: missing_selector
          use:
            backend: host
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    try:
        runtime.resolve_computer(facts, session, surface)
    except ValueError as exc:
        assert "unknown selector" in str(exc)
    else:
        raise AssertionError("unknown when_ref should fail")
