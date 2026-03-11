r"""runtime.reference_backend 定义 reference provider contract.

组件关系:

    future reference skill / Control Plane
                    |
                    v
             ReferenceBackend
                /        \
               v          v
    LocalReferenceBackend  OpenVikingReferenceBackend

这一层负责 `reference / notebook` 类型的高精度资料检索.
它和其他 memory layer 的边界如下:
- `working memory` 作为上下文, 由 runtime 内部维护.
- `sticky notes` 是本地结构化 memory.
- `semantic / relationship / episodic` 走 `MemoryBroker`.
- `reference / notebook` 走这里的 provider-style backend.

默认约束:
- `reference` 是 on-demand lookup, 不默认每轮自动注入 prompt.
- 结果要保留 provenance.
- provider 可以 `enabled / disabled`.
- provider 需要独立 lifecycle, 但允许 lazy init.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
from inspect import isawaitable
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from typing import Any, Callable, Literal

ReferenceMode = Literal["readonly_reference", "appendable_reference"]
ReferenceBodyLevel = Literal["none", "overview", "full"]
ReferenceProviderMode = Literal["embedded", "http"]


# region 数据模型
@dataclass(slots=True)
class ReferenceDocumentInput:
    """待写入 ReferenceBackend 的文档输入.

    Attributes:
        title (str): 文档标题.
        content (str): 文档正文.
        abstract (str): 可选 L0 摘要.
        overview (str): 可选 L1 总览.
        source_path (str): 原始来源路径或标识.
        tags (list[str]): 文档标签.
        metadata (dict[str, Any]): 附加元数据.
    """

    title: str
    content: str
    abstract: str = ""
    overview: str = ""
    source_path: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReferenceDocumentRef:
    """Reference 文档的轻量引用.

    Attributes:
        ref_id (str): 文档稳定引用 ID.
        uri (str): provider 原生 URI.
        tenant_id (str): 当前 tenant 标识.
        space_id (str): 当前 reference space.
        mode (ReferenceMode): 文档所在 reference mode.
        title (str): 文档标题.
        source_path (str): 原始来源路径或标识.
        metadata (dict[str, Any]): 附加元数据.
        created_at (int): 创建时间戳.
        updated_at (int): 更新时间戳.
    """

    ref_id: str
    uri: str
    tenant_id: str
    space_id: str
    mode: ReferenceMode
    title: str = ""
    source_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class ReferenceHit:
    """Reference 检索命中结果.

    Attributes:
        ref_id (str): 命中文档引用 ID.
        uri (str): provider 原生 URI.
        tenant_id (str): 当前 tenant 标识.
        space_id (str): 当前 reference space.
        mode (ReferenceMode): 当前 reference mode.
        title (str): 文档标题.
        score (float): 当前命中的相关性分数.
        abstract (str): L0 摘要.
        overview (str): L1 总览.
        body (str): 按 body_level 返回的正文内容.
        body_level (ReferenceBodyLevel): 当前 body 的解析层级.
        source_path (str): 原始来源路径或标识.
        tags (list[str]): 文档标签.
        metadata (dict[str, Any]): 附加元数据.
    """

    ref_id: str
    uri: str
    tenant_id: str
    space_id: str
    mode: ReferenceMode
    title: str
    score: float
    abstract: str = ""
    overview: str = ""
    body: str = ""
    body_level: ReferenceBodyLevel = "none"
    source_path: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReferenceDocument:
    """Reference 文档详情.

    Attributes:
        ref_id (str): 文档稳定引用 ID.
        uri (str): provider 原生 URI.
        tenant_id (str): 当前 tenant 标识.
        space_id (str): 当前 reference space.
        mode (ReferenceMode): 当前 reference mode.
        title (str): 文档标题.
        abstract (str): L0 摘要.
        overview (str): L1 总览.
        content (str): 完整正文.
        source_path (str): 原始来源路径或标识.
        content_hash (str): 正文内容 hash.
        tags (list[str]): 文档标签.
        metadata (dict[str, Any]): 附加元数据.
        created_at (int): 创建时间戳.
        updated_at (int): 更新时间戳.
    """

    ref_id: str
    uri: str
    tenant_id: str
    space_id: str
    mode: ReferenceMode
    title: str
    abstract: str = ""
    overview: str = ""
    content: str = ""
    source_path: str = ""
    content_hash: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    updated_at: int = 0


@dataclass(slots=True)
class ReferenceSpace:
    """Reference space 元信息.

    Attributes:
        tenant_id (str): 当前 tenant 标识.
        space_id (str): 当前 reference space.
        mode (ReferenceMode): 当前 reference mode.
        document_count (int): 当前 space 中文档数量.
        updated_at (int): 当前 space 最近更新时间.
        metadata (dict[str, Any]): 附加元数据.
    """

    tenant_id: str
    space_id: str
    mode: ReferenceMode
    document_count: int
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# endregion


# region provider接口
class ReferenceBackend:
    """Reference provider 抽象基类.

    Attributes:
        enabled (bool): 当前 provider 是否启用.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        """初始化 ReferenceBackend.

        Args:
            enabled: 当前 provider 是否启用.
        """

        self.enabled = enabled

    async def start(self) -> None:
        """启动 provider.

        Returns:
            无返回值.
        """

        return None

    async def close(self) -> None:
        """关闭 provider.

        Returns:
            无返回值.
        """

        return None

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        """写入一批 reference 文档.

        Args:
            documents: 待写入的文档输入列表.
            tenant_id: 当前 tenant 标识.
            space_id: 目标 reference space.
            mode: 目标 reference mode.

        Returns:
            写入后的文档引用列表.
        """

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
        """检索 reference 文档.

        Args:
            query: 检索词.
            tenant_id: 当前 tenant 标识.
            space_id: 可选 space 过滤.
            mode: 可选 mode 过滤.
            limit: 最多返回多少条命中.
            body: 是否返回额外正文层级.
            min_score: 最小分数阈值.

        Returns:
            命中结果列表.
        """

        raise NotImplementedError

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        """读取一条 reference 文档详情.

        Args:
            ref_id: 文档引用 ID. provider 可接受自己的原生 URI.
            tenant_id: 当前 tenant 标识.
            body: 需要返回的正文层级.

        Returns:
            命中的 ReferenceDocument. 未命中时返回 None.
        """

        raise NotImplementedError

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        """列出 reference spaces.

        Args:
            tenant_id: 可选 tenant 过滤.
            mode: 可选 mode 过滤.

        Returns:
            ReferenceSpace 列表.
        """

        raise NotImplementedError


