from asyncio import Task
import asyncio
from typing import Any
import discord
from discord.abc import Messageable
from loguru import logger

from mybot.bus import message
from mybot.bus.message import OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.config.path import get_media_dir
from mybot.config.schema import Config, DiscordConfig
from mybot.channels.base import BaseChannel
from mybot.channels.discord_bot import MAX_ATTACHMENT_BYTES, DiscordBotClient
from mybot.utils.helper import safe_filename


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
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready, dropping outbound message.")

        is_progress = bool((msg.metadata or {}).get("_progress"))
        try:
            await client.send_outbound(msg)
        except Exception as e:
            logger.error("Discord send message failed: {}", e)
            raise
        finally:
            if not is_progress:
                await self._stop_typing(msg.chat_id)
                await self._clear_reactions(msg.chat_id)


    async def handle_discord_message(self, message: discord.Message) -> None:
        """Handle inbound discord message from discord.py."""
        
        sender_id = str(message.author.id)
        channel_id = self._channel_key(message.channel)
        content = message.content or ""

        media_paths, attachment_marks = await self._download_attachments(message.attachments)
        full_content = self._compose_inbound_content(content, attachment_marks)
        metadata = self._build_inbound_metadata(message)
        
        await self._start_typing(message.channel)

        try:
            await message.add_reaction(self._config.read_receipt_emoji)
            self._pending_reactions[channel_id] = message
        except Exception as e:
            logger.error("Fialed to add read receipt reaction: {}", e)
        
        async def _delayed_working_emoji() -> None:
            await asyncio.sleep(self._config.working_emoji_delay)
            try:
                await message.add_reaction(self._config.working_emoji)
            except Exception:
                pass

        self._working_emoji_tasks[channel_id] = asyncio.create_task(_delayed_working_emoji())

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=full_content,
                media=media_paths,
                metadata=metadata
            )
        except Exception:
            await self._clear_reactions(channel_id)
            await self._stop_typing(channel_id)
            raise

    async def _download_attachments(
        self, 
        attachments: list[discord.Attachment]
    ) -> tuple[list[str], list[str]]:
        """Download supported attachments and return path + display marker."""
        media_paths: list[str] = []
        markers: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in attachments:
            filename = attachment.filename or "attachment"
            if attachment.size and attachment.size > MAX_ATTACHMENT_BYTES:
                markers.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                safe_name = safe_filename(filename)
                file_path = media_dir / f"{attachment.id}_{safe_name}"
                await attachment.save(file_path)
                media_paths.append(str(file_path))
                markers.append(f"[attachment: {file_path.name}]")
            except Exception as e:
                logger.warning("Fail to download Discord attachment: {}", e)
                markers.append(f"[attachment: {filename} - download failed]")

        return media_paths, markers


    @staticmethod
    def _compose_inbound_content(content: str, attachment_markers: list[str]) -> str:
        """Combine message text with attachment marker."""
        content_parts = [content] if content or []
        content_parts.extend(attachment_markers)
        return "\n".join(part for part in content_parts if part) or "[empty message]"

    @staticmethod
    def _build_inbound_metadata(message: discord.Message) -> dict[str, str | None]:
        """Build metadata for inbound Discord message."""
        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
        return {
            "message_id": str(message.id),
            "guild_id": str(message.guild.id) if message.guild else None,
            "reply_to": reply_to
        }
    
    @staticmethod
    def _channel_key(channel_or_id: Any) -> str:
        channel_id = getattr(channel_or_id, "id", channel_or_id)
        return str(channel_id)

    async def _start_typing(self, channel: Messageable) -> None:
        """Start periodic typing indicator for a channel."""
        channel_id = self._channel_key(channel)
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            while self._running:
                try:
                    async with channel.typing():
                        await asyncio.sleep(8)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.error("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

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


