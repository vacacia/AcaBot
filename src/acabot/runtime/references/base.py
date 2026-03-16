"""runtime.references.base 定义 reference provider 基类和空实现."""

from __future__ import annotations

from .contracts import (
    ReferenceBodyLevel,
    ReferenceDocument,
    ReferenceDocumentInput,
    ReferenceDocumentRef,
    ReferenceHit,
    ReferenceMode,
    ReferenceSpace,
)


class ReferenceBackend:
    """Reference provider 抽象基类."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        raise NotImplementedError

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
        raise NotImplementedError

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        raise NotImplementedError

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        raise NotImplementedError


class NullReferenceBackend(ReferenceBackend):
    """默认空 provider."""

    def __init__(self) -> None:
        super().__init__(enabled=False)

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        _ = (documents, tenant_id, space_id, mode)
        return []

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
        _ = (query, tenant_id, space_id, mode, limit, body, min_score)
        return []

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        _ = (ref_id, tenant_id, body)
        return None

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        _ = (tenant_id, mode)
        return []


__all__ = ["NullReferenceBackend", "ReferenceBackend"]
