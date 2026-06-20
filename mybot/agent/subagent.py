
from pathlib import Path
from mybot.bus.queue import MessageBus
from mybot.providers.base import BaseProvider


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: BaseProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        max_iterations: int | None = None,
    ):
        self._provider = provider
        self._workspace = workspace
        self._bus = bus
        self._model = model 


    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background. """

