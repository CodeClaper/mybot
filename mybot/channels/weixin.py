
from typing import Any
from mybot.bus.queue import MessageBus
from mybot.channels.base import BaseChannel

class WeixinChannel(BaseChannel):

    name="weixin"
    display_name = "WeChat"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        super().__init__(config, bus)
