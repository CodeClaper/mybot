import aiohttp
import discord
from discord import app_commands
from discord.abc import Messageable
from loguru import logger

from mybot.bus.queue import MessageBus
from mybot.config.schema import Config, DiscordConfig
from mybot.channels.base import BaseChannel
from mybot.channels.discord_bot import DiscordBotClient


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py"""

    name = "discord"
    display_name = "Discord"
    
    def __init__(self, config: Config, bus: MessageBus) -> None:
        super().__init__(config, bus)
        self._config: DiscordConfig = config.channels.discord
        self._client: DiscordBotClient | None = None
        self._bot_user_id: str | None = None


    async def start(self) -> None:
        """Start discord client."""
        if not self._config.enabled:
            logger.error("Discord channel config is disabled.")
            return

        if not self._config.token:
            logger.error("Discord bot token not configured.")
            return

        try:
            intents = discord.Intents.none()
            intents.value = self._config.intents
            self._client = DiscordBotClient(self, intents=intents)
        except Exception as e:
            logger.error("Fail to initialize Discord client: {}", e)
            self._client = None
            self._running = False
            return

        self._running = True
        logger.info( "Start Discord client via discord.py...")

        try:
            await self._client.start(self._config.token)
        except Exception as e:
            logger.error("Discord client setup fialed: {}", e)

        finally:
            self._running = False
            await self._reset_runtime_state(close_client=True)


    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""

