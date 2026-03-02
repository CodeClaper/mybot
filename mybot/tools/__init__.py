from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    Abstract base class for agent tools.

    Tools are capabilities that the agent can use to interact with 
    the environment, such as reading files.
    """
    def __init__(self) -> None:
        super().__init__()

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls. """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of wht the tool does. """
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        pass


    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        pass
