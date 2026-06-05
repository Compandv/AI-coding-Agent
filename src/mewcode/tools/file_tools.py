from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolDefinition, ToolError, ToolParameter, ToolResult, ToolSchema
from .context import ToolContext


class ReadFileTool(Tool):
    definition = ToolDefinition(
        name="ReadFile",
        description="Read the contents of a file in the current workspace.",
        schema=ToolSchema(
            properties={
                "path": ToolParameter(type="string", description="Path to the file to read."),
            },
            required=["path"],
        ),
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = context.resolve_path(str(arguments["path"]))
        if not path.exists():
            raise ToolError(f"File does not exist: {arguments['path']}")
        if path.is_dir():
            raise ToolError(f"Expected a file but found a directory: {arguments['path']}")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc
        return ToolResult(ok=True, content=context.truncate_output(content), metadata={"path": str(path)})


class WriteFileTool(Tool):
    definition = ToolDefinition(
        name="WriteFile",
        description="Create or overwrite a file in the current workspace.",
        schema=ToolSchema(
            properties={
                "path": ToolParameter(type="string", description="Path to the file to write."),
                "content": ToolParameter(type="string", description="Full content to write into the file."),
            },
            required=["path", "content"],
        ),
        requires_confirmation=True,
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = context.resolve_path(str(arguments["path"]))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(arguments["content"]), encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc
        return ToolResult(ok=True, content=f"Wrote file: {path}", metadata={"path": str(path)})


class EditFileTool(Tool):
    definition = ToolDefinition(
        name="EditFile",
        description="Replace a uniquely matched string inside a file in the current workspace.",
        schema=ToolSchema(
            properties={
                "path": ToolParameter(type="string", description="Path to the file to edit."),
                "old_string": ToolParameter(type="string", description="Exact text to replace."),
                "new_string": ToolParameter(type="string", description="Replacement text."),
            },
            required=["path", "old_string", "new_string"],
        ),
        requires_confirmation=True,
    )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        path = context.resolve_path(str(arguments["path"]))
        if not path.exists():
            raise ToolError(f"File does not exist: {arguments['path']}")
        if path.is_dir():
            raise ToolError(f"Expected a file but found a directory: {arguments['path']}")
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to read file: {exc}") from exc

        old_string = str(arguments["old_string"])
        new_string = str(arguments["new_string"])
        matches = original.count(old_string)
        if matches == 0:
            raise ToolError("old_string did not match any content in the target file.")
        if matches > 1:
            raise ToolError("old_string matched multiple locations in the target file.")

        updated = original.replace(old_string, new_string, 1)
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}") from exc
        return ToolResult(ok=True, content=f"Edited file: {path}", metadata={"path": str(path)})
