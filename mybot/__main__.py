import asyncio

from mybot.agent.loop import AgentLoop
from mybot.providers.default_provider import DefaultProvider

if __name__ == "__main__":
    agent = AgentLoop(DefaultProvider())
    asyncio.run(agent.run("hello world"))
