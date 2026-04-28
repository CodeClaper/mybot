from mybot import __logo__, __name__
from mybot.bus.message import OutboundMessage
from mybot.commands.router import CommandContext, CommandRouter


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
            lines.append(f"- **{__name__}**: \t{conv.get('content', '')}")

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
        f"{__logo__} {__name__} commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/help — Show available commands",
    ]
    return "\n".join(lines)

