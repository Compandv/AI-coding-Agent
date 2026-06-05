from mewcode import cli
from mewcode.config import MewCodeConfig


class FakeStream:
    def __init__(self):
        self.reconfigure_calls = []

    def reconfigure(self, **kwargs):
        self.reconfigure_calls.append(kwargs)


class FakeRepl:
    def __init__(self, provider, config, session, agent):
        self.provider = provider
        self.config = config
        self.session = session
        self.agent = agent

    def run(self):
        return 0


class FakeProvider:
    pass


def test_cli_loads_config_and_runs_repl(monkeypatch, tmp_path):
    config = MewCodeConfig(
        protocol="openai",
        model="gpt-4.1",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )
    calls = {}

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: calls.setdefault("config", loaded) or FakeProvider())
    monkeypatch.setattr(cli, "MewCodeRepl", FakeRepl)
    monkeypatch.setattr(cli, "Path", type("PathShim", (), {"cwd": staticmethod(lambda: tmp_path)}))

    assert cli.main([]) == 0
    assert calls["config"] is config


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
