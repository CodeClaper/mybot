import httpx

from typing import Any
from mybot.tools.base import Tool

class WebSearchTool(Tool):
    
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        pass

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
                "query": {"type": "string", "description": "Search Query"},
                "count": {"type": "integer", "description": "Results (1-10)", "mininum": 1, "maxinum": 10},
            },
            "required": ["query"]
        }

    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        if not self.api_key:
            return "Error: Api key not configure."
        try:
            n = 10 if count is None else min(count, 10)
        except Exception as e:
            return f"Web search error: {e}"
        return ""
    
