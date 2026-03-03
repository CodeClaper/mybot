
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

    async def execute(self, name: str, params: dict[str, Any]) ->str:
        """Execute a tool by name and given params. """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"
        tool = self.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found."
        
        try:
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}"

