import base64
from pathlib import Path

import pytest

from acabot.runtime import (
    ResolvedAgent,
    ComputerPolicy,
    ComputerPolicyDecision,
    ComputerRuntime,
    ComputerRuntimeConfig,
    DockerSandboxBackend,
    RouteDecision,
    RunContext,
    RunRecord,
    ThreadState,
)
from acabot.types import EventAttachment, EventSource, MsgSegment, StandardEvent


_ONE_BY_ONE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAgMBgJ/gS2cAAAAASUVORK5CYII="
)
_ONE_BY_ONE_JPEG_BYTES = b"\xff\xd8\xff\xdb"
_ONE_BY_ONE_GIF_BYTES = b"GIF89a"
_ONE_BY_ONE_WEBP_BYTES = b"RIFF1234WEBP"


def _ctx(tmp_path: Path) -> tuple[ComputerRuntime, RunContext]:
    service = ComputerRuntime(
        config=ComputerRuntimeConfig(
            root_dir=str(tmp_path / "workspaces"),
            host_skills_catalog_root_path=str(tmp_path / "workspaces/catalog/skills"),
        )
    )
    event = StandardEvent(
        event_id="evt-1",
        event_type="message",
        platform="qq",
        timestamp=123,
        source=EventSource(
            platform="qq",
            message_type="private",
            user_id="10001",
            group_id=None,
        ),
        segments=[MsgSegment(type="text", data={"text": "hello"})],
        raw_message_id="msg-1",
        sender_nickname="acacia",
        sender_role=None,
    )
    ctx = RunContext(
        run=RunRecord(
            run_id="run:1",
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            trigger_event_id="evt-1",
            status="queued",
            started_at=123,
        ),
        event=event,
        decision=RouteDecision(
            thread_id="qq:user:10001",
            actor_id="qq:user:10001",
            agent_id="aca",
            channel_scope="qq:user:10001",
        ),
        thread=ThreadState(
            thread_id="qq:user:10001",
            channel_scope="qq:user:10001",
        ),
        agent=ResolvedAgent(
            agent_id="aca",
            name="Aca",
            prompt_ref="prompt/default",
            computer_policy=ComputerPolicy(),
            config={},
            skills=[],
        ),
        computer_policy_decision=ComputerPolicyDecision(
            actor_kind="frontstage_agent",
            backend="host",
            allow_exec=True,
            allow_sessions=True,
            roots={
                "workspace": {"visible": True},
                "skills": {"visible": True},
                "self": {"visible": True},
            },
            visible_skills=None,
        ),
    )
    return service, ctx


async def test_computer_runtime_prepares_workspace_state(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)

    await service.prepare_run_context(ctx)

    assert ctx.workspace_state is not None
    assert ctx.workspace_state.backend_kind == "host"
    assert ctx.workspace_state.workspace_visible_root == "/workspace"
    assert "bash" in ctx.workspace_state.available_tools
    assert Path(ctx.workspace_state.workspace_host_path).exists()
    assert ctx.world_view is not None
    assert ctx.world_view.resolve("/workspace").world_path == "/workspace"
    assert ctx.world_view.execution_view.workspace_path == ctx.workspace_state.workspace_host_path


async def test_computer_runtime_stages_file_url_attachments(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    source_file = tmp_path / "source.txt"
    source_file.write_text("hello attachment", encoding="utf-8")
    ctx.event.attachments = [
        EventAttachment(
            type="file",
            source=source_file.resolve().as_uri(),
            name="source.txt",
        )
    ]

    await service.prepare_run_context(ctx)

    assert len(ctx.attachment_snapshots) == 1
    assert ctx.attachment_snapshots[0].download_status == "staged"
    assert Path(ctx.attachment_snapshots[0].staged_path).read_text(encoding="utf-8") == "hello attachment"
    assert ctx.attachment_snapshots[0].metadata["world_path"].startswith("/workspace/attachments/inbound/evt-1/")


def test_computer_runtime_drops_removed_ls_and_grep_entrypoints() -> None:
    assert not hasattr(ComputerRuntime, "list_world_entries")
    assert not hasattr(ComputerRuntime, "grep_world")


async def test_computer_runtime_supports_exec_and_shell_session(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    policy = ctx.computer_policy_effective
    assert policy is not None

    exec_result = await service.exec_once(
        thread_id=ctx.thread.thread_id,
        command="printf 'hello world'",
        policy=policy,
        world_view=ctx.world_view,
    )
    session = await service.open_session(
        thread_id=ctx.thread.thread_id,
        agent_id=ctx.agent.agent_id,
        policy=policy,
        world_view=ctx.world_view,
    )
    await service.write_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
        command="printf 'session output'\n",
    )
    await service.write_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
        command="exit\n",
    )
    await service.close_session(
        thread_id=ctx.thread.thread_id,
        session_id=session.session_id,
    )

    assert exec_result.ok is True
    assert "hello world" in exec_result.stdout_excerpt
    assert session.cwd_visible == ctx.world_view.execution_view.workspace_path


