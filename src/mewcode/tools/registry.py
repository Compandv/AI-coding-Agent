from __future__ import annotations

from dataclasses import dataclass

from .base import Tool, ToolDefinition, ToolError
from .bash_tool import BashTool
from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .plan_tools import AskUserQuestionTool, WritePlanFileTool
from .search_tools import GlobTool, GrepTool


@dataclass
class ToolRegistry:
    tools: dict[str, Tool]

    def register(self, tool: Tool) -> None:
        name = tool.definition.name
        if name in self.tools:
            raise ToolError(f"Tool already registered: {name}")
        self.tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    def list_definitions(self) -> list[dict]:
        return [tool.definition.to_model_dict() for tool in self.tools.values()]

    def requires_confirmation(self, name: str) -> bool:
        return self.get(name).definition.requires_confirmation


def default_registry() -> ToolRegistry:
    tool_instances = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
        AskUserQuestionTool(),
        WritePlanFileTool(),
    ]
    return ToolRegistry({tool.definition.name: tool for tool in tool_instances})
