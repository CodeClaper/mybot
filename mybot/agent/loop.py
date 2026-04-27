import asyncio
import json

from pathlib import Path
from typing import Any, Awaitable, Callable
from loguru import logger

from mybot.bus.message import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.commands.builtin import register_builtin_commands
from mybot.commands.router import CommandContext, CommandRouter
from mybot.config.schema import Config
from mybot.context.context import ContextBuilder
from mybot.context.session import Session, SessionManager
from mybot.providers.base import BaseProvider
from mybot.tools.shell import ShellTool
from mybot.tools.message import MessageTool
from mybot.tools.registry import TooRegistry
from mybot.tools.web import WebFetchTool, WebSearchTool
from mybot.utils.helper import strip_think

class AgentLoop:
    """
    The Agent Loop is the core processing engine.

    Responsibilities:
    1. Receive messages from the bus.
    2. Build context with history, memory, tools, skills.
    3. Calls the LLM.
    4. Execute tool calls.
    5. Send response back.
    """

    def __init__(
        self, 
        workspace: Path,
        provider: BaseProvider,
        bus: MessageBus,
        session_manager: SessionManager,
        config: Config
    ) -> None:
        self._running = False
        self.max_iterations = 100
        self.provider = provider
        self.bus = bus
        self.workspace = workspace
        self.session_manager = session_manager or SessionManager(self.workspace)
        self.config = config
        self.context = ContextBuilder(workspace)
        self.tool_registry = TooRegistry()
        self._register_defaul_tools()
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

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
        web_config = self.config.tools.web
        self.tool_registry.register(ShellTool())
        self.tool_registry.register(WebSearchTool(proxy=web_config.proxy, api_key=web_config.search.api_key))
        self.tool_registry.register(WebFetchTool(proxy=web_config.proxy))
        self.tool_registry.register(MessageTool(send_callback=self.bus.publish_outbound))


    async def _dispatch(self, msg: InboundMessage) -> None:
        """Dispath the message."""
        try:
            response = await self._process_message(msg)
            if response is not None:
                await self.bus.publish_outbound(response)
        except asyncio.CancelledError:
            logger.info("Task cancelled.") 
            raise
        except Exception as e:
            logger.exception("Error processing message.")
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, 
                chat_id=msg.chat_id,
                content=f"Sorry, I encountered an error: {e}."
            ))

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        session_key = msg.session_key
        session = self.session_manager.get_or_create(session_key)
        
        ## For system command.
        raw = msg.content.strip().lower()
        cxt = CommandContext(msg=msg, session=session, key=session_key, raw=raw, loop=self)
        if result := await self.commands.dispatch(ctx=cxt):
            return result

        history = session.get_history(100)
        initial_messages = self.context.build_messages(msg=msg, history=history)

        async def _bus_process(content: str, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
                metadata=meta
            ))
            
        final_content, messages = await self._run_agent_loop(initial_messages, _bus_process)
        self._save_session_messages(session, messages, 1 + len(history))
        self.session_manager.save(session)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=final_content or "Agent loop task completed.")


    async def _run_agent_loop(
        self, 
        initial_messages: list[dict],
        on_process: Callable[..., Awaitable[None]] | None = None,
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
                if on_process:
                    await on_process(self._tool_hint(response.tool_calls), tool_hint=True)

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
                clean = self._strip_think(response.content)
                if response.finish_reason == "error":
                    logger.error("LLM return error: {}", clean)
                    final_content = "Sorry, I encountered an error calling the AI model."
                    break
                messages = self._add_assistant_message(
                    messages=messages, content=clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = response.content
                break
        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iteration ({}) reached.", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try break the task into smaller steps."
            )

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


    def _tool_hint(self, tool_calls: list) ->str:
        """Print out hint tool."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f"{tc.name}(\"{val[:40]}\")" if len(val) > 40  else f"{tc.name}(\"{val}\")"
        return ", ".join(_fmt(tc) for tc in tool_calls)

    def _strip_think(self, text: str | None) -> str | None:
        """Remove <think>...</think> blocks."""
        if not text:
            return None
        return strip_think(text) or None
