from asyncio import Task
import asyncio
from typing import Any
import discord
from loguru import logger

from mybot.bus.message import OutboundMessage
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
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_reactions: dict[str, Any] = {}  # chat_id -> message object
        self._working_emoji_tasks: dict[str, asyncio.Task[None]] = {}


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

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        await self._reset_runtime_state(close_client=True)


    async def send(self, msg: OutboundMessage) -> None:
        """Send a message."""
        if self._client is None or not self._client.is_ready():
            logger.warning("Discord client not ready, dropping outbound message.")

        is_progress = bool((msg.metadata or {}).get("_progress"))
        try:
            await self._client.send_outbound(msg)
        except Exception as e:
            logger.error("Discord send message failed: {}", e)
        finally:
            if not is_progress:
                await self._stop_typing(msg.chat_id)
                await self._clear_reactions(msg.chat_id)

    @staticmethod
    def _channel_key(channel_or_id: Any) -> str:
        channel_id = getattr(channel_or_id, "id", channel_or_id)
        return str(channel_id)

    async def _stop_typing(self, channel_id: str) -> None:
        task = self._typing_tasks.pop(self._channel_key(channel_id), None)
        if task is None: 
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_all_typing(self) -> None:
        """Stop all typing tasks."""
        channel_ids = list(self._typing_tasks)
        for channel_id in channel_ids:
            await self._stop_typing(channel_id)

    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""
        await self._cancel_all_typing()
        if close_client and self._client is not None and not self._client.is_closed():
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Discord client close failed: {}", e)
            self._client = None
            self._bot_user_id = None

    async def _clear_reactions(self, chat_id: str) -> None:
        """Remove all pending reactions adter bnot replies"""
        task = self._working_emoji_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()


