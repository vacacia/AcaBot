"""runtime.render.protocol 定义 render capability 的通用协议."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from .artifacts import RenderArtifacts


RenderStatus = Literal["ok", "unavailable", "error"]


@dataclass(slots=True)
class RenderRequest:
    """一次 render 调用需要的输入."""

    conversation_id: str
    run_id: str
    source_markdown: str
    artifacts: RenderArtifacts
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RenderResult:
    """render 调用的统一结果对象."""

    status: RenderStatus
    backend_name: str | None = None
    artifact_path: Path | None = None
    html: str | None = None
    mime_type: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        *,
        backend_name: str,
        artifact_path: Path,
        html: str,
        mime_type: str = "image/png",
        metadata: dict[str, Any] | None = None,
    ) -> RenderResult:
        """构造成功结果."""

        return cls(
            status="ok",
            backend_name=backend_name,
            artifact_path=artifact_path,
            html=html,
            mime_type=mime_type,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def unavailable(
        cls,
        *,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> RenderResult:
        """构造 capability unavailable 结果."""

        return cls(
            status="unavailable",
            error=error,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def error_result(
        cls,
        *,
        backend_name: str,
        error: str,
        html: str | None = None,
        artifact_path: Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RenderResult:
        """构造 backend 执行失败结果."""

        return cls(
            status="error",
            backend_name=backend_name,
            artifact_path=artifact_path,
            html=html,
            error=error,
            metadata=dict(metadata or {}),
        )


@runtime_checkable
class RenderBackend(Protocol):
    """render backend 需要实现的最小接口."""

    name: str

    async def render_markdown_to_image(self, request: RenderRequest) -> RenderResult:
        """把 markdown 渲染成图片."""

    async def close(self) -> None:
        """释放 backend 持有的资源."""
