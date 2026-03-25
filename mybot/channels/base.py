
from abc import ABC, abstractmethod
from typing import Any

from mybot.bus.message import InboundMessage, OutboundMessage
from mybot.bus.queue import MessageBus


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.

    Each channel(Telegram, Discord, etc,) should implement this interface
    to integrate with the message bus.
    """

    name: str = "base"
    display_name = "Base"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        """
        Initialize the channel.

        Args:
            config: Channel-special configuration.
            bus: The message bus for communication.
        """ 
        self._config = config
        self._bus = bus
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listenning for message.

        This should be a long-running async task:
        1. Connect to the chat platform.
        2. Listens for incomming message.
        3. Forwards message to the bus via _handle_message()
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.

        Args:
            msg: The message to send.
        """
        pass

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None
    ) -> None:
        """
        Handle an incoming message from the chat platform.

        Args:
            sender_id: The sender's identifier
            chat_id: The chat/chanel identifier
            content: Message text content
            media: Optional list of media URLs
            metadata: Optional Channel-special metadata
            session_key: Optional session key
        """
        meta = metadata or {}
        msg = InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=meta,
            session_key_override=session_key
        )

        await self._bus.publish_inbound(msg)

    def is_running(self) -> bool:
        return self._running
