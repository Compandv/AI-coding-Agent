from mewcode import cli
from mewcode.config import MCPConfig, MCPServerConfig, MewCodeConfig


class FakeStream:
    def __init__(self):
        self.reconfigure_calls = []

    def reconfigure(self, **kwargs):
        self.reconfigure_calls.append(kwargs)


class FakeRepl:
    def __init__(self, provider, config, session, agent, **kwargs):
        self.provider = provider
        self.config = config
        self.session = session
        self.agent = agent
        self.kwargs = kwargs

    def run(self):
        return 0


class FakeProvider:
    pass


class FakeMCPManager:
    instances = []

    def __init__(self, config, timeout_seconds, cwd):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd
        self.errors = {}
        self.read_tool_names = {"fake__echo"}
        self.closed = False
        self.connected = False
        FakeMCPManager.instances.append(self)

    def connect_all(self):
        self.connected = True

    def register_tools(self, registry):
        self.registry = registry

    def status_counts(self):
        return {"configured_servers": 1, "connected_servers": 0, "registered_tools": 0}

    def close(self):
        self.closed = True


def test_cli_loads_config_and_runs_repl(monkeypatch, tmp_path):
    config = MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        max_tool_steps=32,
    )
    calls = {}

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: calls.setdefault("config", loaded) or FakeProvider())
    monkeypatch.setattr(cli, "MCPManager", FakeMCPManager)
    monkeypatch.setattr(
        cli.PermissionChecker,
        "from_workspace",
        lambda context, mode: calls.setdefault("permission", FakePermissionChecker(context, mode)),
    )
    monkeypatch.setattr(cli, "MewCodeRepl", lambda *args, **kwargs: calls.setdefault("repl", FakeRepl(*args, **kwargs)))
    monkeypatch.setattr(cli, "Path", type("PathShim", (), {"cwd": staticmethod(lambda: tmp_path)}))

    assert cli.main([]) == 0
    assert calls["config"] is config
    assert calls["permission"].mode == "default"
    assert calls["permission"].read_tool_names == {"fake__echo"}
    assert calls["repl"].agent.max_tool_steps == 32
    assert calls["repl"].kwargs["mcp_status_provider"]() == {
        "configured_servers": 1,
        "connected_servers": 0,
        "registered_tools": 0,
    }
    assert FakeMCPManager.instances[-1].connected is False
    assert FakeMCPManager.instances[-1].closed is True


class FakePermissionChecker:
    def __init__(self, context, mode):
        self.context = context
        self.mode = mode
        self.read_tool_names = set()

    def add_read_tools(self, tool_names):
        self.read_tool_names.update(tool_names)


def test_cli_reports_config_error(monkeypatch, capsys):
    from mewcode.config import ConfigError

    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(ConfigError("missing config")))

    assert cli.main([]) == 1
    assert "missing config" in capsys.readouterr().err


def test_windows_console_encoding_sets_code_page_and_stdio(monkeypatch):
    calls = []

    class FakeKernel32:
        def SetConsoleCP(self, code_page):
            calls.append(("input", code_page))

        def SetConsoleOutputCP(self, code_page):
            calls.append(("output", code_page))

    class FakeCtypes:
        def WinDLL(self, name, use_last_error=False):
            calls.append(("windll", name, use_last_error))
            return FakeKernel32()

    stdin = FakeStream()
    stdout = FakeStream()
    stderr = FakeStream()
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setitem(cli.sys.modules, "ctypes", FakeCtypes())

    cli.configure_windows_console_encoding()

    assert ("input", cli.WINDOWS_UTF8_CODE_PAGE) in calls
    assert ("output", cli.WINDOWS_UTF8_CODE_PAGE) in calls
    assert stdin.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stdout.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.reconfigure_calls == [{"encoding": "utf-8", "errors": "replace"}]
