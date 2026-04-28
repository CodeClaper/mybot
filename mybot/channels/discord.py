import aiohttp
import discord
from discord import app_commands
from discord.abc import Messageable

from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.config.schema import Config

class DiscordBotClient(discord.Client):

    def __init__(self) -> None:
        super().__init__()

class DiscordChannel(BaseChannel):
    
    def __init__(self, config: Config, bus: MessageBus) -> None:
        super().__init__(config, bus)

