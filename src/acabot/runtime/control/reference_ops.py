"""RuntimeControlPlane 的 reference 管理子模块."""

from __future__ import annotations

from ..references import (
    ReferenceBackend,
    ReferenceBodyLevel,
    ReferenceDocument,
    ReferenceDocumentInput,
    ReferenceDocumentRef,
    ReferenceHit,
    ReferenceMode,
    ReferenceSpace,
)


class RuntimeReferenceControlOps:
    """封装 RuntimeControlPlane 的 reference 相关能力."""

    def __init__(self, *, reference_backend: ReferenceBackend | None) -> None:
        self.reference_backend = reference_backend

    async def list_reference_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        if self.reference_backend is None:
            return []
        return await self.reference_backend.list_spaces(tenant_id=tenant_id, mode=mode)

    async def search_reference(
        self,
        *,
        query: str,
        tenant_id: str,
        space_id: str | None = None,
        mode: ReferenceMode | None = None,
        limit: int = 10,
        body: ReferenceBodyLevel = "none",
        min_score: float = 0.0,
    ) -> list[ReferenceHit]:
        if self.reference_backend is None:
            return []
        return await self.reference_backend.search(
            query,
            tenant_id=tenant_id,
            space_id=space_id,
            mode=mode,
            limit=limit,
            body=body,
            min_score=min_score,
        )

    async def get_reference_document(
        self,
        *,
        ref_id: str,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        if self.reference_backend is None:
            return None
        return await self.reference_backend.get_document(ref_id, tenant_id=tenant_id, body=body)

    async def add_reference_documents(
        self,
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
        documents: list[ReferenceDocumentInput],
    ) -> list[ReferenceDocumentRef]:
        if self.reference_backend is None:
            return []
        return await self.reference_backend.add_documents(
            documents,
            tenant_id=tenant_id,
            space_id=space_id,
            mode=mode,
        )