class NullReferenceBackend(ReferenceBackend):
    """默认空 provider.

    这个实现用于:
    - `reference` 功能未启用.
    - runtime 默认不承担重型 provider 成本.
    """

    def __init__(self) -> None:
        """初始化 NullReferenceBackend."""

        super().__init__(enabled=False)

    async def add_documents(
        self,
        documents: list[ReferenceDocumentInput],
        *,
        tenant_id: str,
        space_id: str,
        mode: ReferenceMode,
    ) -> list[ReferenceDocumentRef]:
        """忽略写入请求.

        Args:
            documents: 待写入的文档输入列表.
            tenant_id: 当前 tenant 标识.
            space_id: 目标 reference space.
            mode: 目标 reference mode.

        Returns:
            空列表.
        """

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
        """返回空命中.

        Args:
            query: 检索词.
            tenant_id: 当前 tenant 标识.
            space_id: 可选 space 过滤.
            mode: 可选 mode 过滤.
            limit: 最多返回多少条命中.
            body: 是否返回额外正文层级.
            min_score: 最小分数阈值.

        Returns:
            空列表.
        """

        _ = (query, tenant_id, space_id, mode, limit, body, min_score)
        return []

    async def get_document(
        self,
        ref_id: str,
        *,
        tenant_id: str,
        body: ReferenceBodyLevel = "full",
    ) -> ReferenceDocument | None:
        """忽略文档读取请求.

        Args:
            ref_id: 文档引用 ID.
            tenant_id: 当前 tenant 标识.
            body: 需要返回的正文层级.

        Returns:
            恒为 None.
        """

        _ = (ref_id, tenant_id, body)
        return None

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        """返回空 space 列表.

        Args:
            tenant_id: 可选 tenant 过滤.
            mode: 可选 mode 过滤.

        Returns:
            空列表.
        """

        _ = (tenant_id, mode)
        return []


