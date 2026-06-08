import json
import sys

import httpx
import pytest

from mewcode.mcp.jsonrpc import make_request, make_success_response
from mewcode.mcp.transports import HTTPTransport, StdioTransport, TransportError, resolve_stdio_command


def test_http_transport_posts_json_and_receives_response():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=make_success_response(payload["id"], {"ok": True}))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = HTTPTransport("https://mcp.example.test", headers={"Authorization": "Bearer token"}, client=client)

    transport.send(make_request(1, "ping", {}))

    assert transport.receive()["result"] == {"ok": True}
    assert requests[0].headers["authorization"] == "Bearer token"
    assert requests[0].headers["content-type"] == "application/json"


def test_http_transport_rejects_sse_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"event: message\n\n")

    transport = HTTPTransport("https://mcp.example.test", client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(TransportError, match="SSE"):
        transport.send(make_request(1, "ping", {}))


def test_stdio_transport_exchanges_newline_delimited_json(tmp_path):
    server = tmp_path / "server.py"
    server.write_text(
        """
import json
import os
import sys

for line in sys.stdin:
    message = json.loads(line)
    result = {"method": message.get("method"), "has_secret": "SECRET" in os.environ, "path": os.environ.get("PATH", "")}
    print(json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}), flush=True)
""",
        encoding="utf-8",
    )
    transport = StdioTransport(sys.executable, [str(server)], env={"EXPLICIT": "yes"})

    transport.send(make_request(1, "ping", {}))
    response = transport.receive(5)
    transport.close()

    assert response["result"]["method"] == "ping"
    assert response["result"]["has_secret"] is False
    assert isinstance(response["result"]["path"], str)


def test_stdio_transport_windows_env_keeps_safe_system_vars(monkeypatch):
    monkeypatch.setattr("mewcode.mcp.transports.sys.platform", "win32")
    monkeypatch.setenv("PATH", "C:\\Tools")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    monkeypatch.setenv("APPDATA", "C:\\Users\\me\\AppData\\Roaming")
    monkeypatch.setenv("TEMP", "C:\\Temp")
    monkeypatch.setenv("SECRET", "do-not-leak")

    env = StdioTransport("npx")._child_env()

    assert env["PATH"] == "C:\\Tools"
    assert env["PATHEXT"] == ".COM;.EXE;.BAT;.CMD"
    assert env["SystemRoot"] == "C:\\Windows"
    assert env["COMSPEC"] == "C:\\Windows\\System32\\cmd.exe"
    assert env["APPDATA"] == "C:\\Users\\me\\AppData\\Roaming"
    assert env["TEMP"] == "C:\\Temp"
    assert "SECRET" not in env


def test_resolve_stdio_command_uses_path_lookup(monkeypatch):
    monkeypatch.setattr("mewcode.mcp.transports.shutil.which", lambda command, path=None: f"C:\\Tools\\{command}.cmd")

    assert resolve_stdio_command("npx", {"PATH": "C:\\Tools"}) == "C:\\Tools\\npx.cmd"
