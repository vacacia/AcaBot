"""runtime.references.models 定义 reference provider 的公开数据对象."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ReferenceMode = Literal["readonly_reference", "appendable_reference"]
ReferenceBodyLevel = Literal["none", "overview", "full"]
ReferenceProviderMode = Literal["embedded", "http"]


@dataclass(slots=True)
class ReferenceDocumentInput:
    """待写入 ReferenceBackend 的文档输入."""

    title: str
    content: str
    abstract: str = ""
    overview: str = ""
    source_path: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReferenceDocumentRef:
    """Reference 文档的轻量引用."""

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
    """Reference 检索命中结果."""

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
    """Reference 文档详情."""

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
    """Reference space 元信息."""

    tenant_id: str
    space_id: str
    mode: ReferenceMode
    document_count: int
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ReferenceBodyLevel",
    "ReferenceDocument",
    "ReferenceDocumentInput",
    "ReferenceDocumentRef",
    "ReferenceHit",
    "ReferenceMode",
    "ReferenceProviderMode",
    "ReferenceSpace",
]
