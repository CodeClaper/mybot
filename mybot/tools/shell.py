import asyncio
from pathlib import Path
import sys
import os
import re
import shutil

from typing import Any

from contextlib import suppress
from loguru import logger
from mybot.tools.base import Tool
from mybot.tools.sandbox import wrap_command

_IS_WINDOWS = sys.platform == "win32"

class ShellTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        path_append: str = "",
        sandbox: str = ""
    ) -> None:
        self.timeout = timeout
        self.working_dir = working_dir
        self.path_append = path_append
        self.sandbox = sandbox
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

        if self.sandbox:
            if _IS_WINDOWS:
                logger.warning(
                    "Sandbox '{}' is not supported on Windows; running unsandboxed",
                    self.sandbox,
                )
            else:
                workspace = self.working_dir or cwd
                command = wrap_command(self.sandbox, command, workspace, cwd)
                cwd = str(Path(workspace).resolve())

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await self._spawn(command, cwd, env)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return f"Error: Command timed out after {self.timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise

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
                half = max_len // 2
                omitted = len(result) - max_len
                result = result[:half] + f"\n...(truncated, {omitted} characters omitted)...\n" + result[-half:]

            return result

        except Exception as e:
            return f"Error executing command {command}: {str(e)}"
    
    
    @staticmethod
    async def _spawn(
        command: str, cwd: str, env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Launch *command* in a platform-appropriate shell."""
        if _IS_WINDOWS:
            # create_subprocess_exec re-quotes args via list2cmdline, which
            # breaks commands containing paths with spaces (e.g. "D:\Program
            # Files\python.exe" "script.py"). create_subprocess_shell passes
            # the raw command string to COMSPEC without re-quoting.
            return await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash, "-l", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Kill a subprocess and reap it to prevent zombies."""
        process.kill()
        try:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5.0)
        finally:
            if not _IS_WINDOWS:
                try:
                    os.waitpid(process.pid, os.WNOHANG)
                except (ProcessLookupError, ChildProcessError) as e:
                    logger.debug("Process already reaped or not found: {}", e)

    def _guard_command(self, command: str, cwd: str) -> str | None:
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return f"Error: Command block by safety guard (dangerous command: {command})"

        return None

