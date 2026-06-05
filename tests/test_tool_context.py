from pathlib import Path

import pytest

from mewcode.tools.base import ToolError
from mewcode.tools.context import ToolContext


def test_resolve_path_keeps_workspace_relative(tmp_path):
    context = ToolContext(root_dir=tmp_path)

    resolved = context.resolve_path("notes.txt")

    assert resolved == tmp_path / "notes.txt"


def test_resolve_path_rejects_escape(tmp_path):
    context = ToolContext(root_dir=tmp_path)

    with pytest.raises(ToolError):
        context.resolve_path("../outside.txt")


def test_truncate_output_limits_size(tmp_path):
    context = ToolContext(root_dir=tmp_path, max_output_chars=5)

    assert context.truncate_output("abcdefgh") == "abcde\n...[truncated]"
