from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolDefinition, ToolParameter, ToolResult, ToolSchema
from .context import ToolContext


def _relative_paths(paths: list[Path], root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in paths]


class GlobTool(Tool):
    definition = ToolDefinition(
        name="Glob",
        description=(
            "Find files in the current workspace that match a glob pattern. "
            "Use this to locate entry files, folders, or file families before opening them. "
            "Always provide a non-empty pattern. For project entry points, start with patterns like "
            "**/main.py, **/app.py, **/cli.py, **/__main__.py, src/**/*.py, or tests/**/*.py."
        ),
        schema=ToolSchema(
            properties={
                "pattern": ToolParameter(
                    type="string",
                    description=(
                        "Required. A glob pattern such as src/**/*.py, **/main.py, or **/cli.py. "
                        "Use forward slashes and keep it as specific as possible."
                    ),
                ),
            },
            required=["pattern"],
        ),
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        pattern = str(arguments["pattern"])
        matches = [path for path in context.root_dir.glob(pattern)]
        paths = _relative_paths(matches, context.root_dir)
        return ToolResult(ok=True, content="\n".join(paths), metadata={"count": len(paths), "paths": paths})


class GrepTool(Tool):
    definition = ToolDefinition(
        name="Grep",
        description=(
            "Search file contents in the current workspace. Use this when you know a symbol, phrase, "
            "or error message and want to locate where it appears. Prefer short, unique queries such as "
            "function names, class names, or exact log text."
        ),
        schema=ToolSchema(
            properties={
                "query": ToolParameter(
                    type="string",
                    description=(
                        "Required. Text to search for inside files. Use the smallest unique snippet that "
                        "can identify the code you want."
                    ),
                ),
            },
            required=["query"],
        ),
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        query = str(arguments["query"])
        matches: list[str] = []
        for path in context.root_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if query in line:
                    relative = path.relative_to(context.root_dir)
                    matches.append(f"{relative}:{line_number}:{line}")
        text = context.truncate_output("\n".join(matches))
        return ToolResult(ok=True, content=text, metadata={"count": len(matches)})
