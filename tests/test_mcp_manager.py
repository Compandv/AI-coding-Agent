from mewcode.config import MCPConfig, MCPServerConfig
from mewcode.mcp.manager import MCPManager
from mewcode.tools.registry import default_registry


class FakeRemoteTool:
    def __init__(self, name, description="", input_schema=None):
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}, "required": []}


class FakeClient:
    def __init__(self, transport, server_name, timeout_seconds=60):
        self.server_name = server_name
        self.closed = False

    def initialize(self):
        if self.server_name == "broken":
            raise RuntimeError("boom")
        return {}

    def list_tools(self):
        return [FakeRemoteTool("echo", "Echo")]

    def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": arguments.get("text", "")}]}

    def close(self):
        self.closed = True


def test_mcp_manager_registers_tools_and_skips_broken_servers(monkeypatch):
    monkeypatch.setattr("mewcode.mcp.manager.MCPClient", FakeClient)
    monkeypatch.setattr("mewcode.mcp.manager.StdioTransport", lambda **kwargs: object())
    config = MCPConfig(
        servers={
            "fake": MCPServerConfig(name="fake", transport="stdio", command="fake", read_only_tools={"echo"}),
            "broken": MCPServerConfig(name="broken", transport="stdio", command="broken"),
        }
    )
    manager = MCPManager(config)
    registry = default_registry()

    manager.register_tools(registry)

    assert "ListMCPServers" in registry.tools
    assert "ActivateMCPServer" in registry.tools
    assert "fake__echo" not in registry.tools

    result = registry.get("ActivateMCPServer").execute({"server": "fake"}, None)

    assert result.ok is True
    assert "fake__echo" in registry.tools
    assert "fake__echo" in manager.read_tool_names
    assert manager.status_counts() == {"configured_servers": 2, "connected_servers": 1, "registered_tools": 1}

    failed = registry.get("ActivateMCPServer").execute({"server": "broken"}, None)

    assert failed.ok is False
    assert "broken" in manager.errors


def test_mcp_manager_lists_servers_without_activation(monkeypatch):
    monkeypatch.setattr("mewcode.mcp.manager.MCPClient", FakeClient)
    monkeypatch.setattr("mewcode.mcp.manager.StdioTransport", lambda **kwargs: object())
    config = MCPConfig(
        servers={
            "fake": MCPServerConfig(name="fake", transport="stdio", command="fake", read_only_tools={"echo"}),
        }
    )
    manager = MCPManager(config)
    registry = default_registry()

    manager.register_tools(registry)
    result = registry.get("ListMCPServers").execute({}, None)

    assert result.ok is True
    assert "fake (stdio, inactive, read-only: echo)" in result.content
    assert "fake__echo" not in registry.tools
