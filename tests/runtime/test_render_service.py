from __future__ import annotations

from pathlib import Path

import pytest

from acabot.runtime.render.artifacts import render_artifacts
from acabot.runtime.render.playwright_backend import PlaywrightRenderBackend
from acabot.runtime.render.service import RenderService


class FakePage:
    def __init__(self) -> None:
        self.viewport_sizes: list[dict[str, int]] = []
        self.contents: list[tuple[str, str]] = []
        self.screenshots: list[dict[str, object]] = []
        self.closed = 0

    async def set_viewport_size(self, size: dict[str, int]) -> None:
        self.viewport_sizes.append(dict(size))

    async def set_content(self, html: str, *, wait_until: str = "load") -> None:
        self.contents.append((html, wait_until))

    async def screenshot(
        self,
        *,
        path: str,
        full_page: bool,
        type: str,
    ) -> None:
        self.screenshots.append(
            {
                "path": path,
                "full_page": full_page,
                "type": type,
            }
        )
        Path(path).write_bytes(b"fake-png")

    async def close(self) -> None:
        self.closed += 1


class FakeBrowser:
    def __init__(self) -> None:
        self.new_page_calls = 0
        self.pages: list[FakePage] = []
        self.closed = 0

    async def new_page(self) -> FakePage:
        self.new_page_calls += 1
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed += 1


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.launch_calls = 0
        self.launch_options: list[dict[str, object]] = []

    async def launch(self, **kwargs: object) -> FakeBrowser:
        self.launch_calls += 1
        self.launch_options.append(dict(kwargs))
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)
        self.stopped = 0

    async def stop(self) -> None:
        self.stopped += 1


@pytest.mark.asyncio
async def test_render_service_returns_unavailable_without_backend(
    tmp_path: Path,
) -> None:
    service = RenderService(runtime_root=tmp_path / "runtime_data")

    result = await service.render_markdown_to_image(
        markdown_text="# Hello",
        conversation_id="qq:user:10001",
        run_id="run:missing-backend",
    )

    assert result.status == "unavailable"
    assert result.backend_name is None
    assert result.artifact_path is None
    assert result.error is not None
    assert "backend" in result.error


@pytest.mark.asyncio
async def test_playwright_backend_reuses_single_browser(
    tmp_path: Path,
) -> None:
    fake_browser = FakeBrowser()
    state: dict[str, object] = {"starts": 0}

    async def start_playwright() -> FakePlaywright:
        state["starts"] = int(state["starts"]) + 1
        playwright = FakePlaywright(fake_browser)
        state["playwright"] = playwright
        return playwright

    backend = PlaywrightRenderBackend(start_playwright=start_playwright)
    service = RenderService(runtime_root=tmp_path / "runtime_data")
    service.register_backend(backend.name, backend)

    first = await service.render_markdown_to_image(
        markdown_text="# First",
        conversation_id="qq:user:10001",
        run_id="run:first",
    )
    second = await service.render_markdown_to_image(
        markdown_text="# Second",
        conversation_id="qq:user:10001",
        run_id="run:second",
    )
    await service.close()

    fake_playwright = state["playwright"]
    assert isinstance(fake_playwright, FakePlaywright)
    assert state["starts"] == 1
    assert fake_playwright.chromium.launch_calls == 1
    assert fake_browser.new_page_calls == 2
    assert first.status == "ok"
    assert second.status == "ok"
    assert fake_browser.closed == 1
    assert fake_playwright.stopped == 1


@pytest.mark.asyncio
async def test_render_markdown_to_image_pipeline(tmp_path: Path) -> None:
    fake_browser = FakeBrowser()

    async def start_playwright() -> FakePlaywright:
        return FakePlaywright(fake_browser)

    backend = PlaywrightRenderBackend(start_playwright=start_playwright)
    service = RenderService(runtime_root=tmp_path / "runtime_data")
    service.register_backend(backend.name, backend)

    result = await service.render_markdown_to_image(
        markdown_text="# Title\n\nInline $x + 1$\n\n$$x^2$$\n",
        conversation_id="qq:group:20002",
        run_id="run:math",
    )

    page = fake_browser.pages[0]
    html = page.contents[0][0]
    assert result.status == "ok"
    assert result.html == html
    assert "<h1>Title</h1>" in html
    assert 'class="math inline"' in html
    assert 'display="inline"' in html
    assert 'display="block"' in html
    assert result.artifact_path is not None
    assert result.artifact_path.read_bytes() == b"fake-png"


def test_render_artifacts_stay_under_internal_runtime_paths(
    tmp_path: Path,
) -> None:
    artifacts = render_artifacts(
        runtime_root=tmp_path / "runtime_data",
        conversation_id="qq:group:20002",
        run_id="run:render",
    )

    assert artifacts.artifact_dir == (
        tmp_path
        / "runtime_data"
        / "render_artifacts"
        / "qq:group:20002"
        / "run:render"
    )
    assert artifacts.artifact_dir.exists()
    assert str(artifacts.image_path).startswith(str(tmp_path / "runtime_data"))
    assert "/workspace/attachments" not in str(artifacts.image_path)
