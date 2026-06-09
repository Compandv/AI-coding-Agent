from __future__ import annotations

from typing import Any

from .base import Tool, ToolDefinition, ToolError, ToolParameter, ToolResult, ToolSchema
from .context import ToolContext


class ReadFileTool(Tool):
    definition = ToolDefinition(
        name="ReadFile",
        description=(
            "Read the contents of a file in the current workspace. Use this after Glob or Grep identifies a candidate "
            "path, and before EditFile when you need to modify an existing file. Prefer ReadFile over Bash commands "
            "like cat, type, or python -c scripts for inspecting workspace files. Use start_line and end_line when "
            "you only need a code snippet or line range. ReadFile accepts one explicit file path, not a glob or "
            "wildcard pattern. For environment files, try explicit names one by one, such as .env, .env.local, "
            ".env.example, .env.development, or .env.production. Use the returned metadata for file length, byte "
            "size, line count, range, and truncation status instead of running Bash just to count or slice the file."
        ),
        schema=ToolSchema(
            properties={
                "path": ToolParameter(type="string", description="Path to the file to read."),
                "start_line": ToolParameter(
                    type="integer",
                    description=(
                        "Optional 1-based first line to return. Use with end_line to inspect a specific snippet "
                        "instead of reading the whole file."
                    ),
                ),
                "end_line": ToolParameter(
                    type="integer",
                    description=(
                        "Optional 1-based inclusive last line to return. If omitted with start_line, returns from "
                        "start_line to the end of the file."
                    ),
                ),
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
        lines = content.splitlines()
        selected_content = content
        range_requested = "start_line" in arguments or "end_line" in arguments
        requested_start_line: int | None = None
        requested_end_line: int | None = None
        if range_requested:
            requested_start_line = _optional_positive_int(arguments, "start_line") or 1
            requested_end_line = _optional_positive_int(arguments, "end_line") or len(lines)
            if requested_end_line < requested_start_line:
                raise ToolError("end_line must be greater than or equal to start_line.")
            selected_content = "\n".join(lines[requested_start_line - 1 : requested_end_line])

        truncated = len(selected_content) > context.max_output_chars
        metadata: dict[str, Any] = {
            "path": str(path),
            "content_chars": len(content),
            "content_bytes": len(content.encode("utf-8")),
            "line_count": len(lines),
            "truncated": truncated,
        }
        if range_requested:
            metadata.update(
                {
                    "range_requested": True,
                    "start_line": requested_start_line,
                    "end_line": requested_end_line,
                    "returned_line_count": len(selected_content.splitlines()),
                    "returned_chars": len(selected_content),
                }
            )
        return ToolResult(
            ok=True,
            content=context.truncate_output(selected_content),
            metadata=metadata,
        )


class WriteFileTool(Tool):
    definition = ToolDefinition(
        name="WriteFile",
        description=(
            "Create or overwrite a file in the current workspace. Use this for new files or deliberate full-file "
            "replacement. Read an existing file first when preserving unknown content matters, because this tool can "
            "replace the whole file. After writing, use ReadFile or Bash tests when verification is useful."
        ),
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
        description=(
            "Replace a uniquely matched string inside an existing workspace file. Read the target file first and build "
            "old_string from exact observed content. Use this for focused edits instead of rewriting whole files. After "
            "editing, use ReadFile or a relevant Bash verification command when useful."
        ),
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


def _optional_positive_int(arguments: dict[str, Any], name: str) -> int | None:
    if name not in arguments or arguments[name] is None:
        return None
    raw_value = arguments[name]
    if isinstance(raw_value, str):
        raw_value = raw_value.strip()
        if not raw_value:
            return None
    if isinstance(raw_value, bool):
        raise ToolError(f"{name} must be a positive integer.")
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise ToolError(f"{name} must be a positive integer.")
    return value
