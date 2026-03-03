import os
import typer
import signal
import asyncio
import uuid

from pathlib import Path
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout

from mybot import __logo__, __version__
from mybot.agent.loop import AgentLoop
from mybot.cli.bus.message import InboundMessage
from mybot.cli.bus.queue import MessageBus
from mybot.providers.default_provider import DefaultProvider

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

app = typer.Typer(name="mybot", help=f"mybot - Personal AI Assistant.", no_args_is_help=True)
console = Console()

_PROMPT_SESSION: PromptSession | None = None

def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} mybot {__version__}")
        raise typer.Exit()

@app.callback()
def main(version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True)):
    pass

@app.command()
def agent():
    chat_id = str(uuid.uuid4())
    bus = MessageBus()
    agent = AgentLoop(provider= DefaultProvider(), bus=bus)
    console.print(f"Welocom to {__logo__} mybot agent. (type [bold]/exit[/bold]) or [bold]Ctrl+C[/bold] to quite")
    _init_prompt_session()

    def _thinking_mode():
        return console.status(f"[dim]{__logo__} mybot is thinking...[/dim]", spinner="dots")
    
    def _exist_on_sigint(signum, frame):
        console.print("\nGoodbye!")
        os._exit(0)


    signal.signal(signal.SIGINT, _exist_on_sigint)

    async def run_interactive():
        loop_task = asyncio.create_task(agent.run())
        turn_done = asyncio.Event()
        turn_done.set()
        turn_response: list[str] = []

        async def _consume_outbound():
            while True:
                try:
                    msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                    if not turn_done.is_set():
                        if msg.content:
                            turn_response.append(msg.content)
                        turn_done.set()
                    elif msg.content:
                        console.print()
                        print(turn_response[0])
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        outbound_task = asyncio.create_task(_consume_outbound())

        try:
            while True:
                try:
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()
                    if not command: 
                        continue
                    if _is_exit_command(command):
                        console.print("\nGoodbye!")
                        break
                    turn_done.clear()
                    await bus.publish_inbound(InboundMessage(
                        channel="cli",
                        sender_id="user",
                        chat_id = chat_id,
                        content=user_input
                    ))
                    with _thinking_mode():
                        await turn_done.wait()

                    if turn_response:
                        print(turn_response[0])
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
                except EOFError:
                    console.print("\nGoodbye!")
                    break
        finally:
            outbound_task.cancel()
            loop_task.cancel()
    
    asyncio.run(run_interactive())


def _init_prompt_session() -> None:
    global _PROMPT_SESSION
    history_file = Path.home() / ".mybot" / "history" / "cli_history"
    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        enable_open_in_editor=False,
        multiline=False
    )

async def _read_interactive_input_async() -> str:
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")
    try:
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You: </b>"),
            )
    except EOFError as e:
        raise KeyboardInterrupt from e

def _is_exit_command(command: str) -> bool:
    return command.lower() in ["/exit", "/quite", ":q"]

