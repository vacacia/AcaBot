"""runtime.plugins.reference_tools 提供 reference 读写插件.

组件关系:

    RuntimePluginManager
            |
            v
    ReferenceToolsPlugin
            |
            v
       ReferenceBackend

这个插件的定位是:
- 让 `reference / notebook` 变成一个真正可调用的 runtime plugin 能力
- 验证 `RuntimePluginContext.reference_backend` 的实际用途
- 先提供最小 add/search/read 能力
"""

from __future__ import annotations

from typing import Any, cast

from acabot.agent import ToolDef

from ..plugin_manager import RuntimePlugin, RuntimePluginContext
from ..references import (
    ReferenceBackend,
    ReferenceDocumentInput,
    ReferenceMode,
)


class ReferenceToolsPlugin(RuntimePlugin):
    """最小 reference 工具插件.

    Attributes:
        name (str): 插件名.
        _backend (ReferenceBackend | None): 当前 reference backend.
        _default_tenant_id (str): 默认 tenant_id.
        _default_space_id (str): 默认 space_id.
        _default_mode (ReferenceMode): 默认 reference mode.
    """

    name = "reference_tools"

    def __init__(self) -> None:
        """初始化空的插件状态."""

        self._backend: ReferenceBackend | None = None
        self._default_tenant_id = "default"
        self._default_space_id = "shared"
        self._default_mode: ReferenceMode = "readonly_reference"

    async def setup(self, runtime: RuntimePluginContext) -> None:
        """读取配置并保存 reference backend.

        Args:
            runtime: runtime plugin 上下文.
        """

        self._backend = runtime.reference_backend
        config = runtime.get_plugin_config(self.name)
        self._default_tenant_id = str(config.get("default_tenant_id", "default"))
        self._default_space_id = str(config.get("default_space_id", "shared"))
        self._default_mode = cast(
            ReferenceMode,
            str(config.get("default_mode", "readonly_reference")),
        )

    def tools(self) -> list[ToolDef]:
        """返回 reference 相关工具定义.

        Returns:
            `reference_add_document`, `reference_search`, `reference_read`.
        """

        return [
            ToolDef(
                name="reference_add_document",
                description="Add a document into the reference notebook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "abstract": {"type": "string"},
                        "overview": {"type": "string"},
                        "source_path": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "tenant_id": {"type": "string"},
                        "space_id": {"type": "string"},
                        "mode": {"type": "string"},
                    },
                    "required": ["title", "content"],
                },
                handler=self._add_document,
            ),
            ToolDef(
                name="reference_search",
                description="Search documents from the reference notebook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "tenant_id": {"type": "string"},
                        "space_id": {"type": "string"},
                        "mode": {"type": "string"},
                        "limit": {"type": "integer"},
                        "body": {"type": "string"},
                    },
                    "required": ["query"],
                },
                handler=self._search,
            ),
            ToolDef(
                name="reference_read",
                description="Read a full document from the reference notebook.",
                parameters={
                    "type": "object",
                    "properties": {
                        "ref_id": {"type": "string"},
                        "tenant_id": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["ref_id"],
                },
                handler=self._read,
            ),
        ]

    # region handler
    async def _add_document(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """写入一条 reference 文档.

        Args:
            arguments: tool arguments.

        Returns:
            写入结果摘要.
        """

        backend = self._require_backend()
        document = ReferenceDocumentInput(
            title=str(arguments.get("title", "") or ""),
            content=str(arguments.get("content", "") or ""),
            abstract=str(arguments.get("abstract", "") or ""),
            overview=str(arguments.get("overview", "") or ""),
            source_path=str(arguments.get("source_path", "") or ""),
            tags=[str(item) for item in list(arguments.get("tags", []) or [])],
        )
        refs = await backend.add_documents(
            [document],
            tenant_id=self._tenant_id(arguments),
            space_id=self._space_id(arguments),
            mode=self._mode(arguments),
        )
        created = refs[0]
        return {
            "ref_id": created.ref_id,
            "uri": created.uri,
            "title": created.title,
            "space_id": created.space_id,
            "mode": created.mode,
        }

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """检索 reference 文档.

        Args:
            arguments: tool arguments.

        Returns:
            命中摘要列表.
        """

        backend = self._require_backend()
        hits = await backend.search(
            str(arguments.get("query", "") or ""),
            tenant_id=self._tenant_id(arguments),
            space_id=str(arguments.get("space_id", "") or "") or None,
            mode=cast(ReferenceMode | None, str(arguments.get("mode", "") or "") or None),
            limit=int(arguments.get("limit", 5) or 5),
            body=str(arguments.get("body", "overview") or "overview"),
        )
        return {
            "hits": [
                {
                    "ref_id": hit.ref_id,
                    "title": hit.title,
                    "score": hit.score,
                    "space_id": hit.space_id,
                    "mode": hit.mode,
                    "abstract": hit.abstract,
                    "overview": hit.overview,
                    "body": hit.body,
                    "body_level": hit.body_level,
                    "source_path": hit.source_path,
                }
                for hit in hits
            ]
        }

    async def _read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """读取一条 reference 文档详情.

        Args:
            arguments: tool arguments.

        Returns:
            文档详情摘要.
        """

        backend = self._require_backend()
        document = await backend.get_document(
            str(arguments.get("ref_id", "") or ""),
            tenant_id=self._tenant_id(arguments),
            body=str(arguments.get("body", "full") or "full"),
        )
        if document is None:
            raise RuntimeError("reference document not found")
        return {
            "ref_id": document.ref_id,
            "uri": document.uri,
            "title": document.title,
            "abstract": document.abstract,
            "overview": document.overview,
            "content": document.content,
            "source_path": document.source_path,
            "mode": document.mode,
            "space_id": document.space_id,
            "tags": list(document.tags),
        }

    # endregion

    # region helper
    def _require_backend(self) -> ReferenceBackend:
        """返回已配置的 reference backend.

        Returns:
            当前可用的 ReferenceBackend.

        Raises:
            RuntimeError: 当前未配置可用 backend.
        """

        if self._backend is None or not self._backend.enabled:
            raise RuntimeError("reference backend is not enabled")
        return self._backend

    def _tenant_id(self, arguments: dict[str, Any]) -> str:
        """解析 tenant_id."""

        return str(arguments.get("tenant_id", "") or self._default_tenant_id)

    def _space_id(self, arguments: dict[str, Any]) -> str:
        """解析 space_id."""

        return str(arguments.get("space_id", "") or self._default_space_id)

    def _mode(self, arguments: dict[str, Any]) -> ReferenceMode:
        """解析 reference mode."""

        value = str(arguments.get("mode", "") or self._default_mode)
        return cast(ReferenceMode, value)

    # endregion
