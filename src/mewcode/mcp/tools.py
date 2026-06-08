from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from mewcode.tools import Tool, ToolContext, ToolDefinition, ToolParameter, ToolResult, ToolSchema

from .client import MCPClient, MCPClientError, MCPTool


TOOL_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_]")


def safe_mcp_tool_name(server_name: str, tool_name: str) -> str:
    server = _safe_name_part(server_name)
    tool = _safe_name_part(tool_name)
    return f"{server}__{tool}"


def _safe_name_part(value: str) -> str:
    cleaned = TOOL_NAME_PATTERN.sub("_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "tool"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


@dataclass
class MCPToolWrapper(Tool):
    client: MCPClient
    server_name: str
    remote_tool: MCPTool
    read_only: bool = False

    def __post_init__(self) -> None:
        self.definition = ToolDefinition(
            name=safe_mcp_tool_name(self.server_name, self.remote_tool.name),
            description=self._description(),
            schema=ToolSchema.from_raw(self.remote_tool.input_schema),
            requires_confirmation=not self.read_only,
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        try:
            result = self.client.call_tool(self.remote_tool.name, arguments)
        except MCPClientError as exc:
            return ToolResult(
                ok=False,
                error=str(exc),
                metadata={"mcp_server": self.server_name, "mcp_tool": self.remote_tool.name},
            )
        return self._tool_result(result)

    def _description(self) -> str:
        description = self.remote_tool.description.strip() or f"MCP tool {self.remote_tool.name}."
        return f"{description}\n\nExternal MCP tool from server `{self.server_name}`."

    def _tool_result(self, result: dict[str, Any]) -> ToolResult:
        is_error = bool(result.get("isError"))
        content = mcp_result_content_text(result)
        return ToolResult(
            ok=not is_error,
            content=content,
            error=content if is_error else None,
            metadata={
                "mcp_server": self.server_name,
                "mcp_tool": self.remote_tool.name,
                "mcp_result": result,
            },
        )


def mcp_result_content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = [mcp_content_part_text(part) for part in content]
        text = "\n".join(part for part in parts if part)
        if text:
            return text
    structured = result.get("structuredContent")
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, indent=2)
    if content is not None:
        return json.dumps(content, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def mcp_content_part_text(part: Any) -> str:
    if not isinstance(part, dict):
        return str(part)
    if part.get("type") == "text":
        return str(part.get("text") or "")
    return json.dumps(part, ensure_ascii=False)


class ListMCPServersTool(Tool):
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.definition = ToolDefinition(
            name="ListMCPServers",
            description=(
                "List configured external MCP servers without activating them. Use this when a task may need external "
                "systems such as GitHub, databases, Slack, browser tools, or other configured MCP capabilities."
            ),
            schema=ToolSchema(),
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = arguments, context
        servers = self.manager.server_summaries()
        if not servers:
            return ToolResult(ok=True, content="No MCP servers are configured.", metadata={"mcp_servers": []})
        lines = []
        for server in servers:
            status = "active" if server["activated"] else "inactive"
            read_only = ", ".join(server["read_only_tools"]) if server["read_only_tools"] else "none"
            lines.append(f"- {server['name']} ({server['transport']}, {status}, read-only: {read_only})")
        return ToolResult(ok=True, content="\n".join(lines), metadata={"mcp_servers": servers})


class ActivateMCPServerTool(Tool):
    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self.definition = ToolDefinition(
            name="ActivateMCPServer",
            description=(
                "Activate one configured MCP server by name, discover its tools, and make those tools available in "
                "the next model step. Use ListMCPServers first if you do not know the configured server names."
            ),
            schema=ToolSchema(
                properties={
                    "server": ToolParameter(
                        type="string",
                        description="Name of the configured MCP server to activate.",
                    )
                },
                required=["server"],
            ),
            requires_confirmation=True,
        )

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        _ = context
        server_name = str(arguments["server"])
        try:
            tools = self.manager.activate_server(server_name)
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=str(exc),
                metadata={"mcp_server": server_name, "activation_failed": True},
            )
        tool_names = [tool.definition.name for tool in tools]
        if tool_names:
            content = "Activated MCP server {server}. Tools now available: {tools}".format(
                server=server_name,
                tools=", ".join(tool_names),
            )
        else:
            content = f"Activated MCP server {server_name}. No tools were discovered."
        return ToolResult(
            ok=True,
            content=content,
            metadata={
                "mcp_server": server_name,
                "activated_tools": tool_names,
                "activated_read_tools": [tool.definition.name for tool in tools if tool.read_only],
            },
        )
