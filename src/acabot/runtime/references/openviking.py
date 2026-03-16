"""runtime.references.openviking 提供 OpenViking 兼容 reference provider."""

from __future__ import annotations

from inspect import isawaitable
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Literal

from .base import ReferenceBackend
from .helpers import (
    hash_text,
    mode_from_uri,
    normalize_title,
    sanitize_filename,
    sanitize_identifier,
    space_id_from_uri,
)
from .contracts import (
    ReferenceBodyLevel,
    ReferenceDocument,
    ReferenceDocumentInput,
    ReferenceDocumentRef,
    ReferenceHit,
    ReferenceMode,
    ReferenceProviderMode,
    ReferenceSpace,
)


class OpenVikingReferenceBackend(ReferenceBackend):
    """OpenViking 兼容的 reference provider."""

    def __init__(
        self,
        *,
        mode: ReferenceProviderMode = "embedded",
        path: str | None = None,
        base_uri: str = "viking://resources/acabot",
        service_factory: Callable[[], Any] | None = None,
        ctx_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__(enabled=True)
        self.mode = mode
        self.path = path
        self.base_uri = base_uri.rstrip("/")
        self.service_factory = service_factory
        self.ctx_factory = ctx_factory
        self._service: Any | None = None
        self._ctx_cache: dict[str, Any] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if self.service_factory is not None:
            service = self.service_factory()
        elif self.mode == "embedded":
            service = self._create_default_service()
        else:
            raise NotImplementedError(
                "OpenVikingReferenceBackend http mode requires a custom service_factory"
            )
        if isawaitable(service):
            service = await service
        self._service = service
        initializer = getattr(service, "initialize", None)
        if callable(initializer):
            result = initializer()
            if isawaitable(result):
                await result
        self._started = True

    async def close(self) -> None:
        service = self._service
        self._service = None
        self._ctx_cache.clear()
        self._started = False
        if service is None:
            return
        closer = getattr(service, "close", None)
        if callable(closer):
            result = closer()
            if isawaitable(result):
                await result

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        await self.start()
        service = self._require_service()
        ctx = self._ctx_for(tenant_id)
        space_uri = self._space_uri(tenant_id, space_id, mode)
        await self._ensure_remote_space(space_uri, ctx)
        refs: list[ReferenceDocumentRef] = []

        for document in documents:
            temp_path = self._write_temp_document(document)
            try:
                result = await service.resources.add_resource(
                    path=temp_path,
                    ctx=ctx,
                    parent=space_uri,
                    wait=False,
                    build_index=True,
                    summarize=True,
                    reason=document.metadata.get("reason", ""),
                    instruction=document.metadata.get("instruction", ""),
                )
            finally:
                Path(temp_path).unlink(missing_ok=True)

            uri = self._extract_root_uri(result, fallback_parent=space_uri, document=document)
            now = int(time.time())
            refs.append(
                ReferenceDocumentRef(
                    ref_id=uri,
                    uri=uri,
                    tenant_id=tenant_id,
                    space_id=space_id,
                    mode=mode,
                    title=normalize_title(document.title, document.source_path),
                    source_path=document.source_path,
                    metadata={
                        "provider": "openviking",
                        "result": dict(result) if isinstance(result, dict) else {},
                        **dict(document.metadata),
                    },
                    created_at=now,
                    updated_at=now,
                )
            )

        return refs

    async def search(
        self,
        query: str,
        *,
        tenant_id: str,
        space_id: str | None = None,
        mode: ReferenceMode | None = None,
        limit: int = 5,
        body: ReferenceBodyLevel = "none",
        min_score: float = 0.0,
    ) -> list[ReferenceHit]:
        await self.start()
        service = self._require_service()
        ctx = self._ctx_for(tenant_id)
        target_uri = self._target_uri(tenant_id=tenant_id, space_id=space_id, mode=mode)
        result = await service.search.find(
            query=query,
            ctx=ctx,
            target_uri=target_uri,
            limit=limit,
            score_threshold=min_score if min_score > 0 else None,
            filter=None,
        )
        hits: list[ReferenceHit] = []
        for entry in self._extract_search_entries(result):
            uri = str(entry.get("uri", "") or "")
            if not uri:
                continue
            space = space_id or space_id_from_uri(uri)
            entry_mode = str(mode or mode_from_uri(uri) or "readonly_reference")
            if space_id is not None and space_id_from_uri(uri) != space_id:
                continue
            if mode is not None and mode_from_uri(uri) != mode:
                continue
            abstract = str(entry.get("abstract", "") or "")
            overview = str(entry.get("overview", "") or "")
            body_text = ""
            if body == "overview":
                body_text = await self._safe_read(uri, ctx, level="overview")
                if not overview:
                    overview = body_text
            elif body == "full":
                body_text = await self._safe_read(uri, ctx, level="full")
                if not overview:
                    overview = await self._safe_read(uri, ctx, level="overview")
            metadata = dict(entry.get("metadata", {}))
            metadata.setdefault("provider", "openviking")
            hits.append(
                ReferenceHit(
                    ref_id=uri,
                    uri=uri,
                    tenant_id=tenant_id,
                    space_id=space,
                    mode=entry_mode,
                    title=normalize_title(
                        str(entry.get("title", "") or entry.get("name", "") or Path(uri).name),
                        str(entry.get("source_path", "") or metadata.get("source_path", "")),
                    ),
                    score=float(entry.get("score", 0.0) or 0.0),
                    abstract=abstract,
                    overview=overview,
                    body=body_text,
                    body_level=body,
                    source_path=str(entry.get("source_path", "") or metadata.get("source_path", "")),
                    tags=list(entry.get("tags", metadata.get("tags", [])) or []),
                    metadata=metadata,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        await self.start()
        ctx = self._ctx_for(tenant_id)
        uri = ref_id
        abstract = await self._safe_read(uri, ctx, level="abstract")
        overview = await self._safe_read(uri, ctx, level="overview")
        content = ""
        if body == "overview":
            content = overview
        elif body == "full":
            content = await self._safe_read(uri, ctx, level="full")
        if not any([abstract, overview, content]):
            return None
        return ReferenceDocument(
            ref_id=uri,
            uri=uri,
            tenant_id=tenant_id,
            space_id=space_id_from_uri(uri),
            mode=str(mode_from_uri(uri) or "readonly_reference"),
            title=normalize_title(Path(uri).name, ""),
            abstract=abstract,
            overview=overview,
            content=content,
            source_path="",
            content_hash=hash_text(content) if content else "",
            tags=[],
            metadata={"provider": "openviking"},
            created_at=0,
            updated_at=0,
        )

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        await self.start()
        if tenant_id is None:
            return []
        service = self._require_service()
        ctx = self._ctx_for(tenant_id)
        mode_values = [mode] if mode is not None else ["readonly_reference", "appendable_reference"]
        spaces: list[ReferenceSpace] = []
        for item_mode in mode_values:
            base_uri = self._mode_uri(tenant_id, item_mode)
            try:
                entries = await service.fs.ls(base_uri, ctx=ctx, simple=True)
            except Exception:
                continue
            for entry in entries:
                uri = str(entry)
                spaces.append(
                    ReferenceSpace(
                        tenant_id=tenant_id,
                        space_id=space_id_from_uri(uri),
                        mode=item_mode,
                        document_count=0,
                        updated_at=0,
                        metadata={
                            "provider": "openviking",
                            "uri": uri,
                        },
                    )
                )
        return spaces

    def _create_default_service(self) -> Any:
        from openviking.service import OpenVikingService

        return OpenVikingService(path=self.path)

    def _require_service(self) -> Any:
        if self._service is None:
            raise RuntimeError("OpenVikingReferenceBackend is not started")
        return self._service

    def _ctx_for(self, tenant_id: str) -> Any:
        normalized = sanitize_identifier(tenant_id)
        if normalized not in self._ctx_cache:
            if self.ctx_factory is not None:
                self._ctx_cache[normalized] = self.ctx_factory(normalized)
            else:
                from openviking.server.identity import RequestContext, Role
                from openviking_cli.session.user_id import UserIdentifier

                user = UserIdentifier(normalized, "acabot", "reference")
                self._ctx_cache[normalized] = RequestContext(user=user, role=Role.ROOT)
        return self._ctx_cache[normalized]

    def _mode_uri(self, tenant_id: str, mode: ReferenceMode) -> str:
        return f"{self.base_uri}/{sanitize_identifier(tenant_id)}/{mode}"

    def _space_uri(self, tenant_id: str, space_id: str, mode: ReferenceMode) -> str:
        return f"{self._mode_uri(tenant_id, mode)}/{sanitize_identifier(space_id)}"

    def _target_uri(
        self,
        *,
        tenant_id: str,
        space_id: str | None,
        mode: ReferenceMode | None,
    ) -> str:
        if mode is None:
            tenant = sanitize_identifier(tenant_id)
            return f"{self.base_uri}/{tenant}"
        if space_id is None:
            return self._mode_uri(tenant_id, mode)
        return self._space_uri(tenant_id, space_id, mode)

    async def _ensure_remote_space(self, space_uri: str, ctx: Any) -> None:
        service = self._require_service()
        try:
            await service.fs.mkdir(space_uri, ctx=ctx)
        except Exception:
            return None

    def _write_temp_document(self, document: ReferenceDocumentInput) -> str:
        title = normalize_title(document.title, document.source_path)
        content = document.content
        if document.abstract:
            content = f"# Abstract\n\n{document.abstract}\n\n{content}"
        if document.overview:
            content = f"# Overview\n\n{document.overview}\n\n{content}"
        suffix = Path(document.source_path).suffix or ".md"
        safe_title = sanitize_filename(title)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=suffix,
            prefix=f"{safe_title}_",
            delete=False,
        ) as handle:
            handle.write(content)
            return handle.name

    def _extract_root_uri(
        self,
        result: Any,
        *,
        fallback_parent: str,
        document: ReferenceDocumentInput,
    ) -> str:
        if isinstance(result, dict):
            root_uri = result.get("root_uri") or result.get("uri")
            if root_uri:
                return str(root_uri)
        title = sanitize_filename(normalize_title(document.title, document.source_path))
        return f"{fallback_parent}/{title}.md"

    async def _safe_read(self, uri: str, ctx: Any, *, level: Literal["abstract", "overview", "full"]) -> str:
        service = self._require_service()
        try:
            if level == "abstract":
                return str(await service.fs.abstract(uri, ctx=ctx))
            if level == "overview":
                return str(await service.fs.overview(uri, ctx=ctx))
            return str(await service.fs.read(uri, ctx=ctx))
        except Exception:
            return ""

    @staticmethod
    def _extract_search_entries(result: Any) -> list[dict[str, Any]]:
        payload = result
        to_dict = getattr(payload, "to_dict", None)
        if callable(to_dict):
            payload = to_dict()
        if isinstance(payload, dict) and isinstance(payload.get("result"), (dict, list)):
            payload = payload["result"]
        if isinstance(payload, dict):
            for key in ("resources", "items", "data", "hits"):
                entries = payload.get(key)
                if isinstance(entries, list):
                    return [OpenVikingReferenceBackend._normalize_entry(entry) for entry in entries]
        if isinstance(payload, list):
            return [OpenVikingReferenceBackend._normalize_entry(entry) for entry in payload]
        return []

    @staticmethod
    def _normalize_entry(entry: Any) -> dict[str, Any]:
        if isinstance(entry, dict):
            metadata = dict(entry.get("meta") or entry.get("metadata") or {})
            return {
                "uri": entry.get("uri", ""),
                "title": entry.get("title") or entry.get("name") or "",
                "score": entry.get("score", 0.0),
                "abstract": entry.get("abstract", ""),
                "overview": entry.get("overview", ""),
                "source_path": entry.get("source_path", metadata.get("source_path", "")),
                "tags": entry.get("tags", metadata.get("tags", [])),
                "metadata": metadata,
            }
        return {}


__all__ = ["OpenVikingReferenceBackend"]
