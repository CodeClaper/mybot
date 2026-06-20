
from typing import Any
from contextvars import ContextVar
from mybot.agent.subagent import SubagentManager, MAX_CONCURRENT_SUBAGENTS
from mybot.tools.base import Tool

class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager
        self._origin_channel: ContextVar[str] = ContextVar("spawn_origin_channel", default="cli")
        self._origin_chat_id: ContextVar[str] = ContextVar("spawn_origin_chat_id", default="direct")
        self._session_key: ContextVar[str] = ContextVar("spawn_session_key", default="cli:direct")

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The task for the subagent to complete"},
                "label": {"type": "string", "description": "Optional short label for the task (for display)"},
                "tool_profile": {
                    "type": "string",
                    "enum": ["general", "code", "research"],
                    "description": "Tool profile for the subagent: 'general' (all tools), 'code' (shell + file read/write - for development tasks), 'research' (web search/fetch + file read - for information gathering). Default: 'general'."
                },
            },
            "required": ["task"]
        }

    async def execute(self, task: str, label: str | None = None, tool_profile: str = "general", **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        running = self._manager.get_running_count()
        limit = MAX_CONCURRENT_SUBAGENTS 
        if running >= limit:
            return (
                f"Cannot spawn subagent: concurrency limit reached "
                f"({running}/{limit} running). Wait for a running subagent "
                f"to complete before spawning a new one."
            )
        return await self._manager.spawn(
            task=task,
            label=label,
            tool_profile=tool_profile,
            origin_channel=self._origin_channel.get(),
            origin_chat_id=self._origin_chat_id.get(),
            session_key=self._session_key.get()
        )
