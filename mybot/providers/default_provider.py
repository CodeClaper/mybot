import secrets
import string
from typing import Any

import json_repair
from litellm import acompletion

from mybot.providers.base import BaseProvider, LLMResponse, ToolCallRequest

_ALNUM = string.ascii_letters + string.digits

def _short_tool_id() -> str:
    return "".join(secrets.choice(_ALNUM) for _ in range(9))

class DefaultProvider(BaseProvider):
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "deepseek/deepseek-chat"
    ) -> None:
        super().__init__(api_key, api_base)
        self.default_model = default_model

    async def chat(
        self, 
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 8094,
        temperature: float = 0.1
    ) -> LLMResponse:
        kargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if tools:
            kargs["tools"] = tools
            kargs["tool_choice"] = "auto"
        
        if self.api_key:
            kargs["api_key"] = self.api_key

        if self.api_base:
            kargs["api_base"] = self.api_base

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
