"""旧 memory store 导出删除测试."""

import os
from pathlib import Path
import subprocess
import sys

import acabot.runtime as runtime


def test_runtime_facade_no_longer_exports_legacy_memory_store_types() -> None:
    assert not hasattr(runtime, "MemoryItem")
    assert not hasattr(runtime, "MemoryStore")
    assert not hasattr(runtime, "SQLiteMemoryStore")
    assert not hasattr(runtime, "InMemoryMemoryStore")


def test_runtime_facade_import_does_not_require_lancedb() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    existing_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
    src_path = str(root_dir / "src")
    env["PYTHONPATH"] = (
        src_path
        if not existing_pythonpath
        else f"{src_path}{os.pathsep}{existing_pythonpath}"
    )
    script = """
import importlib.abc

class BlockLanceDb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "lancedb" or fullname.startswith("lancedb."):
            raise ModuleNotFoundError("No module named 'lancedb'")
        return None

import sys
sys.meta_path.insert(0, BlockLanceDb())

import acabot.runtime
print("runtime-import-ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=root_dir,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "runtime-import-ok"


def test_build_long_term_memory_store_reports_missing_lancedb_dependency() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    existing_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
    src_path = str(root_dir / "src")
    env["PYTHONPATH"] = (
        src_path
        if not existing_pythonpath
        else f"{src_path}{os.pathsep}{existing_pythonpath}"
    )
    script = """
import importlib.abc
import sys

from acabot.config import Config
from acabot.runtime.bootstrap.builders import build_long_term_memory_store

class BlockLanceDb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "lancedb" or fullname.startswith("lancedb."):
            raise ModuleNotFoundError("No module named 'lancedb'")
        return None

sys.meta_path.insert(0, BlockLanceDb())

try:
    build_long_term_memory_store(Config({"runtime": {"long_term_memory": {"enabled": True}}}))
except RuntimeError as exc:
    print(str(exc))
    raise SystemExit(0)

raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=root_dir,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "requires LanceDB runtime dependencies" in result.stdout
    assert "lancedb" in result.stdout
