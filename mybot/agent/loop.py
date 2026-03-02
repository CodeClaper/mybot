from mybot.providers.base import BaseProvider
from mybot.tools.math import MathTool
from mybot.tools.registry import TooRegistry

class AgentLoop:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider
        self.tool_registry = TooRegistry()


    def _register_defaul_tools(self) -> None:
        self.tool_registry.register(MathTool())

    async def run(self, user_message):
        iteration = 0
        while iteration < 10:
            iteration += 1
            
            response = await self.provider.chat(
                user_message=user_message,
                tools=self.tool_registry.get_definations(),
            )

            print(response)
            if response.has_error:
                print(f"LLM error:{response.content}")
                break
            elif response.has_tool_calls:
                pass
            else:
                print(response.content)
                break
            

