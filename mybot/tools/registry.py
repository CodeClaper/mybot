
from typing import Any
from mybot.tools.base import Tool


class TooRegistry:
    """
    Registry for agent tools.
    """
    
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def get_definations(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]
