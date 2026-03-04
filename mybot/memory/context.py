
from pathlib import Path
from typing import Any
from mybot import __logo__
from mybot.bus.message import InboundMessage 

class ContextBuilder:

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
    
    def build_system_promp(self) -> str:
        return f"""# mybot {__logo__}
    You are mybot, a personal AI assistant.
    """

    def build_messages(self, msg: InboundMessage, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build messages."""
        return [
            {"role": "system", "content": self.build_system_promp()},
            *history,
            {"role": "user", "content": msg.content},
        ]


