import os
import typer
import signal
import asyncio

from pathlib import Path
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout

from mybot import __logo__, __version__
from mybot.agent.loop import AgentLoop
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
    agent = AgentLoop(DefaultProvider())
    console.print(f"Welocom to {__logo__} mybot agent. (type [bold]/exit[/bold]) or [bold]Ctrl+C[/bold] to quite")
    _init_prompt_session()

    def _thinking_mode():
        return console.status(f"[dim]{__logo__} mybot is thinking...[/dim]", spinner="dots")
    
    def _exist_on_sigint(signum, frame):
        console.print("\nGoodbye!")
        os._exit(0)


    signal.signal(signal.SIGINT, _exist_on_sigint)

    async def run_interactive():
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
                    with _thinking_mode():
                        pass
                    print(user_input)
                except KeyboardInterrupt:
                    console.print("\nGoodbye!")
                    break
                except EOFError:
                    console.print("\nGoodbye!")
                    break
        finally:
            pass
    
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

