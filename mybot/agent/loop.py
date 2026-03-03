import json

from typing import Any
from mybot.providers.base import BaseProvider
from mybot.tools.math import MathTool
from mybot.tools.registry import TooRegistry

class AgentLoop:
    def __init__(self, provider: BaseProvider) -> None:
        self.max_iterations = 20
        self.provider = provider
        self.tool_registry = TooRegistry()
        self._register_defaul_tools()


    def _register_defaul_tools(self) -> None:
        self.tool_registry.register(MathTool())

    async def run(self, initial_message: list[dict]) -> None:
        messages = initial_message
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tool_registry.get_definations(),
            )

            print(response)
            if response.has_error:
                print(f"LLM error:{response.content}")
                break
            elif response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]

                messages = self._add_assistant_message(
                        messages, response.content, tool_call_dicts,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks
                )
                for tool_call in response.tool_calls:
                    result = await self.tool_registry.execute(tool_call.name, tool_call.arguments)
                    messages = self._add_tool_result(messages, tool_call.id, tool_call.name, result)
            else:
                print(response.content)
                break
        if iteration >= self.max_iterations:
            print(f"I reached the maximum number of tool call iterations ({self.max_iterations}) ")

    def _add_assistant_message(
        self,
        messages: list[dict[str, Any]], 
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None
    ) -> list[dict[str, Any]]:
        """Add assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        if thinking_blocks:
            msg["thinking_blocks"] = thinking_blocks
        messages.append(msg)
        return messages
    
    def _add_tool_result(
        self, 
        messages: list[dict[str, Any]], 
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages
