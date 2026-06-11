from dataclasses import dataclass
from mybot import __logo__, __title__
from mybot.bus.message import OutboundMessage
from mybot.commands.router import CommandContext, CommandRouter

@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/new",
        "New chat",
        "Stop the current task and start a fresh conversation.",
        "square-pen",
    ),
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active agent turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart mybot",
        "Restart the bot process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/status",
        "Show status",
        "Display runtime, provider, and channel status.",
        "activity",
    ),
    BuiltinCommandSpec(
        "/model",
        "Switch model preset",
        "Show or switch the active model preset.",
        "brain",
        "[preset]",
    ),
    BuiltinCommandSpec(
        "/history",
        "Show conversation history",
        "Print the last N persisted conversation messages.",
        "history",
        "[n]",
    ),
    BuiltinCommandSpec(
        "/dream",
        "Run Dream",
        "Manually trigger memory consolidation.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/dream-log",
        "Show Dream log",
        "Show what the last Dream consolidation changed.",
        "book-open",
    ),
    BuiltinCommandSpec(
        "/dream-restore",
        "Restore memory",
        "Revert memory to a previous Dream snapshot.",
        "undo-2",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
)


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a new session"""
    loop = ctx.loop
    msg = ctx.msg
    session = ctx.session or loop.session_manager.get_or_create(ctx.key)
    loop.session_manager.archive(session)
    loop.session_manager.invalidate(session.key)
    session.clear()
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, 
        content="New session started",
    )

async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show history records of current session. """
    loop = ctx.loop
    msg = ctx.msg
    session = ctx.session or loop.session_manager.get_or_create(ctx.key)
    conversations = session.get_conversations(0)

    lines: list[str] = []
    for conv in conversations:
        if conv.get("role") == "user":
            lines.append(f"- **you**: \t{conv.get('content', '')}")
        elif conv.get("role") == "assistant":
            lines.append(f"- **{__title__}**: \t{conv.get('content', '')}")

    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, 
        content="\r\n ".join(lines)
    )

async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Show all available commands."""

    lines = [
            f"System comnmands:",
            "/new       - Start a new session.",
            "/history   - Show history records of current session.",
            "/help      - Show available commands.",
            "/status    - Show bot status."
    ]
    
    msg = ctx.msg
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, 
        content="\n".join(lines),
        metadata={"render_as": "text"}
    )

def register_builtin_commands(router: CommandRouter) -> None:
    """Register builtin commands into router."""

    router.exact("/new", cmd_new)
    router.exact("/history", cmd_history)
    router.exact("/help", cmd_help)


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = [
        f"{__logo__} {__title__} commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/help — Show available commands",
    ]
    return "\n".join(lines)

