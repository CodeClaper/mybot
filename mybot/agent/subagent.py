import json
from typing import Any
import uuid
import asyncio
import time
from pathlib import Path
from dataclasses import dataclass, field

from loguru import logger
from mybot.agent.skill import BUILTIN_SKILL_DIR
from mybot.bus.message import InboundMessage
from mybot.bus.queue import MessageBus
from mybot.config.path import get_worksapce_path
from mybot.config.schema import Config
from mybot.providers.base import BaseProvider
from mybot.tools.fielstate import FileStates
from mybot.tools.filesystem import ReadFileTool, WriteFileTool
from mybot.tools.message import MessageTool
from mybot.tools.registry import ToolRegistry
from mybot.tools.shell import ShellTool
from mybot.tools.web import WebFetchTool, WebSearchTool 

MAX_CONCURRENT_SUBAGENTS = 2

TOOL_PROFILES = {
    "general":  ["shell", "web_search", "web_fetch", "message", "read_file", "write_file"],
    "code":     ["shell", "read_file", "write_file"],
    "research": ["web_search", "web_fetch", "read_file"],
}

class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: BaseProvider,
        workspace: Path,
        bus: MessageBus,
        config: Config,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_iterations: int = 20
    ):
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.config = config
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations
        self.running_tasks: dict[str, asyncio.Task[None]] = {}
        self.session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        tool_profile: str = "general",
    ) -> str:
        """Spawn a subagent to execute a task in the background. """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if (len(task) > 30) else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id, "session_key": session_key}
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, tool_profile)
        )
        self.running_tasks[task_id] = bg_task
        if session_key:
            self.session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self.running_tasks.pop(task_id, None)
            if session_key and (ids := self.session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self.session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)
        
        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        tool_profile: str = "general",
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        try:
            tools = ToolRegistry()
            self._register_tools(tools, profile=tool_profile)
            system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Run agent loop (limited iterations)
            iteration = 0
            final_result: str | None = None
            
            while iteration < self.max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definations(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break
            
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    def _register_tools(self, tools, profile: str = "general") -> None:
        """Register tools based on tool profile."""
        if profile not in TOOL_PROFILES:
            logger.warning("Unknown tool profile '{}', falling back to 'general'", profile)
            profile = "general"

        web_config = self.config.tools.web
        workspace = get_worksapce_path()
        extra_allowed_dir = [BUILTIN_SKILL_DIR] if BUILTIN_SKILL_DIR.exists() else None
        file_states = FileStates()
        skills_dir = workspace / "skills"

        tool_factories = {
            "shell": lambda: ShellTool(),
            "web_search": lambda: WebSearchTool(proxy=web_config.proxy, api_key=web_config.search.api_key),
            "web_fetch": lambda: WebFetchTool(proxy=web_config.proxy),
            "message": lambda: MessageTool(send_callback=self.bus.publish_outbound),
            "read_file": lambda: ReadFileTool(workspace=workspace, allowed_dir=workspace, extra_allowed_dirs=extra_allowed_dir, file_states=file_states),
            "write_file": lambda: WriteFileTool(workspace=workspace, allowed_dir=skills_dir, file_states=file_states),
        }

        for tool_name in TOOL_PROFILES[profile]:
            factory = tool_factories.get(tool_name)
            if factory:
                tools.register(factory())
            else:
                logger.warning("Unknown tool '{}' in profile '{}'", tool_name, profile)


    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self.running_tasks)


    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"
        
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from mybot.context.context import ContextBuilder
        from mybot.agent.skill import SkillLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]

        skills_summary = SkillLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}")

        return "\n\n".join(parts)
