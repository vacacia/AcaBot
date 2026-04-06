from dataclasses import replace
from pathlib import Path

import pytest

from acabot.runtime import RuntimeRouter
from acabot.runtime.control.session_loader import SessionConfigLoader, StaticSessionConfigLoader
from acabot.runtime.control.session_runtime import SessionRuntime
from acabot.runtime.contracts import SessionConfig
from acabot.types import EventSource, MsgSegment, StandardEvent


def _write_session(tmp_path: Path, *, plain_mode: str = "record_only") -> Path:
    """写入一份最小可用的 session config 测试夹具.

    Args:
        tmp_path (Path): pytest 提供的临时目录.
        plain_mode (str): `message.plain` surface 的 admission mode.

    Returns:
        Path: 写入后的配置文件路径.
    """

    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        f"""
session:
  id: qq:group:123
  template: qq_group
  title: Example Group
frontstage:
  agent_id: aca.qq.group.default
selectors:
  sender_is_admin:
    sender_roles: [admin]
surfaces:
  message.mention:
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
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
""".strip(),
        encoding="utf-8",
    )
    return bundle_dir


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


def _write_bot_admin_routed_group_session(tmp_path: Path) -> None:
    """写入一份按 bot 管理员身份切换 computer backend 的群聊会话."""

    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
selectors:
  bot_admin:
    is_bot_admin: true
surfaces:
  message.mention:
    admission:
      default:
        mode: respond
    computer:
      default:
        backend: docker
        allow_exec: true
        allow_sessions: true
      cases:
        - case_id: bot_admin_host
          when_ref: bot_admin
          use:
            backend: host
            allow_exec: true
            allow_sessions: true
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
""".strip(),
        encoding="utf-8",
    )


def test_session_loader_reads_surface_matrix_and_selectors(tmp_path: Path) -> None:
    _write_session(tmp_path)
    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    session = loader.load_by_session_id("qq:group:123")

    assert session.template_id == "qq_group"
    assert session.frontstage_agent_id == "aca.qq.group.default"
    assert session.selectors["sender_is_admin"].sender_roles == ["admin"]
    assert session.surfaces["message.mention"].computer is not None
    assert session.surfaces["message.mention"].computer.cases[0].use["backend"] == "host"


def test_session_loader_reads_is_bot_admin_selectors(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
frontstage:
  agent_id: aca.qq.group.default
selectors:
  bot_admin:
    is_bot_admin: true
surfaces:
  message.mention:
    admission:
      default:
        mode: respond
""".strip(),
        encoding="utf-8",
    )
    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    session = loader.load_by_session_id("qq:group:123")

    assert session.selectors["bot_admin"].is_bot_admin is True


def _build_default_static_session() -> SessionConfig:
    """构造一份带默认 extraction 的静态 session，用于替代已删除的 ConfigBackedSessionConfigLoader."""
    from acabot.runtime.contracts import (
        ExtractionDomainConfig,
        SurfaceConfig,
    )
    surface_ids = [
        "message.mention", "message.reply_to_bot", "message.command",
        "message.private", "message.plain", "notice.default",
    ]
    surfaces = {
        sid: SurfaceConfig(extraction=ExtractionDomainConfig(default={"tags": []}, cases=[]))
        for sid in surface_ids
    }
    return SessionConfig(session_id="", template_id="default", frontstage_agent_id="aca", surfaces=surfaces)


def test_static_session_loader_default_extraction_only_keeps_tags() -> None:
    loader = StaticSessionConfigLoader(_build_default_static_session())

    session = loader.load_by_session_id("qq:group:123")

    assert {
        surface_id: dict(surface.extraction.default)
        for surface_id, surface in session.surfaces.items()
        if surface.extraction is not None
    } == {
        "message.mention": {"tags": []},
        "message.reply_to_bot": {"tags": []},
        "message.command": {"tags": []},
        "message.private": {"tags": []},
        "message.plain": {"tags": []},
        "notice.default": {"tags": []},
    }


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


