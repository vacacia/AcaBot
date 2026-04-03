"""test_plugin_package 测试 PackageCatalog 扫描逻辑."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from acabot.runtime.plugin_package import PackageCatalog, PluginPackage


def _write_manifest(plugin_dir: Path, manifest: dict) -> None:
    """辅助函数: 写入 plugin.yaml."""

    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


class TestPackageCatalog:
    """测试 PackageCatalog."""

    def test_scan_valid_plugin(self, tmp_path: Path) -> None:
        """扫描一个有效插件包, 应正确解析所有字段."""

        _write_manifest(tmp_path / "demo", {
            "plugin": {
                "plugin_id": "demo",
                "display_name": "Demo Plugin",
                "version": "2",
                "entrypoint": "plugins.demo:DemoPlugin",
                "default_config": {"key": "value"},
                "config_schema": {"type": "object"},
            }
        })

        catalog = PackageCatalog(tmp_path)
        packages, errors = catalog.scan()

        assert not errors
        assert "demo" in packages
        pkg = packages["demo"]
        assert pkg.plugin_id == "demo"
        assert pkg.display_name == "Demo Plugin"
        assert pkg.version == "2"
        assert pkg.entrypoint == "plugins.demo:DemoPlugin"
        assert pkg.default_config == {"key": "value"}
        assert pkg.config_schema == {"type": "object"}
        assert pkg.package_root == tmp_path / "demo"

    def test_scan_missing_manifest_skipped(self, tmp_path: Path) -> None:
        """没有 plugin.yaml 的目录应被静默跳过."""

        (tmp_path / "no_manifest").mkdir()

        catalog = PackageCatalog(tmp_path)
        packages, errors = catalog.scan()

        assert not packages
        assert not errors

    def test_scan_bad_manifest_error(self, tmp_path: Path) -> None:
        """plugin.yaml 格式错误应记录为 PackageScanError."""

        plugin_dir = tmp_path / "broken"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.yaml").write_text("not: [valid: yaml: {{", encoding="utf-8")

        catalog = PackageCatalog(tmp_path)
        packages, errors = catalog.scan()

        assert not packages
        assert len(errors) == 1
        assert errors[0].plugin_id == "broken"

    def test_scan_id_mismatch_error(self, tmp_path: Path) -> None:
        """plugin_id 和目录名不一致应记录为错误."""

        _write_manifest(tmp_path / "mydir", {
            "plugin": {
                "plugin_id": "different_id",
                "display_name": "Test",
            }
        })

        catalog = PackageCatalog(tmp_path)
        packages, errors = catalog.scan()

        assert not packages
        assert len(errors) == 1
        assert "different_id" in errors[0].error

    def test_scan_default_entrypoint(self, tmp_path: Path) -> None:
        """不写 entrypoint 时应使用默认值 plugins.<id>:Plugin."""

        _write_manifest(tmp_path / "simple", {
            "plugin": {
                "plugin_id": "simple",
                "display_name": "Simple",
            }
        })

        catalog = PackageCatalog(tmp_path)
        packages, errors = catalog.scan()

        assert not errors
        assert packages["simple"].entrypoint == "plugins.simple:Plugin"

    def test_get_reads_from_cache(self, tmp_path: Path) -> None:
        """get() 从最新 scan 缓存读取."""

        _write_manifest(tmp_path / "cached", {
            "plugin": {"plugin_id": "cached", "display_name": "Cached"}
        })

        catalog = PackageCatalog(tmp_path)
        assert catalog.get("cached") is None  # 扫描前为 None

        catalog.scan()
        pkg = catalog.get("cached")
        assert pkg is not None
        assert pkg.plugin_id == "cached"

    def test_scan_nonexistent_dir(self, tmp_path: Path) -> None:
        """目录不存在时应返回空结果."""

        catalog = PackageCatalog(tmp_path / "does_not_exist")
        packages, errors = catalog.scan()

        assert not packages
        assert not errors
