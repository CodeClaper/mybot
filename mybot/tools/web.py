import html
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from curl_cffi.requests import AsyncSession as CurlSession
from loguru import logger
from readability import Document

from mybot.tools.base import Tool

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowd, but got '{p.scheme or 'None'}'"
        if not p.netloc:
            return False, "Missing domain."
        return True, ""
    except Exception as e:
        return False, str(e)

class WebSearchTool(Tool):
    """Use google search to query up-to-date information."""
    def __init__(self, api_key: str | None = None, proxy: str | None = None) -> None:
        self.api_key = api_key
        self.proxy = proxy

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web, return titles, URLS and snappets."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search Query, use it when user's question requires up-to-date."},
                "count": {"type": "integer", "description": "Results (1-10)", "mininum": 1, "maxinum": 10},
            },
            "required": ["query"]
        }


    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return "Error: Api key not configure."
        try:
            n = 10 if count is None else min(count, 10)
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "engine": "google", "api_key": self.api_key},
                    headers={"Accept": "application/json"},
                    timeout=10.0
                )
                r.raise_for_status()

            results = r.json().get("organic_results", [])[:n]
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('link', '')}\n   {item.get('about_this_result').get('source').get('description')}")

            return "\n".join(lines)
        except httpx.ProtocolError as e:
            logger.error("Web search proxy error: {}", e)
            return f"Web search proxy error: {e}"
        except Exception as e:
            return f"Web search error: {e}"


class WebFetchTool(Tool):
    """Fetch given url."""
    def __init__(self, max_chars: int = 5000, proxy: str | None = None) -> None:
        self.max_chars = max_chars
        self.proxy = proxy

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch URL and extract readable content(HTML -> markdown/text)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
                "maxChars": {"type": "integer", "default": 1000}
            },
            "required": ["url"]
        }


    async def execute(self, url: str, extractMode: str = "markdown",  **kwargs: Any) -> str:
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        try:
            proxy = {"http": self.proxy, "https": self.proxy} if self.proxy else None
            async with CurlSession(
                impersonate="chrome120",
                timeout=30,
                proxy=proxy,
                max_redirects=MAX_REDIRECTS,
            ) as client:
                r = await client.get(url, headers=BROWSER_HEADERS)
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<htlm")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else self._strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > self.max_chars
            if truncated: text = text[:self.max_chars]

            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                               "extractor": extractor, "truncated": truncated, "length": len(text), "text": text})
        except Exception as e:
            logger.error("Web fetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)


    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{self._strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {self._strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {self._strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return self._normalize(self._strip_tags(text))

    def _strip_tags(self, text: str) -> str:
        """Remove HTML tags and decode entities."""
        text = re.sub(r"<script>[\s\S]*?</script>", '', text, flags=re.I)
        text = re.sub(r"<style>[\s\S]*?</style>", '', text, flags=re.I)
        text = re.sub(r"<[^>]+>", '', text)
        return html.unescape(text).strip()

    def _normalize(self, text: str) -> str:
        """Normalize whitespace."""
        text = re.sub(r'[ \t]+', ' ', text)
        return re.sub(r'\n{3,}', '\n\n', text).strip()