async def test_computer_runtime_reads_and_writes_through_world_path_interface(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    write_result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        content="hello world",
    )
    read_result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
    )

    assert write_result.world_path == "/workspace/demo.txt"
    assert write_result.size_bytes == len("hello world".encode("utf-8"))
    assert read_result.world_path == "/workspace/demo.txt"
    assert read_result.text == "hello world"


async def test_computer_runtime_write_world_path_creates_parent_directories(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/nested/notes/demo.txt",
        content="nested hello",
    )

    nested_file = Path(ctx.world_view.resolve("/workspace/nested/notes/demo.txt").host_path)
    assert nested_file.read_text(encoding="utf-8") == "nested hello"
    assert result.world_path == "/workspace/nested/notes/demo.txt"
    assert result.size_bytes == len("nested hello".encode("utf-8"))


async def test_computer_runtime_write_world_path_overwrites_existing_file(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("old text", encoding="utf-8")

    result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        content="new text",
    )

    assert workspace_file.read_text(encoding="utf-8") == "new text"
    assert result.size_bytes == len("new text".encode("utf-8"))


async def test_computer_runtime_write_world_path_reports_utf8_byte_count(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        content="你好",
    )

    assert result.size_bytes == len("你好".encode("utf-8"))


async def test_computer_runtime_edit_world_path_replaces_exact_text(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("hello world\n", encoding="utf-8")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text="world",
        new_text="acabot",
    )

    assert workspace_file.read_text(encoding="utf-8") == "hello acabot\n"
    assert result.world_path == "/workspace/demo.txt"
    assert result.first_changed_line == 1
    assert "acabot" in result.diff


async def test_computer_runtime_edit_world_path_allows_deletion(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("hello world", encoding="utf-8")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text=" world",
        new_text="",
    )

    assert workspace_file.read_text(encoding="utf-8") == "hello"
    assert result.first_changed_line == 1


async def test_computer_runtime_edit_world_path_rejects_missing_old_text(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("hello world", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Could not find the exact text in /workspace/demo.txt",
    ):
        await service.edit_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            old_text="missing",
            new_text="new",
        )


async def test_computer_runtime_edit_world_path_rejects_multiple_matches(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("hello\nhello\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Found 2 occurrences of the text in /workspace/demo.txt",
    ):
        await service.edit_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            old_text="hello",
            new_text="bye",
        )


async def test_computer_runtime_edit_world_path_keeps_utf8_bom(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_bytes(b"\xef\xbb\xbfhello world")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text="world",
        new_text="acabot",
    )

    written = workspace_file.read_bytes()
    assert written.startswith(b"\xef\xbb\xbf")
    assert written.decode("utf-8-sig") == "hello acabot"
    assert result.first_changed_line == 1


async def test_computer_runtime_edit_world_path_keeps_crlf_line_endings(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_bytes(b"hello world\r\nsecond line\r\n")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text="world",
        new_text="acabot",
    )

    assert workspace_file.read_bytes() == b"hello acabot\r\nsecond line\r\n"
    assert result.first_changed_line == 1


async def test_computer_runtime_edit_world_path_supports_fuzzy_match(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text('say “hello”\n', encoding="utf-8")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text='say "hello"',
        new_text='say "hi"',
    )

    assert workspace_file.read_text(encoding="utf-8") == 'say "hi"\n'
    assert result.first_changed_line == 1