def test_session_runtime_marks_bot_admin_and_routes_host_without_sender_role_dependency(tmp_path: Path) -> None:
    _write_bot_admin_routed_group_session(tmp_path)
    runtime = SessionRuntime(
        SessionConfigLoader(config_root=tmp_path / "sessions"),
        shared_admin_actor_ids={"qq:user:10001"},
    )

    admin_facts = runtime.build_facts(_group_mention_event(sender_role="member"))
    admin_session = runtime.load_session(admin_facts)
    admin_surface = runtime.resolve_surface(admin_facts, admin_session)
    admin_computer = runtime.resolve_computer(admin_facts, admin_session, admin_surface)

    assert admin_facts.is_bot_admin is True
    assert admin_computer.backend == "host"
    assert admin_computer.source_case_id == "bot_admin_host"

    non_admin_runtime = SessionRuntime(
        SessionConfigLoader(config_root=tmp_path / "sessions"),
        shared_admin_actor_ids=set(),
    )
    non_admin_facts = non_admin_runtime.build_facts(_group_mention_event(sender_role="admin"))
    non_admin_session = non_admin_runtime.load_session(non_admin_facts)
    non_admin_surface = non_admin_runtime.resolve_surface(non_admin_facts, non_admin_session)
    non_admin_computer = non_admin_runtime.resolve_computer(non_admin_facts, non_admin_session, non_admin_surface)

    assert non_admin_facts.is_bot_admin is False
    assert non_admin_computer.backend == "docker"


def test_static_session_loader_inline_default_extraction_only_keeps_tags() -> None:
    session_config = _build_default_static_session()
    runtime = SessionRuntime(StaticSessionConfigLoader(session_config))
    router = RuntimeRouter(session_runtime=runtime)
    facts = router.session_runtime.build_facts(_group_mention_event(sender_role="admin"))

    session = router.session_runtime.load_session(facts)

    assert {
        surface_id: dict(surface.extraction.default)
        for surface_id, surface in session.surfaces.items()
        if surface.extraction is not None
    } == {
        "message.mention": {"tags": []},
        "message.reply_to_bot": {"tags": []},
        "message.command": {"tags": []},
        "message.private": {"tags": []},
        "message.plain": {"tags": []},
        "notice.default": {"tags": []},
    }


def test_session_runtime_resolves_domain_decisions_from_surface_cases(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    routing = runtime.resolve_routing(facts, session, surface)
    admission = runtime.resolve_admission(facts, session, surface)
    computer = runtime.resolve_computer(facts, session, surface)

    assert routing.agent_id == "aca.qq.group.default"
    assert admission.mode == "respond"
    assert computer.backend == "host"
    assert computer.source_case_id == "admin_host"


def test_session_loader_rejects_surface_routing_agent_override(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
frontstage:
  agent_id: aca.qq.group.default
surfaces:
  message.mention:
    routing:
      default:
        agent_id: should.be.ignored
        actor_lane: backstage
    admission:
      default:
        mode: respond
""".strip(),
        encoding="utf-8",
    )
    loader = SessionConfigLoader(config_root=tmp_path / "sessions")

    with pytest.raises(ValueError, match="routing agent_id override is not supported"):
        loader.load_by_session_id("qq:group:123")


def test_session_runtime_reads_visible_subagents_from_computer_block(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
surfaces:
  message.mention:
    admission:
      default:
        mode: respond
    computer:
      default:
        visible_subagents:
          - excel-worker
          - search-worker
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
  - search-worker
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_computer(facts, session, surface)

    assert decision.visible_subagents == ["excel-worker", "search-worker"]


def test_static_session_loader_inline_default_visible_subagents_is_empty() -> None:
    session_config = _build_default_static_session()
    runtime = SessionRuntime(StaticSessionConfigLoader(session_config))
    router = RuntimeRouter(session_runtime=runtime)
    facts = router.session_runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = router.session_runtime.load_session(facts)
    surface = router.session_runtime.resolve_surface(facts, session)

    decision = router.session_runtime.resolve_computer(facts, session, surface)

    assert decision.visible_subagents == []


def test_session_runtime_context_decision_no_longer_exposes_prompt_slots(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert not hasattr(decision, "prompt_slots")


def test_session_runtime_defaults_sticky_note_targets_from_group_scene(tmp_path: Path) -> None:
    _write_session(tmp_path)
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert decision.sticky_note_targets == [facts.actor_id, facts.channel_scope]


def test_session_runtime_preserves_explicit_empty_sticky_note_targets(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
surfaces:
  message.mention:
    context:
      default:
        sticky_note_targets: []
    admission:
      default:
        mode: respond
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    decision = runtime.resolve_context(facts, session, surface)

    assert decision.sticky_note_targets == []


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
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
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
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="member"))
    session = runtime.load_session(facts)

    surface = runtime.resolve_surface(facts, session)

    assert surface.surface_id == "message.plain"



def test_session_runtime_rejects_unknown_when_ref(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
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
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
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


def test_session_runtime_rejects_scalar_context_lists(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "sessions/qq/group/123"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:123
  template: qq_group
frontstage:
  agent_id: aca.qq.group.default
surfaces:
  message.mention:
    context:
      default:
        retrieval_tags: urgent
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills:
  - frontend-design
visible_subagents:
  - excel-worker
""".strip(),
        encoding="utf-8",
    )
    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))
    facts = runtime.build_facts(_group_mention_event(sender_role="admin"))
    session = runtime.load_session(facts)
    surface = runtime.resolve_surface(facts, session)

    try:
        runtime.resolve_context(facts, session, surface)
    except ValueError as exc:
        assert "retrieval_tags" in str(exc)
    else:
        raise AssertionError("scalar retrieval_tags should fail")


