from ast import arguments
from litellm import acompletion
from typing import Any
import json_repair

from mybot.providers.base import BaseProvider, LLMResponse, ToolCallRequest

class DefaultProvider(BaseProvider):
    def __init__(self) -> None:
        pass

    async def chat(self, user_message: str) -> LLMResponse:
        kargs: dict[str, Any] = {
            "model": "deepseek/deepseek-chat",
            "messages": [
                {"role": "system", "content": "Your are a help assistant."},
                {"role": "user", "content": user_message}
            ],
            "api_key": "sk-6b09e81523294dc5b84a4583124be3c5",
            "base_url": "https://api.deepseek.com",
            "max_token": 8094,
            "temperature": 0.1
        }
        try:
            response = await acompletion(**kargs)
            return self._parse_reponse(response)
        except Exception as e:
            return LLMResponse(content=f"Error calling LLM: {str(e)}", finish_reason="error")
    
    def _parse_reponse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)

                tool_calls.append(ToolCallRequest(
                    id="",
                    name=tc.function.name,
                    arguments=args
                ))

        reasoning_content = getattr(message, "reasoning_content", None) or None
        thinking_blocks = getattr(message, "thinking_blocks", None) or None

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )
