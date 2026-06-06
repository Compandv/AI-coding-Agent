from __future__ import annotations

import subprocess
import sys
from typing import Any

from .base import Tool, ToolDefinition, ToolError, ToolParameter, ToolResult, ToolSchema
from .context import ToolContext


class BashTool(Tool):
    definition = ToolDefinition(
        name="Bash",
        description=(
            "Run a shell command in the current workspace when command execution is necessary, such as running tests, "
            "formatters, build commands, or project-specific scripts. Prefer Glob, Grep, ReadFile, WriteFile, and "
            "EditFile for normal file search, inspection, and editing. Use Bash after changes when a command is the "
            "right way to verify behavior."
        ),
        schema=ToolSchema(
            properties={
                "command": ToolParameter(type="string", description="Shell command to execute."),
            },
            required=["command"],
        ),
        requires_confirmation=True,
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        command = str(arguments["command"])
        if command == "python":
            command = subprocess.list2cmdline([sys.executable])
        elif command.startswith("python "):
            command = f'{subprocess.list2cmdline([sys.executable])}{command[len("python"):]}'.strip()
        try:
            completed = subprocess.run(
                command,
                cwd=context.root_dir,
                shell=True,
                text=True,
                capture_output=True,
                timeout=context.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Command timed out after {context.timeout_seconds} seconds.") from exc
        except OSError as exc:
            raise ToolError(f"Failed to execute command: {exc}") from exc

        stdout = context.truncate_output(completed.stdout)
        stderr = context.truncate_output(completed.stderr)
        ok = completed.returncode == 0
        content_parts = [f"exit_code={completed.returncode}"]
        if stdout:
            content_parts.append(f"stdout:\n{stdout}")
        if stderr:
            content_parts.append(f"stderr:\n{stderr}")
        return ToolResult(ok=ok, content="\n\n".join(content_parts), metadata={"exit_code": completed.returncode})
