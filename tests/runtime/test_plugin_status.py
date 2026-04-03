"""test_plugin_status 测试 StatusStore 读写逻辑."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acabot.runtime.plugin_status import PluginStatus, StatusStore


class TestStatusStore:
    """测试 StatusStore."""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """save + load 应能完整还原 PluginStatus."""

        store = StatusStore(tmp_path)
        status = PluginStatus(
            plugin_id="roundtrip",
            phase="loaded",
            load_error="",
            registered_tools=["tool_a", "tool_b"],
            registered_hooks=["pre_agent:MyHook"],
            updated_at="2026-04-03T00:00:00+00:00",
        )
        store.save(status)

        loaded = store.load("roundtrip")
        assert loaded is not None
        assert loaded.plugin_id == "roundtrip"
        assert loaded.phase == "loaded"
        assert loaded.registered_tools == ["tool_a", "tool_b"]
        assert loaded.registered_hooks == ["pre_agent:MyHook"]
        assert loaded.updated_at == "2026-04-03T00:00:00+00:00"

    def test_load_all_skips_bad_files(self, tmp_path: Path) -> None:
        """load_all 遇到坏文件应跳过, 不影响其他插件."""

        store = StatusStore(tmp_path)

        # 写一个好文件
        store.save(PluginStatus(plugin_id="good", phase="loaded"))

        # 写一个坏文件
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "status.json").write_text("not valid json {{}", encoding="utf-8")

        statuses = store.load_all()
        assert "good" in statuses
        assert "bad" not in statuses

    def test_delete_preserves_data_dir(self, tmp_path: Path) -> None:
        """delete 只删 status.json, 不删目录 (保护 data/)."""

        store = StatusStore(tmp_path)
        store.save(PluginStatus(plugin_id="with_data", phase="loaded"))

        # 模拟插件在自己的 data/ 下写了文件
        data_dir = tmp_path / "with_data" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "cache.db").write_text("some data", encoding="utf-8")

        store.delete("with_data")

        # status.json 应被删除
        assert not (tmp_path / "with_data" / "status.json").exists()
        # data/ 下的文件应保留
        assert (data_dir / "cache.db").exists()
        # 目录本身应保留
        assert (tmp_path / "with_data").is_dir()

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        """load 不存在的 plugin_id 应返回 None."""

        store = StatusStore(tmp_path)
        assert store.load("ghost") is None

    def test_save_creates_dirs(self, tmp_path: Path) -> None:
        """save 应自动创建子目录."""

        store = StatusStore(tmp_path / "nested" / "plugins")
        store.save(PluginStatus(plugin_id="deep", phase="disabled"))

        loaded = store.load("deep")
        assert loaded is not None
        assert loaded.phase == "disabled"
