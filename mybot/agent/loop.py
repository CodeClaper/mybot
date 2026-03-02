from mybot.providers.base import BaseProvider, LLMResponse
from mybot.tools.math import MathTool
from mybot.tools.registry import TooRegistry

class AgentLoop:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider
        self.tool_registry = TooRegistry()
        self._register_defaul_tools()


    def _register_defaul_tools(self) -> None:
        self.tool_registry.register(MathTool())

    async def run(self, user_message) -> None:
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
                await self._execute_tool(response)
            else:
                print(response.content)
                break
    
    async def _execute_tool(self, response: LLMResponse) -> None:
        for tool_call in response.tool_calls:
            result = await self.tool_registry.execute(tool_call.name, tool_call.arguments)
            print(result)
        pass

