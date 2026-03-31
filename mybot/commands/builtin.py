
from mybot.bus.message import OutboundMessage
from mybot.commands.router import CommandContext


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a new session"""
    loop = ctx.loop
    msg = ctx.msg
    session = ctx.session or loop.session_manager.get_or_create(ctx.key)
    session.clear()
    loop.session_manager.archive(session)
    loop.session_manager.invalidate(session.key)
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="New session started")