async def test_computer_runtime_edit_world_path_fuzzy_match_normalizes_other_lines_like_pi(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text('keep “quoted”\nreplace “hello”\n', encoding="utf-8")

    result = await service.edit_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        old_text='replace "hello"',
        new_text='replace "hi"',
    )

    assert workspace_file.read_text(encoding="utf-8") == 'keep "quoted"\nreplace "hi"\n'
    assert 'keep "quoted"' in result.diff


async def test_computer_runtime_edit_world_path_exact_match_still_rejects_fuzzy_duplicates_like_pi(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("a b\na\u00a0b\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Found 2 occurrences of the text in /workspace/demo.txt",
    ):
        await service.edit_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            old_text="a b",
            new_text="x",
        )


async def test_computer_runtime_read_world_path_supports_offset_and_limit(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("line1\nline2\nline3", encoding="utf-8")

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        offset=2,
        limit=1,
    )

    assert result.text == "line2\n\n[1 more lines in file. Use offset=3 to continue.]"


async def test_computer_runtime_read_world_path_counts_trailing_newline_correctly(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("line1\nline2\n", encoding="utf-8")

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
        offset=1,
        limit=1,
    )

    assert result.text == "line1\n\n[1 more lines in file. Use offset=2 to continue.]"
    with pytest.raises(ValueError, match=r"Offset 3 is beyond end of file \(2 lines total\)"):
        await service.read_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            offset=3,
        )


async def test_computer_runtime_read_world_path_rejects_offset_beyond_end(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("line1\nline2\nline3", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Offset 5 is beyond end of file \(3 lines total\)"):
        await service.read_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            offset=5,
        )


async def test_computer_runtime_read_world_path_rejects_non_positive_offset(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("line1\nline2\nline3", encoding="utf-8")

    with pytest.raises(ValueError, match="Offset must be a positive integer"):
        await service.read_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            offset=0,
        )


async def test_computer_runtime_read_world_path_rejects_non_positive_limit(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text("line1\nline2\nline3", encoding="utf-8")

    with pytest.raises(ValueError, match="Limit must be a positive integer"):
        await service.read_world_path(
            world_view=ctx.world_view,
            world_path="/workspace/demo.txt",
            limit=0,
        )


async def test_computer_runtime_read_world_path_does_not_point_to_missing_bash_tool(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    long_line = "a" * (50 * 1024 + 1)
    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.txt").host_path)
    workspace_file.write_text(long_line, encoding="utf-8")

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.txt",
    )

    assert "Use bash:" not in result.text
    assert "exceeds 50KB limit" in result.text


@pytest.mark.parametrize(
    ("world_path", "payload", "expected_mime"),
    [
        ("/workspace/pixel.png", base64.b64decode(_ONE_BY_ONE_PNG_BASE64), "image/png"),
        ("/workspace/pixel.jpg", _ONE_BY_ONE_JPEG_BYTES, "image/jpeg"),
        ("/workspace/pixel.gif", _ONE_BY_ONE_GIF_BYTES, "image/gif"),
        ("/workspace/pixel.webp", _ONE_BY_ONE_WEBP_BYTES, "image/webp"),
        ("/workspace/pixel.txt", base64.b64decode(_ONE_BY_ONE_PNG_BASE64), "image/png"),
    ],
)
async def test_computer_runtime_read_world_path_returns_image_blocks_for_supported_images(
    tmp_path: Path,
    world_path: str,
    payload: bytes,
    expected_mime: str,
) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve(world_path).host_path)
    workspace_file.write_bytes(payload)

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path=world_path,
    )

    assert isinstance(result.content, list)
    assert result.text == ""
    assert result.content[0]["type"] == "text"
    assert result.content[0]["text"].startswith(f"Read image file [{expected_mime}]")
    assert result.content[1]["type"] == "image_url"
    assert result.content[1]["image_url"]["url"].startswith(f"data:{expected_mime};base64,")


async def test_computer_runtime_read_world_path_replaces_invalid_utf8_bytes(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    workspace_file = Path(ctx.world_view.resolve("/workspace/demo.bin").host_path)
    workspace_file.write_bytes(b"abc\xffdef")

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/workspace/demo.bin",
    )

    assert result.text == "abc�def"
    assert result.content == "abc�def"