def _group_plain_event(*, sender_role: str = "member") -> StandardEvent:
    """构造一条群聊里普通文本消息事件（无 @，无回复机器人）."""
    return StandardEvent(
        event_id="evt-plain",
        event_type="message",
        platform="qq",
        timestamp=456,
        source=EventSource(platform="qq", message_type="group", user_id="10002", group_id="999"),
        segments=[MsgSegment(type="text", data={"text": "hello everyone"})],
        raw_message_id="msg-plain",
        sender_nickname="alice",
        sender_role=sender_role,
        mentions_self=False,
        targets_self=False,
    )


def test_surface_naming_resolves_admission_correctly(tmp_path: Path) -> None:
    """验证正确 surface 命名（message.plain / message.mention）时 admission 逻辑正确.

    当 surface 键使用正确命名时，resolve_surface() 能正确匹配候选链，
    resolve_admission() 返回对应的 mode。
    """
    # 写入 session config，使用正确的 surface 键名
    bundle_dir = tmp_path / "sessions/qq/group/999"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "session.yaml").write_text(
        """
session:
  id: qq:group:999
  template: qq_group
  title: Test Group
frontstage:
  agent_id: aca.qq.group.default
selectors:
  sender_is_admin:
    sender_roles: [admin]
surfaces:
  message.plain:
    admission:
      default:
        mode: silent_drop
  message.mention:
    admission:
      default:
        mode: respond
  message.reply_to_bot:
    admission:
      default:
        mode: respond
""".strip(),
        encoding="utf-8",
    )
    (bundle_dir / "agent.yaml").write_text(
        """
agent_id: aca.qq.group.default
prompt_ref: prompt/aca/default
visible_tools:
  - read
visible_skills: []
visible_subagents: []
""".strip(),
        encoding="utf-8",
    )

    runtime = SessionRuntime(SessionConfigLoader(config_root=tmp_path / "sessions"))

    # 场景 1: 普通消息（mentions_self=False, reply_targets_self=False）
    # 候选链: ["message.plain"] → 期望 admission.mode == "silent_drop"
    plain_facts = runtime.build_facts(_group_plain_event(sender_role="member"))
    plain_session = runtime.load_session(plain_facts)
    plain_surface = runtime.resolve_surface(plain_facts, plain_session)
    plain_admission = runtime.resolve_admission(plain_facts, plain_session, plain_surface)

    assert plain_surface.surface_id == "message.plain", (
        f"plain message should resolve to message.plain, got {plain_surface.surface_id}"
    )
    assert plain_admission.mode == "silent_drop", (
        f"plain message with silent_drop config should return silent_drop, got {plain_admission.mode}"
    )

    # 场景 2: @ 消息（mentions_self=True）
    # 候选链: ["message.mention", "message.plain"] → 期望 admission.mode == "respond"
    mention_event = StandardEvent(
        event_id="evt-mention",
        event_type="message",
        platform="qq",
        timestamp=789,
        source=EventSource(platform="qq", message_type="group", user_id="10003", group_id="999"),
        segments=[MsgSegment(type="text", data={"text": "hello @bot"})],
        raw_message_id="msg-mention",
        sender_nickname="bob",
        sender_role="member",
        mentions_self=True,
        targets_self=True,
    )
    mention_facts = runtime.build_facts(mention_event)
    mention_session = runtime.load_session(mention_facts)
    mention_surface = runtime.resolve_surface(mention_facts, mention_session)
    mention_admission = runtime.resolve_admission(mention_facts, mention_session, mention_surface)

    assert mention_surface.surface_id == "message.mention", (
        f"mention message should resolve to message.mention, got {mention_surface.surface_id}"
    )
    assert mention_admission.mode == "respond", (
        f"mention message with respond config should return respond, got {mention_admission.mode}"
    )
