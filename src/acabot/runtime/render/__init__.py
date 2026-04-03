"""runtime.render 导出 render capability 的公共接口."""

from __future__ import annotations

from .artifacts import RenderArtifacts, render_artifacts
from .playwright_backend import PlaywrightRenderBackend
from .protocol import RenderBackend, RenderRequest, RenderResult, RenderStatus
from .service import RenderService

__all__ = [
    "PlaywrightRenderBackend",
    "RenderArtifacts",
    "RenderBackend",
    "RenderRequest",
    "RenderResult",
    "RenderService",
    "RenderStatus",
    "render_artifacts",
]
