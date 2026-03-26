
import asyncio
from loguru import logger
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel
from mybot.channels.registry import discover_all
from mybot.config.schema import Config

class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Reponsiblities:
    - Initailize enabled channels.
    - Start/Stop channels
    - Route outbound messages.
    """

    def __init__(self, config: Config, bus: MessageBus):
       self.config = config
       self.bus = bus
       self.channels: dict[str, BaseChannel] = {}
       self._init_channels()
    
    def _init_channels(self) -> None:

        for name, cls in discover_all().items():
            cfg = getattr(self.config.channels, name, None)
            if cfg is None:
                continue

            enabled = cfg.get("enabled", False) if isinstance(cfg, dict) else getattr(cfg, "enabled", False)
            if not enabled:
                continue

            try:
                channel = cls(self.config, self.bus)
                self.channels[name] = channel
                logger.info("{} channel enabled", cls.display_name)
            except Exception as e:
                logger.warning("{} channel not available", name, e)


    async def start_all(self) -> None:
        """Start all available channels out the outbound dispatcher."""

        if not self.channels:
            logger.warning("Not any channel available.")
            return

        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))
    
        ## Wait for all to complete.,
        await asyncio.gather(*tasks, return_exceptions=True)


    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped {} channel", name)
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)

    

    async def _start_channel(self, name, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)

