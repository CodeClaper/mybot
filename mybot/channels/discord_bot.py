import discord
from discord import app_commands
from discord.ext.commands import bot
from mybot.channels.discord import DiscordChannel
from loguru import logger

from mybot.commands.builtin import build_help_text

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


