import asyncio
import aiohttp
import discord

from typing import Any
from discord import app_commands
from discord.abc import Messageable
from loguru import logger
from pathlib import Path
from mybot.commands.builtin import build_help_text
from mybot.bus.message import OutboundMessage
from mybot.bus.queue import MessageBus
from mybot.config.path import get_media_dir
from mybot.config.schema import Config, DiscordConfig
from mybot.channels.base import BaseChannel
from mybot.utils.helper import safe_filename, split_message

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit


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
        self._known_channels: dict[str, Any] = {}
    
    async def login(self, force: bool = False) -> bool:
        logger.error("Not support direct login for discord channel.")
        return False

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
            proxy_auth = None
            has_user = bool(self._config.proxy_username)
            has_pass = bool(self._config.proxy_password)
            if has_user and has_pass:
                proxy_auth = aiohttp.BasicAuth(
                    login=self._config.proxy_username, 
                    password=self._config.proxy_password
                )
            elif has_user != has_pass:
                logger.warning(
                    "Discord proxy auth incomplete: both proxy_username and "
                    "proxy_password must be set; ignoring partial credentials",
                )

            self._client = DiscordBotClient(
                self, 
                intents=intents,
                proxy=self._config.proxy,
                proxy_auth=proxy_auth
            )
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
        if self._bot_user_id is not None and str(message.author.id) == self._bot_user_id:
            return
        if self._is_system_message(message):
            return

        sender_id = str(message.author.id)
        channel_id = self._channel_key(message.channel)
        self._remember_channel(message.channel)
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
        content_parts = [content] if content else []
        content_parts.extend(attachment_markers)
        return "\n".join(part for part in content_parts if part) or "[empty message]"
    
    @staticmethod
    def _is_system_message(message: discord.Message) -> bool:
        """Return True for Discord system messages that carry no user prompt."""
        message_type = getattr(message, "type", discord.MessageType.default)
        return message_type not in {discord.MessageType.default, discord.MessageType.reply}

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


    def _remember_channel(self, channel: Any) -> None:
        self._known_channels[self._channel_key(channel)] = channel

    def _forget_channel(self, channel_or_id: Any) -> None:
        self._known_channels.pop(self._channel_key(channel_or_id), None)

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


###################################################################################
#####                     DiscordBotClient                                   ######
###################################################################################
class DiscordBotClient(discord.Client):
    """discord.py client that forwards events to the channle."""

    def __init__(
        self, 
        channel: DiscordChannel, 
        intents: discord.Intents,
        proxy: str | None = None,
        proxy_auth: aiohttp.BasicAuth | None = None
    ) -> None:
        super().__init__(intents=intents, proxy=proxy, proxy_auth=proxy_auth)
        self._channel = channel
        self.tree = discord.app_commands.CommandTree(self)
        self._register_app_commands()

    async def on_ready(self) -> None:
        self._channel._bot_user_id = str(self.user.id) if self.user.id else None
        logger.info("Discord bot connected as user {}", self._channel._bot_user_id)
        try:
            synced = await self.tree.sync()
            logger.info("Discord app commands synced: {}", len(synced))
        except Exception as e:
            logger.warning("Discord app command sync failed: {}", e)

    async def on_message(self, message: discord.Message) -> None:
        await self._channel.handle_discord_message(message)

    async def on_thread_delete(self, thread: discord.Thread) -> None:
        self._channel._forget_channel(thread)

    async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
        if getattr(after, "archived", False):
            self._channel._forget_channel(after)
        else:
            self._channel._remember_channel(after)

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

        if not self._channel.is_allowed(sender_id):
            await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
            return
        
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
