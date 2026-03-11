"""reference backend 测试.

这一组测试覆盖两类 provider:

- `LocalReferenceBackend`, 作为轻量默认实现.
- `OpenVikingReferenceBackend`, 作为 provider seam 和 lazy lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from acabot.runtime import (
    LocalReferenceBackend,
    OpenVikingReferenceBackend,
    ReferenceDocumentInput,
)


# region local backend
async def test_local_reference_backend_add_search_get_and_list_spaces(tmp_path: Path) -> None:
    backend = LocalReferenceBackend(tmp_path / "reference.sqlite3")

    refs = await backend.add_documents(
        [
            ReferenceDocumentInput(
                title="Aca Bio",
                content="Acacia was born in 2000.\nShe likes building bots.",
                source_path="bio.md",
                tags=["bio"],
                metadata={"created_by": "user"},
            )
        ],
        tenant_id="tenant-1",
        space_id="people",
        mode="readonly_reference",
    )
    hits = await backend.search(
        "born in 2000",
        tenant_id="tenant-1",
        space_id="people",
        mode="readonly_reference",
        body="overview",
    )
    document = await backend.get_document(
        refs[0].ref_id,
        tenant_id="tenant-1",
        body="full",
    )
    spaces = await backend.list_spaces(tenant_id="tenant-1")

    assert len(refs) == 1
    assert refs[0].uri.startswith("localref://tenant-1/readonly_reference/people/")
    assert len(hits) == 1
    assert hits[0].title == "Aca Bio"
    assert hits[0].body_level == "overview"
    assert "Acacia was born in 2000" in hits[0].body
    assert document is not None
    assert document.content == "Acacia was born in 2000.\nShe likes building bots."
    assert document.metadata["created_by"] == "user"
    assert spaces[0].space_id == "people"
    assert spaces[0].document_count == 1

    await backend.close()


async def test_local_reference_backend_filters_by_space_and_mode(tmp_path: Path) -> None:
    backend = LocalReferenceBackend(tmp_path / "reference.sqlite3")

    await backend.add_documents(
        [
            ReferenceDocumentInput(
                title="User Manual",
                content="Manual for group usage.",
            )
        ],
        tenant_id="tenant-1",
        space_id="manuals",
        mode="readonly_reference",
    )
    await backend.add_documents(
        [
            ReferenceDocumentInput(
                title="Draft Note",
                content="Work in progress note.",
            )
        ],
        tenant_id="tenant-1",
        space_id="manuals",
        mode="appendable_reference",
    )

    readonly_hits = await backend.search(
        "manual",
        tenant_id="tenant-1",
        space_id="manuals",
        mode="readonly_reference",
    )
    draft_hits = await backend.search(
        "manual",
        tenant_id="tenant-1",
        space_id="manuals",
        mode="appendable_reference",
    )

    assert len(readonly_hits) == 1
    assert readonly_hits[0].mode == "readonly_reference"
    assert draft_hits == []

    await backend.close()


# endregion


# region openviking seam
class FakeOpenVikingResources:
    """OpenViking resources fake.

    Attributes:
        calls (list[dict[str, object]]): add_resource 调用记录.
    """

    def __init__(self) -> None:
        """初始化 FakeOpenVikingResources."""

        self.calls: list[dict[str, object]] = []

    async def add_resource(self, **kwargs):
        """记录 add_resource 调用.

        Args:
            **kwargs: provider 透传参数.

        Returns:
            一个最小 root_uri 结果.
        """

        self.calls.append(dict(kwargs))
        return {
            "root_uri": f"{kwargs['parent']}/guide.md",
            "source_path": kwargs["path"],
        }


class FakeOpenVikingSearch:
    """OpenViking search fake.

    Attributes:
        calls (list[dict[str, object]]): find 调用记录.
    """

    def __init__(self) -> None:
        """初始化 FakeOpenVikingSearch."""

        self.calls: list[dict[str, object]] = []

    async def find(self, **kwargs):
        """记录一次 find 调用.

        Args:
            **kwargs: provider 透传参数.

        Returns:
            一个最小搜索结果.
        """

        self.calls.append(dict(kwargs))
        target_uri = str(kwargs["target_uri"])
        return {
            "resources": [
                {
                    "uri": f"{target_uri}/guide.md",
                    "score": 0.92,
                    "abstract": "Guide abstract",
                    "name": "guide.md",
                    "meta": {
                        "source_path": "guide.md",
                        "tags": ["guide"],
                    },
                }
            ]
        }


class FakeOpenVikingFS:
    """OpenViking fs fake.

    Attributes:
        mkdir_calls (list[str]): mkdir 调用记录.
        ls_calls (list[str]): ls 调用记录.
        read_calls (list[str]): read 调用记录.
        overview_calls (list[str]): overview 调用记录.
        abstract_calls (list[str]): abstract 调用记录.
    """

    def __init__(self) -> None:
        """初始化 FakeOpenVikingFS."""

        self.mkdir_calls: list[str] = []
        self.ls_calls: list[str] = []
        self.read_calls: list[str] = []
        self.overview_calls: list[str] = []
        self.abstract_calls: list[str] = []

    async def mkdir(self, uri: str, ctx) -> None:
        """记录 mkdir 调用.

        Args:
            uri: 目标 URI.
            ctx: provider context.
        """

        _ = ctx
        self.mkdir_calls.append(uri)

    async def ls(self, uri: str, ctx, **kwargs) -> list[str]:
        """返回最小 space 列表.

        Args:
            uri: 目标 URI.
            ctx: provider context.
            **kwargs: 其他 provider 参数.

        Returns:
            一个最小 URI 列表.
        """

        _ = (ctx, kwargs)
        self.ls_calls.append(uri)
        return [f"{uri}/people", f"{uri}/manuals"]

    async def read(self, uri: str, ctx, offset: int = 0, limit: int = -1) -> str:
        """记录 read 调用.

        Args:
            uri: 目标 URI.
            ctx: provider context.
            offset: 偏移量.
            limit: 读取限制.

        Returns:
            一段固定正文.
        """

        _ = (ctx, offset, limit)
        self.read_calls.append(uri)
        return "Full reference content"

    async def overview(self, uri: str, ctx) -> str:
        """记录 overview 调用.

        Args:
            uri: 目标 URI.
            ctx: provider context.

        Returns:
            一段固定 overview.
        """

        _ = ctx
        self.overview_calls.append(uri)
        return "Reference overview"

    async def abstract(self, uri: str, ctx) -> str:
        """记录 abstract 调用.

        Args:
            uri: 目标 URI.
            ctx: provider context.

        Returns:
            一段固定 abstract.
        """

        _ = ctx
        self.abstract_calls.append(uri)
        return "Reference abstract"


class FakeOpenVikingService:
    """OpenViking service fake.

    Attributes:
        resources (FakeOpenVikingResources): resource 子服务.
        search (FakeOpenVikingSearch): search 子服务.
        fs (FakeOpenVikingFS): fs 子服务.
        initialized (bool): 是否调用过 initialize.
        closed (bool): 是否调用过 close.
    """

    def __init__(self) -> None:
        """初始化 FakeOpenVikingService."""

        self.resources = FakeOpenVikingResources()
        self.search = FakeOpenVikingSearch()
        self.fs = FakeOpenVikingFS()
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        """记录 initialize 调用."""

        self.initialized = True

    async def close(self) -> None:
        """记录 close 调用."""

        self.closed = True


async def test_openviking_reference_backend_is_lazy_and_maps_basic_calls() -> None:
    calls: list[str] = []
    service = FakeOpenVikingService()

    def service_factory() -> FakeOpenVikingService:
        calls.append("factory")
        return service

    backend = OpenVikingReferenceBackend(
        mode="embedded",
        path="./ov-data",
        base_uri="viking://resources/acabot",
        service_factory=service_factory,
        ctx_factory=lambda tenant_id: {"tenant_id": tenant_id},
    )

    assert calls == []

    refs = await backend.add_documents(
        [
            ReferenceDocumentInput(
                title="Guide",
                content="How to use AcaBot safely.",
                source_path="guide.md",
            )
        ],
        tenant_id="tenant-1",
        space_id="manuals",
        mode="readonly_reference",
    )
    hits = await backend.search(
        "use AcaBot",
        tenant_id="tenant-1",
        space_id="manuals",
        mode="readonly_reference",
        body="overview",
    )
    document = await backend.get_document(
        refs[0].ref_id,
        tenant_id="tenant-1",
        body="full",
    )
    spaces = await backend.list_spaces(
        tenant_id="tenant-1",
        mode="readonly_reference",
    )

    assert calls == ["factory"]
    assert service.initialized is True
    assert service.fs.mkdir_calls == [
        "viking://resources/acabot/tenant-1/readonly_reference/manuals"
    ]
    assert refs[0].uri.endswith("/guide.md")
    assert hits[0].uri.endswith("/guide.md")
    assert hits[0].body == "Reference overview"
    assert document is not None
    assert document.abstract == "Reference abstract"
    assert document.content == "Full reference content"
    assert [space.space_id for space in spaces] == ["people", "manuals"]

    await backend.close()

    assert service.closed is True


# endregion
