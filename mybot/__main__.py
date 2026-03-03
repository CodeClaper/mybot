import asyncio

from mybot.agent.loop import AgentLoop
from mybot.providers.default_provider import DefaultProvider

if __name__ == "__main__":
    agent = AgentLoop(DefaultProvider())
    asyncio.run(agent.run(
        [
            {"role": "system", "content": "Your are a help assistant."},
            {"role": "user", "content": "Please help me calculate (1 + 3) * 5"}
        ]
    ))
