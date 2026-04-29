from typing import Any
import discord
from discord import app_commands
from discord.abc import Messageable
from mybot.bus.message import OutboundMessage
from mybot.channels.discord import DiscordChannel
from loguru import logger
from pathlib import Path
from mybot.commands.builtin import build_help_text
from mybot.utils.helper import split_message

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit

class DiscordBotClient(discord.Client):
    """discord.py client that forwards events to the channle."""

    def __init__(self, channel: DiscordChannel, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._channel = channel
        self.tree = discord.app_commands.CommandTree(self)
        self._register_app_commands()

    async def on_ready(self) -> None:
        self._channel._bot_user_id = str(self.user.id) if self.user.id else None
        logger.info("Discord bot connected as user {}", self._channel._bot_user_id)

    async def on_message(self, message: discord.Message) -> None:
        await self._channel.handle_discord_message(message)

    async def send_outbound(self, msg: OutboundMessage) -> None:
        """Send a outbund message using Discord channel."""
        channel_id = int(msg.chat_id)
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except Exception as e:
                logger.error("Discord channel {} unavaliable: {}", msg.chat_id, e)
                return

        reference, mention_setting = self._build_reply_context(channel, msg.reply_to)
        send_media = False
        failed_media: list[str] = []
        
        for index, media_path in enumerate(msg.media or []):
            if await self._send_file(
                    channel, 
                    media_path, 
                    reference=reference if index == 0 else None, 
                    mention_setting=mention_setting
            ):
                send_media = True
            else:
                failed_media.append(Path(media_path).name)
        
        for index, chunk in enumerate(
            self._build_chunks(msg.content or "", failed_media, send_media)
        ):
            kwargs: dict[str, Any] = {"content": chunk}
            if index == 0 and reference is not None and not send_media:
                kwargs["reference"] = reference
                kwargs["allowed_mentions"] = mention_setting
            await channel.send(**kwargs)

    
    async def _send_file(
        self, 
        channel: Messageable, 
        file_path: str, 
        reference: discord.PartialMessage | None,
        mention_setting: discord.AllowedMentions
    ) -> bool:
        """Send a file attachment via discord.py."""    
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
            return False

        try:
            kwargs: dict[str, Any] = {"file": discord.File(path)}
            if reference is not None:
                kwargs["reference"] = reference
                kwargs["allowed_mentions"] = mention_setting
            await channel.send(**kwargs)
            logger.info("Discord file send: {}", path.name)
            return True
        except Exception as e:
            logger.error("Error sending Discord file {}: {}", path.name, e)
            return False

    async def _reply_ephemeral(self, interation: discord.Interaction, text: str) -> bool:
        try:
            await interation.response.send_message(text, ephemeral=True)
            return True
        except Exception as e:
            logger.warning("Discord interation response failed: {}", e)
            return False
 
    async def _forward_slash_command(self, interaction: discord.Interaction, command_text: str) -> None:
        sender_id = str(interaction.user.id)
        channel_id = interaction.channel_id

        if channel_id is None:
            logger.warning("Discord slash command missing channel_id: {}", command_text)
        
        await self._reply_ephemeral(interaction, f"Processing {command_text}...")
        await self._channel._handle_message(
            sender_id=sender_id,
            chat_id=str(channel_id),
            content=command_text,
            metadata={
                "interaction_id": str(interaction.id),
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "is_slash_command": True
            }
        )


    def _register_app_commands(self) -> None:
        commands = (
            ("new", "Start a new session", "/new"),
            ("stop", "Stop the current task", "/stop"),
            ("restart", "Restart the bot", "/restart"),
            ("status", "Show bot status", "/status"),
        )

        for name, description, command_text in commands:
            @self.tree.command(name=name, description=description)
            async def command_handler(
                interaction: discord.Interaction,
                _command_text: str = command_text,
            ) -> None:
                await self._forward_slash_command(interaction, _command_text)

        @self.tree.command(name="help", description="Show available commands")
        async def help_command(interaction: discord.Interaction) -> None:
            sender_id = str(interaction.user.id)
            await self._reply_ephemeral(interaction, build_help_text())

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            command_name = interaction.command.qualified_name if interaction.command else "?"
            logger.warning(
                "Discord app command failed user={} channel={} cmd={} error={}",
                interaction.user.id,
                interaction.channel_id,
                command_name,
                error,
            )
    
    @staticmethod
    def _build_reply_context(channel: Messageable, reply_to: str | None) -> tuple[discord.PartialMessage | None, discord.AllowedMentions]:
        """Build reply context for outbund message."""
        mention_setting = discord.AllowedMentions(replied_user=False)
        if not reply_to:
            return None, mention_setting
        try:
            message_id = int(reply_to)
        except ValueError:
            logger.warning("Invalid Discord reply target: {}", reply_to)
            return None, mention_setting
        
        return channel.get_partial_message(message_id), mention_setting

    @staticmethod
    def _build_chunks(context: str, failed_media: list[str], send_media: bool) -> list[str]:
        """Build outbound text chunks, including attachment-failure fallback text."""
        chunks = split_message(context, MAX_MESSAGE_LEN)
        if chunks or not failed_media or send_media:
            return chunks
        fallbacks = "\n".join(f"[attachment: {name} - send failed]" for name in failed_media)
        return split_message(fallbacks, MAX_MESSAGE_LEN)
