from mybot.providers.base import BaseProvider

class AgentLoop:
    def __init__(self, provider: BaseProvider) -> None:
        self.provider = provider

    async def run(self, user_message):
        iteration = 0
        while iteration < 10:
            iteration += 1
            response = await self.provider.chat(user_message=user_message)
            print(response)
            if response.has_error:
                print(f"LLM error:{response.content}")
                break
            elif response.has_tool_calls:
                pass
            else:
                print(response.content)
                break
            

