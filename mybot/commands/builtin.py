import json
from mybot.bus.message import OutboundMessage
from mybot.commands.router import CommandContext, CommandRouter
from mybot import __logo__

async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a new session"""
    loop = ctx.loop
    msg = ctx.msg
    session = ctx.session or loop.session_manager.get_or_create(ctx.key)
    session.clear()
    loop.session_manager.archive(session)
    loop.session_manager.invalidate(session.key)
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, 
        content="New session started",
    )

async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show history records of current session. """
    loop = ctx.loop
    msg = ctx.msg
    session = ctx.session or loop.session_manager.get_or_create(ctx.key)
    history = session.get_history(100)
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, 
        content=json.dumps(history, ensure_ascii=False, indent=4)
    )

async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Show all available commands."""

    lines = [
            f"{__logo__} mybot comnmands:",
            "/new       - Start a new session.",
            "/history   - Show history records of current session."
            "/help      - Show available commands."
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
