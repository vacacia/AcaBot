"""test_plugin_spec 测试 SpecStore 读写逻辑."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from acabot.runtime.plugin_spec import PluginSpec, SpecStore


class TestSpecStore:
    """测试 SpecStore."""

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        """save + load 应能完整还原 PluginSpec."""

        store = SpecStore(tmp_path)
        spec = PluginSpec(
            plugin_id="roundtrip",
            enabled=True,
            config={"key": "value", "num": 42},
        )
        store.save(spec)

        loaded = store.load("roundtrip")
        assert loaded is not None
        assert loaded.plugin_id == "roundtrip"
        assert loaded.enabled is True
        assert loaded.config == {"key": "value", "num": 42}

    def test_load_all(self, tmp_path: Path) -> None:
        """load_all 应返回所有已保存的 specs."""

        store = SpecStore(tmp_path)
        store.save(PluginSpec(plugin_id="alpha", enabled=True))
        store.save(PluginSpec(plugin_id="beta", enabled=False))

        specs, errors = store.load_all()
        assert not errors
        assert len(specs) == 2
        assert "alpha" in specs
        assert "beta" in specs
        assert specs["alpha"].enabled is True
        assert specs["beta"].enabled is False

    def test_delete(self, tmp_path: Path) -> None:
        """delete 应删除 spec 文件和空目录."""

        store = SpecStore(tmp_path)
        store.save(PluginSpec(plugin_id="to_delete", enabled=True))
        assert store.load("to_delete") is not None

        store.delete("to_delete")
        assert store.load("to_delete") is None
        # 目录也应被删除 (因为空了)
        assert not (tmp_path / "to_delete").exists()

    def test_atomic_write(self, tmp_path: Path) -> None:
        """save 应使用原子写, 文件应是有效 YAML."""

        store = SpecStore(tmp_path)
        store.save(PluginSpec(plugin_id="atomic", enabled=True, config={"x": 1}))

        file_path = tmp_path / "atomic" / "plugin.yaml"
        assert file_path.exists()
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["plugin"]["enabled"] is True
        assert raw["config"]["x"] == 1

    def test_bad_yaml_error(self, tmp_path: Path) -> None:
        """解析失败的 spec 应出现在 errors 列表中."""

        plugin_dir = tmp_path / "bad"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.yaml").write_text("not: [valid: yaml: {{", encoding="utf-8")

        store = SpecStore(tmp_path)
        specs, errors = store.load_all()

        assert not specs
        assert len(errors) == 1
        assert errors[0].plugin_id == "bad"

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        """load 不存在的 plugin_id 应返回 None."""

        store = SpecStore(tmp_path)
        assert store.load("ghost") is None

    def test_load_all_empty_dir(self, tmp_path: Path) -> None:
        """空目录应返回空结果."""

        store = SpecStore(tmp_path)
        specs, errors = store.load_all()
        assert not specs
        assert not errors
