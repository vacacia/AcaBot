"""runtime.builtin_tools.web 提供受限的网页抓取与搜索工具。


- `web_fetch`: 读取单个网页正文, 返回模型可消费的纯文本摘要
- `web_search`: 通过受控 provider 搜索网页, 返回结构化候选结果

- 对模型暴露简单稳定的工具名
- 真实实现留在 runtime 内部, 后续可以替换 provider
- 默认限制只读、只支持 http/https、限制体积与超时
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from inspect import isawaitable
import re
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from acabot.agent import ToolSpec

from ..tool_broker import ToolBroker, ToolExecutionContext, ToolResult


# region source
BUILTIN_WEB_TOOL_SOURCE = "builtin:web"


# endregion


# region data
@dataclass(slots=True)
class FetchedWebDocument:
    """一次网页抓取结果。"""

    url: str
    final_url: str
    status_code: int
    content_type: str
    title: str
    text: str
    truncated: bool = False


@dataclass(slots=True)
class WebSearchHit:
    """一条网页搜索命中结果。"""

    title: str
    url: str
    snippet: str = ""


# endregion


# region parser
class _VisibleHtmlTextExtractor(HTMLParser):
    """把 HTML 收成可读文本, 并尽量保留 title。"""

    def __init__(self) -> None:
        """初始化文本收集状态。"""

        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """在进入标签时更新忽略与分段状态。"""

        _ = attrs
        normalized = str(tag or "").lower()
        if normalized in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if normalized == "title":
            self._in_title = True
            return
        if normalized in {"p", "div", "section", "article", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """在离开标签时恢复状态。"""

        normalized = str(tag or "").lower()
        if normalized in {"script", "style", "noscript"} and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if normalized == "title":
            self._in_title = False
            return
        if normalized in {"p", "div", "section", "article", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        """收集可见文本。"""

        if self._ignored_depth > 0:
            return
        text = str(data or "")
        if not text.strip():
            return
        if self._in_title:
            self._title_parts.append(text)
            return
        self._text_parts.append(text)

    def title(self) -> str:
        """返回解析出的标题。"""

        return _normalize_visible_text(" ".join(self._title_parts))

    def text(self) -> str:
        """返回解析出的正文。"""

        return _normalize_visible_text("".join(self._text_parts))


class _DuckDuckGoHtmlParser(HTMLParser):
    """从 DuckDuckGo HTML 结果页里抽取标题、链接和摘要。

    早期版本用状态机增量解析, 但 DuckDuckGo 的 HTML 结果层级较深,
    snippet 与 title 经常被拆进不同标签层里, 很容易出现全空结果。
    这里改成“先用 HTMLParser 拿到纯净文本, 再按 result block 做正则提取”
    的混合策略, 稳定性更高。
    """

    _RESULT_BLOCK_RE = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>(?P<tail>.*?)(?=(?:<h2 class="result__title">)|(?:<div class="nav-link">)|\Z)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    _SNIPPET_RE = re.compile(
        r'class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def __init__(self) -> None:
        """保留 HTMLParser 基类初始化, 便于未来扩展。"""

        super().__init__(convert_charrefs=True)

    def results(self, *, html: str, limit: int) -> list[WebSearchHit]:
        """直接从完整 HTML 里提取搜索结果。"""

        hits: list[WebSearchHit] = []
        for match in self._RESULT_BLOCK_RE.finditer(str(html or "")):
            href = _decode_search_result_url(str(match.group("href") or ""))
            title = _strip_html_tags(str(match.group("title") or ""))
            snippet_match = self._SNIPPET_RE.search(str(match.group("tail") or ""))
            snippet = _strip_html_tags(str(snippet_match.group("snippet") or "")) if snippet_match else ""
            if not href or not title:
                continue
            hits.append(WebSearchHit(title=title, url=href, snippet=snippet))
            if len(hits) >= max(1, limit):
                break
        return hits


# endregion


# region surface
class BuiltinWebToolSurface:
    """向模型暴露受控 `web_fetch` 与 `web_search`。"""

    def __init__(
        self,
        *,
        fetch_document: Callable[..., FetchedWebDocument | Any] | None = None,
        search_web: Callable[..., list[WebSearchHit] | Any] | None = None,
    ) -> None:
        """保存可替换的抓取与搜索实现。

        Args:
            fetch_document: 可选网页抓取函数, 便于测试替身或后续 provider 替换。
            search_web: 可选网页搜索函数, 便于测试替身或后续 provider 替换。
        """

        self._fetch_document_impl = fetch_document or self._default_fetch_document
        self._search_web_impl = search_web or self._default_search_web

    def register(self, tool_broker: ToolBroker) -> list[str]:
        """把网页工具注册进 ToolBroker。"""

        tool_broker.unregister_source(BUILTIN_WEB_TOOL_SOURCE)
        names: list[str] = []
        for spec, handler in self._tool_definitions():
            tool_broker.register_tool(
                spec,
                handler,
                source=BUILTIN_WEB_TOOL_SOURCE,
            )
            names.append(spec.name)
        return names

    def _tool_definitions(self) -> list[tuple[ToolSpec, Any]]:
        """返回本模块导出的工具列表。"""

        return [
            (
                ToolSpec(
                    name="web_fetch",
                    description=(
                        "Fetch a web page over HTTP(S) and return a cleaned text summary. "
                        "Use this to read external documentation, articles, or reference pages."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "HTTP(S) URL to fetch.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Optional network timeout in seconds.",
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Maximum cleaned characters to return.",
                            },
                        },
                        "required": ["url"],
                    },
                ),
                self._web_fetch,
            ),
            (
                ToolSpec(
                    name="web_search",
                    description=(
                        "Search the public web and return ranked result candidates. "
                        "Use this to find documentation, tutorials, or relevant pages before fetching them."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query in natural language.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return.",
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Optional network timeout in seconds.",
                            },
                        },
                        "required": ["query"],
                    },
                ),
                self._web_search,
            ),
        ]

    async def _web_fetch(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """执行单页抓取。"""

        self._ensure_network_enabled(ctx)
        url = str(arguments.get("url", "") or "").strip()
        if not url:
            raise ValueError("url is required")
        timeout = int(arguments.get("timeout", 15) or 15)
        max_chars = int(arguments.get("max_chars", 12000) or 12000)
        result = await self._resolve_fetch_document(url=url, timeout=timeout, max_chars=max_chars)
        payload = asdict(result)
        return ToolResult(
            llm_content=self._format_fetch_result(result),
            raw=payload,
            metadata={
                "url": result.url,
                "final_url": result.final_url,
                "status_code": result.status_code,
                "content_type": result.content_type,
                "title": result.title,
            },
        )

    async def _web_search(self, arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        """执行网页搜索。"""

        self._ensure_network_enabled(ctx)
        query = str(arguments.get("query", "") or "").strip()
        if not query:
            raise ValueError("query is required")
        timeout = int(arguments.get("timeout", 15) or 15)
        limit = max(1, min(int(arguments.get("limit", 5) or 5), 10))
        hits = await self._resolve_search_web(query=query, limit=limit, timeout=timeout)
        payload = {
            "query": query,
            "results": [asdict(item) for item in hits],
        }
        return ToolResult(
            llm_content=self._format_search_results(query=query, hits=hits),
            raw=payload,
            metadata={"query": query, "result_count": len(hits)},
        )

    async def _resolve_fetch_document(self, *, url: str, timeout: int, max_chars: int) -> FetchedWebDocument:
        """统一兼容同步或异步抓取实现。"""

        result = self._fetch_document_impl(url=url, timeout=timeout, max_chars=max_chars)
        if isawaitable(result):
            result = await result
        if not isinstance(result, FetchedWebDocument):
            raise TypeError("fetch_document must return FetchedWebDocument")
        return result

    async def _resolve_search_web(self, *, query: str, limit: int, timeout: int) -> list[WebSearchHit]:
        """统一兼容同步或异步搜索实现。"""

        result = self._search_web_impl(query=query, limit=limit, timeout=timeout)
        if isawaitable(result):
            result = await result
        hits = list(result or [])
        for item in hits:
            if not isinstance(item, WebSearchHit):
                raise TypeError("search_web must return WebSearchHit items")
        return hits

    @staticmethod
    def _ensure_network_enabled(ctx: ToolExecutionContext) -> None:
        """检查当前运行上下文是否允许网络访问。"""

        network_mode = str(
            ctx.metadata.get("network_mode", getattr(ctx.agent.computer_policy, "network_mode", "enabled")) or "enabled"
        ).strip()
        if network_mode == "disabled":
            raise PermissionError("network access disabled for web tools")

    @staticmethod
    def _format_fetch_result(result: FetchedWebDocument) -> str:
        """把网页抓取结果整理成模型可读文本。"""

        lines = [
            f"Fetched URL: {result.final_url or result.url}",
            f"Status: {result.status_code}",
            f"Content-Type: {result.content_type or '-'}",
        ]
        if result.title:
            lines.append(f"Title: {result.title}")
        lines.append("")
        lines.append(result.text or "(empty page body)")
        if result.truncated:
            lines.extend(["", "[truncated]"])
        return "\n".join(lines)

    @staticmethod
    def _format_search_results(*, query: str, hits: list[WebSearchHit]) -> str:
        """把搜索结果排成稳定文本格式。"""

        lines = [f"Search query: {query}", ""]
        if not hits:
            lines.append("No results.")
            return "\n".join(lines)
        for index, item in enumerate(hits, start=1):
            lines.append(f"{index}. {item.title}")
            lines.append(f"   URL: {item.url}")
            if item.snippet:
                lines.append(f"   Snippet: {item.snippet}")
        return "\n".join(lines)

    @staticmethod
    def _default_fetch_document(*, url: str, timeout: int, max_chars: int) -> FetchedWebDocument:
        """使用内置 provider 抓取网页。

        优先直接抓原站；遇到常见 403 / 401 / 406 之类的站点限制时，
        回退到 `r.jina.ai/http://...` 文本镜像，尽量保证模型仍能拿到正文。
        """

        _validate_http_url(url)
        max_bytes = max(4096, min(max_chars * 4, 400_000))
        try:
            return _fetch_document_once(url=url, timeout=timeout, max_chars=max_chars, max_bytes=max_bytes)
        except HTTPError as exc:
            if int(getattr(exc, "code", 0) or 0) not in {401, 403, 406, 429}:
                raise
            fallback_url = _jina_reader_url(url)
            return _fetch_document_once(
                url=url,
                request_url=fallback_url,
                timeout=timeout,
                max_chars=max_chars,
                max_bytes=max_bytes,
            )

    @staticmethod
    def _default_search_web(*, query: str, limit: int, timeout: int) -> list[WebSearchHit]:
        """使用 DuckDuckGo HTML provider 执行搜索。"""

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(300_000)
            content_type = str(response.headers.get("Content-Type", "") or "")
        html = raw.decode(_charset_from_content_type(content_type) or "utf-8", errors="replace")
        parser = _DuckDuckGoHtmlParser()
        return parser.results(html=html, limit=limit)


# endregion


# region util
def _charset_from_content_type(content_type: str) -> str:
    """从 Content-Type 里提取 charset。"""

    match = re.search(r"charset=([A-Za-z0-9._-]+)", str(content_type or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _fetch_document_once(
    *,
    url: str,
    timeout: int,
    max_chars: int,
    max_bytes: int,
    request_url: str | None = None,
) -> FetchedWebDocument:
    """执行一次真实网页抓取。"""

    resolved_request_url = str(request_url or url)
    request = Request(
        resolved_request_url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
            "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[:max_bytes]
        content_type = str(response.headers.get("Content-Type", "") or "")
        charset = _charset_from_content_type(content_type) or "utf-8"
        decoded = raw.decode(charset, errors="replace")
        if "html" in content_type.lower() or "<html" in decoded.lower():
            extractor = _VisibleHtmlTextExtractor()
            extractor.feed(decoded)
            title = extractor.title()
            text = extractor.text()
        else:
            title = _extract_title_from_plaintext(decoded)
            text = _normalize_visible_text(decoded)
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            truncated = True
        final_url = str(getattr(response, "url", "") or resolved_request_url)
        return FetchedWebDocument(
            url=url,
            final_url=final_url,
            status_code=int(getattr(response, "status", 200) or 200),
            content_type=content_type,
            title=title,
            text=text,
            truncated=truncated,
        )


def _extract_title_from_plaintext(text: str) -> str:
    """从纯文本抓取结果里尝试抽标题。"""

    for line in str(text or "").splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        if normalized.lower().startswith("title:"):
            return normalized.split(":", 1)[1].strip()
        return normalized[:160]
    return ""


def _jina_reader_url(url: str) -> str:
    """把原始 URL 转成 Jina Reader 文本镜像地址。"""

    return f"https://r.jina.ai/http://{url}"


def _validate_http_url(url: str) -> None:
    """限制只允许 http/https URL。"""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http/https URLs are supported")
    if not parsed.netloc:
        raise ValueError("url host is required")


def _normalize_visible_text(text: str) -> str:
    """压缩多余空白, 保留段落感。"""

    normalized = unescape(str(text or ""))
    normalized = normalized.replace("\r", "")
    normalized = re.sub(r"[\t\x0b\x0c ]+", " ", normalized)
    normalized = re.sub(r"\n\s+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    lines = [line.strip() for line in normalized.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _strip_html_tags(html_fragment: str) -> str:
    """把小片段 HTML 收成纯文本。"""

    return _normalize_visible_text(re.sub(r"<.*?>", "", str(html_fragment or ""), flags=re.DOTALL))


def _decode_search_result_url(raw_url: str) -> str:
    """把 DuckDuckGo 跳转链接解码回原始目标 URL。"""

    text = str(raw_url or "")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[-1]
        if uddg:
            return unquote(uddg)
    return text


# endregion


__all__ = [
    "BUILTIN_WEB_TOOL_SOURCE",
    "BuiltinWebToolSurface",
    "FetchedWebDocument",
    "WebSearchHit",
]