async def test_computer_runtime_read_world_path_can_materialize_visible_skill(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.agent.skills = ["sample_skill"]
    source_skill = tmp_path / "catalog" / "sample_skill"
    source_skill.mkdir(parents=True, exist_ok=True)
    (source_skill / "SKILL.md").write_text("sample skill", encoding="utf-8")

    class Catalog:
        def get(self, skill_name: str):
            if skill_name != "sample_skill":
                return None
            return type("Manifest", (), {"host_skill_root_path": str(source_skill)})()

    service.skill_catalog = Catalog()
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    result = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/skills/sample_skill/SKILL.md",
    )

    assert result.text == "sample skill"


async def test_computer_runtime_write_world_path_updates_canonical_skill_file(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.agent.skills = ["sample_skill"]
    source_skill = tmp_path / "catalog" / "sample_skill"
    source_skill.mkdir(parents=True, exist_ok=True)
    (source_skill / "SKILL.md").write_text("sample skill", encoding="utf-8")

    class Catalog:
        def get(self, skill_name: str):
            if skill_name != "sample_skill":
                return None
            return type("Manifest", (), {"host_skill_root_path": str(source_skill)})()

    service.skill_catalog = Catalog()
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/skills/sample_skill/SKILL.md",
        content="updated skill",
    )

    canonical_file = service.workspace_manager.skills_dir_for_thread(ctx.thread.thread_id) / "sample_skill" / "SKILL.md"
    assert result.world_path == "/skills/sample_skill/SKILL.md"
    assert canonical_file.read_text(encoding="utf-8") == "updated skill"

    read_back = await service.read_world_path(
        world_view=ctx.world_view,
        world_path="/skills/sample_skill/SKILL.md",
    )
    assert read_back.text == "updated skill"


