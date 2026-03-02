from typing import Any
from mybot.tools.base import Tool

class MathTool(Tool):
    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "math"

    @property
    def description(self) -> str:
        return "Math library, support method <add>, <multipy>"


    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "multipy"],
                    "description": "Math methods."
                },
                "arguements": {
                    "a": { "type": "int"},
                    "b": { "type": "int"}
                }
            },
            "required": ["action", "arguements"]
        }

    async def execute(
        self, 
        action: str,
        arguements: dict[str, int]
    ) -> str:
        print("Invoke tool math.")
        if action == 'add':
            return str(arguements["a"] + arguements["b"])
        elif action == 'multipy':
            return str(arguements["a"] * arguements["b"])
        else:
            return f"Unkonwo actionL {action}"
