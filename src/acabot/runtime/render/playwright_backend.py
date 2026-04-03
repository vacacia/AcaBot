"""runtime.render.playwright_backend 提供基于 Playwright 的 render backend."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from latex2mathml.converter import convert
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin

from .protocol import RenderRequest, RenderResult


StartPlaywright = Callable[[], Awaitable[Any]]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root {{
        color-scheme: light;
      }}

      body {{
        margin: 0;
        background: #f4f1e8;
        color: #171717;
        font-family: "Noto Serif CJK SC", "Source Han Serif SC", serif;
      }}

      .render-shell {{
        box-sizing: border-box;
        width: 960px;
        padding: 40px;
      }}

      .render-card {{
        background: #fffdf8;
        border: 1px solid #d7cfbf;
        border-radius: 20px;
        box-shadow: 0 18px 48px rgba(23, 23, 23, 0.08);
        padding: 36px 40px;
      }}

      .render-card > :first-child {{
        margin-top: 0;
      }}

      .render-card > :last-child {{
        margin-bottom: 0;
      }}

      .math.block {{
        margin: 16px 0;
        overflow-x: auto;
      }}
    </style>
  </head>
  <body>
    <main class="render-shell">
      <article class="render-card">{body}</article>
    </main>
  </body>
</html>
"""


class PlaywrightRenderBackend:
    """Playwright render backend.

    browser 和 playwright 对象都是 backend 级缓存, 第一次 render 才真正启动.
    """

    name = "playwright"

    def __init__(
        self,
        *,
        start_playwright: StartPlaywright | None = None,
    ) -> None:
        """初始化 backend."""

        self._start_playwright = start_playwright or _default_start_playwright
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._browser_lock = asyncio.Lock()
        self._markdown = self._build_markdown_renderer()

    async def render_markdown_to_image(self, request: RenderRequest) -> RenderResult:
        """把 markdown 渲染成 HTML, 再截图成 png."""

        document_html = self._build_document(request.source_markdown)
        request.artifacts.html_path.write_text(document_html, encoding="utf-8")
        page = None
        try:
            browser = await self._ensure_browser()
            page = await browser.new_page()
            await page.set_viewport_size({"width": 960, "height": 540})
            await page.set_content(document_html, wait_until="load")
            await page.screenshot(
                path=str(request.artifacts.image_path),
                full_page=True,
                type="png",
            )
            return RenderResult.ok(
                backend_name=self.name,
                artifact_path=request.artifacts.image_path,
                html=document_html,
                metadata={"html_path": str(request.artifacts.html_path)},
            )
        except Exception as exc:
            return RenderResult.error_result(
                backend_name=self.name,
                artifact_path=request.artifacts.image_path,
                html=document_html,
                error=str(exc),
                metadata={"html_path": str(request.artifacts.html_path)},
            )
        finally:
            if page is not None:
                await page.close()

    async def close(self) -> None:
        """关闭 browser 和 playwright."""

        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    async def _ensure_browser(self) -> Any:
        """按需启动并复用 browser."""

        if self._browser is not None:
            return self._browser
        async with self._browser_lock:
            if self._browser is not None:
                return self._browser
            self._playwright = await self._start_playwright()
            self._browser = await self._playwright.chromium.launch(headless=True)
            return self._browser

    def _build_document(self, markdown_text: str) -> str:
        """把 markdown source 组装成完整 HTML 文档."""

        body = self._markdown.render(markdown_text)
        return HTML_TEMPLATE.format(body=body)

    @staticmethod
    def _build_markdown_renderer() -> MarkdownIt:
        """构造 markdown + math 渲染器."""

        renderer = MarkdownIt("commonmark", {"html": False})
        renderer.use(
            dollarmath_plugin,
            allow_labels=False,
            renderer=_render_math,
        )
        return renderer


def _render_math(content: str, options: dict[str, Any]) -> str:
    """把 LaTeX math 片段转成 MathML."""

    display = "block" if bool(options.get("display_mode")) else "inline"
    return convert(content, display=display)


async def _default_start_playwright() -> Any:
    """延迟导入 Playwright, 保持 import 轻量."""

    from playwright.async_api import async_playwright

    return await async_playwright().start()
