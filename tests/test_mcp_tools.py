from mewcode.mcp.client import MCPClient, MCPTool
from mewcode.mcp.jsonrpc import make_success_response
from mewcode.mcp.tools import MCPToolWrapper, mcp_result_content_text, safe_mcp_tool_name
from mewcode.tools.context import ToolContext


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def receive(self, timeout_seconds=None):
        return self.responses.pop(0)

    def close(self):
        pass


def test_mcp_tool_wrapper_registers_stable_name_and_executes(tmp_path):
    client = MCPClient(ScriptedTransport([make_success_response(1, {"content": [{"type": "text", "text": "pong"}]})]), "fake")
    wrapper = MCPToolWrapper(
        client=client,
        server_name="fake",
        remote_tool=MCPTool(
            name="echo-tool",
            description="Echo text",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        ),
        read_only=True,
    )

    result = wrapper.execute({"text": "pong"}, ToolContext(root_dir=tmp_path))

    assert wrapper.definition.name == "fake__echo_tool"
    assert wrapper.definition.requires_confirmation is False
    assert wrapper.definition.schema.required == ["text"]
    assert result.ok is True
    assert result.content == "pong"
    assert client.transport.sent[0]["method"] == "tools/call"


def test_mcp_tool_wrapper_marks_unknown_tools_as_confirmation_required():
    client = MCPClient(ScriptedTransport([]), "db")
    wrapper = MCPToolWrapper(client, "db", MCPTool(name="query", description="Query DB"), read_only=False)

    assert wrapper.definition.name == "db__query"
    assert wrapper.definition.requires_confirmation is True


def test_mcp_result_content_text_prefers_text_parts_and_structured_content():
    assert mcp_result_content_text({"content": [{"type": "text", "text": "hello"}]}) == "hello"
    assert '"value": 1' in mcp_result_content_text({"structuredContent": {"value": 1}})
    assert safe_mcp_tool_name("my-server", "list.issues") == "my_server__list_issues"
