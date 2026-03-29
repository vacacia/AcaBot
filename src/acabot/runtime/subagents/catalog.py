"""runtime.subagents.catalog 定义 subagent catalog."""

from __future__ import annotations

from collections import defaultdict

from .loader import FileSystemSubagentPackageLoader
from .package import SubagentPackageDocument, SubagentPackageManifest


class SubagentCatalog:
    """统一 subagent catalog."""

    def __init__(self, loader: FileSystemSubagentPackageLoader | None = None) -> None:
        self.loader = loader
        self._subagents: list[SubagentPackageManifest] = []
        self._subagents_by_name: dict[str, list[SubagentPackageManifest]] = {}

    def reload(self) -> list[SubagentPackageManifest]:
        """重新扫描全部 subagent metadata."""

        if self.loader is None:
            self._subagents = []
            self._subagents_by_name = {}
            return []
        manifests = list(self.loader.discover())
        grouped: dict[str, list[SubagentPackageManifest]] = defaultdict(list)
        for item in manifests:
            grouped[item.subagent_name].append(item)
        self._subagents = sorted(
            manifests,
            key=lambda item: (item.subagent_name, self._scope_rank(item.scope), item.host_subagent_file_path),
        )
        self._subagents_by_name = {
            name: sorted(
                items,
                key=lambda item: (self._scope_rank(item.scope), item.host_subagent_file_path),
            )
            for name, items in grouped.items()
        }
        return self.list_all()

    def replace_loader(self, loader: FileSystemSubagentPackageLoader | None) -> None:
        """替换当前 catalog 使用的底层 loader."""

        self.loader = loader

    def get(self, subagent_name: str) -> SubagentPackageManifest | None:
        """按当前正式选择规则拿一条 subagent metadata."""

        candidates = self._subagents_by_name.get(subagent_name, [])
        if not candidates:
            return None
        return candidates[0]

    def list_all(self) -> list[SubagentPackageManifest]:
        """列出全部扫描到的 subagent metadata, 不做同名过滤."""

        return list(self._subagents)

    def read(self, subagent_name: str) -> SubagentPackageDocument:
        """按当前正式选择规则读取一条 subagent 文档."""

        manifest = self.get(subagent_name)
        if manifest is None:
            raise KeyError(subagent_name)
        if self.loader is None:
            raise KeyError(subagent_name)
        return self.loader.read_document_for_manifest(manifest)

    @staticmethod
    def _scope_rank(scope: str) -> int:
        """给 scope 一个稳定优先级."""

        if scope == "project":
            return 0
        if scope == "user":
            return 1
        return 99
