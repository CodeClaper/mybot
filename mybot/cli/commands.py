import os
import sys
import typer
import signal
import asyncio
import uuid

from pathlib import Path
from rich.text import Text
from rich.console import Console
from rich.markdown import Markdown
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout

from mybot import __logo__, __version__
from mybot.agent.loop import AgentLoop
from mybot.bus.message import InboundMessage
from mybot.bus.queue import MessageBus
from mybot.config.loader import get_config_path, get_history_path, get_worksapce_path, load_config, save_config
from mybot.config.question import question_config
from mybot.config.schema import Config
from mybot.memory.session import SessionManager
from mybot.providers.base import BaseProvider
from mybot.providers.default_provider import DefaultProvider

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
def onboard():
    config_path = get_config_path()
    workspace_path = get_worksapce_path()
    history_path = get_history_path()
    config = Config()

    if config_path.exists():
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = overwrite with defaults (existing values will be lost)")
        console.print("  [bold]N[/bold] = keep old config, and adding new fields")
        if not typer.confirm("Overwrite?"):
            console.print(f"Config keeps values preseved.")
            sys.exit(0)

    if not workspace_path.exists():
        workspace_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created worksapce at {workspace_path}")

    if not history_path.exists():
        history_path.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created history at {history_path}")

    ## question_config(config)
    save_config(config)
    console.print(f"[green]✓[/green] Created config at {config_path}")

    console.print(f"\n{__logo__} mybot is ready!")

@app.command()
def agent():
    chat_id = str(uuid.uuid4())
    bus = MessageBus()
    config = load_config()
    agent = AgentLoop(
        provider= _make_provider(config), 
        workspace=_workspace_path(),
        bus=bus,
        session_manager=SessionManager(_workspace_path()),
        config=config
    )
    console.print(f"Welocom to {__logo__} mybot agent. (type [bold]/exit[/bold]) or [bold]Ctrl+C[/bold] to quite")
    _init_prompt_session()

    def _thinking_mode():
        return console.status(f"[dim]{__logo__} mybot is thinking...[/dim]", spinner="moon")
    
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
                    if msg.metadata.get("_progress"):
                        is_tool_hint = msg.metadata.get("_tool_hint", False)
                        if is_tool_hint:
                            console.print(f"  [dim]↳ {msg.content}[/dim]")
                        pass
                    elif not turn_done.is_set():
                        if msg.content:
                            turn_response.append(msg.content)
                        turn_done.set()
                    elif msg.content:
                        console.print()
                        _print_agent_response(turn_response[0], render_markdown=True)
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
                    turn_response.clear()
                    await bus.publish_inbound(InboundMessage(
                        channel="cli",
                        sender_id="user",
                        chat_id = chat_id,
                        content=user_input
                    ))

                    with _thinking_mode():
                        await turn_done.wait()

                    if turn_response:
                        _print_agent_response(turn_response[0], render_markdown=True)
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

def _workspace_path() -> Path:
    return Path("~/.mybot").expanduser()

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


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """Render assistant response with consistent terminal styling. """
    content = response or ''
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__} mybot[/cyan]")
    console.print(body)
    console.print()


def _make_provider(config: Config) -> BaseProvider:
    """Create the appropriate LLM provider by config. """
    
    model = config.agents.defaults.model
    provider = config.get_provider(model)
    return DefaultProvider(
        default_model=model,
        api_key=provider.api_key if provider else None,
        api_base=provider.api_base if provider else None
    )
