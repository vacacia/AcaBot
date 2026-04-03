"""runtime.render.service 提供 capability-based render service."""

from __future__ import annotations

from pathlib import Path

from .artifacts import render_artifacts
from .protocol import RenderBackend, RenderRequest, RenderResult


class RenderService:
    """统一的 render service.

    service 自己不绑定具体实现, 只维护 backend registry.
    没有 backend 时要安全返回 unavailable, 不能拖垮 runtime 启动.
    """

    def __init__(
        self,
        *,
        runtime_root: Path | str,
        backends: list[RenderBackend] | None = None,
    ) -> None:
        """初始化 render service."""

        self.runtime_root = Path(runtime_root).expanduser()
        self._backends: dict[str, RenderBackend] = {}
        for backend in backends or []:
            self.register_backend(backend.name, backend)

    def register_backend(self, name: str, backend: RenderBackend) -> None:
        """注册一个 render backend."""

        backend_name = str(name or "").strip()
        if not backend_name:
            raise ValueError("backend name cannot be empty")
        self._backends[backend_name] = backend

    def unregister_backend(self, name: str) -> RenderBackend | None:
        """移除一个 render backend."""

        backend_name = str(name or "").strip()
        if not backend_name:
            return None
        return self._backends.pop(backend_name, None)

    def get_backend(self, name: str) -> RenderBackend | None:
        """按名字获取 backend."""

        backend_name = str(name or "").strip()
        if not backend_name:
            return None
        return self._backends.get(backend_name)

    def backend_names(self) -> tuple[str, ...]:
        """返回当前已注册 backend 名字列表."""

        return tuple(self._backends)

    async def render_markdown_to_image(
        self,
        *,
        markdown_text: str,
        conversation_id: str,
        run_id: str,
        backend_name: str | None = None,
        filename_stem: str = "rendered",
    ) -> RenderResult:
        """通过已注册 backend 渲染 markdown 到图片."""

        backend = self._pick_backend(backend_name)
        if backend is None:
            return RenderResult.unavailable(
                error=self._missing_backend_error(backend_name),
                metadata={"requested_backend": backend_name},
            )

        artifacts = render_artifacts(
            runtime_root=self.runtime_root,
            conversation_id=conversation_id,
            run_id=run_id,
            filename_stem=filename_stem,
        )
        return await backend.render_markdown_to_image(
            request=RenderRequest(
                conversation_id=conversation_id,
                run_id=run_id,
                source_markdown=markdown_text,
                artifacts=artifacts,
            )
        )

    async def close(self) -> None:
        """关闭所有已注册 backend."""

        for backend in list(self._backends.values()):
            await backend.close()

    def _pick_backend(self, backend_name: str | None) -> RenderBackend | None:
        """解析这次 render 要使用的 backend."""

        if backend_name is not None:
            return self.get_backend(backend_name)
        return next(iter(self._backends.values()), None)

    def _missing_backend_error(self, backend_name: str | None) -> str:
        """生成统一的 unavailable 错误文案."""

        if backend_name is not None:
            return f"render backend '{backend_name}' is unavailable"
        return "render backend is unavailable"
