"""runtime.references.local 提供轻量本地 SQLite reference provider."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import time
from typing import Any

from .base import ReferenceBackend
from .helpers import (
    body_for_level,
    build_abstract,
    build_overview,
    compute_local_score,
    decode_json,
    encode_json,
    hash_text,
    normalize_title,
)
from .contracts import (
    ReferenceBodyLevel,
    ReferenceDocument,
    ReferenceDocumentInput,
    ReferenceDocumentRef,
    ReferenceHit,
    ReferenceMode,
    ReferenceSpace,
)


class LocalReferenceBackend(ReferenceBackend):
    """轻量本地 ReferenceBackend."""

    def __init__(self, db_path: str | Path) -> None:
        super().__init__(enabled=True)
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    async def start(self) -> None:
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    async def close(self) -> None:
        if self._conn is None:
            return
        self._conn.close()
        self._conn = None

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        await self.start()
        now = int(time.time())
        refs: list[ReferenceDocumentRef] = []
        conn = self._require_conn()

        async with self._lock:
            for document in documents:
                title = normalize_title(document.title, document.source_path)
                content = document.content.strip()
                overview = document.overview.strip() or build_overview(content)
                abstract = document.abstract.strip() or build_abstract(overview or content)
                content_hash = hash_text(content)
                ref_seed = f"{tenant_id}\0{space_id}\0{mode}\0{title}\0{content_hash}"
                ref_id = hash_text(ref_seed)[:16]
                uri = f"localref://{tenant_id}/{mode}/{space_id}/{ref_id}"
                metadata = dict(document.metadata)
                metadata.setdefault("provider", "local")
                row = (
                    ref_id,
                    uri,
                    tenant_id,
                    space_id,
                    mode,
                    title,
                    document.source_path,
                    abstract,
                    overview,
                    content,
                    content_hash,
                    encode_json(document.tags),
                    encode_json(metadata),
                    now,
                    now,
                )
                conn.execute(
                    """
                    INSERT INTO reference_documents (
                        ref_id,
                        uri,
                        tenant_id,
                        space_id,
                        mode,
                        title,
                        source_path,
                        abstract,
                        overview,
                        content,
                        content_hash,
                        tags_json,
                        metadata_json,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ref_id) DO UPDATE SET
                        uri = excluded.uri,
                        tenant_id = excluded.tenant_id,
                        space_id = excluded.space_id,
                        mode = excluded.mode,
                        title = excluded.title,
                        source_path = excluded.source_path,
                        abstract = excluded.abstract,
                        overview = excluded.overview,
                        content = excluded.content,
                        content_hash = excluded.content_hash,
                        tags_json = excluded.tags_json,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    row,
                )
                refs.append(
                    ReferenceDocumentRef(
                        ref_id=ref_id,
                        uri=uri,
                        tenant_id=tenant_id,
                        space_id=space_id,
                        mode=mode,
                        title=title,
                        source_path=document.source_path,
                        metadata=metadata,
                        created_at=now,
                        updated_at=now,
                    )
                )
            conn.commit()

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
        normalized_query = query.strip().lower()
        conn = self._require_conn()
        sql = [
            """
            SELECT
                ref_id,
                uri,
                tenant_id,
                space_id,
                mode,
                title,
                source_path,
                abstract,
                overview,
                content,
                tags_json,
                metadata_json,
                created_at,
                updated_at
            FROM reference_documents
            WHERE tenant_id = ?
            """
        ]
        params: list[Any] = [tenant_id]
        if space_id is not None:
            sql.append("AND space_id = ?")
            params.append(space_id)
        if mode is not None:
            sql.append("AND mode = ?")
            params.append(mode)

        async with self._lock:
            rows = conn.execute("\n".join(sql), params).fetchall()

        scored_rows: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            score = compute_local_score(normalized_query, row)
            effective_min_score = min_score
            if normalized_query and effective_min_score <= 0:
                effective_min_score = 0.0001
            if score < effective_min_score:
                continue
            scored_rows.append((score, row))

        scored_rows.sort(
            key=lambda item: (
                item[0],
                int(item[1]["updated_at"]),
                int(item[1]["created_at"]),
                str(item[1]["ref_id"]),
            ),
            reverse=True,
        )
        hits: list[ReferenceHit] = []
        for score, row in scored_rows[:limit]:
            hits.append(
                ReferenceHit(
                    ref_id=str(row["ref_id"]),
                    uri=str(row["uri"]),
                    tenant_id=str(row["tenant_id"]),
                    space_id=str(row["space_id"]),
                    mode=str(row["mode"]),
                    title=str(row["title"]),
                    score=score,
                    abstract=str(row["abstract"]),
                    overview=str(row["overview"]),
                    body=body_for_level(row=row, level=body),
                    body_level=body,
                    source_path=str(row["source_path"]),
                    tags=list(decode_json(row["tags_json"])),
                    metadata=dict(decode_json(row["metadata_json"])),
                )
            )
        return hits

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        await self.start()
        conn = self._require_conn()
        async with self._lock:
            row = conn.execute(
                """
                SELECT
                    ref_id,
                    uri,
                    tenant_id,
                    space_id,
                    mode,
                    title,
                    source_path,
                    abstract,
                    overview,
                    content,
                    content_hash,
                    tags_json,
                    metadata_json,
                    created_at,
                    updated_at
                FROM reference_documents
                WHERE tenant_id = ?
                  AND (ref_id = ? OR uri = ?)
                """,
                (tenant_id, ref_id, ref_id),
            ).fetchone()

        if row is None:
            return None

        content = ""
        if body == "full":
            content = str(row["content"])
        elif body == "overview":
            content = str(row["overview"])

        return ReferenceDocument(
            ref_id=str(row["ref_id"]),
            uri=str(row["uri"]),
            tenant_id=str(row["tenant_id"]),
            space_id=str(row["space_id"]),
            mode=str(row["mode"]),
            title=str(row["title"]),
            abstract=str(row["abstract"]),
            overview=str(row["overview"]),
            content=content,
            source_path=str(row["source_path"]),
            content_hash=str(row["content_hash"]),
            tags=list(decode_json(row["tags_json"])),
            metadata=dict(decode_json(row["metadata_json"])),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        await self.start()
        conn = self._require_conn()
        sql = [
            """
            SELECT
                tenant_id,
                space_id,
                mode,
                COUNT(*) AS document_count,
                MAX(updated_at) AS updated_at
            FROM reference_documents
            WHERE 1 = 1
            """
        ]
        params: list[Any] = []
        if tenant_id is not None:
            sql.append("AND tenant_id = ?")
            params.append(tenant_id)
        if mode is not None:
            sql.append("AND mode = ?")
            params.append(mode)
        sql.append("GROUP BY tenant_id, space_id, mode ORDER BY tenant_id, mode, space_id")

        async with self._lock:
            rows = conn.execute("\n".join(sql), params).fetchall()

        return [
            ReferenceSpace(
                tenant_id=str(row["tenant_id"]),
                space_id=str(row["space_id"]),
                mode=str(row["mode"]),
                document_count=int(row["document_count"]),
                updated_at=int(row["updated_at"] or 0),
                metadata={"provider": "local"},
            )
            for row in rows
        ]

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("LocalReferenceBackend is not started")
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._require_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reference_documents (
                ref_id TEXT PRIMARY KEY,
                uri TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                title TEXT NOT NULL,
                source_path TEXT NOT NULL,
                abstract TEXT NOT NULL,
                overview TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reference_documents_scope
            ON reference_documents (tenant_id, space_id, mode, updated_at)
            """
        )
        conn.commit()


__all__ = ["LocalReferenceBackend"]
