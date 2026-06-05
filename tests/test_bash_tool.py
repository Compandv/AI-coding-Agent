from pathlib import Path

from mewcode.tools.bash_tool import BashTool
from mewcode.tools.context import ToolContext


def test_bash_runs_command_and_returns_output(tmp_path):
    result = BashTool().execute({"command": "python -c \"print('hello')\""}, ToolContext(root_dir=tmp_path, timeout_seconds=5))

    assert result.metadata["exit_code"] == 0
    assert "hello" in result.content
