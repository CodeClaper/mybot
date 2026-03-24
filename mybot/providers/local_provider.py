import json_repair
import string
import secrets
from typing import Any
from openai import AsyncOpenAI
from mybot.providers.base import BaseProvider, LLMResponse, ToolCallRequest

_ALNUM = string.ascii_letters + string.digits

def _short_tool_id() -> str:
    return "".join(secrets.choice(_ALNUM) for _ in range(9))

class LocalProvider(BaseProvider):
    def __init__(
        self, 
        api_key: str = "sk-no-key", 
        api_base: str = "http://localhost:8080/v1"
    ) -> None:
        super().__init__(api_key, api_base)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base
        )

    async def chat(
        self, 
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 8094,
        temperature: float = 0.1
    ) -> LLMResponse:
        kargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if tools:
            kargs["tools"] = tools
            kargs["tool_choice"] = "auto"
        
        try:
            response = await self._client.chat.completions.create(**kargs)
            return self._parse_reponse(response)
        except Exception as e:
            return LLMResponse(content=f"Error calling LLM: {str(e)}", finish_reason="error")

    def _parse_reponse(self, response: Any) -> LLMResponse:
        if not response.choices:
            return LLMResponse(content="Error: API returned empty choices.", finish_reason="error")

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)

                tool_calls.append(ToolCallRequest(
                    id=_short_tool_id(),
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
