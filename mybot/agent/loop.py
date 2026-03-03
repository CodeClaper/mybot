import asyncio
import json

from typing import Any
from loguru import logger

from mybot.cli.bus.message import InboundMessage, OutboundMessage
from mybot.cli.bus.queue import MessageBus
from mybot.providers.base import BaseProvider
from mybot.tools.math import MathTool
from mybot.tools.registry import TooRegistry

class AgentLoop:
    def __init__(
        self, 
        provider: BaseProvider,
        bus: MessageBus
    ) -> None:
        self._running = False
        self.max_iterations = 20
        self.provider = provider
        self.bus = bus
        self.tool_registry = TooRegistry()
        self._register_defaul_tools()


    def _register_defaul_tools(self) -> None:
        self.tool_registry.register(MathTool())

    async def run(self) -> None:
        """Agent loop run."""
        self._running = True

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            asyncio.create_task(self._dispatch(msg))

    def stop(self) -> None:
        """Agent loop stop."""
        self._running = False

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Dispath the message."""
        try:
            response = await self._process_message(msg)
            if response is not None:
                await self.bus.publish_outbound(response)
        except asyncio.CancelledError:
            logger.info("Task cancelled.") 
            raise
        except Exception:
            logger.exception("Error processing message.")
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, 
                chat_id=msg.chat_id,
                content="Sorry, I encountered an error."
            ))

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        final_content = await self._run_agent_loop(self._build_messages(msg))
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                               content=final_content or "Agent loop task completed.")


    async def _run_agent_loop(self, initial_message: list[dict]) -> str | None:
        """Run agent loop."""
        messages = initial_message
        final_content = None
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tool_registry.get_definations(),
            )

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
                final_content = response.content
                break
        if iteration >= self.max_iterations:
            final_content = (f"I reached the maximum number of tool call iterations ({self.max_iterations}) ")

        return final_content

    def _build_messages(self, msg: InboundMessage) -> list[dict[str, Any]]:
        """Build messages."""
        return [
            {"role": "system", "content": "You are a personal AI Assistant."},
            {"role": "user", "content": msg.content}
        ]

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
