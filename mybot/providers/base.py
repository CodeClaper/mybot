
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None
    thinking_blocks: list[dict] | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls. """
        return len(self.tool_calls) > 0

    @property
    def has_error(self) -> bool:
        return self.finish_reason == "error"

class BaseProvider(ABC):
    def __init__(self) -> None:
        pass

    @abstractmethod
    async def chat(
        self, 
        user_message: str,
        tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        """
        Send a chat completion request.
        """
        pass