async def test_computer_runtime_write_world_path_creates_new_file_inside_visible_skill(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.agent.skills = ["sample_skill"]
    source_skill = tmp_path / "catalog" / "sample_skill"
    source_skill.mkdir(parents=True, exist_ok=True)
    (source_skill / "SKILL.md").write_text("sample skill", encoding="utf-8")

    class Catalog:
        def get(self, skill_name: str):
            if skill_name != "sample_skill":
                return None
            return type("Manifest", (), {"host_skill_root_path": str(source_skill)})()

    service.skill_catalog = Catalog()
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    result = await service.write_world_path(
        world_view=ctx.world_view,
        world_path="/skills/sample_skill/new.txt",
        content="new file",
    )

    canonical_file = service.workspace_manager.skills_dir_for_thread(ctx.thread.thread_id) / "sample_skill" / "new.txt"
    assert result.world_path == "/skills/sample_skill/new.txt"
    assert canonical_file.read_text(encoding="utf-8") == "new file"


async def test_computer_runtime_bash_world_runs_command_in_execution_view(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None
    policy = ctx.computer_policy_effective
    assert policy is not None

    result = await service.bash_world(
        thread_id=ctx.thread.thread_id,
        command="printf 'hello from bash_world'",
        policy=policy,
        world_view=ctx.world_view,
    )

    assert result.ok is True
    assert "hello from bash_world" in result.stdout_excerpt


async def test_computer_runtime_bash_world_passes_timeout_to_backend(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None
    policy = ctx.computer_policy_effective
    assert policy is not None

    class Backend:
        kind = "host"

        async def exec_once(self, *, host_path, command, policy, timeout=None):
            assert host_path == Path(ctx.world_view.workspace_root_host_path)
            assert command == "printf 'timeout test'"
            assert timeout == 7
            assert policy.backend == "host"
            return type(
                "Result",
                (),
                {
                    "ok": True,
                    "exit_code": 0,
                    "stdout_excerpt": "timeout ok",
                    "stderr_excerpt": "",
                    "stdout_truncated": False,
                    "stderr_truncated": False,
                    "metadata": {},
                },
            )()

    service.backends["host"] = Backend()

    result = await service.bash_world(
        thread_id=ctx.thread.thread_id,
        command="printf 'timeout test'",
        timeout=7,
        policy=policy,
        world_view=ctx.world_view,
    )

    assert result.ok is True
    assert result.stdout_excerpt == "timeout ok"


async def test_computer_runtime_world_view_respects_decision_visible_skills(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.agent.skills = ["profile_skill"]
    ctx.computer_policy_decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="host",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": True},
            "skills": {"visible": True},
            "self": {"visible": True},
        },
        visible_skills=["decision_skill"],
    )
    shared_skills = service.workspace_manager.ensure_skills_layout(ctx.thread.thread_id)
    (shared_skills / "decision_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "decision_skill" / "SKILL.md").write_text("decision", encoding="utf-8")
    (shared_skills / "profile_skill").mkdir(parents=True, exist_ok=True)
    (shared_skills / "profile_skill" / "SKILL.md").write_text("profile", encoding="utf-8")

    await service.prepare_run_context(ctx)

    assert ctx.world_view is not None
    assert ctx.world_view.resolve("/skills/decision_skill/SKILL.md").root_kind == "skills"
    try:
        ctx.world_view.resolve("/skills/profile_skill/SKILL.md")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("profile-level skill should not leak into world view")


async def test_computer_runtime_refreshes_skills_world_view_after_mirroring(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.agent.skills = ["sample_skill"]
    source_skill = tmp_path / "catalog" / "sample_skill"
    source_skill.mkdir(parents=True, exist_ok=True)
    (source_skill / "SKILL.md").write_text("sample skill", encoding="utf-8")

    class Catalog:
        def get(self, skill_name: str):
            if skill_name != "sample_skill":
                return None
            return type("Manifest", (), {"host_skill_root_path": str(source_skill)})()

    await service.prepare_run_context(ctx)
    assert ctx.world_view is not None

    with pytest.raises(FileNotFoundError):
        ctx.world_view.resolve("/skills/sample_skill/SKILL.md")

    service.mark_skill_loaded(ctx.thread.thread_id, "sample_skill")
    await service.ensure_loaded_skills_mirrored(
        ctx.thread.thread_id,
        Catalog(),
        world_view=ctx.world_view,
    )

    resolved = ctx.world_view.resolve("/skills/sample_skill/SKILL.md")
    assert Path(resolved.host_path).read_text(encoding="utf-8") == "sample skill"


async def test_computer_runtime_hides_shell_tools_when_workspace_is_not_visible(tmp_path: Path) -> None:
    service, ctx = _ctx(tmp_path)
    ctx.computer_policy_decision = ComputerPolicyDecision(
        actor_kind="frontstage_agent",
        backend="host",
        allow_exec=True,
        allow_sessions=True,
        roots={
            "workspace": {"visible": False},
            "skills": {"visible": True},
            "self": {"visible": True},
        },
        visible_skills=None,
    )

    await service.prepare_run_context(ctx)

    assert ctx.workspace_state is not None
    assert "bash" not in ctx.workspace_state.available_tools
    assert "exec" not in ctx.workspace_state.available_tools
    assert "bash_open" not in ctx.workspace_state.available_tools


async def test_computer_runtime_resolves_platform_file_id_via_gateway_api(tmp_path: Path) -> None:
    source_file = tmp_path / "resolved.txt"
    source_file.write_text("resolved from gateway api", encoding="utf-8")

    class Gateway:
        async def call_api(self, action: str, params: dict[str, object]):
            assert action in {"get_file", "get_group_file_url"}
            assert params["file_id"] == "file-123"
            return {
                "status": "ok",
                "data": {
                    "url": source_file.resolve().as_uri(),
                },
            }

    service, ctx = _ctx(tmp_path)
    service.gateway = Gateway()
    ctx.event.attachments = [
        EventAttachment(
            type="file",
            source="file-123",
            name="resolved.txt",
            metadata={"id": "file-123"},
        )
    ]

    await service.prepare_run_context(ctx)

    assert len(ctx.attachment_snapshots) == 1
    assert ctx.attachment_snapshots[0].download_status == "staged"
    assert ctx.attachment_snapshots[0].source_kind == "platform_api_resolved"
    assert Path(ctx.attachment_snapshots[0].staged_path).read_text(encoding="utf-8") == "resolved from gateway api"


async def test_docker_backend_reports_status_from_known_container() -> None:
    backend = DockerSandboxBackend(
        image="python:3.12-slim",
        stdout_window_bytes=1024,
        stderr_window_bytes=1024,
        network_mode="bridge",
    )
    backend._containers["qq:user:10001"] = "container-123"

    status = await backend.get_sandbox_status(
        thread_id="qq:user:10001",
        host_path=Path("/tmp/workspace"),
    )

    assert status.active is True
    assert status.container_id == "container-123"
