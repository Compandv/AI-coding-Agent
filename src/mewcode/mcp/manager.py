from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mewcode.config import MCPConfig, MCPServerConfig
from mewcode.tools import ToolError, ToolRegistry

from .client import MCPClient
from .tools import ActivateMCPServerTool, ListMCPServersTool, MCPToolWrapper
from .transports import HTTPTransport, StdioTransport


@dataclass
class MCPServerRuntime:
    config: MCPServerConfig
    client: MCPClient
    tools: list[MCPToolWrapper] = field(default_factory=list)


class MCPManager:
    def __init__(
        self,
        config: MCPConfig,
        timeout_seconds: float = 60.0,
        cwd: Path | None = None,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd
        self.runtimes: dict[str, MCPServerRuntime] = {}
        self.errors: dict[str, str] = dict(config.skipped_servers)
        self.registry: ToolRegistry | None = None
        self.registered_tool_names: set[str] = set()

    @property
    def read_tool_names(self) -> set[str]:
        names: set[str] = set()
        for runtime in self.runtimes.values():
            for tool in runtime.tools:
                if tool.read_only:
                    names.add(tool.definition.name)
        return names

    def connect_all(self) -> None:
        """Retained for compatibility; MCP servers are now activated lazily."""

    def register_tools(self, registry: ToolRegistry) -> None:
        self.registry = registry
        for tool in (ListMCPServersTool(self), ActivateMCPServerTool(self)):
            try:
                registry.register(tool)
            except ToolError as exc:
                    self.errors[tool.definition.name] = str(exc)

    def status_counts(self) -> dict[str, int]:
        return {
            "configured_servers": len(self.config.servers),
            "connected_servers": len(self.runtimes),
            "registered_tools": len(self.registered_tool_names),
        }

    def close(self) -> None:
        for runtime in self.runtimes.values():
            runtime.client.close()
        self.runtimes.clear()
        self.registered_tool_names.clear()

    def server_summaries(self) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        for server in self.config.servers.values():
            summaries.append(
                {
                    "name": server.name,
                    "transport": server.transport,
                    "activated": server.name in self.runtimes,
                    "read_only_tools": sorted(server.read_only_tools),
                }
            )
        return summaries

    def activate_server(self, server_name: str) -> list[MCPToolWrapper]:
        if server_name in self.runtimes:
            return list(self.runtimes[server_name].tools)
        server = self.config.servers.get(server_name)
        if server is None:
            raise ToolError(f"Unknown MCP server: {server_name}")
        runtime = self._connect_server(server)
        if self.registry is not None:
            for tool in runtime.tools:
                try:
                    self.registry.register(tool)
                    self.registered_tool_names.add(tool.definition.name)
                except ToolError as exc:
                    self.errors[tool.definition.name] = str(exc)
        return list(runtime.tools)

    def _connect_server(self, server: MCPServerConfig) -> MCPServerRuntime:
        client: MCPClient | None = None
        try:
            client = MCPClient(
                transport=self._transport_for(server),
                server_name=server.name,
                timeout_seconds=self.timeout_seconds,
            )
            client.initialize()
            remote_tools = client.list_tools()
            wrappers = [
                MCPToolWrapper(
                    client=client,
                    server_name=server.name,
                    remote_tool=remote_tool,
                    read_only=remote_tool.name in server.read_only_tools,
                )
                for remote_tool in remote_tools
            ]
            runtime = MCPServerRuntime(config=server, client=client, tools=wrappers)
            self.runtimes[server.name] = runtime
            return runtime
        except Exception as exc:
            if client is not None:
                client.close()
            self.errors[server.name] = str(exc)
            raise ToolError(f"Failed to activate MCP server {server.name}: {exc}") from exc

    def _transport_for(self, server: MCPServerConfig):
        if server.transport == "stdio":
            return StdioTransport(
                command=server.command,
                args=list(server.args),
                env=dict(server.env),
                cwd=str(self.cwd) if self.cwd is not None else None,
            )
        return HTTPTransport(
            url=server.url,
            headers=dict(server.headers),
            timeout_seconds=self.timeout_seconds,
        )
