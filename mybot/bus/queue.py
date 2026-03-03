import asyncio

from mybot.bus.message import InboundMessage, OutboundMessage

class MessageBus:
    """
    Async message bus that decouples chat channels from the agent.
    """
    def __init__(self) -> None:
        self.inboud: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outboud: asyncio.Queue[OutboundMessage] = asyncio.Queue()


    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a meesage from a channle to the agent."""
        await self.inboud.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inboud message(block if queue is empty)."""
        return await self.inboud.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from a agent to the channels."""
        await self.outboud.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outboud message(block if queue is empty)."""
        return await self.outboud.get()
