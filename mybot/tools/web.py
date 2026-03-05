import httpx

from loguru import logger
from typing import Any
from mybot.tools.base import Tool

class WebSearchTool(Tool):
    
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
    
