from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from mybot.bus.message import InboundMessage, OutboundMessage
from mybot.context.session import Session

@dataclass()
class CommandContext:
    """Everything a command handler needs to produce a response."""

    msg: InboundMessage
    session: Session | None
    key: str
    raw: str
    args: str = ""
    loop: Any = None

Handler = Callable[[CommandContext], Awaitable[OutboundMessage | None]]


class CommandRouter:
    """
    Dict-based command dispatcher.

    Three tiers checked in order:
      1. *priority* — exact-match commands handled before the dispatch lock
         (e.g. /stop, /restart).
      2. *exact* — exact-match commands handled inside the dispatch lock.
      3. *prefix* — longest-prefix-first match (e.g. "/team ").
      4. *interceptors* — fallback predicates (e.g. team-mode active check).
    """


    def __init__(self) -> None:
        self._priority: dict[str, Handler] = {}
        self._exact: dict[str, Handler] = {}
        self._prefix: list[tuple[str, Handler]] = []
        self._interceptors: list[Handler] = []


    def priority(self, cmd: str, handler: Handler) -> None:
        self._priority[cmd] = handler


    def exact(self, cmd: str, handler: Handler) -> None:
        self._exact[cmd] = handler
