import subprocess

from pathlib import Path

import pytest

from mewcode.tools.base import ToolError
from mewcode.tools.bash_tool import BashTool
from mewcode.tools.context import ToolContext


def test_bash_runs_command_and_returns_output(tmp_path):
    result = BashTool().execute({"command": "python -c \"print('hello')\""}, ToolContext(root_dir=tmp_path, timeout_seconds=5))

    assert result.metadata["exit_code"] == 0
    assert "hello" in result.content


def test_bash_handles_missing_stdout_and_stderr(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=None, stderr=None)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = BashTool().execute({"command": "echo hello"}, ToolContext(root_dir=tmp_path, timeout_seconds=5))

    assert result.ok is True
    assert result.content == "exit_code=0"


def test_bash_rejects_posix_heredoc_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("mewcode.tools.bash_tool.sys.platform", "win32")

    with pytest.raises(ToolError) as exc_info:
        BashTool().execute({"command": "python - <<'PY'\nprint('hello')\nPY"}, ToolContext(root_dir=tmp_path))

    assert "POSIX heredoc" in str(exc_info.value)
