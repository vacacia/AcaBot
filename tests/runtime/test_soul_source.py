from pathlib import Path

from acabot.runtime import SoulSource


def test_soul_source_initializes_self_layout_instead_of_legacy_core_files(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)

    assert source.list_files()[0]["name"] == "today.md"
    assert (tmp_path / "today.md").exists()
    assert (tmp_path / "daily").is_dir()
    assert not (tmp_path / "identity.md").exists()


def test_soul_source_appends_today_and_renders_recent_self_context(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)

    source.append_today_entry("[qq:group:123 time=1] vi 交代了部署任务")
    source.write_file("daily/2026-03-23.md", "# 2026-03-23\n- 完成部署")

    rendered = source.build_recent_context_text(max_daily_files=1)

    assert "today.md" in rendered
    assert "daily/2026-03-23.md" in rendered
    assert "部署任务" in rendered


def test_soul_source_only_renders_today_and_daily_files(tmp_path: Path) -> None:
    source = SoulSource(root_dir=tmp_path)

    source.append_today_entry("[qq:group:123 time=1] vi 交代了部署任务")
    source.write_file("daily/2026-03-23.md", "# 2026-03-23\n- 完成部署")
    source.write_file("identity.md", "# identity\n- aca")
    source.write_file("task.md", "# task\n- finish migration")
    source.write_file("notes.md", "# notes\n- do not inject")

    rendered = source.build_recent_context_text(max_daily_files=1)

    assert "today.md" in rendered
    assert "daily/2026-03-23.md" in rendered
    assert "identity.md" not in rendered
    assert "task.md" not in rendered
    assert "notes.md" not in rendered
