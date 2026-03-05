import asyncio
import os
import re

from typing import Any
from mybot.tools.base import Tool

class ShellTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        path_append: str = ""
    ) -> None:
        self.timeout = timeout
        self.working_dir = working_dir
        self.path_append = path_append
        self.deny_patterns = [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]


    @property
    def name(self) -> str:
        return "exec"


    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."


    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute."
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working director for the command."
                }
            },
            "required": ["command"]
        }

    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                cmd=command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                # Wait for the process to fully terminate so pipes are
                # drained and file descriptors are released.
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"

            outputs = []
            
            if stdout:
                outputs.append(stdout.decode(encoding="utf-8", errors="replace"))
            
            if stderr:
                stderr_txt = stderr.decode(encoding="utf-8", errors="replace")
                if stderr_txt.strip():
                    outputs.append(f"STDERR:\n{stderr_txt}")

            result = "\n".join(outputs) if outputs else "(no ouput)"
            
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n...(truncated, {len(result) - max_len} more character."

            return result

        except Exception as e:
            return f"Error executing command {command}: {str(e)}"



    def _guard_command(self, command: str, cwd: str) -> str | None:
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return f"Error: Command block by safety guard (dangerous command: {command})"

        return None

