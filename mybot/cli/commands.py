import typer
from rich.console import Console
from mybot import __logo__, __version__

app = typer.Typer(name="mybot", help=f"mybot - Personal AI Assistant.", no_args_is_help=True)
console = Console()

def version_callback(value: bool):
    if value:
        console.print(f"{__logo__} mybot {__version__}")
        raise typer.Exit()

@app.callback()
def main(version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True)):
    pass