# endregion


# region 本地provider
class LocalReferenceBackend(ReferenceBackend):
    """轻量本地 ReferenceBackend.

    Attributes:
        db_path (Path): SQLite 数据库路径.
        _lock (asyncio.Lock): SQLite 并发锁.
        _conn (sqlite3.Connection | None): SQLite 连接.
    """

    def __init__(self, db_path: str | Path) -> None:
        """初始化 LocalReferenceBackend.

        Args:
            db_path: SQLite 数据库路径.
        """

        super().__init__(enabled=True)
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    async def start(self) -> None:
        """初始化本地 SQLite catalog.

        Returns:
            无返回值.
        """

        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._ensure_schema()

    async def close(self) -> None:
        """关闭 SQLite 连接.

        Returns:
            无返回值.
        """

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
        """写入一批本地 reference 文档.

        Args:
            documents: 待写入的文档输入列表.
            tenant_id: 当前 tenant 标识.
            space_id: 目标 reference space.
            mode: 目标 reference mode.

        Returns:
            写入后的文档引用列表.
        """

        await self.start()
        now = int(time.time())
        refs: list[ReferenceDocumentRef] = []
        conn = self._require_conn()

        async with self._lock:
            for document in documents:
                title = _normalize_title(document.title, document.source_path)
                content = document.content.strip()
                overview = document.overview.strip() or _build_overview(content)
                abstract = document.abstract.strip() or _build_abstract(overview or content)
                content_hash = _hash_text(content)
                ref_seed = f"{tenant_id}\0{space_id}\0{mode}\0{title}\0{content_hash}"
                ref_id = _hash_text(ref_seed)[:16]
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
                    _encode_json(document.tags),
                    _encode_json(metadata),
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
        """检索本地 reference 文档.

        Args:
            query: 检索词.
            tenant_id: 当前 tenant 标识.
            space_id: 可选 space 过滤.
            mode: 可选 mode 过滤.
            limit: 最多返回多少条命中.
            body: 是否返回额外正文层级.
            min_score: 最小分数阈值.

        Returns:
            命中结果列表.
        """

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
            score = _compute_local_score(normalized_query, row)
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
                    body=_body_for_level(row=row, level=body),
                    body_level=body,
                    source_path=str(row["source_path"]),
                    tags=list(_decode_json(row["tags_json"])),
                    metadata=dict(_decode_json(row["metadata_json"])),
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
        """读取一条本地 reference 文档.

        Args:
            ref_id: 文档引用 ID 或 URI.
            tenant_id: 当前 tenant 标识.
            body: 需要返回的正文层级.

        Returns:
            命中的 ReferenceDocument. 未命中时返回 None.
        """

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
            tags=list(_decode_json(row["tags_json"])),
            metadata=dict(_decode_json(row["metadata_json"])),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    async def list_spaces(
        self,
        *,
        tenant_id: str | None = None,
        mode: ReferenceMode | None = None,
    ) -> list[ReferenceSpace]:
        """列出本地 reference spaces.

        Args:
            tenant_id: 可选 tenant 过滤.
            mode: 可选 mode 过滤.

        Returns:
            ReferenceSpace 列表.
        """

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

    # region 内部辅助
    def _require_conn(self) -> sqlite3.Connection:
        """返回已经初始化的 SQLite 连接.

        Returns:
            当前 SQLite 连接.

        Raises:
            RuntimeError: provider 尚未启动.
        """

        if self._conn is None:
            raise RuntimeError("LocalReferenceBackend is not started")
        return self._conn

    def _ensure_schema(self) -> None:
        """初始化本地 reference_documents 表.

        Returns:
            无返回值.
        """

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

    # endregion


# endregion


