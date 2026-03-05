import asyncio
import json

from pathlib import Path
from typing import Any
from loguru import logger

from mybot.bus.message import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.memory.context import ContextBuilder
from mybot.memory.session import Session, SessionManager
from mybot.providers.base import BaseProvider
from mybot.tools.math import MathTool
from mybot.tools.shell import ShellTool
from mybot.tools.registry import TooRegistry

class AgentLoop:
    def __init__(
        self, 
        workspace: Path,
        provider: BaseProvider,
        bus: MessageBus,
        session_manager: SessionManager
    ) -> None:
        self._running = False
        self.max_iterations = 20
        self.provider = provider
        self.bus = bus
        self.session_manager = session_manager
        self.context = ContextBuilder(workspace)
        self.tool_registry = TooRegistry()
        self._register_defaul_tools()

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


    def _register_defaul_tools(self) -> None:
        """Register default tools."""
        self.tool_registry.register(ShellTool())


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
        """Process a single inbound message and return the response."""
        session = self.session_manager.get_or_create(msg.chat_id)
        history = session.get_history(100)
        initial_messages = self.context.build_messages(msg, history)
        final_content, messages = await self._run_agent_loop(initial_messages)
        self._save_session_messages(session, messages, 1 + len(history))
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content or "Agent loop task completed.")


    async def _run_agent_loop(
        self, 
        initial_messages: list[dict]
    ) -> tuple[str | None, list[dict]]:
        """Run agent loop."""
        messages = initial_messages
        final_content = None
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tool_registry.get_definations(),
            )

            if response.has_error:
                logger.error(f"LLM error:{response.content}")
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

        return final_content, messages

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

    def _save_session_messages(
        self, 
        session: Session, 
        messages: list[dict[str, Any]], 
        skip: int
    ) ->None:
        """Save messages into session."""
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role is None or content is None:
                continue
            if role == "tool" and len(content) > 500:
                entry["content"] = content[:500] + f"\n...(truncated {len(content) - 500} characters.)"
            session.add_message(entry)
