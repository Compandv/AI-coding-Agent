from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .jsonrpc import make_notification, make_request, response_error, response_id
from .transports import MCPTransport, TransportError


MCP_PROTOCOL_VERSION = "2025-11-25"


class MCPClientError(Exception):
    """Raised when MCP protocol communication fails."""


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    def __init__(
        self,
        transport: MCPTransport,
        server_name: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.transport = transport
        self.server_name = server_name
        self.timeout_seconds = timeout_seconds
        self._next_id = 1
        self._pending: dict[int | str, dict[str, Any]] = {}
        self.initialized = False

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mewcode", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized")
        self.initialized = True
        return result

    def list_tools(self) -> list[MCPTool]:
        result = self.request("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            raise MCPClientError(f"MCP server {self.server_name} returned invalid tools/list result.")
        parsed: list[MCPTool] = []
        for raw_tool in tools:
            if not isinstance(raw_tool, dict):
                continue
            name = str(raw_tool.get("name") or "").strip()
            if not name:
                continue
            input_schema = raw_tool.get("inputSchema") or raw_tool.get("input_schema") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}
            parsed.append(
                MCPTool(
                    name=name,
                    description=str(raw_tool.get("description") or ""),
                    input_schema=input_schema,
                )
            )
        return parsed

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise MCPClientError(f"MCP tool {name} returned a non-object result.")
        return result

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_request_id()
        self.transport.send(make_request(request_id, method, params))
        while True:
            response = self._pop_or_receive_response(request_id)
            if response is None:
                continue
            error = response_error(response)
            if error is not None:
                raise MCPClientError(f"MCP {method} failed: {error.message}")
            result = response.get("result")
            if isinstance(result, dict):
                return result
            if result is None:
                return {}
            return {"value": result}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.transport.send(make_notification(method, params))

    def close(self) -> None:
        self.transport.close()

    def _next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _pop_or_receive_response(self, request_id: int | str) -> dict[str, Any] | None:
        if request_id in self._pending:
            return self._pending.pop(request_id)
        try:
            message = self.transport.receive(self.timeout_seconds)
        except TransportError as exc:
            raise MCPClientError(str(exc)) from exc
        current_id = response_id(message)
        if current_id is None:
            return None
        if current_id != request_id:
            self._pending[current_id] = message
            return None
        return message