# region openviking provider
class OpenVikingReferenceBackend(ReferenceBackend):
    """OpenViking 兼容的 reference provider.

    Attributes:
        mode (ReferenceProviderMode): provider 模式. 当前主要实现 `embedded`.
        path (str | None): OpenViking embedded mode 的本地路径.
        base_uri (str): reference 根 URI.
        service_factory (Callable[[], Any] | None): 可选 service factory.
        ctx_factory (Callable[[str], Any] | None): 可选 ctx factory.
        _service (Any | None): 当前绑定的 service 实例.
        _ctx_cache (dict[str, Any]): 按 tenant 缓存的 RequestContext.
        _started (bool): provider 是否已经初始化.
    """

    def __init__(
        self,
        *,
        mode: ReferenceProviderMode = "embedded",
        path: str | None = None,
        base_uri: str = "viking://resources/acabot",
        service_factory: Callable[[], Any] | None = None,
        ctx_factory: Callable[[str], Any] | None = None,
    ) -> None:
        """初始化 OpenVikingReferenceBackend.

        Args:
            mode: provider 模式.
            path: OpenViking embedded mode 的本地路径.
            base_uri: reference 根 URI.
            service_factory: 可选 service factory. 主要用于测试或外部注入.
            ctx_factory: 可选 ctx factory. 主要用于测试或外部注入.
        """

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
        """按需初始化 OpenViking service.

        Returns:
            无返回值.

        Raises:
            NotImplementedError: `http` 模式尚未提供默认 client.
        """

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
        """关闭 OpenViking service.

        Returns:
            无返回值.
        """

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
        """把一批文档写入 OpenViking resources.

        Args:
            documents: 待写入的文档输入列表.
            tenant_id: 当前 tenant 标识.
            space_id: 目标 reference space.
            mode: 目标 reference mode.

        Returns:
            写入后的文档引用列表.
        """

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
                    title=_normalize_title(document.title, document.source_path),
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
        """检索 OpenViking reference.

        Args:
            query: 检索词.
            tenant_id: 当前 tenant 标识.
            space_id: 可选 space 过滤.
            mode: 可选 mode 过滤.
            limit: 最多返回多少条命中.
            body: 是否返回额外正文层级.
            min_score: 最小分数阈值.

        Returns:
            命中结果列表.
        """

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
            space = space_id or _space_id_from_uri(uri)
            entry_mode = str(mode or _mode_from_uri(uri) or "readonly_reference")
            if space_id is not None and _space_id_from_uri(uri) != space_id:
                continue
            if mode is not None and _mode_from_uri(uri) != mode:
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
                    title=_normalize_title(
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
        """读取一条 OpenViking reference 文档.

        Args:
            ref_id: 文档引用 ID. 对 OpenViking 来说通常等于 URI.
            tenant_id: 当前 tenant 标识.
            body: 需要返回的正文层级.

        Returns:
            命中的 ReferenceDocument. provider 无法读取时返回 None.
        """

        await self.start()
        service = self._require_service()
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
            space_id=_space_id_from_uri(uri),
            mode=str(_mode_from_uri(uri) or "readonly_reference"),
            title=_normalize_title(Path(uri).name, ""),
            abstract=abstract,
            overview=overview,
            content=content,
            source_path="",
            content_hash=_hash_text(content) if content else "",
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
        """列出 OpenViking reference spaces.

        Args:
            tenant_id: 可选 tenant 过滤.
            mode: 可选 mode 过滤.

        Returns:
            ReferenceSpace 列表.
        """

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
                        space_id=_space_id_from_uri(uri),
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

    # region 内部辅助
    def _create_default_service(self) -> Any:
        """创建默认 embedded OpenVikingService.

        Returns:
            一个 OpenVikingService 实例.
        """

        from openviking.service import OpenVikingService

        return OpenVikingService(path=self.path)

    def _require_service(self) -> Any:
        """返回已经初始化的 service.

        Returns:
            当前 service 实例.

        Raises:
            RuntimeError: provider 尚未启动.
        """

        if self._service is None:
            raise RuntimeError("OpenVikingReferenceBackend is not started")
        return self._service

    def _ctx_for(self, tenant_id: str) -> Any:
        """返回指定 tenant 的 RequestContext.

        Args:
            tenant_id: 当前 tenant 标识.

        Returns:
            一个 provider 原生 RequestContext.
        """

        normalized = _sanitize_identifier(tenant_id)
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
        """构造 mode 根 URI.

        Args:
            tenant_id: 当前 tenant 标识.
            mode: 当前 reference mode.

        Returns:
            对应的 mode 根 URI.
        """

        return f"{self.base_uri}/{_sanitize_identifier(tenant_id)}/{mode}"

    def _space_uri(self, tenant_id: str, space_id: str, mode: ReferenceMode) -> str:
        """构造 space URI.

        Args:
            tenant_id: 当前 tenant 标识.
            space_id: 当前 space 标识.
            mode: 当前 reference mode.

        Returns:
            对应的 space URI.
        """

        return f"{self._mode_uri(tenant_id, mode)}/{_sanitize_identifier(space_id)}"

    def _target_uri(
        self,
        *,
        tenant_id: str,
        space_id: str | None,
        mode: ReferenceMode | None,
    ) -> str:
        """构造检索使用的 target_uri.

        Args:
            tenant_id: 当前 tenant 标识.
            space_id: 可选 space 标识.
            mode: 可选 reference mode.

        Returns:
            对应的 target_uri.
        """

        if mode is None:
            tenant = _sanitize_identifier(tenant_id)
            return f"{self.base_uri}/{tenant}"
        actual_mode = mode
        if space_id is None:
            return self._mode_uri(tenant_id, actual_mode)
        return self._space_uri(tenant_id, space_id, actual_mode)

    async def _ensure_remote_space(self, space_uri: str, ctx: Any) -> None:
        """确保远端 space 目录存在.

        Args:
            space_uri: 目标 space URI.
            ctx: provider 原生 RequestContext.

        Returns:
            无返回值.
        """

        service = self._require_service()
        try:
            await service.fs.mkdir(space_uri, ctx=ctx)
        except Exception:
            return None

    def _write_temp_document(self, document: ReferenceDocumentInput) -> str:
        """把 ReferenceDocumentInput 落成临时文件.

        Args:
            document: 待写入的文档输入.

        Returns:
            临时文件路径.
        """

        title = _normalize_title(document.title, document.source_path)
        content = document.content
        if document.abstract:
            content = f"# Abstract\n\n{document.abstract}\n\n{content}"
        if document.overview:
            content = f"# Overview\n\n{document.overview}\n\n{content}"
        suffix = Path(document.source_path).suffix or ".md"
        safe_title = _sanitize_filename(title)
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
        """从 provider 返回值中提取 root URI.

        Args:
            result: provider 返回值.
            fallback_parent: 回退目录 URI.
            document: 当前文档输入.

        Returns:
            一条 provider 原生 URI.
        """

        if isinstance(result, dict):
            root_uri = result.get("root_uri") or result.get("uri")
            if root_uri:
                return str(root_uri)
        title = _sanitize_filename(_normalize_title(document.title, document.source_path))
        return f"{fallback_parent}/{title}.md"

    async def _safe_read(self, uri: str, ctx: Any, *, level: Literal["abstract", "overview", "full"]) -> str:
        """安全读取一段 OpenViking 内容.

        Args:
            uri: 目标 URI.
            ctx: provider 原生 RequestContext.
            level: 目标读取层级.

        Returns:
            读取到的文本. 失败时返回空字符串.
        """

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
        """把 provider 搜索结果规整成条目列表.

        Args:
            result: provider 返回值.

        Returns:
            统一后的条目字典列表.
        """

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
        """规整 provider 搜索条目结构.

        Args:
            entry: 原始 provider 条目.

        Returns:
            一个统一的 dict 结构.
        """

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

    # endregion


# endregion


# region 通用辅助
def _encode_json(value: Any) -> str:
    """把 Python 对象编码成 JSON 字符串.

    Args:
        value: 待编码的 Python 对象.

    Returns:
        对应的 JSON 文本.
    """

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode_json(raw: str | None) -> Any:
    """把 JSON 字符串解码成 Python 对象.

    Args:
        raw: 原始 JSON 文本.

    Returns:
        解码后的 Python 对象.
    """

    if not raw:
        return {}
    return json.loads(raw)


def _hash_text(value: str) -> str:
    """计算文本内容 hash.

    Args:
        value: 原始文本.

    Returns:
        对应的 sha256 十六进制字符串.
    """

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truncate_text(value: str, *, limit: int) -> str:
    """按字符数截断文本.

    Args:
        value: 原始文本.
        limit: 最大字符数.

    Returns:
        截断后的文本.
    """

    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _build_abstract(content: str) -> str:
    """从正文生成 L0 摘要.

    Args:
        content: 原始正文.

    Returns:
        截断后的简短摘要.
    """

    return _truncate_text(content, limit=120)


def _build_overview(content: str) -> str:
    """从正文生成 L1 总览.

    Args:
        content: 原始正文.

    Returns:
        截断后的总览文本.
    """

    return _truncate_text(content, limit=400)


def _normalize_title(title: str, source_path: str) -> str:
    """规范化文档标题.

    Args:
        title: 原始标题.
        source_path: 原始来源路径.

    Returns:
        可用于展示的标题.
    """

    if title.strip():
        return title.strip()
    if source_path.strip():
        return Path(source_path).name or source_path.strip()
    return "untitled-reference"


def _sanitize_identifier(value: str) -> str:
    """把任意字符串转成 provider 可接受的 identifier.

    Args:
        value: 原始字符串.

    Returns:
        只包含 `[a-zA-Z0-9_-]` 的 identifier.
    """

    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return cleaned or "default"


def _sanitize_filename(value: str) -> str:
    """把任意标题转成文件名片段.

    Args:
        value: 原始标题.

    Returns:
        相对安全的文件名片段.
    """

    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "reference"


def _space_id_from_uri(uri: str) -> str:
    """从 provider URI 反推 space_id.

    Args:
        uri: provider 原生 URI.

    Returns:
        推断出的 space_id.
    """

    parts = [part for part in uri.rstrip("/").split("/") if part]
    if not parts:
        return ""
    last = parts[-1]
    if last not in {"readonly_reference", "appendable_reference"} and "." not in last:
        return last
    if len(parts) >= 2:
        return parts[-2]
    return ""


def _mode_from_uri(uri: str) -> str | None:
    """从 provider URI 反推 reference mode.

    Args:
        uri: provider 原生 URI.

    Returns:
        推断出的 reference mode. 推断失败时返回 None.
    """

    parts = [part for part in uri.rstrip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part in {"readonly_reference", "appendable_reference"}:
            return part
        if part == "acabot" and index + 2 < len(parts):
            candidate = parts[index + 2]
            if candidate in {"readonly_reference", "appendable_reference"}:
                return candidate
    return None


def _body_for_level(*, row: sqlite3.Row, level: ReferenceBodyLevel) -> str:
    """按层级从 SQLite row 中提取正文.

    Args:
        row: SQLite 查询结果.
        level: 目标正文层级.

    Returns:
        对应层级的文本内容.
    """

    if level == "overview":
        return str(row["overview"])
    if level == "full":
        return str(row["content"])
    return ""


def _compute_local_score(query: str, row: sqlite3.Row) -> float:
    """计算本地 reference 命中的简单相关性分数.

    Args:
        query: 归一化后的检索词.
        row: SQLite 查询结果.

    Returns:
        一个简单相关性分数.
    """

    if not query:
        return 1.0
    weighted_fields = [
        (str(row["title"]).lower(), 4.0),
        (str(row["abstract"]).lower(), 3.0),
        (str(row["overview"]).lower(), 2.0),
        (str(row["content"]).lower(), 1.0),
    ]
    score = 0.0
    for text, weight in weighted_fields:
        score += float(text.count(query)) * weight
    if score > 0:
        return score

    tokens = [token for token in re.split(r"\s+", query) if token]
    if not tokens:
        return 0.0
    for text, weight in weighted_fields:
        overlap = sum(1 for token in tokens if token in text)
        if overlap:
            score += (overlap / len(tokens)) * weight
    return score


# endregion
