from mewcode.mcp.client import MCPClient
from mewcode.mcp.jsonrpc import make_success_response


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(message)

    def receive(self, timeout_seconds=None):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_mcp_client_initializes_lists_tools_and_calls_tool():
    transport = ScriptedTransport(
        [
            make_success_response(1, {"protocolVersion": "2025-11-25"}),
            make_success_response(
                2,
                {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                },
            ),
            make_success_response(3, {"content": [{"type": "text", "text": "hello"}]}),
        ]
    )
    client = MCPClient(transport, "fake")

    init = client.initialize()
    tools = client.list_tools()
    result = client.call_tool("echo", {"text": "hello"})

    assert init["protocolVersion"] == "2025-11-25"
    assert transport.sent[0]["method"] == "initialize"
    assert transport.sent[1]["method"] == "notifications/initialized"
    assert tools[0].name == "echo"
    assert tools[0].input_schema["required"] == ["text"]
    assert result["content"][0]["text"] == "hello"
